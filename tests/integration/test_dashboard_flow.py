"""Dashboard, notes, overview and KPIs over PostgreSQL, under row level security.

The clinic rows are inserted with a superuser connection (it bypasses RLS), as
the importer does. Every use case runs as ``insumap_app`` inside the transaction
context of its actor, so the database itself decides what each doctor sees.
"""

from typing import Any
from uuid import UUID

import psycopg
import pytest

from insumap.application.access.ports import DataResource
from insumap.application.clinic_kpis.queries import GetClinicKpisUseCase
from insumap.application.commands.transactional import (
    CurrentUnitOfWork,
    TransactionalCommandHandler,
)
from insumap.application.common.actor import Actor
from insumap.application.common.pagination import PageRequest
from insumap.application.common.unit_of_work import TransactionalUnitOfWorkPort
from insumap.application.dashboard.clinical_notes_queries import (
    ListClinicalNotesInput,
    ListClinicalNotesUseCase,
)
from insumap.application.dashboard.commands import (
    CreateClinicalNoteCommand,
    CreateClinicalNoteCommandHandler,
    MarkPatientReviewedCommand,
    MarkPatientReviewedCommandHandler,
)
from insumap.application.dashboard.triage_facade import (
    DoctorDashboardFacade,
    TriageInput,
)
from insumap.application.events.publisher import InProcessDomainEventPublisher
from insumap.application.metrics.metrics import MetricWindow
from insumap.application.monitoring.gate import AssignedPatientGate, OwnPatientGate
from insumap.application.overview.patient_overview_facade import PatientOverviewFacade
from insumap.domain.common.errors import ResourceNotFoundError
from insumap.domain.identity.errors import PermissionDeniedError
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role
from insumap.domain.metrics.target_strategy import GlycemicTargetStrategyRegistry
from insumap.infrastructure.alerts_adapters import build_alerts_adapters
from insumap.infrastructure.dashboard_adapters import build_dashboard_adapters
from insumap.infrastructure.identity_adapters import build_engine
from insumap.infrastructure.monitoring_adapters import build_monitoring_adapters
from insumap.infrastructure.persistence.activation_repositories import ConsentRepository
from insumap.infrastructure.persistence.dashboard_repositories import (
    ClinicKpiRepository,
)
from insumap.infrastructure.persistence.transactions import (
    CurrentSession,
    SqlTransactionFactory,
)
from insumap.infrastructure.security.uuid7 import Uuid7Generator
from insumap.infrastructure.targets_adapters import build_targets_adapters
from insumap.infrastructure.treatment_adapters import build_treatment_adapters
from insumap.shared.time import SystemClock
from tests.support.db_seed import DemoWorld
from tests.support.settings import make_settings

PATIENT_MRN = "DEMO-0001"
DASHBOARD = frozenset({PermissionCode.DASHBOARD_READ_ASSIGNED})
NOTES = frozenset(
    {PermissionCode.CLINICAL_NOTES_MANAGE, PermissionCode.PATIENTS_READ_ASSIGNED}
)


class Wiring:
    """The real ports over PostgreSQL, built the way the container builds them."""

    def __init__(self, app_url: str) -> None:
        settings = make_settings(database_url=app_url)
        self.current = CurrentSession()
        engine = build_engine(settings)
        transactions = SqlTransactionFactory(engine, self.current)
        self.uow = TransactionalUnitOfWorkPort(
            transactions, InProcessDomainEventPublisher()
        )
        self.clock = SystemClock.instance()
        self.ids = Uuid7Generator(self.clock)
        self.monitoring = build_monitoring_adapters(
            current=self.current, clock=self.clock, transactions=transactions
        )
        self.dashboard = build_dashboard_adapters(
            current=self.current, transactions=transactions
        )
        self.alerts = build_alerts_adapters(current=self.current)
        self.targets = build_targets_adapters(current=self.current)
        self.treatment = build_treatment_adapters(
            current=self.current, metrics_targets=self.monitoring.targets
        )

    def handler(self, inner: Any) -> TransactionalCommandHandler[Any, Any]:
        return TransactionalCommandHandler(inner, self.uow, CurrentUnitOfWork())

    def gate(self) -> AssignedPatientGate:
        return AssignedPatientGate(self.monitoring.patient_records)

    def facade(self) -> DoctorDashboardFacade:
        return DoctorDashboardFacade(
            uow=self.uow,
            roster=self.dashboard.roster,
            targets=self.monitoring.targets,
            series=self.monitoring.series,
            open_alerts=self.dashboard.open_alerts,
            reviews=self.dashboard.reviews,
            audit=self.dashboard.audit,
            strategies=GlycemicTargetStrategyRegistry(),
            clock=self.clock,
        )


def doctor(demo: DemoWorld, permissions: frozenset[PermissionCode]) -> Actor:
    return Actor(
        user_id=demo.doctor_user_id,
        clinic_id=demo.clinic_id,
        role=Role.DOCTOR,
        permissions=permissions,
        requires_mfa=True,
        mfa_verified=True,
    )


def _patient_id(conn: psycopg.Connection, clinic_id: UUID) -> UUID:
    row = conn.execute(
        "SELECT id FROM clinic.patients WHERE clinic_id = %s AND mrn = %s",
        (clinic_id, PATIENT_MRN),
    ).fetchone()
    assert row is not None
    found = row[0]
    assert isinstance(found, UUID)
    return found


@pytest.fixture
def assigned(migrated_url: str, demo_world: DemoWorld) -> UUID:
    """The demo patient, assigned to the demo doctor, with the clinic settings."""
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        patient = _patient_id(conn, demo_world.clinic_id)
        conn.execute(
            "INSERT INTO clinic.care_team_assignments (clinic_id, patient_id,"
            " doctor_user_id, is_primary, assigned_by) VALUES (%s, %s, %s, true, %s)",
            (
                demo_world.clinic_id,
                patient,
                demo_world.doctor_user_id,
                demo_world.admin_user_id,
            ),
        )
        conn.execute(
            "INSERT INTO care.target_profiles (clinic_id, code, label, population,"
            " version, status, is_default, range_low_mg_dl, range_high_mg_dl,"
            " very_low_mg_dl, very_high_mg_dl, tir_min_pct, tbr_l1_max_pct,"
            " tbr_l2_max_pct, tar_l1_max_pct, tar_l2_max_pct, cv_max_pct,"
            " min_data_sufficiency_pct, min_days, max_gap_minutes,"
            " hypo_episode_min_minutes, min_readings_for_cv,"
            " min_readings_for_cv_smbg, night_start, night_end, source_reference)"
            " VALUES (NULL, 'DASHBOARD_TEST', 'Perfil de prueba', 'ADULT', 1,"
            " 'ACTIVE', true, 70, 180, 54, 250, 70, 4, 1, 25, 5, 36, 70, 7, 15,"
            " 10, 50, 20, '00:00', '06:00', 'Fuente de prueba')"
        )
        conn.execute(
            "INSERT INTO clinic.clinic_settings (clinic_id,"
            " recommendation_expiry_hours, forecast_refresh_minutes,"
            " dropout_inactivity_days, kpi_min_cell_size)"
            " VALUES (%s, 24, 60, 14, 1)",
            (demo_world.clinic_id,),
        )
    return patient


def audit_rows(migrated_url: str, resource: str) -> int:
    with psycopg.connect(migrated_url) as conn:
        row = conn.execute(
            "SELECT count(*) FROM audit.data_access_log WHERE resource_type = %s",
            (resource,),
        ).fetchone()
    assert row is not None
    return int(row[0])


def test_the_assigned_doctor_sees_the_patient_and_each_listing_is_audited(
    migrated_url: str, app_url: str, demo_world: DemoWorld, assigned: UUID
) -> None:
    wiring = Wiring(app_url)
    before = audit_rows(migrated_url, DataResource.TRIAGE_LIST.value)

    page = wiring.facade().triage(
        TriageInput(
            actor=doctor(demo_world, DASHBOARD),
            window=MetricWindow.LAST_14_DAYS,
            reviewed=None,
            page=PageRequest(limit=20),
        )
    )

    assert [item.patient_id for item in page.items] == [assigned]
    assert audit_rows(migrated_url, DataResource.TRIAGE_LIST.value) == before + 1


def test_a_doctor_without_the_assignment_sees_nobody(
    migrated_url: str, app_url: str, demo_world: DemoWorld, assigned: UUID
) -> None:
    wiring = Wiring(app_url)
    stranger = Actor(
        user_id=UUID(int=0xBEEF),
        clinic_id=demo_world.clinic_id,
        role=Role.DOCTOR,
        permissions=DASHBOARD,
        requires_mfa=True,
        mfa_verified=True,
    )

    page = wiring.facade().triage(
        TriageInput(
            actor=stranger,
            window=MetricWindow.LAST_14_DAYS,
            reviewed=None,
            page=PageRequest(limit=20),
        )
    )

    assert page.items == []


def test_a_review_is_appended_and_the_patient_is_marked(
    migrated_url: str, app_url: str, demo_world: DemoWorld, assigned: UUID
) -> None:
    wiring = Wiring(app_url)
    handler = wiring.handler(
        MarkPatientReviewedCommandHandler(
            gate=wiring.gate(),
            reviews=wiring.dashboard.reviews,
            ids=wiring.ids,
            clock=wiring.clock,
        )
    )

    review = handler.handle(
        MarkPatientReviewedCommand(
            actor=doctor(
                demo_world,
                frozenset(
                    {
                        PermissionCode.DASHBOARD_READ_ASSIGNED,
                        PermissionCode.PATIENTS_READ_ASSIGNED,
                    }
                ),
            ),
            patient_id=assigned,
            window_days=14,
        )
    )

    assert review.patient_id == assigned
    with psycopg.connect(migrated_url) as conn:
        count = conn.execute(
            "SELECT count(*) FROM care.triage_reviews WHERE patient_id = %s",
            (assigned,),
        ).fetchone()
    assert count is not None and count[0] == 1


def test_a_note_is_appended_and_a_correction_points_at_it(
    migrated_url: str, app_url: str, demo_world: DemoWorld, assigned: UUID
) -> None:
    wiring = Wiring(app_url)
    create = wiring.handler(
        CreateClinicalNoteCommandHandler(
            gate=wiring.gate(),
            notes=wiring.dashboard.notes,
            ids=wiring.ids,
            clock=wiring.clock,
        )
    )
    actor = doctor(demo_world, NOTES)

    first = create.handle(
        CreateClinicalNoteCommand(
            actor=actor, patient_id=assigned, text="Primera", corrects_note_id=None
        )
    )
    second = create.handle(
        CreateClinicalNoteCommand(
            actor=actor,
            patient_id=assigned,
            text="Corregida",
            corrects_note_id=first.id,
        )
    )

    assert second.supersedes_id == first.id
    listed = ListClinicalNotesUseCase(
        uow=wiring.uow, gate=wiring.gate(), notes=wiring.dashboard.notes
    ).execute(
        ListClinicalNotesInput(
            actor=actor, patient_id=assigned, page=PageRequest(limit=20)
        )
    )
    assert [note.body for note in listed.items] == ["Primera", "Corregida"]


def test_a_note_on_another_patient_is_refused_and_the_note_is_not_written(
    migrated_url: str, app_url: str, demo_world: DemoWorld, assigned: UUID
) -> None:
    wiring = Wiring(app_url)
    create = wiring.handler(
        CreateClinicalNoteCommandHandler(
            gate=wiring.gate(),
            notes=wiring.dashboard.notes,
            ids=wiring.ids,
            clock=wiring.clock,
        )
    )
    with pytest.raises(ResourceNotFoundError):
        create.handle(
            CreateClinicalNoteCommand(
                actor=doctor(demo_world, NOTES),
                patient_id=UUID(int=0xFFFF),
                text="No debe guardarse",
                corrects_note_id=None,
            )
        )
    with psycopg.connect(migrated_url) as conn:
        row = conn.execute("SELECT count(*) FROM care.clinical_notes").fetchone()
    assert row is not None and row[0] == 0


def test_the_administrator_cannot_list_clinical_notes(
    app_url: str, demo_world: DemoWorld, assigned: UUID
) -> None:
    wiring = Wiring(app_url)
    admin = Actor(
        user_id=demo_world.admin_user_id,
        clinic_id=demo_world.clinic_id,
        role=Role.CLINIC_ADMIN,
        permissions=frozenset({PermissionCode.CLINIC_KPIS_READ}),
        requires_mfa=True,
        mfa_verified=True,
    )

    with pytest.raises(PermissionDeniedError):
        ListClinicalNotesUseCase(
            uow=wiring.uow, gate=wiring.gate(), notes=wiring.dashboard.notes
        ).execute(
            ListClinicalNotesInput(
                actor=admin, patient_id=assigned, page=PageRequest(limit=20)
            )
        )


def test_the_overview_reads_the_assigned_patient(
    app_url: str, demo_world: DemoWorld, assigned: UUID
) -> None:
    wiring = Wiring(app_url)
    overview = PatientOverviewFacade(
        uow=wiring.uow,
        assigned=wiring.gate(),
        own=OwnPatientGate(ConsentRepository(wiring.current)),
        targets=wiring.monitoring.targets,
        series=wiring.monitoring.series,
        readings=wiring.monitoring.readings,
        plans=wiring.treatment.plans,
        alerts=wiring.alerts.alerts,
        open_alerts=wiring.dashboard.open_alerts,
        reminders=wiring.targets.reminders,
        strategies=GlycemicTargetStrategyRegistry(),
        clock=wiring.clock,
    ).for_assigned(
        doctor(demo_world, frozenset({PermissionCode.PATIENTS_READ_ASSIGNED})),
        assigned,
        MetricWindow.LAST_14_DAYS,
    )

    assert overview.patient_id == assigned
    assert overview.open_alerts_count == 0


def test_the_clinic_kpis_count_the_patients_by_status(
    app_url: str, demo_world: DemoWorld, assigned: UUID
) -> None:
    wiring = Wiring(app_url)
    admin = Actor(
        user_id=demo_world.admin_user_id,
        clinic_id=demo_world.clinic_id,
        role=Role.CLINIC_ADMIN,
        permissions=frozenset({PermissionCode.CLINIC_KPIS_READ}),
        requires_mfa=True,
        mfa_verified=True,
    )

    kpis = GetClinicKpisUseCase(
        uow=wiring.uow,
        kpis=ClinicKpiRepository(wiring.current),
        alerts=wiring.alerts.summary,
    ).execute(admin)

    assert kpis.total_patients is not None and kpis.total_patients >= 1
    assert kpis.open_alerts == 0
