"""``DoctorDashboardFacade`` (P10): one list, risk order, one audit batch (P09)."""

from datetime import timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from insumap.application.access.ports import DataAccessOutcome, DataResource
from insumap.application.common.pagination import Page, PageRequest
from insumap.application.dashboard.ports import AssignedPatientRow
from insumap.application.dashboard.triage_facade import (
    DoctorDashboardFacade,
    TriageInput,
)
from insumap.application.metrics.metrics import MetricWindow
from insumap.domain.dashboard.triage import TriageAssessment, TriageFlag, TriageReview
from insumap.domain.identity.errors import PermissionDeniedError
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.metrics.target_strategy import GlycemicTargetStrategyRegistry
from tests.support.dashboard_fakes import (
    FakeAudit,
    FakeOpenAlerts,
    FakeReviews,
    FakeRoster,
)
from tests.support.metrics_factories import series
from tests.support.monitoring_factories import CLINIC_ID, NOW, PATIENT_ID
from tests.support.monitoring_fakes import (
    DOCTOR_ID,
    OTHER_PATIENT_ID,
    RecordsWorld,
    doctor_actor,
)


@pytest.fixture
def world() -> RecordsWorld:
    return RecordsWorld()


DASHBOARD = frozenset({PermissionCode.DASHBOARD_READ_ASSIGNED})
ROW_A = AssignedPatientRow(patient_id=PATIENT_ID, full_name="Paciente A")
ROW_B = AssignedPatientRow(patient_id=OTHER_PATIENT_ID, full_name="Paciente B")


def build(
    world: RecordsWorld,
    *,
    rows: list[AssignedPatientRow],
    alerts: dict[UUID, int] | None = None,
    reviews: FakeReviews | None = None,
    audit: FakeAudit | None = None,
) -> DoctorDashboardFacade:
    return DoctorDashboardFacade(
        uow=world.uow,
        roster=FakeRoster({DOCTOR_ID: rows}),
        targets=world.targets,
        series=world.series,
        open_alerts=FakeOpenAlerts(alerts or {}),
        reviews=reviews or FakeReviews(),
        audit=audit or FakeAudit(),
        strategies=GlycemicTargetStrategyRegistry(),
        clock=world.clock,
    )


def triage(
    facade: DoctorDashboardFacade,
    *,
    reviewed: bool | None = None,
    limit: int = 20,
    after: UUID | None = None,
) -> Page[TriageAssessment]:
    return facade.triage(
        TriageInput(
            actor=doctor_actor(permissions=DASHBOARD),
            window=MetricWindow.LAST_14_DAYS,
            reviewed=reviewed,
            page=PageRequest(limit=limit, after=after),
        )
    )


def test_a_patient_without_readings_is_flagged_and_listed(world: RecordsWorld) -> None:
    [item] = triage(build(world, rows=[ROW_A])).items

    assert item.patient_id == PATIENT_ID
    assert TriageFlag.NO_RECENT_READINGS in item.flags
    assert item.last_reading_at is None


def test_open_alerts_raise_a_flag_with_their_count(world: RecordsWorld) -> None:
    [item] = triage(build(world, rows=[ROW_A], alerts={PATIENT_ID: 2})).items

    assert item.open_alerts_count == 2
    assert TriageFlag.OPEN_ALERTS in item.flags


def test_the_most_urgent_patient_comes_first(world: RecordsWorld) -> None:
    # B has an open alert (one more flag); A has none. B is listed first.
    page = triage(build(world, rows=[ROW_A, ROW_B], alerts={OTHER_PATIENT_ID: 1}))

    assert [item.patient_id for item in page.items] == [OTHER_PATIENT_ID, PATIENT_ID]


def test_each_listed_patient_is_audited_in_one_batch(world: RecordsWorld) -> None:
    audit = FakeAudit()

    triage(build(world, rows=[ROW_A, ROW_B], audit=audit))

    assert audit.batches == [2]
    assert {r.patient_id for r in audit.granted} == {PATIENT_ID, OTHER_PATIENT_ID}
    assert all(r.resource is DataResource.TRIAGE_LIST for r in audit.granted)
    assert all(r.outcome is DataAccessOutcome.GRANTED for r in audit.granted)


def test_a_page_audits_only_the_patients_it_returns(world: RecordsWorld) -> None:
    audit = FakeAudit()

    page = triage(build(world, rows=[ROW_A, ROW_B], audit=audit), limit=1)

    assert len(page.items) == 1
    assert audit.batches == [1]
    assert page.next_cursor is not None


def test_the_next_page_starts_after_the_cursor_patient(world: RecordsWorld) -> None:
    facade = build(world, rows=[ROW_A, ROW_B])
    first = triage(facade, limit=1)
    second = triage(facade, limit=1, after=first.items[0].patient_id)

    assert [item.patient_id for item in second.items] != [first.items[0].patient_id]
    assert second.next_cursor is None


def test_a_review_holds_until_a_newer_reading_arrives(world: RecordsWorld) -> None:
    reviews = FakeReviews()
    reviews.add(
        TriageReview(
            id=UUID(int=9001),
            clinic_id=CLINIC_ID,
            patient_id=PATIENT_ID,
            reviewed_by=DOCTOR_ID,
            window_days=14,
            reviewed_at=NOW,
        )
    )
    # A reading before the review: the review still holds.
    world.series.points_by_patient[PATIENT_ID] = series(NOW - timedelta(days=1), [120])
    facade = build(world, rows=[ROW_A, ROW_B], reviews=reviews)

    assert [i.patient_id for i in triage(facade, reviewed=True).items] == [PATIENT_ID]
    assert [i.patient_id for i in triage(facade, reviewed=False).items] == [
        OTHER_PATIENT_ID
    ]


def test_the_list_needs_the_dashboard_permission(world: RecordsWorld) -> None:
    facade = build(world, rows=[ROW_A])

    with pytest.raises(PermissionDeniedError):
        facade.triage(
            TriageInput(
                actor=doctor_actor(permissions=frozenset()),
                window=MetricWindow.LAST_14_DAYS,
                reviewed=None,
                page=PageRequest(limit=20),
            )
        )
    assert world.uow.commits == 0


def test_the_window_average_is_a_decimal(world: RecordsWorld) -> None:
    world.series.points_by_patient[PATIENT_ID] = series(
        NOW - timedelta(days=1), [100, 110, 120, 130]
    )

    [item] = triage(build(world, rows=[ROW_A])).items

    assert isinstance(item.tir_pct, Decimal)
    assert item.last_reading_mg_dl == Decimal(130)
