"""Corrections and annulments: new rows that point at the original."""

from dataclasses import replace
from decimal import Decimal
from uuid import UUID

import pytest

from insumap.application.monitoring.corrections import (
    AnnulRecordInput,
    AnnulRecordUseCase,
    CorrectRecordInput,
    CorrectRecordUseCase,
)
from insumap.application.monitoring.data import GlucoseData, MealData
from insumap.domain.identity.errors import (
    InvalidStateTransitionError,
    PermissionDeniedError,
)
from insumap.domain.monitoring.errors import GlucoseOutOfRangeError, ReasonRequiredError
from insumap.domain.monitoring.glucose import (
    GlucoseReading,
    GlucoseUnit,
    IssueCode,
    ReadingSource,
)
from insumap.domain.monitoring.record import EntryType, RecordLifecycle, RecordType
from insumap.domain.monitoring.records import Meal, MealType
from insumap.shared.errors import ErrorCode, InsumapError
from tests.support.monitoring_factories import NOW, make_meal, make_reading
from tests.support.monitoring_fakes import RecordsWorld, patient_actor

REASON = "El sensor estaba mal calibrado"


@pytest.fixture
def world() -> RecordsWorld:
    return RecordsWorld()


def correct(world: RecordsWorld) -> CorrectRecordUseCase:
    return CorrectRecordUseCase(
        uow=world.uow,
        gate=world.own_gate,
        readings=world.readings,
        records=world.records,
        catalog=world.catalog,
        recorder=world.recorder,
        chain=world.chain,
        ids=world.ids,
        clock=world.clock,
    )


def annul(world: RecordsWorld) -> AnnulRecordUseCase:
    return AnnulRecordUseCase(
        uow=world.uow,
        gate=world.own_gate,
        readings=world.readings,
        records=world.records,
        ids=world.ids,
        clock=world.clock,
    )


def new_value(value: str = "125") -> GlucoseData:
    return GlucoseData(
        value=Decimal(value),
        unit=GlucoseUnit.MG_DL,
        measured_at=NOW,
        source=ReadingSource.SMBG,
    )


def test_a_correction_adds_a_row_and_the_original_shows_as_corrected(
    world: RecordsWorld,
) -> None:
    original = make_reading(1)
    world.readings.add(original)

    fixed = correct(world).execute(
        CorrectRecordInput(
            actor=patient_actor(),
            record_type=RecordType.READINGS,
            record_id=original.id,
            reason=REASON,
            data=new_value(),
        )
    )

    assert isinstance(fixed, GlucoseReading)
    assert fixed.supersedes_id == original.id
    assert fixed.entry_type is EntryType.CORRECTION
    assert fixed.value_mg_dl == Decimal(125)
    assert len(world.readings.rows) == 2
    assert world.readings.rows[0] == original
    refreshed = world.readings.get(original.patient_id, original.id)
    assert refreshed is not None
    assert refreshed.lifecycle is RecordLifecycle.CORRECTED
    assert refreshed.display_status == "CORRECTED"


def test_a_corrected_reading_goes_through_the_chain_again(world: RecordsWorld) -> None:
    original = make_reading(1)
    world.readings.add(original)

    with pytest.raises(GlucoseOutOfRangeError):
        correct(world).execute(
            CorrectRecordInput(
                actor=patient_actor(),
                record_type=RecordType.READINGS,
                record_id=original.id,
                reason=REASON,
                data=new_value("9"),
            )
        )
    assert len(world.readings.rows) == 1


def test_the_correction_is_flagged_by_the_chain_not_by_the_old_flags(
    world: RecordsWorld,
) -> None:
    flagged = make_reading(1, issues=(IssueCode.DUPLICATE_SUSPECTED,))
    world.readings.add(flagged)

    fixed = correct(world).execute(
        CorrectRecordInput(
            actor=patient_actor(),
            record_type=RecordType.READINGS,
            record_id=flagged.id,
            reason=REASON,
            data=new_value(),
        )
    )

    assert isinstance(fixed, GlucoseReading)
    assert fixed.issues == ()


def test_a_record_cannot_be_corrected_twice(world: RecordsWorld) -> None:
    original = make_reading(1)
    world.readings.add(original)
    request = CorrectRecordInput(
        actor=patient_actor(),
        record_type=RecordType.READINGS,
        record_id=original.id,
        reason=REASON,
        data=new_value(),
    )
    correct(world).execute(request)

    with pytest.raises(InvalidStateTransitionError):
        correct(world).execute(request)


def test_a_missing_or_short_reason_is_rejected(world: RecordsWorld) -> None:
    original = make_reading(1)
    world.readings.add(original)

    with pytest.raises(ReasonRequiredError):
        correct(world).execute(
            CorrectRecordInput(
                actor=patient_actor(),
                record_type=RecordType.READINGS,
                record_id=original.id,
                reason="corto",
                data=new_value(),
            )
        )


def test_someone_elses_or_unknown_record_is_not_found(world: RecordsWorld) -> None:
    stranger = replace(make_reading(1), patient_id=UUID(int=0xA2))
    world.readings.add(stranger)

    for record_id in (stranger.id, UUID(int=12345)):
        with pytest.raises(InsumapError) as caught:
            correct(world).execute(
                CorrectRecordInput(
                    actor=patient_actor(),
                    record_type=RecordType.READINGS,
                    record_id=record_id,
                    reason=REASON,
                    data=new_value(),
                )
            )
        assert caught.value.code is ErrorCode.NOT_FOUND


def test_other_record_types_are_corrected_and_annulled(world: RecordsWorld) -> None:
    meal = make_meal(3)
    world.records.add(meal)

    fixed = correct(world).execute(
        CorrectRecordInput(
            actor=patient_actor(),
            record_type=RecordType.MEALS,
            record_id=meal.id,
            reason=REASON,
            data=MealData(eaten_at=NOW, meal_type=MealType.DINNER, carbs_g=Decimal(80)),
        )
    )

    assert isinstance(fixed, Meal)
    assert fixed.meal_type is MealType.DINNER
    voided = annul(world).execute(
        AnnulRecordInput(
            actor=patient_actor(),
            record_type=RecordType.MEALS,
            record_id=fixed.id,
            reason=REASON,
        )
    )
    assert voided.entry_type is EntryType.VOID
    assert voided.supersedes_id == fixed.id


def test_annulling_a_reading_keeps_the_original_row(world: RecordsWorld) -> None:
    original = make_reading(1)
    world.readings.add(original)

    voided = annul(world).execute(
        AnnulRecordInput(
            actor=patient_actor(),
            record_type=RecordType.READINGS,
            record_id=original.id,
            reason=REASON,
        )
    )

    assert voided.entry_type is EntryType.VOID
    assert len(world.readings.rows) == 2
    refreshed = world.readings.get(original.patient_id, original.id)
    assert refreshed is not None
    assert refreshed.display_status == "VOIDED"
    with pytest.raises(InvalidStateTransitionError):
        annul(world).execute(
            AnnulRecordInput(
                actor=patient_actor(),
                record_type=RecordType.READINGS,
                record_id=original.id,
                reason=REASON,
            )
        )


def test_the_correction_values_must_match_the_record_type(world: RecordsWorld) -> None:
    meal = make_meal(3)
    world.records.add(meal)

    with pytest.raises(InsumapError) as caught:
        correct(world).execute(
            CorrectRecordInput(
                actor=patient_actor(),
                record_type=RecordType.MEALS,
                record_id=meal.id,
                reason=REASON,
                data=new_value(),
            )
        )

    assert caught.value.code is ErrorCode.VALIDATION_ERROR


def test_it_needs_the_correct_permission(world: RecordsWorld) -> None:
    with pytest.raises(PermissionDeniedError):
        annul(world).execute(
            AnnulRecordInput(
                actor=patient_actor(permissions=frozenset()),
                record_type=RecordType.READINGS,
                record_id=UUID(int=1),
                reason=REASON,
            )
        )
