"""Transactions with the row level security context set by ``set_config``."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import final, override

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from insumap.application.common.unit_of_work import (
    Transaction,
    TransactionContext,
    TransactionFactory,
)

SET_CONTEXT = text(
    "SELECT set_config('app.clinic_id', :clinic_id, true), "
    "set_config('app.user_id', :user_id, true), "
    "set_config('app.role', :role, true)"
)
"""``set_config(..., true)`` is ``SET LOCAL`` with bind parameters: it lasts until
the end of the transaction and never leaks to the next one on the connection."""
NOT_SET = ""


SYSTEM_ROLE = "SYSTEM"


def _role_value(context: TransactionContext) -> str:
    """The ``app.role`` of the transaction: ``SYSTEM``, a role or nothing."""
    if context.system:
        return SYSTEM_ROLE
    return NOT_SET if context.role is None else context.role.value


@final
class CurrentSession:
    """The session of the transaction that is open in this thread of control.

    Repositories are built once; each call asks for the session of the
    transaction the use case opened. Outside a transaction there is none, so a
    repository can never run a statement without the RLS context.
    """

    def __init__(self) -> None:
        self._current: ContextVar[Session | None] = ContextVar(
            "insumap_current_session", default=None
        )

    def get(self) -> Session:
        """The session of the open transaction."""
        session = self._current.get()
        if session is None:
            raise RuntimeError("no transaction is open")
        return session

    @contextmanager
    def bind(self, session: Session) -> Iterator[None]:
        """Make ``session`` the current one for the block."""
        token = self._current.set(session)
        try:
            yield
        finally:
            self._current.reset(token)


@final
class SqlTransaction(Transaction):
    """A SQLAlchemy session as the unit of work sees it."""

    def __init__(self, session: Session) -> None:
        self._session = session

    @override
    def apply_context(self, context: TransactionContext) -> None:
        self._session.execute(
            SET_CONTEXT,
            {
                "clinic_id": NOT_SET
                if context.clinic_id is None
                else str(context.clinic_id),
                "user_id": NOT_SET if context.user_id is None else str(context.user_id),
                "role": _role_value(context),
            },
        )

    @override
    def commit(self) -> None:
        self._session.commit()

    @override
    def rollback(self) -> None:
        self._session.rollback()


@final
class SqlTransactionFactory(TransactionFactory):
    """Opens one session per transaction and releases the connection after."""

    def __init__(self, engine: Engine, current: CurrentSession) -> None:
        self._engine = engine
        self._current = current

    @override
    @contextmanager
    def open(self) -> Iterator[Transaction]:
        with (
            Session(self._engine, expire_on_commit=False) as session,
            self._current.bind(session),
        ):
            yield SqlTransaction(session)
