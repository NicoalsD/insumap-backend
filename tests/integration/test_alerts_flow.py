"""Alerts over PostgreSQL: a rule, a reading, and the row level security.

The rows of the clinic are inserted with a superuser connection (it bypasses RLS),
as the importer does. Everything the application does runs as ``insumap_app``
under the transaction context of each actor, so RLS applies for real.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

import psycopg

from insumap.application.alerts.commands import (
    CreateAlertRuleCommand,
    CreateAlertRuleCommandHandler,
)
from insumap.application.alerts.evaluation import EvaluateAlertRulesOnReading
from insumap.application.alerts.ports import AlertFilter
from insumap.application.commands.transactional import (
    CurrentUnitOfWork,
    TransactionalCommandHandler,
)
from insumap.application.common.actor import Actor
from insumap.application.common.pagination import PageRequest
from insumap.application.common.unit_of_work import (
    TransactionalUnitOfWorkPort,
    TransactionContext,
)
from insumap.application.events.publisher import InProcessDomainEventPublisher
from insumap.domain.alerts.alert import AlertPriority, AlertType
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role
from insumap.domain.monitoring.events import GlucoseReadingRecorded
from insumap.infrastructure.alerts_adapters import build_alerts_adapters
from insumap.infrastructure.identity_adapters import build_engine
from insumap.infrastructure.persistence.transactions import (
    CurrentSession,
    SqlTransactionFactory,
)
from insumap.infrastructure.security.uuid7 import Uuid7Generator
from insumap.shared.time import SystemClock
from tests.support.db_seed import DemoWorld
from tests.support.settings import make_settings

PATIENT_MRN = "DEMO-0001"
CONDITION = {"kind": "THRESHOLD", "comparator": "LT", "value_mg_dl": 70}


def _patient_id(conn: psycopg.Connection, clinic_id: UUID) -> UUID:
    row = conn.execute(
        "SELECT id FROM clinic.patients WHERE clinic_id = %s AND mrn = %s",
        (clinic_id, PATIENT_MRN),
    ).fetchone()
    assert row is not None
    found = row[0]
    assert isinstance(found, UUID)
    return found


def _insert_reading(
    conn: psycopg.Connection,
    *,
    clinic_id: UUID,
    patient_id: UUID,
    recorded_by: UUID,
    value: str,
    measured_at: datetime,
) -> UUID:
    row = conn.execute(
        "INSERT INTO monitoring.glucose_readings (clinic_id, patient_id,"
        " recorded_by, received_at, client_reading_id, measured_at, value_mg_dl,"
        " source, status) VALUES (%s, %s, %s, now(), gen_random_uuid(), %s, %s,"
        " 'MANUAL', 'ACCEPTED') RETURNING id",
        (clinic_id, patient_id, recorded_by, measured_at, Decimal(value)),
    ).fetchone()
    assert row is not None
    found = row[0]
    assert isinstance(found, UUID)
    return found


def test_low_reading_opens_one_alert_visible_to_the_assigned_doctor(
    migrated_url: str, app_url: str, demo_world: DemoWorld
) -> None:
    clinic, admin = demo_world.clinic_id, demo_world.admin_user_id
    doctor, patient_user = demo_world.doctor_user_id, demo_world.patient_user_id
    now = SystemClock.instance().now()
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        patient = _patient_id(conn, clinic)
        conn.execute(
            "INSERT INTO clinic.care_team_assignments (clinic_id, patient_id,"
            " doctor_user_id, is_primary, assigned_by) VALUES (%s, %s, %s, true, %s)",
            (clinic, patient, doctor, admin),
        )
        reading = _insert_reading(
            conn,
            clinic_id=clinic,
            patient_id=patient,
            recorded_by=patient_user,
            value="60",
            measured_at=now - timedelta(minutes=5),
        )

    settings = make_settings(database_url=app_url)
    current = CurrentSession()
    engine = build_engine(settings)
    uow = TransactionalUnitOfWorkPort(
        SqlTransactionFactory(engine, current), InProcessDomainEventPublisher()
    )
    alerts = build_alerts_adapters(current=current)
    clock = SystemClock.instance()
    ids = Uuid7Generator(clock)
    admin_actor = Actor(
        user_id=admin,
        clinic_id=clinic,
        role=Role.CLINIC_ADMIN,
        permissions=frozenset({PermissionCode.ALERT_RULES_MANAGE}),
        requires_mfa=True,
        mfa_verified=True,
    )
    create = TransactionalCommandHandler(
        CreateAlertRuleCommandHandler(rules=alerts.rules, ids=ids, clock=clock),
        uow,
        CurrentUnitOfWork(),
    )
    rule = create.handle(
        CreateAlertRuleCommand(
            actor=admin_actor,
            name="Hipoglucemia nivel 1",
            alert_type=AlertType.HYPOGLYCEMIA,
            priority=AlertPriority.HIGH,
            level=1,
            condition=CONDITION,
            escalation=[
                {"level": 1, "recipient": "PRIMARY_DOCTOR", "wait_minutes": 15}
            ],
        )
    )
    subscriber = EvaluateAlertRulesOnReading(
        uow=uow,
        rules=alerts.rules,
        alerts=alerts.alerts,
        history=alerts.history,
        ids=ids,
        clock=clock,
    )
    event = GlucoseReadingRecorded(
        event_id=ids.new_id(),
        occurred_at=now,
        reading_id=reading,
        patient_id=patient,
        clinic_id=clinic,
    )

    subscriber.handle(event)
    subscriber.handle(event)  # a repeat of the same reading must not open a second one

    doctor_actor = TransactionContext(
        user_id=doctor, clinic_id=clinic, role=Role.DOCTOR
    )
    with uow.begin(doctor_actor):
        visible = alerts.alerts.list(AlertFilter(), PageRequest(limit=10))
    with uow.begin(
        TransactionContext(user_id=admin, clinic_id=clinic, role=Role.CLINIC_ADMIN)
    ):
        hidden = alerts.alerts.list(AlertFilter(), PageRequest(limit=10))

    [alert] = visible.items
    assert alert.rule_id == rule.rule_id
    assert alert.patient_id == patient
    assert alert.trigger_reading_id == reading
    assert alert.status.value == "OPEN"
    assert alert.next_escalation_at is not None and alert.next_escalation_at > now
    assert list(hidden.items) == []
