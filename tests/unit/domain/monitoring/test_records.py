"""Glucose values, append-only corrections and the lab unit conversion."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from insumap.domain.identity.errors import InvalidStateTransitionError
from insumap.domain.monitoring.errors import ReasonRequiredError
from insumap.domain.monitoring.events import (
    GlucoseReadingRecorded,
    HypoglycemiaDetected,
    HypoglycemiaLevel,
)
from insumap.domain.monitoring.glucose import (
    GlucoseReading,
    GlucoseUnit,
    GlucoseValue,
    IssueCode,
    ReadingSource,
    ReadingStatus,
)
from insumap.domain.monitoring.record import (
    EntryType,
    RecordLifecycle,
    require_reason,
)
from insumap.domain.monitoring.records import LabUnit, hba1c_to_percent

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
GOOD_REASON = "El sensor estaba mal calibrado"


def uid(number: int) -> UUID:
    return UUID(int=number)


def reading(*issues: IssueCode) -> GlucoseReading:
    return GlucoseReading.record(
        reading_id=uid(1),
        event_id=uid(100),
        clinic_id=uid(2),
        patient_id=uid(3),
        client_reading_id=uid(4),
        recorded_by=uid(5),
        value=GlucoseValue.from_input(Decimal("110"), GlucoseUnit.MG_DL),
        measured_at=NOW,
        source=ReadingSource.SMBG,
        context=None,
        note=None,
        issues=issues,
        now=NOW,
    )


def test_mmol_l_is_converted_and_rounded_half_up() -> None:
    assert GlucoseValue.from_input(Decimal("5.5"), GlucoseUnit.MMOL_L).mg_dl == Decimal(
        "99.1"
    )
    assert GlucoseValue.from_input(Decimal("110.25"), GlucoseUnit.MG_DL).mg_dl == (
        Decimal("110.3")
    )


def test_a_reading_with_issues_is_flagged_and_without_them_accepted() -> None:
    assert reading().status is ReadingStatus.ACCEPTED
    flagged = reading(IssueCode.DUPLICATE_SUSPECTED)
    assert flagged.status is ReadingStatus.FLAGGED
    assert flagged.revalidated(()).status is ReadingStatus.ACCEPTED


def test_recording_queues_the_event_with_identifiers_only() -> None:
    event = reading().pending_events[0]

    assert isinstance(event, GlucoseReadingRecorded)
    assert (event.reading_id, event.patient_id, event.clinic_id) == (
        uid(1),
        uid(3),
        uid(2),
    )


def test_hypoglycemia_adds_a_second_event() -> None:
    marked = reading().with_hypoglycemia(
        HypoglycemiaLevel.LEVEL_2, event_id=uid(101), now=NOW
    )

    assert isinstance(marked.pending_events[1], HypoglycemiaDetected)
    assert marked.pending_events[1].level is HypoglycemiaLevel.LEVEL_2


def test_a_correction_is_a_new_row_that_points_at_the_original() -> None:
    original = reading()

    fixed = original.corrected(
        new_id=uid(9),
        client_record_id=uid(10),
        reason=GOOD_REASON,
        now=NOW,
        recorded_by=uid(5),
        value_mg_dl=Decimal("118"),
    )

    assert fixed.entry_type is EntryType.CORRECTION
    assert fixed.supersedes_id == original.id
    assert fixed.correction_reason == GOOD_REASON
    assert fixed.value_mg_dl == Decimal(118)
    assert original.value_mg_dl == Decimal(110)
    assert fixed.pending_events == ()


def test_an_annulment_keeps_the_values_of_the_original() -> None:
    voided = reading().voided(
        new_id=uid(9),
        client_record_id=uid(10),
        reason=GOOD_REASON,
        now=NOW,
        recorded_by=uid(5),
    )

    assert voided.entry_type is EntryType.VOID
    assert voided.value_mg_dl == Decimal(110)


@pytest.mark.parametrize(
    "lifecycle", [RecordLifecycle.CORRECTED, RecordLifecycle.VOIDED]
)
def test_a_superseded_row_cannot_be_corrected_again(
    lifecycle: RecordLifecycle,
) -> None:
    old = replace(reading(), lifecycle=lifecycle)

    with pytest.raises(InvalidStateTransitionError):
        old.voided(
            new_id=uid(9),
            client_record_id=uid(10),
            reason=GOOD_REASON,
            now=NOW,
            recorded_by=uid(5),
        )


def test_a_void_row_cannot_be_corrected() -> None:
    voided = reading().voided(
        new_id=uid(9),
        client_record_id=uid(10),
        reason=GOOD_REASON,
        now=NOW,
        recorded_by=uid(5),
    )

    with pytest.raises(InvalidStateTransitionError):
        voided.corrected(
            new_id=uid(11),
            client_record_id=uid(12),
            reason=GOOD_REASON,
            now=NOW,
            recorded_by=uid(5),
        )


@pytest.mark.parametrize("reason", [None, "", "corto", " " * 20, "x" * 501])
def test_a_reason_must_have_ten_to_five_hundred_characters(reason: str | None) -> None:
    with pytest.raises(ReasonRequiredError):
        require_reason(reason)


def test_a_reason_of_the_limits_is_accepted_and_stripped() -> None:
    assert require_reason("  " + "x" * 10 + "  ") == "x" * 10
    assert require_reason("x" * 500) == "x" * 500


def test_hba1c_percent_is_kept_and_mmol_per_mol_converted() -> None:
    assert hba1c_to_percent(Decimal("7.0"), LabUnit.PERCENT) == Decimal("7.0")
    # IFCC 53 mmol/mol is NGSP 7.0 %.
    assert hba1c_to_percent(Decimal(53), LabUnit.MMOL_PER_MOL) == Decimal("7.0")
