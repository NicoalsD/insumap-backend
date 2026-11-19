"""A batch of patients to import: its rows' verdicts, totals and state."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID

from insumap.domain.identity.errors import InvalidStateTransitionError
from insumap.domain.onboarding.vocabulary import (
    BatchStatus,
    DataOrigin,
    ImportIssue,
    RowVerdict,
    SourceFormat,
)

MACHINE_NAME: str = "import_batch"


@dataclass(frozen=True, slots=True, kw_only=True)
class RowOutcome:
    """What the preview decided about one row, with the issues that explain it."""

    row_number: int
    resource_type: str | None
    verdict: RowVerdict
    issues: tuple[ImportIssue, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class ImportTotals:
    """Counters of a batch (the ``*_rows`` columns of ``clinic.import_batches``).

    ``valid`` and ``warning`` count rows that can become patients; ``error``
    counts rejected rows; ``skipped`` counts duplicates; ``created`` counts the
    patients a confirmation created. Unsupported rows only count in ``total``.
    """

    total: int = 0
    valid: int = 0
    warning: int = 0
    error: int = 0
    skipped: int = 0
    created: int = 0

    @classmethod
    def from_outcomes(cls, outcomes: Iterable[RowOutcome]) -> ImportTotals:
        """The counters of a preview."""
        total = valid = warning = error = skipped = 0
        for outcome in outcomes:
            total += 1
            if outcome.verdict is RowVerdict.VALID:
                valid += 1
            elif outcome.verdict is RowVerdict.WARNING:
                warning += 1
            elif outcome.verdict is RowVerdict.ERROR:
                error += 1
            elif outcome.verdict is RowVerdict.DUPLICATE:
                skipped += 1
        return cls(
            total=total, valid=valid, warning=warning, error=error, skipped=skipped
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ImportBatch:
    """One upload of patients for one clinic. The file itself is not kept."""

    batch_id: UUID
    clinic_id: UUID
    source_format: SourceFormat
    data_origin: DataOrigin
    status: BatchStatus
    file_sha256: str
    file_size_bytes: int
    totals: ImportTotals
    created_by: UUID
    created_at: datetime
    finished_at: datetime | None = None

    @property
    def simulated(self) -> bool:
        """Whether the rows are simulated data (only demo clinics accept them)."""
        return self.data_origin is DataOrigin.SIMULATED

    def require_previewed(self, action: str) -> None:
        """Only a previewed batch can be confirmed (``409`` otherwise)."""
        if self.status is not BatchStatus.PREVIEWED:
            raise InvalidStateTransitionError(MACHINE_NAME, self.status.value, action)

    def completed(self, *, totals: ImportTotals, at: datetime) -> ImportBatch:
        """The batch after its patients were created."""
        return replace(
            self, status=BatchStatus.COMPLETED, totals=totals, finished_at=at
        )
