"""Repositories of the messaging tables, under row level security.

Every statement runs in the session of the open transaction, so the RLS context
of the use case applies: a patient reads its own thread, a doctor the threads of
his clinic (the assignment is checked before, by the access gate).
"""

from __future__ import annotations

from datetime import datetime
from typing import final, override
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from insumap.application.common.pagination import Page, PageRequest, build_page
from insumap.application.messaging.ports import (
    MessageThreadRepositoryPort,
    ThreadMessageRepositoryPort,
    ThreadReadRepositoryPort,
)
from insumap.domain.messaging.message import (
    MessageThread,
    SenderRole,
    ThreadMessage,
)
from insumap.infrastructure.persistence.messaging_orm import (
    MessageThreadOrm,
    ThreadMessageOrm,
    ThreadReadOrm,
)
from insumap.infrastructure.persistence.transactions import CurrentSession


def _thread(row: MessageThreadOrm) -> MessageThread:
    return MessageThread(
        thread_id=row.id,
        clinic_id=row.clinic_id,
        patient_id=row.patient_id,
        last_message_at=row.last_message_at,
    )


def _message(row: ThreadMessageOrm) -> ThreadMessage:
    return ThreadMessage(
        message_id=row.id,
        clinic_id=row.clinic_id,
        thread_id=row.thread_id,
        sender_user_id=row.sender_user_id,
        sender_role=SenderRole(row.sender_role),
        body=row.body,
        sent_at=row.sent_at,
    )


@final
class MessageThreadRepository(MessageThreadRepositoryPort):
    """One thread per patient; the unique index on ``patient_id`` decides the race."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def find_by_patient(self, patient_id: UUID) -> MessageThread | None:
        row = (
            self._current.get()
            .scalars(
                select(MessageThreadOrm).where(
                    MessageThreadOrm.patient_id == patient_id
                )
            )
            .first()
        )
        return None if row is None else _thread(row)

    @override
    def ensure(
        self, *, thread_id: UUID, clinic_id: UUID, patient_id: UUID
    ) -> MessageThread:
        session = self._current.get()
        session.execute(
            pg_insert(MessageThreadOrm)
            .values(id=thread_id, clinic_id=clinic_id, patient_id=patient_id)
            .on_conflict_do_nothing(index_elements=["patient_id"])
        )
        row = session.scalars(
            select(MessageThreadOrm).where(MessageThreadOrm.patient_id == patient_id)
        ).one()
        return _thread(row)

    @override
    def touch(self, thread_id: UUID, *, at: datetime) -> None:
        session = self._current.get()
        row = session.get(MessageThreadOrm, thread_id)
        if row is not None:
            row.last_message_at = at
            session.flush()


@final
class ThreadMessageRepository(ThreadMessageRepositoryPort):
    """Append-only: the messages are inserted and read, never updated or deleted."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def append(self, message: ThreadMessage) -> None:
        session = self._current.get()
        session.add(
            ThreadMessageOrm(
                id=message.message_id,
                clinic_id=message.clinic_id,
                thread_id=message.thread_id,
                sender_user_id=message.sender_user_id,
                sender_role=message.sender_role.value,
                body=message.body,
                sent_at=message.sent_at,
            )
        )
        session.flush()

    @override
    def list_for_thread(
        self, thread_id: UUID, page: PageRequest
    ) -> Page[ThreadMessage]:
        statement = select(ThreadMessageOrm).where(
            ThreadMessageOrm.thread_id == thread_id
        )
        if page.after is not None:
            statement = statement.where(ThreadMessageOrm.id < page.after)
        rows = self._current.get().scalars(
            statement.order_by(ThreadMessageOrm.id.desc()).limit(page.limit + 1)
        )
        return build_page(
            [_message(row) for row in rows],
            limit=page.limit,
            key=lambda message: message.message_id,
        )


@final
class ThreadReadRepository(ThreadReadRepositoryPort):
    """The read mark of each participant: one row per (thread, user)."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def mark_read(
        self, *, thread_id: UUID, user_id: UUID, clinic_id: UUID, at: datetime
    ) -> None:
        self._current.get().execute(
            pg_insert(ThreadReadOrm)
            .values(
                thread_id=thread_id,
                user_id=user_id,
                clinic_id=clinic_id,
                last_read_at=at,
            )
            .on_conflict_do_update(
                index_elements=["thread_id", "user_id"],
                set_={"last_read_at": at},
            )
        )
