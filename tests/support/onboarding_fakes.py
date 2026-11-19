"""In-memory doubles of the patient import ports, for unit and API tests.

They keep the rules the database enforces (one clinic per session, unique MRN
and document hash per clinic) so the tests see the same outcomes.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import final, override
from uuid import UUID

from insumap.application.common.ids import IdGenerator
from insumap.application.common.pagination import Page, PageRequest, build_page
from insumap.application.onboarding.ports import (
    BatchFilter,
    ExistingIdentities,
    ImportBatchRepositoryPort,
    ImportRowRecord,
    KeyedDigest,
    PatientAccountWriterPort,
    PatientDocumentVaultPort,
    SealedDocument,
    StagedImportStorePort,
    StagedPatient,
    StoredRow,
)
from insumap.domain.common.errors import ConflictError
from insumap.domain.onboarding.batch import ImportBatch
from insumap.domain.onboarding.vocabulary import DocumentType, RowStatus
from insumap.infrastructure.onboarding.adapters import OnboardingAdapters
from insumap.shared.time import Clock
from tests.support.identity_world import CLINIC

FAKE_KEY_ID: str = "f" * 16
FIXED_NOW: datetime = datetime(2026, 11, 19, 12, tzinfo=UTC)


@final
class FixedClock(Clock):
    """A clock that never moves."""

    def __init__(self, now: datetime = FIXED_NOW) -> None:
        self._now = now

    @override
    def now(self) -> datetime:
        return self._now


@final
class SequentialIds(IdGenerator):
    """Ids 1, 2, 3... (offset), for deterministic tests."""

    def __init__(self, offset: int = 1000) -> None:
        self._last = offset

    @override
    def new_id(self) -> UUID:
        self._last += 1
        return UUID(int=self._last)


@final
class FakeDocumentVault(PatientDocumentVaultPort):
    """A deterministic hash and a reversible 'seal'; for tests only."""

    @override
    def hash_document(
        self, *, clinic_id: UUID, document_type: DocumentType, document_number: str
    ) -> KeyedDigest:
        message = f"{clinic_id}|{document_type.value}|{document_number}"
        return KeyedDigest(
            value=hashlib.sha256(message.encode()).hexdigest(), key_id=FAKE_KEY_ID
        )

    @override
    def hash_key_id(self) -> str:
        return FAKE_KEY_ID

    @override
    def seal_document(
        self, *, patient_id: UUID, clinic_id: UUID, document_number: str
    ) -> SealedDocument:
        del patient_id, clinic_id
        return SealedDocument(ciphertext=document_number.encode(), key_id=FAKE_KEY_ID)


@dataclass
class FakePatient:
    """A patient the fake account writer created."""

    patient_id: UUID
    mrn: str
    document_hash: str
    batch_id: UUID
    user_status: str = "IMPORTED"


@final
class FakeAccountWriter(PatientAccountWriterPort):
    """Keeps created patients; a duplicate MRN or document is a ``409``."""

    def __init__(self) -> None:
        self.patients: list[FakePatient] = []

    @override
    def create_imported(
        self,
        patient: StagedPatient,
        *,
        clinic_id: UUID,
        batch_id: UUID,
        now: datetime,
    ) -> None:
        del clinic_id, now
        if any(
            known.mrn == patient.mrn or known.document_hash == patient.document_hash
            for known in self.patients
        ):
            raise ConflictError("patient_exists")
        self.patients.append(
            FakePatient(
                patient_id=patient.patient_id,
                mrn=patient.mrn,
                document_hash=patient.document_hash,
                batch_id=batch_id,
            )
        )


@dataclass
class FakeBatchRepository(ImportBatchRepositoryPort):
    """Batches and rows of one clinic; another clinic's batch is invisible."""

    accounts: FakeAccountWriter
    clinic_id: UUID = CLINIC.clinic_id
    batches: dict[UUID, ImportBatch] = field(default_factory=dict)
    rows: list[tuple[UUID, int, StoredRow, UUID]] = field(default_factory=list)
    _next_row_id: int = 0

    @override
    def add_batch(self, batch: ImportBatch) -> None:
        self.batches[batch.batch_id] = batch

    @override
    def get_batch(self, batch_id: UUID) -> ImportBatch | None:
        batch = self.batches.get(batch_id)
        return (
            batch if batch is not None and batch.clinic_id == self.clinic_id else None
        )

    @override
    def complete(self, batch: ImportBatch) -> None:
        self.batches[batch.batch_id] = batch

    @override
    def add_rows(
        self, batch_id: UUID, rows: Sequence[StoredRow], *, clinic_id: UUID
    ) -> None:
        del clinic_id
        for row in rows:
            self._next_row_id += 1
            self.rows.append(
                (batch_id, row.row_number, row, UUID(int=self._next_row_id))
            )

    @override
    def list_batches(
        self, filters: BatchFilter, page: PageRequest
    ) -> Page[ImportBatch]:
        found = [
            batch
            for batch in sorted(
                self.batches.values(), key=lambda b: b.batch_id, reverse=True
            )
            if batch.clinic_id == self.clinic_id
            and (filters.source is None or batch.source_format is filters.source)
            and (page.after is None or batch.batch_id < page.after)
        ]
        return build_page(
            found[: page.limit + 1], limit=page.limit, key=lambda b: b.batch_id
        )

    @override
    def list_rows(
        self, batch_id: UUID, status: RowStatus | None, page: PageRequest
    ) -> Page[ImportRowRecord]:
        records = [self._record(entry) for entry in self._rows_of(batch_id, status)]
        records.sort(key=lambda record: record.row_number)
        if page.after is not None:
            after = next((r.row_number for r in records if r.row_id == page.after), 0)
            records = [record for record in records if record.row_number > after]
        return build_page(
            records[: page.limit + 1], limit=page.limit, key=lambda r: r.row_id
        )

    @override
    def rejected_rows(self, batch_id: UUID) -> Sequence[ImportRowRecord]:
        return [
            self._record(entry) for entry in self._rows_of(batch_id, RowStatus.REJECTED)
        ]

    @override
    def existing_identities(
        self, *, mrns: frozenset[str], document_hashes: frozenset[str]
    ) -> ExistingIdentities:
        return ExistingIdentities(
            mrns=frozenset(p.mrn for p in self.accounts.patients if p.mrn in mrns),
            document_hashes=frozenset(
                p.document_hash
                for p in self.accounts.patients
                if p.document_hash in document_hashes
            ),
        )

    def _rows_of(
        self, batch_id: UUID, status: RowStatus | None
    ) -> list[tuple[UUID, int, StoredRow, UUID]]:
        return [
            entry
            for entry in self.rows
            if entry[0] == batch_id and (status is None or entry[2].status is status)
        ]

    @staticmethod
    def _record(entry: tuple[UUID, int, StoredRow, UUID]) -> ImportRowRecord:
        _, number, row, row_id = entry
        return ImportRowRecord(
            row_id=row_id,
            row_number=number,
            resource_type=row.resource_type,
            status=row.status,
            issues=row.issues,
            patient_id=row.patient_id,
        )


@final
class FakeStagedStore(StagedImportStorePort):
    """Staged patients by batch id; no expiry in tests."""

    def __init__(self) -> None:
        self.entries: dict[UUID, tuple[StagedPatient, ...]] = {}

    @override
    def put(self, batch_id: UUID, patients: tuple[StagedPatient, ...]) -> None:
        self.entries[batch_id] = patients

    @override
    def peek(self, batch_id: UUID) -> tuple[StagedPatient, ...] | None:
        return self.entries.get(batch_id)

    @override
    def discard(self, batch_id: UUID) -> None:
        self.entries.pop(batch_id, None)


@dataclass
class OnboardingWorld:
    """The doubles of one import world, handed to ``Container`` as adapters."""

    accounts: FakeAccountWriter = field(default_factory=FakeAccountWriter)
    batches: FakeBatchRepository = field(init=False)
    vault: FakeDocumentVault = field(default_factory=FakeDocumentVault)
    staged: FakeStagedStore = field(default_factory=FakeStagedStore)

    def __post_init__(self) -> None:
        self.batches = FakeBatchRepository(accounts=self.accounts)

    def adapters(self) -> OnboardingAdapters:
        return OnboardingAdapters(
            batches=self.batches,
            accounts=self.accounts,
            vault=self.vault,
            staged=self.staged,
        )
