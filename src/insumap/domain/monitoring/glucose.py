"""Glucose readings: value in mg/dL, source, context and validation status."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, final, override
from uuid import UUID

from insumap.domain.common.rounding import round_half_up
from insumap.domain.monitoring.events import (
    GlucoseReadingRecorded,
    HypoglycemiaDetected,
    HypoglycemiaLevel,
)
from insumap.domain.monitoring.record import TimelineRecord
from insumap.shared.units import MG_DL_PER_MMOL_L

if TYPE_CHECKING:
    from insumap.domain.monitoring.clinical_event import ClinicalEventVisitor

MG_DL_DECIMALS = 1


class GlucoseUnit(StrEnum):
    """Units a person may type a glucose value in."""

    MG_DL = "mg/dL"
    MMOL_L = "mmol/L"


class ReadingSource(StrEnum):
    CGM = "CGM"
    SMBG = "SMBG"
    MANUAL = "MANUAL"


class ReadingContext(StrEnum):
    FASTING = "FASTING"
    PRE_MEAL = "PRE_MEAL"
    POST_MEAL = "POST_MEAL"
    BEDTIME = "BEDTIME"
    EXERCISE = "EXERCISE"
    OTHER = "OTHER"


class ReadingStatus(StrEnum):
    """Stored status: a suspicious reading is flagged, never hidden."""

    ACCEPTED = "ACCEPTED"
    FLAGGED = "FLAGGED"


class IssueCode(StrEnum):
    """Flags the validation chain leaves on a reading."""

    DUPLICATE_SUSPECTED = "DUPLICATE_SUSPECTED"
    IMPLAUSIBLE_RATE_OF_CHANGE = "IMPLAUSIBLE_RATE_OF_CHANGE"
    UNIT_MISMATCH_SUSPECTED = "UNIT_MISMATCH_SUSPECTED"


@final
@dataclass(frozen=True, slots=True)
class GlucoseValue:
    """A glucose value, always kept in mg/dL with one decimal."""

    mg_dl: Decimal

    @classmethod
    def from_input(cls, value: Decimal, unit: GlucoseUnit) -> GlucoseValue:
        """Normalize what the person typed; mmol/L is converted and rounded."""
        mg_dl = value if unit is GlucoseUnit.MG_DL else value * MG_DL_PER_MMOL_L
        return cls(round_half_up(mg_dl, MG_DL_DECIMALS))


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class GlucoseReading(TimelineRecord):
    """One glucose measurement. Pattern use: P21 element, P12 subject."""

    value_mg_dl: Decimal
    measured_at: datetime
    source: ReadingSource
    context: ReadingContext | None = None
    note: str | None = None
    status: ReadingStatus = ReadingStatus.ACCEPTED
    issues: tuple[IssueCode, ...] = ()

    @classmethod
    def record(  # noqa: PLR0913 - the columns of the row
        cls,
        *,
        reading_id: UUID,
        event_id: UUID,
        clinic_id: UUID,
        patient_id: UUID,
        client_reading_id: UUID,
        recorded_by: UUID,
        value: GlucoseValue,
        measured_at: datetime,
        source: ReadingSource,
        context: ReadingContext | None,
        note: str | None,
        issues: tuple[IssueCode, ...],
        now: datetime,
        sync_batch_id: UUID | None = None,
    ) -> GlucoseReading:
        """Create the reading; issues make it ``FLAGGED``."""
        return cls(
            id=reading_id,
            clinic_id=clinic_id,
            patient_id=patient_id,
            client_record_id=client_reading_id,
            recorded_by=recorded_by,
            received_at=now,
            sync_batch_id=sync_batch_id,
            value_mg_dl=value.mg_dl,
            measured_at=measured_at,
            source=source,
            context=context,
            note=note,
            issues=issues,
            status=ReadingStatus.FLAGGED if issues else ReadingStatus.ACCEPTED,
            pending_events=(
                GlucoseReadingRecorded(
                    event_id=event_id,
                    occurred_at=now,
                    reading_id=reading_id,
                    patient_id=patient_id,
                    clinic_id=clinic_id,
                ),
            ),
        )

    def revalidated(self, issues: tuple[IssueCode, ...]) -> GlucoseReading:
        """The same row with the issues of a new run of the chain."""
        return replace(
            self,
            issues=issues,
            status=ReadingStatus.FLAGGED if issues else ReadingStatus.ACCEPTED,
        )

    def with_hypoglycemia(
        self, level: HypoglycemiaLevel, *, event_id: UUID, now: datetime
    ) -> GlucoseReading:
        """Add ``HypoglycemiaDetected`` to the events published after commit."""
        event = HypoglycemiaDetected(
            event_id=event_id,
            occurred_at=now,
            reading_id=self.id,
            patient_id=self.patient_id,
            clinic_id=self.clinic_id,
            level=level,
        )
        return replace(self, pending_events=(*self.pending_events, event))

    @override
    def _stored_status(self) -> str:
        return self.status.value

    @property
    @override
    def occurred_at(self) -> datetime:
        return self.measured_at

    @override
    def accept[R](self, visitor: ClinicalEventVisitor[R]) -> R:
        return visitor.visit_glucose_reading(self)
