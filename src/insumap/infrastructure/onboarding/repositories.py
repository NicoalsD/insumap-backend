"""Batches, rows and patient accounts of the import over PostgreSQL.

Every statement runs in the transaction of the command, under row level
security (CLINIC_ADMIN of the session clinic). Rows are only inserted: the
table grants have no UPDATE on ``clinic.import_rows``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Final, final, override
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from insumap.application.common.pagination import Page, PageRequest, build_page
from insumap.application.onboarding.ports import (
    BatchFilter,
    ExistingIdentities,
    ImportBatchRepositoryPort,
    ImportRowRecord,
    PatientAccountWriterPort,
    StagedPatient,
    StoredRow,
)
from insumap.domain.common.errors import ConflictError
from insumap.domain.onboarding.batch import ImportBatch, ImportTotals
from insumap.domain.onboarding.vocabulary import (
    BatchStatus,
    DataOrigin,
    ImportIssue,
    RowStatus,
    SourceFormat,
    stored_resource_type,
)
from insumap.infrastructure.persistence.orm import (
    ImportBatchOrm,
    ImportRowOrm,
    MembershipOrm,
    PatientOrm,
    RoleOrm,
    UserOrm,
)
from insumap.infrastructure.persistence.transactions import CurrentSession

PATIENT_ROLE: Final = "PATIENT"
IMPORTED_STATUS: Final = "IMPORTED"
DUPLICATE_REASON: Final = "patient_exists"


def _batch(row: ImportBatchOrm) -> ImportBatch:
    return ImportBatch(
        batch_id=row.id,
        clinic_id=row.clinic_id,
        source_format=SourceFormat(row.source_format),
        data_origin=DataOrigin(row.data_origin),
        status=BatchStatus(row.status),
        file_sha256=row.file_sha256,
        file_size_bytes=row.file_size_bytes,
        totals=ImportTotals(
            total=row.total_rows,
            valid=row.valid_rows,
            warning=row.warning_rows,
            error=row.error_rows,
            created=row.created_rows,
            skipped=row.skipped_rows,
        ),
        created_by=row.created_by,
        created_at=row.created_at,
        finished_at=row.finished_at,
    )


def _record(row: ImportRowOrm) -> ImportRowRecord:
    return ImportRowRecord(
        row_id=row.id,
        row_number=row.row_number,
        resource_type=row.resource_type,
        status=RowStatus(row.status),
        issues=tuple(ImportIssue(code) for code in row.issue_codes),
        patient_id=row.patient_id,
    )


@final
class ImportBatchRepository(ImportBatchRepositoryPort):
    """``clinic.import_batches`` and ``clinic.import_rows``.

    Pattern: P06 Adapter is not used here; this is the plain repository of the
    slice (the ORM rows are mapped to domain values in both directions).
    """

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def add_batch(self, batch: ImportBatch) -> None:
        session = self._current.get()
        totals = batch.totals
        session.add(
            ImportBatchOrm(
                id=batch.batch_id,
                clinic_id=batch.clinic_id,
                source_format=batch.source_format.value,
                data_origin=batch.data_origin.value,
                status=batch.status.value,
                file_sha256=batch.file_sha256,
                file_size_bytes=batch.file_size_bytes,
                total_rows=totals.total,
                valid_rows=totals.valid,
                warning_rows=totals.warning,
                error_rows=totals.error,
                created_rows=totals.created,
                skipped_rows=totals.skipped,
                created_by=batch.created_by,
                created_at=batch.created_at,
                finished_at=batch.finished_at,
            )
        )
        session.flush()

    @override
    def get_batch(self, batch_id: UUID) -> ImportBatch | None:
        row = self._current.get().get(ImportBatchOrm, batch_id)
        return None if row is None else _batch(row)

    @override
    def complete(self, batch: ImportBatch) -> None:
        session = self._current.get()
        row = session.get(ImportBatchOrm, batch.batch_id)
        if row is None:
            raise ConflictError(DUPLICATE_REASON)
        totals = batch.totals
        row.status = batch.status.value
        row.created_rows = totals.created
        row.skipped_rows = totals.skipped
        row.finished_at = batch.finished_at
        session.flush()

    @override
    def add_rows(
        self, batch_id: UUID, rows: Sequence[StoredRow], *, clinic_id: UUID
    ) -> None:
        session = self._current.get()
        session.add_all(
            ImportRowOrm(
                clinic_id=clinic_id,
                batch_id=batch_id,
                row_number=row.row_number,
                resource_type=stored_resource_type(row.resource_type),
                status=row.status.value,
                issue_codes=[issue.value for issue in row.issues],
                patient_id=row.patient_id,
            )
            for row in rows
        )
        session.flush()

    @override
    def list_batches(
        self, filters: BatchFilter, page: PageRequest
    ) -> Page[ImportBatch]:
        statement = select(ImportBatchOrm).order_by(ImportBatchOrm.id.desc())
        if filters.source is not None:
            statement = statement.where(
                ImportBatchOrm.source_format == filters.source.value
            )
        if page.after is not None:
            statement = statement.where(ImportBatchOrm.id < page.after)
        rows = self._current.get().scalars(statement.limit(page.limit + 1)).all()
        return build_page(
            [_batch(row) for row in rows],
            limit=page.limit,
            key=lambda batch: batch.batch_id,
        )

    @override
    def list_rows(
        self, batch_id: UUID, status: RowStatus | None, page: PageRequest
    ) -> Page[ImportRowRecord]:
        statement = (
            select(ImportRowOrm)
            .where(ImportRowOrm.batch_id == batch_id)
            .order_by(ImportRowOrm.row_number)
        )
        if status is not None:
            statement = statement.where(ImportRowOrm.status == status.value)
        if page.after is not None:
            # The cursor is the id of the last row seen: continue after its number.
            last_number = (
                select(ImportRowOrm.row_number)
                .where(ImportRowOrm.id == page.after)
                .scalar_subquery()
            )
            statement = statement.where(ImportRowOrm.row_number > last_number)
        rows = self._current.get().scalars(statement.limit(page.limit + 1)).all()
        return build_page(
            [_record(row) for row in rows],
            limit=page.limit,
            key=lambda record: record.row_id,
        )

    @override
    def rejected_rows(self, batch_id: UUID) -> Sequence[ImportRowRecord]:
        statement = (
            select(ImportRowOrm)
            .where(
                ImportRowOrm.batch_id == batch_id,
                ImportRowOrm.status == RowStatus.REJECTED.value,
            )
            .order_by(ImportRowOrm.row_number)
        )
        return [_record(row) for row in self._current.get().scalars(statement).all()]

    @override
    def existing_identities(
        self, *, mrns: frozenset[str], document_hashes: frozenset[str]
    ) -> ExistingIdentities:
        session = self._current.get()
        known_mrns: frozenset[str] = frozenset()
        known_hashes: frozenset[str] = frozenset()
        if mrns:
            known_mrns = frozenset(
                session.scalars(
                    select(PatientOrm.mrn).where(PatientOrm.mrn.in_(mrns))
                ).all()
            )
        if document_hashes:
            known_hashes = frozenset(
                session.scalars(
                    select(PatientOrm.document_hash).where(
                        PatientOrm.document_hash.in_(document_hashes)
                    )
                ).all()
            )
        return ExistingIdentities(mrns=known_mrns, document_hashes=known_hashes)


@final
class PatientAccountWriter(PatientAccountWriterPort):
    """Creates the user (IMPORTED, no password), its PATIENT membership and the patient.

    The MRN and the document hash are unique per clinic: a duplicate that
    appeared after the preview is a ``409``, which rolls the batch back.
    """

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def create_imported(
        self,
        patient: StagedPatient,
        *,
        clinic_id: UUID,
        batch_id: UUID,
        now: datetime,
    ) -> None:
        session = self._current.get()
        role_id = session.scalars(
            select(RoleOrm.id).where(RoleOrm.code == PATIENT_ROLE)
        ).one()
        try:
            session.add(
                UserOrm(
                    id=patient.user_id,
                    token_version=0,
                    status=IMPORTED_STATUS,
                    status_changed_at=now,
                    updated_at=now,
                )
            )
            session.flush()
            session.add(
                MembershipOrm(
                    id=patient.membership_id,
                    user_id=patient.user_id,
                    clinic_id=clinic_id,
                    role_id=role_id,
                    is_active=True,
                    updated_at=now,
                )
            )
            session.flush()
            session.add(
                PatientOrm(
                    id=patient.patient_id,
                    clinic_id=clinic_id,
                    user_id=patient.user_id,
                    mrn=patient.mrn,
                    full_name=patient.full_name,
                    birth_date=patient.birth_date,
                    sex=patient.sex.value,
                    diabetes_type=patient.diabetes_type.value,
                    contact_email=patient.contact_email,
                    contact_phone=patient.contact_phone,
                    document_type=patient.document_type.value,
                    document_hash=patient.document_hash,
                    document_hash_key_id=patient.document_hash_key_id,
                    document_ciphertext=patient.document_ciphertext,
                    document_key_id=patient.document_key_id,
                    document_last4=patient.document_last4,
                    import_batch_id=batch_id,
                    created_at=now,
                    updated_at=now,
                    lock_version=0,
                )
            )
            session.flush()
        except IntegrityError:
            raise ConflictError(DUPLICATE_REASON) from None
