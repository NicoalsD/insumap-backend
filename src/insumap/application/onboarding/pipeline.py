"""The patient import pipeline (P20 Template Method).

Every format runs the same steps in the same order: read, parse, map,
validate, deduplicate, stage. Subclasses only fill in ``read()`` and
``integration_factory()``. The pipeline writes the batch and the rows that are
final at preview; the validated patients are returned to the caller, which
keeps them until the confirmation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import final
from uuid import UUID

from insumap.application.common.ids import IdGenerator
from insumap.application.onboarding.integration import (
    ClinicIntegrationFactory,
    ImportValidator,
    PatientRecordMapper,
    SourceRow,
    SourceRowError,
)
from insumap.application.onboarding.ports import (
    ImportBatchRepositoryPort,
    KeyedDigest,
    PatientDocumentVaultPort,
    StagedPatient,
    StoredRow,
)
from insumap.domain.onboarding.batch import ImportBatch, ImportTotals, RowOutcome
from insumap.domain.onboarding.patient import PatientCandidate, ValidatedPatient
from insumap.domain.onboarding.vocabulary import (
    BatchStatus,
    DataOrigin,
    ImportIssue,
    RowVerdict,
)
from insumap.shared.errors import ErrorCode, InsumapError
from insumap.shared.time import Clock


@dataclass(frozen=True, slots=True, kw_only=True)
class ImportRequest:
    """One upload, already authorized: who uploads it, for which clinic, and what."""

    clinic_id: UUID
    created_by: UUID
    clinic_is_demo: bool
    content: bytes
    file_sha256: str


@dataclass(frozen=True, slots=True, kw_only=True)
class PreparedImport:
    """What a preview produced: the stored batch and the patients it staged."""

    batch: ImportBatch
    staged: tuple[StagedPatient, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class _Decided:
    """A row the mapper or the validator already rejected or set aside."""

    outcome: RowOutcome


@dataclass(frozen=True, slots=True, kw_only=True)
class _Pending:
    """A valid row, waiting for the duplicate check (the MRN and the hash are known)."""

    row: SourceRow
    patient: ValidatedPatient
    warnings: tuple[ImportIssue, ...]
    digest: KeyedDigest


_Assessed = _Decided | _Pending


class PatientImportPipeline(ABC):
    """Fixed order of an import; the families plug in their parts.

    Pattern: P20 Template Method
    """

    def __init__(
        self,
        *,
        batches: ImportBatchRepositoryPort,
        vault: PatientDocumentVaultPort,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._batches = batches
        self._vault = vault
        self._ids = ids
        self._clock = clock

    @final
    def run(self, request: ImportRequest) -> PreparedImport:
        """Preview one file: nothing becomes a patient here."""
        if not request.content:
            raise InsumapError(
                ErrorCode.VALIDATION_ERROR,
                detail={"errors": [{"field": "body", "type": "empty"}]},
            )
        content = self.read(request.content)
        factory = self.integration_factory()
        parser = factory.create_parser()
        mapper = factory.create_mapper()
        validator = factory.create_validator()

        parsed = parser.parse(content)
        if parsed.origin is DataOrigin.SIMULATED and not request.clinic_is_demo:
            raise InsumapError(
                ErrorCode.VALIDATION_ERROR,
                detail={
                    "errors": [{"field": "body", "type": "simulated_data_not_allowed"}]
                },
            )
        today = self._clock.now().date()
        assessed = [
            self._assess(row, request, mapper, validator, today=today)
            for row in parsed.rows
        ]
        pending = [item for item in assessed if isinstance(item, _Pending)]
        existing = self._batches.existing_identities(
            mrns=frozenset(item.patient.mrn for item in pending),
            document_hashes=frozenset(item.digest.value for item in pending),
        )

        outcomes: list[RowOutcome] = []
        staged: list[StagedPatient] = []
        seen_mrns: set[str] = set()
        seen_hashes: set[str] = set()
        for item in assessed:
            if isinstance(item, _Decided):
                outcomes.append(item.outcome)
                continue
            duplicates = _duplicates(
                item.patient,
                item.digest,
                seen_mrns,
                seen_hashes,
                existing.mrns,
                existing.document_hashes,
            )
            seen_mrns.add(item.patient.mrn)
            seen_hashes.add(item.digest.value)
            if duplicates:
                outcomes.append(
                    RowOutcome(
                        row_number=item.row.row_number,
                        resource_type=item.row.resource_type,
                        verdict=RowVerdict.DUPLICATE,
                        issues=duplicates,
                    )
                )
                continue
            outcomes.append(
                RowOutcome(
                    row_number=item.row.row_number,
                    resource_type=item.row.resource_type,
                    verdict=RowVerdict.WARNING if item.warnings else RowVerdict.VALID,
                    issues=item.warnings,
                )
            )
            staged.append(self._stage_patient(item, request))

        batch = ImportBatch(
            batch_id=self._ids.new_id(),
            clinic_id=request.clinic_id,
            source_format=factory.source_format,
            data_origin=parsed.origin,
            status=BatchStatus.PREVIEWED,
            file_sha256=request.file_sha256,
            file_size_bytes=len(request.content),
            totals=ImportTotals.from_outcomes(outcomes),
            created_by=request.created_by,
            created_at=self._clock.now(),
        )
        self.stage(batch, outcomes, clinic_id=request.clinic_id)
        return PreparedImport(batch=batch, staged=tuple(staged))

    def stage(
        self, batch: ImportBatch, outcomes: Sequence[RowOutcome], *, clinic_id: UUID
    ) -> None:
        """Write the batch and the rows that are final at preview."""
        self._batches.add_batch(batch)
        rows = [
            StoredRow(
                row_number=outcome.row_number,
                resource_type=outcome.resource_type,
                status=status,
                issues=outcome.issues,
            )
            for outcome in outcomes
            if (status := outcome.stored_status()) is not None
        ]
        if rows:
            self._batches.add_rows(batch.batch_id, rows, clinic_id=clinic_id)

    @abstractmethod
    def read(self, content: bytes) -> bytes:
        """Primitive step: check the bytes are what the format says (UTF-8)."""

    @abstractmethod
    def integration_factory(self) -> ClinicIntegrationFactory:
        """Primitive step: the P03 family of this format, asked once per run."""

    def _assess(
        self,
        row: SourceRow,
        request: ImportRequest,
        mapper: PatientRecordMapper,
        validator: ImportValidator,
        *,
        today: date,
    ) -> _Assessed:
        try:
            candidate: PatientCandidate = mapper.to_candidate(row)
        except SourceRowError as error:
            return _Decided(outcome=error.outcome(row))
        result = validator.validate(candidate, today=today)
        patient = result.patient
        if patient is None:
            return _Decided(
                outcome=RowOutcome(
                    row_number=row.row_number,
                    resource_type=row.resource_type,
                    verdict=RowVerdict.ERROR,
                    issues=result.errors,
                )
            )
        digest = self._vault.hash_document(
            clinic_id=request.clinic_id,
            document_type=patient.document_type,
            document_number=patient.document_number,
        )
        return _Pending(
            row=row, patient=patient, warnings=result.warnings, digest=digest
        )

    def _stage_patient(self, item: _Pending, request: ImportRequest) -> StagedPatient:
        """Fix the ids of a patient and seal its document under the patient id."""
        ids = (self._ids.new_id(), self._ids.new_id(), self._ids.new_id())
        sealed = self._vault.seal_document(
            patient_id=ids[0],
            clinic_id=request.clinic_id,
            document_number=item.patient.document_number,
        )
        return StagedPatient.of(
            item.patient,
            row_number=item.row.row_number,
            resource_type=item.row.resource_type,
            ids=ids,
            digest=item.digest,
            sealed=sealed,
            warnings=item.warnings,
        )


def _duplicates(
    patient: ValidatedPatient,
    digest: KeyedDigest,
    seen_mrns: set[str],
    seen_hashes: set[str],
    known_mrns: frozenset[str],
    known_hashes: frozenset[str],
) -> tuple[ImportIssue, ...]:
    """Why a row repeats a patient of this file or of the clinic."""
    issues: list[ImportIssue] = []
    if patient.mrn in seen_mrns or patient.mrn in known_mrns:
        issues.append(ImportIssue.MRN_DUPLICATE)
    if digest.value in seen_hashes or digest.value in known_hashes:
        issues.append(ImportIssue.DOCUMENT_DUPLICATE)
    return tuple(issues)
