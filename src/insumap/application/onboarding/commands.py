"""Decisions about an import: preview a file, then confirm its batch (P13).

Both commands run through ``CommandGuard``: the transaction, the audit row
(P09) and the RLS context come from there. Staged patients are published to
the store only after the commit, and dropped only after a confirmation commits.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import ClassVar, final, override
from uuid import UUID

from insumap.application.commands.base import AuditSubject, Command, CommandHandler
from insumap.application.commands.transactional import CurrentUnitOfWork
from insumap.application.common.ids import IdGenerator
from insumap.application.onboarding.pipeline import ImportRequest, PatientImportPipeline
from insumap.application.onboarding.ports import (
    ImportBatchRepositoryPort,
    PatientAccountWriterPort,
    StagedImportStorePort,
    StagedPatient,
    StoredRow,
)
from insumap.domain.common.errors import ConflictError, ResourceNotFoundError
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.onboarding.batch import ImportBatch
from insumap.domain.onboarding.events import PatientsImported
from insumap.domain.onboarding.vocabulary import (
    ImportIssue,
    RowStatus,
    SourceFormat,
)
from insumap.shared.time import Clock

BATCH_ENTITY: str = "IMPORT_BATCH"
CONFIRM_ACTION: str = "confirm"
PREVIEW_EXPIRED_REASON: str = "preview_expired"


@dataclass(frozen=True, slots=True, kw_only=True)
class PreviewImportCommand(Command[ImportBatch]):
    """A clinic administrator uploads a file; nothing becomes a patient yet."""

    audit_action: ClassVar[str] = "IMPORT_PREVIEWED"
    audit_entity_type: ClassVar[str] = BATCH_ENTITY

    source_format: SourceFormat
    content: bytes

    @override
    def audit_subject(self, result: ImportBatch) -> AuditSubject:
        return AuditSubject(
            clinic_id=self.actor.clinic_id,
            entity_id=result.batch_id,
            changed_fields=("source_format", "status"),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ConfirmImportCommand(Command[ImportBatch]):
    """The administrator confirms the whole batch; its valid rows become patients."""

    audit_action: ClassVar[str] = "IMPORT_CONFIRMED"
    audit_entity_type: ClassVar[str] = BATCH_ENTITY

    batch_id: UUID

    @override
    def audit_subject(self, result: ImportBatch) -> AuditSubject:
        return AuditSubject(
            clinic_id=self.actor.clinic_id,
            entity_id=result.batch_id,
            changed_fields=("status", "created_rows", "skipped_rows"),
        )


@final
class PreviewImportCommandHandler(CommandHandler[PreviewImportCommand, ImportBatch]):
    """Runs the pipeline of the format; stages the patients after the commit."""

    def __init__(
        self,
        *,
        pipelines: Mapping[SourceFormat, PatientImportPipeline],
        staged: StagedImportStorePort,
        current: CurrentUnitOfWork,
    ) -> None:
        self._pipelines = pipelines
        self._staged = staged
        self._current = current

    @override
    def handle(self, command: PreviewImportCommand) -> ImportBatch:
        actor = command.actor
        actor.require(PermissionCode.PATIENTS_IMPORT)
        if actor.clinic_id is None:
            raise ResourceNotFoundError
        prepared = self._pipelines[command.source_format].run(
            ImportRequest(
                clinic_id=actor.clinic_id,
                created_by=actor.user_id,
                clinic_is_demo=actor.clinic_is_demo,
                content=command.content,
                file_sha256=hashlib.sha256(command.content).hexdigest(),
            )
        )
        batch_id, staged = prepared.batch.batch_id, prepared.staged
        self._current.after_commit(lambda: self._staged.put(batch_id, staged))
        return prepared.batch


@final
class ConfirmImportCommandHandler(CommandHandler[ConfirmImportCommand, ImportBatch]):
    """Creates the patients of a preview, re-checking duplicates in the transaction.

    A row that repeats a patient created since the preview is skipped, not
    failed: one unique violation must not roll back the whole batch.
    """

    def __init__(
        self,
        *,
        batches: ImportBatchRepositoryPort,
        accounts: PatientAccountWriterPort,
        staged: StagedImportStorePort,
        current: CurrentUnitOfWork,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._batches = batches
        self._accounts = accounts
        self._staged = staged
        self._current = current
        self._ids = ids
        self._clock = clock

    @override
    def handle(self, command: ConfirmImportCommand) -> ImportBatch:
        command.actor.require(PermissionCode.PATIENTS_IMPORT)
        batch = self._batches.get_batch(command.batch_id)
        if batch is None:
            raise ResourceNotFoundError
        batch.require_previewed(CONFIRM_ACTION)
        patients = self._staged.peek(batch.batch_id)
        if patients is None:
            raise ConflictError(PREVIEW_EXPIRED_REASON)

        now = self._clock.now()
        existing = self._batches.existing_identities(
            mrns=frozenset(p.mrn for p in patients),
            document_hashes=frozenset(p.document_hash for p in patients),
        )
        rows: list[StoredRow] = []
        created = 0
        skipped = 0
        for patient in patients:
            clash = _clash(
                patient,
                existing_mrns=existing.mrns,
                existing_hashes=existing.document_hashes,
            )
            if clash:
                skipped += 1
                rows.append(_skipped_row(patient, clash))
                continue
            self._accounts.create_imported(
                patient, clinic_id=batch.clinic_id, batch_id=batch.batch_id, now=now
            )
            created += 1
            rows.append(_created_row(patient))
        if rows:
            self._batches.add_rows(batch.batch_id, rows, clinic_id=batch.clinic_id)

        totals = replace(
            batch.totals,
            created=created,
            skipped=batch.totals.skipped + skipped,
        )
        completed = batch.completed(totals=totals, at=now)
        self._batches.complete(completed)
        self._current.collect(
            [
                PatientsImported(
                    event_id=self._ids.new_id(),
                    occurred_at=now,
                    batch_id=batch.batch_id,
                    clinic_id=batch.clinic_id,
                    created=created,
                )
            ]
        )
        self._current.after_commit(lambda: self._staged.discard(batch.batch_id))
        return completed


def _clash(
    patient: StagedPatient,
    *,
    existing_mrns: frozenset[str],
    existing_hashes: frozenset[str],
) -> tuple[ImportIssue, ...]:
    issues: list[ImportIssue] = []
    if patient.mrn in existing_mrns:
        issues.append(ImportIssue.MRN_DUPLICATE)
    if patient.document_hash in existing_hashes:
        issues.append(ImportIssue.DOCUMENT_DUPLICATE)
    return tuple(issues)


def _created_row(patient: StagedPatient) -> StoredRow:
    return StoredRow(
        row_number=patient.row_number,
        resource_type=patient.resource_type,
        status=RowStatus.CREATED,
        issues=patient.warnings,
        patient_id=patient.patient_id,
    )


def _skipped_row(patient: StagedPatient, issues: tuple[ImportIssue, ...]) -> StoredRow:
    return StoredRow(
        row_number=patient.row_number,
        resource_type=patient.resource_type,
        status=RowStatus.SKIPPED_DUPLICATE,
        issues=issues,
    )
