"""Ports of the patient import: batches, rows, staged patients and the vault.

Staged patients are the validated rows a preview keeps until the confirmation.
They hold names and contact data in clear (class C) and the document only as
ciphertext and hash: the plain document number is sealed before it is staged.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from insumap.application.common.pagination import Page, PageRequest
from insumap.domain.onboarding.batch import ImportBatch
from insumap.domain.onboarding.patient import ValidatedPatient
from insumap.domain.onboarding.vocabulary import (
    DiabetesType,
    DocumentType,
    ImportIssue,
    RowStatus,
    Sex,
    SourceFormat,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class KeyedDigest:
    """An HMAC of a document and the fingerprint of the key that made it."""

    value: str
    key_id: str


@dataclass(frozen=True, slots=True, kw_only=True)
class SealedDocument:
    """A document number under AES-256-GCM and the fingerprint of its key."""

    ciphertext: bytes
    key_id: str


class PatientDocumentVaultPort(ABC):
    """Hashes and seals identity documents; the plain number never leaves it."""

    @abstractmethod
    def hash_document(
        self, *, clinic_id: UUID, document_type: DocumentType, document_number: str
    ) -> KeyedDigest:
        """The lookup hash: a document is unique within its clinic."""

    @abstractmethod
    def hash_key_id(self) -> str:
        """Fingerprint of the key behind ``hash_document``."""

    @abstractmethod
    def seal_document(
        self, *, patient_id: UUID, clinic_id: UUID, document_number: str
    ) -> SealedDocument:
        """The document under AES-GCM, bound to its row by the associated data."""


@dataclass(frozen=True, slots=True, kw_only=True)
class StagedPatient:
    """A validated row waiting for its confirmation.

    The ids are fixed at preview: the sealed document binds to ``patient_id``.
    """

    row_number: int
    resource_type: str | None
    patient_id: UUID
    user_id: UUID
    membership_id: UUID
    mrn: str
    full_name: str
    birth_date: date
    document_type: DocumentType
    document_hash: str
    document_hash_key_id: str
    document_ciphertext: bytes
    document_key_id: str
    document_last4: str
    sex: Sex
    diabetes_type: DiabetesType
    contact_email: str | None
    contact_phone: str | None
    warnings: tuple[ImportIssue, ...] = ()

    @classmethod
    def of(
        cls,
        patient: ValidatedPatient,
        *,
        row_number: int,
        resource_type: str | None,
        ids: tuple[UUID, UUID, UUID],
        digest: KeyedDigest,
        sealed: SealedDocument,
        warnings: tuple[ImportIssue, ...],
    ) -> StagedPatient:
        """Staged form of a validated patient; the plain document is not kept."""
        patient_id, user_id, membership_id = ids
        return cls(
            row_number=row_number,
            resource_type=resource_type,
            patient_id=patient_id,
            user_id=user_id,
            membership_id=membership_id,
            mrn=patient.mrn,
            full_name=patient.full_name,
            birth_date=patient.birth_date,
            document_type=patient.document_type,
            document_hash=digest.value,
            document_hash_key_id=digest.key_id,
            document_ciphertext=sealed.ciphertext,
            document_key_id=sealed.key_id,
            document_last4=patient.document_last4,
            sex=patient.sex,
            diabetes_type=patient.diabetes_type,
            contact_email=patient.contact_email,
            contact_phone=patient.contact_phone,
            warnings=warnings,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class StoredRow:
    """A row to write to ``clinic.import_rows`` (write-once: never updated)."""

    row_number: int
    resource_type: str | None
    status: RowStatus
    issues: tuple[ImportIssue, ...] = ()
    patient_id: UUID | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ImportRowRecord:
    """A stored row as the API lists it."""

    row_id: UUID
    row_number: int
    resource_type: str | None
    status: RowStatus
    issues: tuple[ImportIssue, ...]
    patient_id: UUID | None


@dataclass(frozen=True, slots=True, kw_only=True)
class BatchFilter:
    """Filters of ``GET /imports`` (all optional)."""

    source: SourceFormat | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ExistingIdentities:
    """The MRNs and document hashes already in the clinic, of those asked for."""

    mrns: frozenset[str]
    document_hashes: frozenset[str]


class ImportBatchRepositoryPort(ABC):
    """Batches and rows of one clinic, under row level security."""

    @abstractmethod
    def add_batch(self, batch: ImportBatch) -> None:
        """Insert the batch in the current transaction."""

    @abstractmethod
    def get_batch(self, batch_id: UUID) -> ImportBatch | None:
        """One batch, or ``None`` when the session cannot see it."""

    @abstractmethod
    def complete(self, batch: ImportBatch) -> None:
        """Write the status, totals and finish time of a confirmed batch."""

    @abstractmethod
    def add_rows(
        self, batch_id: UUID, rows: Sequence[StoredRow], *, clinic_id: UUID
    ) -> None:
        """Insert the rows of a batch (never update them)."""

    @abstractmethod
    def list_batches(
        self, filters: BatchFilter, page: PageRequest
    ) -> Page[ImportBatch]:
        """A page of batches, most recent first."""

    @abstractmethod
    def list_rows(
        self, batch_id: UUID, status: RowStatus | None, page: PageRequest
    ) -> Page[ImportRowRecord]:
        """A page of the stored rows of a batch, in file order."""

    @abstractmethod
    def rejected_rows(self, batch_id: UUID) -> Sequence[ImportRowRecord]:
        """Every rejected row of a batch, for the error report."""

    @abstractmethod
    def existing_identities(
        self, *, mrns: frozenset[str], document_hashes: frozenset[str]
    ) -> ExistingIdentities:
        """Which of these MRNs and document hashes the clinic already has."""


class PatientAccountWriterPort(ABC):
    """Creates the account, the membership and the patient of one staged row."""

    @abstractmethod
    def create_imported(
        self, patient: StagedPatient, *, clinic_id: UUID, batch_id: UUID, now: datetime
    ) -> None:
        """Insert the user (IMPORTED), its membership and the patient."""


class StagedImportStorePort(ABC):
    """Holds the staged patients of a preview between the two requests."""

    @abstractmethod
    def put(self, batch_id: UUID, patients: tuple[StagedPatient, ...]) -> None:
        """Keep the staged patients of ``batch_id`` until they expire."""

    @abstractmethod
    def peek(self, batch_id: UUID) -> tuple[StagedPatient, ...] | None:
        """The staged patients, or ``None`` if they expired or never existed."""

    @abstractmethod
    def discard(self, batch_id: UUID) -> None:
        """Forget the staged patients of a confirmed batch."""


__all__ = [
    "BatchFilter",
    "ExistingIdentities",
    "ImportBatchRepositoryPort",
    "ImportRowRecord",
    "KeyedDigest",
    "PatientAccountWriterPort",
    "PatientDocumentVaultPort",
    "SealedDocument",
    "StagedImportStorePort",
    "StagedPatient",
    "StoredRow",
]
