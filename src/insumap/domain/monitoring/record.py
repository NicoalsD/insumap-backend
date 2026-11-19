"""Base of every append-only patient record: corrections are new rows."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, fields, replace
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Self
from uuid import UUID

from insumap.domain.common.events import DomainEvent
from insumap.domain.identity.errors import InvalidStateTransitionError
from insumap.domain.monitoring.errors import ReasonRequiredError
from insumap.shared.field_limits import FieldLimits

if TYPE_CHECKING:
    from insumap.domain.monitoring.clinical_event import ClinicalEventVisitor

RECORD_MACHINE = "ClinicalRecord"
ACTIVE_STATUS = "ACTIVE"
NOT_CONTENT = frozenset(
    {
        "id",
        "received_at",
        "recorded_by",
        "sync_batch_id",
        "lifecycle",
        "pending_events",
        "status",
        "issues",
        "plan_id",
    }
)


class EntryType(StrEnum):
    """What a row is: the original, a correction or an annulment."""

    ORIGINAL = "ORIGINAL"
    CORRECTION = "CORRECTION"
    VOID = "VOID"


class RecordLifecycle(StrEnum):
    """Derived from the rows that point at this one; never stored."""

    CURRENT = "CURRENT"
    CORRECTED = "CORRECTED"
    VOIDED = "VOIDED"


class RecordType(StrEnum):
    """The ``record_type`` of the correction routes (path segment)."""

    READINGS = "readings"
    INSULIN_DOSES = "insulin-doses"
    MEALS = "meals"
    ACTIVITIES = "activities"
    SYMPTOMS = "symptoms"


def require_reason(reason: str | None) -> str:
    """The reason of a correction: 10 to 500 characters once stripped."""
    text = (reason or "").strip()
    if not FieldLimits.REASON_MIN_LENGTH <= len(text) <= FieldLimits.REASON_MAX_LENGTH:
        raise ReasonRequiredError
    return text


@dataclass(frozen=True, slots=True, kw_only=True)
class ClinicalRecord(ABC):
    """Common columns of the ``monitoring`` rows of a patient.

    A row is never edited: ``corrected`` and ``voided`` return a new row that
    points at the original with ``supersedes_id``.
    """

    id: UUID
    clinic_id: UUID
    patient_id: UUID
    client_record_id: UUID
    recorded_by: UUID
    received_at: datetime
    entry_type: EntryType = EntryType.ORIGINAL
    supersedes_id: UUID | None = None
    correction_reason: str | None = None
    sync_batch_id: UUID | None = None
    lifecycle: RecordLifecycle = RecordLifecycle.CURRENT
    pending_events: tuple[DomainEvent, ...] = field(default=())

    @property
    @abstractmethod
    def occurred_at(self) -> datetime:
        """When the thing happened, the key of the listings and the timeline."""

    def has_same_content(self, other: ClinicalRecord) -> bool:
        """``True`` if ``other`` carries the same values (a repeated request).

        Identity, audit and derived columns are not content: the id, the
        reception time, the author, the batch, the lifecycle, the validation
        status and the plan active at the time.
        """
        return type(self) is type(other) and all(
            getattr(self, item.name) == getattr(other, item.name)
            for item in fields(self)
            if item.name not in NOT_CONTENT
        )

    @property
    def display_status(self) -> str:
        """What the API shows: ``CORRECTED``/``VOIDED`` once superseded."""
        if self.lifecycle is not RecordLifecycle.CURRENT:
            return self.lifecycle.value
        return self._stored_status()

    def _stored_status(self) -> str:
        """Status of a row nobody superseded; rows without one are ``ACTIVE``."""
        return ACTIVE_STATUS

    def corrected(
        self,
        *,
        new_id: UUID,
        client_record_id: UUID,
        reason: str | None,
        now: datetime,
        recorded_by: UUID,
        **changes: Any,
    ) -> Self:
        """The correction row: this row with ``changes``, pointing back."""
        return self._supersede(
            EntryType.CORRECTION,
            new_id=new_id,
            client_record_id=client_record_id,
            reason=reason,
            now=now,
            recorded_by=recorded_by,
            changes=changes,
        )

    def voided(
        self,
        *,
        new_id: UUID,
        client_record_id: UUID,
        reason: str | None,
        now: datetime,
        recorded_by: UUID,
    ) -> Self:
        """The annulment row: it keeps the values (the columns are required)."""
        return self._supersede(
            EntryType.VOID,
            new_id=new_id,
            client_record_id=client_record_id,
            reason=reason,
            now=now,
            recorded_by=recorded_by,
            changes={},
        )

    def _supersede(
        self,
        entry_type: EntryType,
        *,
        new_id: UUID,
        client_record_id: UUID,
        reason: str | None,
        now: datetime,
        recorded_by: UUID,
        changes: dict[str, Any],
    ) -> Self:
        text = require_reason(reason)
        if (
            self.entry_type is EntryType.VOID
            or self.lifecycle is not RecordLifecycle.CURRENT
        ):
            raise InvalidStateTransitionError(
                RECORD_MACHINE, self.lifecycle.value, entry_type.value
            )
        return replace(
            self,
            **changes,
            id=new_id,
            client_record_id=client_record_id,
            received_at=now,
            recorded_by=recorded_by,
            entry_type=entry_type,
            supersedes_id=self.id,
            correction_reason=text,
            sync_batch_id=None,
            lifecycle=RecordLifecycle.CURRENT,
            pending_events=(),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class TimelineRecord(ClinicalRecord, ABC):
    """A record that appears in the timeline: glucose, dose, meal, activity, symptom."""

    @abstractmethod
    def accept[R](self, visitor: ClinicalEventVisitor[R]) -> R:
        """P21: let a visitor handle this kind of event."""
