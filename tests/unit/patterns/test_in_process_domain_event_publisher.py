"""Pattern: P17 Observer. Subscribers receive committed events by type."""

import logging
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from insumap.application.events.publisher import (
    EventSubscriber,
    InProcessDomainEventPublisher,
)
from insumap.domain.identity.events import PatientActivated

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)


class RecordingSubscriber(EventSubscriber[PatientActivated]):
    def __init__(self) -> None:
        self.received: list[PatientActivated] = []

    def handle(self, event: PatientActivated) -> None:
        self.received.append(event)


class FailingSubscriber(EventSubscriber[PatientActivated]):
    def handle(self, event: PatientActivated) -> None:
        raise RuntimeError("boom")


def make_event() -> PatientActivated:
    return PatientActivated(
        event_id=uuid4(),
        occurred_at=NOW,
        user_id=uuid4(),
        patient_id=uuid4(),
        clinic_id=uuid4(),
    )


def test_delivers_each_event_to_its_subscribers_in_order() -> None:
    publisher = InProcessDomainEventPublisher()
    first, second = RecordingSubscriber(), RecordingSubscriber()
    publisher.subscribe(PatientActivated, first)
    publisher.subscribe(PatientActivated, second)
    events = [make_event(), make_event()]

    publisher.publish_all(events)

    assert first.received == events
    assert second.received == events


def test_ignores_events_without_subscribers() -> None:
    InProcessDomainEventPublisher().publish_all([make_event()])


def test_a_failing_subscriber_does_not_stop_the_others(
    caplog: pytest.LogCaptureFixture,
) -> None:
    publisher = InProcessDomainEventPublisher()
    recording = RecordingSubscriber()
    publisher.subscribe(PatientActivated, FailingSubscriber())
    publisher.subscribe(PatientActivated, recording)

    with caplog.at_level(logging.ERROR):
        publisher.publish_all([make_event()])

    assert len(recording.received) == 1
    record = caplog.records[0]
    assert record.__dict__["event_type"] == "PatientActivated"
    assert "boom" not in record.getMessage()
