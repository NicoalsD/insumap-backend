"""Transactions of the use cases and the delivery of events after commit.

A use case never opens a database session: it asks the ``UnitOfWorkPort`` for a
``UnitOfWork`` scoped to a ``TransactionContext``. Infrastructure sets that
context inside the transaction (``app.clinic_id``, ``app.user_id`` and
``app.role`` with ``set_config(..., true)``) so row level security applies.
Leaving the block without ``commit()`` rolls the transaction back.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, final
from uuid import UUID

from insumap.domain.common.events import DomainEvent
from insumap.domain.identity.roles import Role

if TYPE_CHECKING:
    from insumap.application.common.actor import Actor
    from insumap.application.events.publisher import DomainEventPublisher
    from insumap.domain.identity.user import UserAccount


@dataclass(frozen=True, slots=True, kw_only=True)
class TransactionContext:
    """Row level security context of a transaction.

    The empty context is the one of the lookups that run before the clinic is
    known (login, activation, refresh); they go through ``SECURITY DEFINER``
    functions in the database.
    """

    user_id: UUID | None = None
    clinic_id: UUID | None = None
    role: Role | None = None
    system: bool = False
    """``True`` for the work of the system (a subscriber, a job): ``app.role = SYSTEM``.

    ``SYSTEM`` is not a ``Role``: it never comes from a token or ``iam.roles``.
    """

    @classmethod
    def anonymous(cls) -> TransactionContext:
        """Context of a request with no known user yet."""
        return cls()

    @classmethod
    def for_system(cls, clinic_id: UUID) -> TransactionContext:
        """Context of the system acting inside one clinic (no user, no role)."""
        return cls(clinic_id=clinic_id, system=True)

    @classmethod
    def for_actor(cls, actor: Actor) -> TransactionContext:
        """Context of an authenticated actor."""
        return cls(user_id=actor.user_id, clinic_id=actor.clinic_id, role=actor.role)

    @classmethod
    def for_account(cls, account: UserAccount) -> TransactionContext:
        """Provisional context once a lookup found the account."""
        return cls(
            user_id=account.user_id, clinic_id=account.clinic_id, role=account.role
        )


class Transaction(ABC):
    """A database transaction as seen by the unit of work."""

    @abstractmethod
    def apply_context(self, context: TransactionContext) -> None:
        """Set the row level security context for the rest of the transaction."""

    @abstractmethod
    def commit(self) -> None:
        """Make the changes durable."""

    @abstractmethod
    def rollback(self) -> None:
        """Discard the changes."""


class UnitOfWork(ABC):
    """One transaction of a use case."""

    @abstractmethod
    def apply_context(self, context: TransactionContext) -> None:
        """Switch to a provisional context after a pre-context lookup."""

    @abstractmethod
    def collect(self, events: Sequence[DomainEvent]) -> None:
        """Keep events to publish once the transaction commits."""

    @abstractmethod
    def commit(self) -> None:
        """Commit, then publish the collected events."""


class UnitOfWorkPort(ABC):
    """Opens units of work. Implemented by infrastructure."""

    @abstractmethod
    def begin(self, context: TransactionContext) -> AbstractContextManager[UnitOfWork]:
        """Open a transaction whose first statement sets ``context``."""


@final
class TransactionalUnitOfWork(UnitOfWork):
    """Unit of work over a ``Transaction``: events leave only after the commit.

    If the commit raises, nothing is published. A rollback drops the events.
    """

    def __init__(
        self, transaction: Transaction, publisher: DomainEventPublisher
    ) -> None:
        self._transaction = transaction
        self._publisher = publisher
        self._pending: list[DomainEvent] = []
        self._committed = False

    @property
    def committed(self) -> bool:
        """``True`` once ``commit()`` returned."""
        return self._committed

    def apply_context(self, context: TransactionContext) -> None:
        self._transaction.apply_context(context)

    def collect(self, events: Sequence[DomainEvent]) -> None:
        self._pending.extend(events)

    def commit(self) -> None:
        self._transaction.commit()
        self._committed = True
        events, self._pending = self._pending, []
        self._publisher.publish_all(events)

    def rollback(self) -> None:
        """Discard the transaction and its events (used when the block fails)."""
        self._pending = []
        self._transaction.rollback()


class TransactionFactory(ABC):
    """Opens database transactions. Implemented by infrastructure."""

    @abstractmethod
    def open(self) -> AbstractContextManager[Transaction]:
        """Open a transaction; the context manager releases it on exit."""


@final
class TransactionalUnitOfWorkPort(UnitOfWorkPort):
    """Opens a ``TransactionalUnitOfWork`` per use case.

    The context is applied as the first statement of the transaction, and a
    block that ends without ``commit()`` (normally or by an error) is rolled
    back, so nothing half done is ever kept.
    """

    def __init__(
        self, transactions: TransactionFactory, publisher: DomainEventPublisher
    ) -> None:
        self._transactions = transactions
        self._publisher = publisher

    @contextmanager
    def begin(self, context: TransactionContext) -> Iterator[UnitOfWork]:
        with self._transactions.open() as transaction:
            unit = TransactionalUnitOfWork(transaction, self._publisher)
            unit.apply_context(context)
            try:
                yield unit
            finally:
                if not unit.committed:
                    unit.rollback()
