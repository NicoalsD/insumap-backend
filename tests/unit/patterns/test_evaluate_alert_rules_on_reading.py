"""P17 Observer subscriber: a saved reading opens the alerts its rules raise."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from insumap.application.alerts.evaluation import EvaluateAlertRulesOnReading, effective_rules
from insumap.domain.alerts.alert import (
    AlertPriority,
    AlertRuleVersion,
    AlertType,
    RuleStatus,
)
from insumap.domain.alerts.escalation import parse_escalation
from insumap.domain.alerts.state import AlertStatus
from insumap.domain.metrics.window import GlucosePoint
from insumap.domain.monitoring.events import GlucoseReadingRecorded
from tests.support.alerts_fakes import FakeAlertRules, FakeAlerts, FakeGlucoseHistory
from tests.support.fixed_clock import FixedClock
from tests.support.identity_fakes import FakeIds, FakeUnitOfWorkPort

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
CLINIC = UUID(int=0xC1)
PATIENT = UUID(int=0xA1)
READING = UUID(int=0xE1)
RULE = UUID(int=0x77)
CONDITION = {
    "kind": "THRESHOLD",
    "comparator": "LT",
    "value_mg_dl": 70,
}


def rule(**overrides: object) -> AlertRuleVersion:
    values: dict[str, object] = {
        "rule_id": RULE,
        "clinic_id": CLINIC,
        "code": "RULE_TEST",
        "name": "Hipoglucemia",
        "alert_type": AlertType.HYPOGLYCEMIA,
        "level": 1,
        "priority": AlertPriority.HIGH,
        "condition": CONDITION,
        "escalation": parse_escalation(
            [{"level": 1, "recipient": "PRIMARY_DOCTOR", "wait_minutes": 15}]
        ),
        "version": 1,
        "status": RuleStatus.ACTIVE,
        "change_reason": None,
        "created_by": None,
        "created_at": NOW,
        "activated_at": NOW,
    }
    values.update(overrides)
    return AlertRuleVersion(**values)  # type: ignore[arg-type]


class Harness:
    def __init__(self, *rules: AlertRuleVersion) -> None:
        self.rules = FakeAlertRules(*rules)
        self.alerts = FakeAlerts()
        self.history = FakeGlucoseHistory()
        self.uow = FakeUnitOfWorkPort()
        self.subscriber = EvaluateAlertRulesOnReading(
            uow=self.uow,
            rules=self.rules,
            alerts=self.alerts,
            history=self.history,
            ids=FakeIds(),
            clock=FixedClock(NOW),
        )

    def save_reading(self, minutes: int, mg_dl: str) -> None:
        at = NOW + timedelta(minutes=minutes)
        self.history.record(PATIENT, READING, GlucosePoint(at=at, mg_dl=Decimal(mg_dl)))

    def publish(self) -> None:
        self.subscriber.handle(
            GlucoseReadingRecorded(
                event_id=UUID(int=1),
                occurred_at=NOW,
                reading_id=READING,
                patient_id=PATIENT,
                clinic_id=CLINIC,
            )
        )


def test_a_matching_reading_opens_one_open_alert() -> None:
    harness = Harness(rule())
    harness.save_reading(0, "65")

    harness.publish()

    [alert] = harness.alerts.rows.values()
    assert alert.status is AlertStatus.OPEN
    assert alert.patient_id == PATIENT
    assert alert.rule_id == RULE
    assert alert.trigger_reading_id == READING
    assert alert.next_escalation_at == NOW + timedelta(minutes=15)
    assert [h.to_status for h in harness.alerts.history_rows] == [AlertStatus.OPEN]


def test_a_reading_that_does_not_match_opens_nothing() -> None:
    harness = Harness(rule())
    harness.save_reading(0, "120")

    harness.publish()

    assert harness.alerts.rows == {}


def test_an_open_alert_of_the_same_rule_is_not_opened_again() -> None:
    harness = Harness(rule())
    harness.save_reading(0, "65")
    harness.publish()
    harness.save_reading(5, "60")

    harness.publish()

    assert len(harness.alerts.rows) == 1


def test_a_clinic_version_wins_over_a_seed_of_the_same_code() -> None:
    seed = rule(rule_id=UUID(int=0x10), clinic_id=None, code="RULE_SHARED")
    own = rule(rule_id=UUID(int=0x11), clinic_id=CLINIC, code="RULE_SHARED")

    chosen = effective_rules([seed, own])

    assert chosen == (own,)


def test_a_rule_with_an_unreadable_condition_is_skipped() -> None:
    harness = Harness(rule(condition={"kind": "UNKNOWN"}))
    harness.save_reading(0, "60")

    harness.publish()

    assert harness.alerts.rows == {}
