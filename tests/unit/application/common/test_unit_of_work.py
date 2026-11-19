from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from insumap.application.common.actor import Actor
from insumap.application.common.unit_of_work import (
    Transaction,
    TransactionalUnitOfWorkPort,
    TransactionContext,
    TransactionFactory,
)
from insumap.application.events.publisher import DomainEventPublisher
from insumap.domain.common.events import DomainEvent
from insumap.domain.identity.errors import PermissionDeniedError
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role


class FakeTransaction(Transaction):
    def __init__(self, journal: list[str], fail_commit: bool = False) -> None:
        self.journal = journal
        self.fail_commit = fail_commit

    def apply_context(self, context: TransactionContext) -> None:
        self.journal.append(f"context:{context.role}")

    def commit(self) -> None:
        if self.fail_commit:
            raise RuntimeError("commit failed")
        self.journal.append("commit")

    def rollback(self) -> None:
        self.journal.append("rollback")


class FakeFactory(TransactionFactory):
    def __init__(self, journal: list[str], fail_commit: bool = False) -> None:
        self.journal = journal
        self.fail_commit = fail_commit

    @contextmanager
    def open(self) -> Iterator[Transaction]:
        yield FakeTransaction(self.journal, self.fail_commit)


class FakePublisher(DomainEventPublisher):
    def __init__(self, journal: list[str]) -> None:
        self.journal = journal

    def publish_all(self, events: Sequence[DomainEvent]) -> None:
        self.journal.append(f"publish:{len(events)}")


def make_event() -> DomainEvent:
    return DomainEvent(event_id=uuid4(), occurred_at=datetime(2026, 1, 1, tzinfo=UTC))


def test_context_is_the_first_statement_and_events_leave_after_commit() -> None:
    journal: list[str] = []
    port = TransactionalUnitOfWorkPort(FakeFactory(journal), FakePublisher(journal))

    with port.begin(TransactionContext(role=Role.DOCTOR)) as uow:
        uow.collect([make_event()])
        journal.append("work")
        uow.commit()

    assert journal == ["context:DOCTOR", "work", "commit", "publish:1"]


def test_a_block_without_commit_rolls_back_and_drops_events() -> None:
    journal: list[str] = []
    port = TransactionalUnitOfWorkPort(FakeFactory(journal), FakePublisher(journal))

    with port.begin(TransactionContext.anonymous()) as uow:
        uow.collect([make_event()])

    assert journal == ["context:None", "rollback"]


def test_an_error_rolls_back() -> None:
    journal: list[str] = []
    port = TransactionalUnitOfWorkPort(FakeFactory(journal), FakePublisher(journal))

    with pytest.raises(ValueError), port.begin(TransactionContext.anonymous()):
        raise ValueError

    assert "rollback" in journal
    assert not any(item.startswith("publish") for item in journal)


def test_nothing_is_published_when_the_commit_fails() -> None:
    journal: list[str] = []
    port = TransactionalUnitOfWorkPort(
        FakeFactory(journal, fail_commit=True), FakePublisher(journal)
    )

    with pytest.raises(RuntimeError), port.begin(TransactionContext.anonymous()) as uow:
        uow.collect([make_event()])
        uow.commit()

    assert not any(item.startswith("publish") for item in journal)
    assert journal[-1] == "rollback"


def test_actor_denies_by_default() -> None:
    actor = Actor(user_id=uuid4(), clinic_id=uuid4(), role=Role.DOCTOR)

    with pytest.raises(PermissionDeniedError):
        actor.require(PermissionCode.USERS_READ)
    with pytest.raises(PermissionDeniedError):
        actor.own_patient_id()


def test_actor_allows_granted_permissions_and_uses_the_token_patient() -> None:
    patient_id = uuid4()
    actor = Actor(
        user_id=uuid4(),
        clinic_id=uuid4(),
        role=Role.PATIENT,
        permissions=frozenset({PermissionCode.PATIENTS_READ_OWN}),
        patient_id=patient_id,
    )

    actor.require(PermissionCode.PATIENTS_READ_OWN)
    assert actor.own_patient_id() == patient_id


def test_transaction_context_builders() -> None:
    actor = Actor(user_id=uuid4(), clinic_id=uuid4(), role=Role.DOCTOR)

    context = TransactionContext.for_actor(actor)

    assert (context.user_id, context.clinic_id, context.role) == (
        actor.user_id,
        actor.clinic_id,
        Role.DOCTOR,
    )
    assert TransactionContext.anonymous() == TransactionContext()
