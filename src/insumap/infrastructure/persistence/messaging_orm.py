"""``*Orm`` of the messaging tables and of ``care.follow_ups``.

They only map tables of ``insumap-database`` (Diccionario de datos, sections 10
and 6); nothing here creates or alters a table. Each class is declared once.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from insumap.infrastructure.persistence.orm import Base

MESSAGING = {"schema": "messaging"}
CARE = {"schema": "care"}
UUIDV7 = text("uuidv7()")
NOW = text("now()")


def _id() -> Mapped[UUID]:
    return mapped_column(Uuid, primary_key=True, server_default=UUIDV7)


class MessageThreadOrm(Base):
    __tablename__ = "threads"
    __table_args__ = MESSAGING

    id: Mapped[UUID] = _id()
    clinic_id: Mapped[UUID] = mapped_column(Uuid)
    patient_id: Mapped[UUID] = mapped_column(Uuid)
    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=NOW
    )


class ThreadMessageOrm(Base):
    __tablename__ = "messages"
    __table_args__ = MESSAGING

    id: Mapped[UUID] = _id()
    clinic_id: Mapped[UUID] = mapped_column(Uuid)
    thread_id: Mapped[UUID] = mapped_column(Uuid)
    sender_user_id: Mapped[UUID] = mapped_column(Uuid)
    sender_role: Mapped[str] = mapped_column(String(7))
    body: Mapped[str] = mapped_column(String(1000))
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=NOW
    )


class ThreadReadOrm(Base):
    __tablename__ = "thread_reads"
    __table_args__ = MESSAGING

    thread_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    clinic_id: Mapped[UUID] = mapped_column(Uuid)
    last_read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class FollowUpOrm(Base):
    __tablename__ = "follow_ups"
    __table_args__ = CARE

    id: Mapped[UUID] = _id()
    clinic_id: Mapped[UUID] = mapped_column(Uuid)
    patient_id: Mapped[UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(9))
    scheduled_for: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    assigned_to: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    source: Mapped[str] = mapped_column(String(10))
    risk_assessment_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    title: Mapped[str] = mapped_column(String(120))
    result_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by: Mapped[UUID] = mapped_column(Uuid)
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=NOW
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=NOW
    )
