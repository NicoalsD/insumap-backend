"""Insulin, meals, activities, symptoms and lab results."""

from datetime import date
from decimal import Decimal

import pytest

from insumap.application.monitoring.data import (
    ActivityData,
    InsulinData,
    LabData,
    MealData,
    SymptomData,
)
from insumap.application.monitoring.ports import ClinicalRecordKind
from insumap.application.monitoring.records import (
    AssignedLabInput,
    RecordActivityUseCase,
    RecordInput,
    RecordInsulinDoseUseCase,
    RecordMealUseCase,
    RecordOwnLabResultUseCase,
    RecordPatientLabResultUseCase,
    RecordSymptomUseCase,
    RecordWriter,
)
from insumap.domain.identity.errors import ConsentRequiredError, PermissionDeniedError
from insumap.domain.monitoring.records import (
    ActivityIntensity,
    InsulinKind,
    LabOrigin,
    LabUnit,
    MealType,
)
from insumap.shared.errors import ErrorCode, InsumapError
from tests.support.monitoring_factories import NOW, PATIENT_ID, uid
from tests.support.monitoring_fakes import (
    OTHER_PATIENT_ID,
    RecordsWorld,
    doctor_actor,
    patient_actor,
)

INSULIN = InsulinData(
    administered_at=NOW,
    insulin_kind=InsulinKind.BASAL,
    product_name="Glargina",
    units=Decimal("12.5"),
)


@pytest.fixture
def world() -> RecordsWorld:
    return RecordsWorld()


def writer(world: RecordsWorld) -> RecordWriter:
    return RecordWriter(world.records)


def test_an_insulin_dose_keeps_what_the_patient_said_and_the_active_plan(
    world: RecordsWorld,
) -> None:
    use_case = RecordInsulinDoseUseCase(
        uow=world.uow,
        gate=world.own_gate,
        writer=writer(world),
        plans=world.plans,
        ids=world.ids,
        clock=world.clock,
    )

    recorded = use_case.execute(RecordInput(actor=patient_actor(), data=INSULIN))

    assert recorded.created
    assert recorded.record.units == Decimal("12.5")
    assert recorded.record.plan_id == uid(700)
    assert recorded.record.patient_id == PATIENT_ID
    assert world.uow.commits == 1
    assert len(world.records.rows[ClinicalRecordKind.INSULIN_DOSES]) == 1


def test_the_same_client_id_is_idempotent_and_a_changed_one_conflicts(
    world: RecordsWorld,
) -> None:
    use_case = RecordInsulinDoseUseCase(
        uow=world.uow,
        gate=world.own_gate,
        writer=writer(world),
        plans=world.plans,
        ids=world.ids,
        clock=world.clock,
    )
    first = use_case.execute(
        RecordInput(actor=patient_actor(), data=INSULIN, client_record_id=uid(9))
    )

    again = use_case.execute(
        RecordInput(actor=patient_actor(), data=INSULIN, client_record_id=uid(9))
    )
    assert not again.created
    assert again.record.id == first.record.id

    world.plans.plan_id = None  # a plan change is not a content change
    assert not use_case.execute(
        RecordInput(actor=patient_actor(), data=INSULIN, client_record_id=uid(9))
    ).created

    changed = InsulinData(
        administered_at=NOW,
        insulin_kind=InsulinKind.BASAL,
        product_name="Glargina",
        units=Decimal("13"),
    )
    with pytest.raises(InsumapError) as caught:
        use_case.execute(
            RecordInput(actor=patient_actor(), data=changed, client_record_id=uid(9))
        )
    assert caught.value.code is ErrorCode.CONFLICT
    assert len(world.records.rows[ClinicalRecordKind.INSULIN_DOSES]) == 1


def test_a_meal_and_an_activity_are_recorded(world: RecordsWorld) -> None:
    meal = RecordMealUseCase(
        uow=world.uow,
        gate=world.own_gate,
        writer=writer(world),
        ids=world.ids,
        clock=world.clock,
    ).execute(
        RecordInput(
            actor=patient_actor(),
            data=MealData(eaten_at=NOW, meal_type=MealType.LUNCH, carbs_g=Decimal(60)),
        )
    )
    activity = RecordActivityUseCase(
        uow=world.uow,
        gate=world.own_gate,
        writer=writer(world),
        ids=world.ids,
        clock=world.clock,
    ).execute(
        RecordInput(
            actor=patient_actor(),
            data=ActivityData(
                started_at=NOW,
                activity_type="Caminata",
                duration_min=30,
                intensity=ActivityIntensity.LOW,
            ),
        )
    )

    assert meal.record.carbs_g == Decimal(60)
    assert activity.record.duration_min == 30


def symptom_use_case(world: RecordsWorld) -> RecordSymptomUseCase:
    return RecordSymptomUseCase(
        uow=world.uow,
        gate=world.own_gate,
        writer=writer(world),
        catalog=world.catalog,
        ids=world.ids,
        clock=world.clock,
    )


def test_a_symptom_uses_the_catalog_and_tells_if_it_is_an_alarm(
    world: RecordsWorld,
) -> None:
    calm = symptom_use_case(world).execute(
        RecordInput(
            actor=patient_actor(),
            data=SymptomData(symptom_code="THIRST", occurred_at=NOW),
        )
    )
    alarm = symptom_use_case(world).execute(
        RecordInput(
            actor=patient_actor(),
            data=SymptomData(symptom_code="CONFUSION", occurred_at=NOW),
        )
    )

    assert not calm.record.symptom.is_alarm
    assert alarm.record.symptom.is_alarm


def test_a_symptom_outside_the_catalog_is_a_validation_error(
    world: RecordsWorld,
) -> None:
    with pytest.raises(InsumapError) as caught:
        symptom_use_case(world).execute(
            RecordInput(
                actor=patient_actor(),
                data=SymptomData(symptom_code="NOPE", occurred_at=NOW),
            )
        )

    assert caught.value.code is ErrorCode.VALIDATION_ERROR
    assert world.records.rows[ClinicalRecordKind.SYMPTOMS] == []


def test_a_self_reported_lab_result_is_normalized_to_percent(
    world: RecordsWorld,
) -> None:
    recorded = RecordOwnLabResultUseCase(
        uow=world.uow,
        gate=world.own_gate,
        writer=writer(world),
        ids=world.ids,
        clock=world.clock,
    ).execute(
        RecordInput(
            actor=patient_actor(),
            data=LabData(
                value=Decimal(53),
                unit=LabUnit.MMOL_PER_MOL,
                performed_on=date(2026, 11, 1),
            ),
        )
    )

    assert recorded.record.value_pct == Decimal("7.0")
    assert recorded.record.origin is LabOrigin.PATIENT_REPORTED


def patient_lab(world: RecordsWorld) -> RecordPatientLabResultUseCase:
    return RecordPatientLabResultUseCase(
        uow=world.uow,
        gate=world.assigned_gate,
        writer=writer(world),
        ids=world.ids,
        clock=world.clock,
    )


LAB = LabData(
    value=Decimal("7.2"), unit=LabUnit.PERCENT, performed_on=date(2026, 11, 1)
)


def test_an_assigned_doctor_records_a_lab_result_with_origin_lab(
    world: RecordsWorld,
) -> None:
    recorded = patient_lab(world).execute(
        AssignedLabInput(actor=doctor_actor(), patient_id=PATIENT_ID, data=LAB)
    )

    assert recorded.record.origin is LabOrigin.LAB
    assert recorded.record.recorded_by == doctor_actor().user_id
    assert recorded.record.patient_id == PATIENT_ID


def test_a_doctor_without_assignment_gets_not_found_and_nothing_is_saved(
    world: RecordsWorld,
) -> None:
    with pytest.raises(InsumapError) as caught:
        patient_lab(world).execute(
            AssignedLabInput(
                actor=doctor_actor(), patient_id=OTHER_PATIENT_ID, data=LAB
            )
        )

    assert caught.value.code is ErrorCode.NOT_FOUND
    assert world.records.rows[ClinicalRecordKind.LAB_RESULTS] == []


def test_a_doctor_without_the_permission_is_forbidden(world: RecordsWorld) -> None:
    with pytest.raises(PermissionDeniedError):
        patient_lab(world).execute(
            AssignedLabInput(
                actor=doctor_actor(permissions=frozenset()),
                patient_id=PATIENT_ID,
                data=LAB,
            )
        )


def test_consent_is_required_for_every_patient_write(world: RecordsWorld) -> None:
    world.consents.accepted = False
    use_case = RecordMealUseCase(
        uow=world.uow,
        gate=world.own_gate,
        writer=writer(world),
        ids=world.ids,
        clock=world.clock,
    )

    with pytest.raises(ConsentRequiredError):
        use_case.execute(
            RecordInput(
                actor=patient_actor(),
                data=MealData(
                    eaten_at=NOW, meal_type=MealType.SNACK, carbs_g=Decimal(10)
                ),
            )
        )
