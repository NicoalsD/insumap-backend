"""The clinic report use case: permission, rate limit, disclosure and the EXPORT row."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from insumap.application.access.ports import (
    AccessPurpose,
    DataAccessAction,
    DataResource,
)
from insumap.application.alerts.ports import AlertSummary
from insumap.application.alerts.queries import GetAlertSummaryUseCase
from insumap.application.common.actor import Actor
from insumap.application.patients.ports import PatientAdministrativeView
from insumap.application.patients.queries import ListPatientsUseCase
from insumap.application.reports.generate import (
    ClinicReportInput,
    GenerateClinicReportUseCase,
)
from insumap.application.reports.model import ReportFormat
from insumap.application.security.rate_limit import RateLimitCheck, RateLimitRule
from insumap.domain.clinic.clinic import Clinic, ClinicStatus
from insumap.domain.identity.account_state import AccountStatus
from insumap.domain.identity.errors import PermissionDeniedError
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role
from insumap.infrastructure.reports.adapter import ReportRenderingAdapter
from insumap.shared.i18n.message_catalog import MessageCatalog
from tests.support.access_fakes import InMemoryDataAccessLog
from tests.support.alerts_fakes import FakeAlertSummary
from tests.support.clinic_fakes import FakeClinics
from tests.support.fixed_clock import FixedClock
from tests.support.identity_fakes import FakeRateLimiter, FakeUnitOfWorkPort
from tests.support.patient_fakes import FakePatientRoster

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
CLINIC_ID = UUID(int=7000)
ADMIN = UUID(int=7001)
THRESHOLD = 5
RATE_LIMIT = 20
PERMISSIONS = frozenset(
    {
        PermissionCode.REPORTS_GENERATE_CLINIC,
        PermissionCode.PATIENTS_READ_ROSTER,
        PermissionCode.ALERTS_READ_SUMMARY,
    }
)


def _clinic() -> Clinic:
    return Clinic(
        clinic_id=CLINIC_ID,
        name="Clínica de prueba",
        tax_id="900000002",
        timezone="America/Bogota",
        status=ClinicStatus.ACTIVE,
        is_demo=False,
        created_at=NOW,
    )


def _actor(permissions: frozenset[PermissionCode] = PERMISSIONS) -> Actor:
    return Actor(
        user_id=ADMIN,
        clinic_id=CLINIC_ID,
        role=Role.CLINIC_ADMIN,
        permissions=permissions,
    )


def _view(index: int, status: AccountStatus) -> PatientAdministrativeView:
    return PatientAdministrativeView(
        patient_id=UUID(int=8000 + index),
        clinic_id=CLINIC_ID,
        full_name=f"Paciente {index}",
        mrn=f"MRN-{index}",
        document_last4="1234",
        account_status=status,
        primary_doctor_id=None,
        assigned_doctor_count=0,
        invitation_status=None,
        simulated=False,
    )


class Harness:
    def __init__(self, statuses: list[AccountStatus], alerts: int = 0) -> None:
        self.uow = FakeUnitOfWorkPort()
        self.limiter = FakeRateLimiter()
        self.log = InMemoryDataAccessLog()
        self.clock = FixedClock(NOW)
        roster = FakePatientRoster()
        roster.views = {}
        for index, status in enumerate(statuses):
            view = _view(index, status)
            roster.views[view.patient_id] = view
        clinics = FakeClinics(_clinic())
        patients = ListPatientsUseCase(
            uow=self.uow, roster=roster, access_log=self.log, clock=self.clock
        )
        summary = FakeAlertSummary(
            AlertSummary(open_count=alerts, escalated_count=0, by_care_team=())
        )
        self.use_case = GenerateClinicReportUseCase(
            uow=self.uow,
            clinics=clinics,
            log=self.log,
            patients=patients,
            alerts=GetAlertSummaryUseCase(uow=self.uow, summary=summary),
            rate_limit=RateLimitCheck(
                self.limiter,
                RateLimitRule(
                    family="exports_user_hour",
                    limit=RATE_LIMIT,
                    window=timedelta(hours=1),
                ),
            ),
            renderer=ReportRenderingAdapter(MessageCatalog.load_spanish()),
            clock=self.clock,
            small_count_threshold=THRESHOLD,
        )


def _html(harness: Harness, actor: Actor | None = None) -> str:
    rendered = harness.use_case.execute(
        ClinicReportInput(actor=actor or _actor(), output=ReportFormat.HTML)
    )
    return rendered.content.decode("utf-8")


def test_a_caller_without_the_permission_is_refused_before_the_rate_limit() -> None:
    harness = Harness([])

    with pytest.raises(PermissionDeniedError):
        harness.use_case.execute(
            ClinicReportInput(actor=_actor(frozenset()), output=ReportFormat.HTML)
        )

    assert harness.limiter.hits == []
    assert harness.log.granted == []


def test_the_export_is_logged_as_an_administration_export_of_the_report() -> None:
    harness = Harness([AccountStatus.ACTIVE] * THRESHOLD)

    _html(harness)

    # The roster walk leaves its own PATIENT_LIST read rows (P09); the export is one.
    [row] = [r for r in harness.log.granted if r.action is DataAccessAction.EXPORT]
    assert row.resource is DataResource.REPORT
    assert row.purpose is AccessPurpose.ADMINISTRATION
    assert row.patient_id is None
    assert row.clinic_id == CLINIC_ID


def test_a_group_below_the_threshold_is_hidden_and_zero_is_shown() -> None:
    harness = Harness([AccountStatus.ACTIVE, AccountStatus.ACTIVE])

    html = _html(harness)

    assert (
        MessageCatalog.load_spanish().render("report.small_count", threshold=THRESHOLD)
        in html
    )
    assert "<td>2</td>" not in html
    assert "<td>0</td>" in html


def test_the_activation_rate_is_withheld_for_a_small_clinic() -> None:
    harness = Harness([AccountStatus.ACTIVE] * 3)

    html = _html(harness)

    assert "Tasa de activación (%)" in html
    assert "<td>100.00</td>" not in html


def test_a_large_clinic_shows_its_exact_counts_and_rate() -> None:
    statuses = [AccountStatus.ACTIVE] * 8 + [AccountStatus.INVITED] * 2

    html = _html(Harness(statuses))

    assert "<td>10</td>" in html
    assert "<td>80.00</td>" in html
