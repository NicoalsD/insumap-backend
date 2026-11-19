"""``*Orm`` classes of the notification tables in the ``alerts`` schema.

They map ``insumap-database`` (Modelo de datos 9.5, Diccionario 8). Nothing here
creates or alters a table.
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CHAR,
    Boolean,
    DateTime,
    LargeBinary,
    SmallInteger,
    String,
    Time,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from insumap.infrastructure.persistence.orm import Base

ALERTS = {"schema": "alerts"}
UUIDV7 = text("uuidv7()")
NOW = text("now()")


class NotificationOrm(Base):
    __tablename__ = "notifications"
    __table_args__ = ALERTS

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, server_default=UUIDV7)
    clinic_id: Mapped[UUID | None] = mapped_column(Uuid)
    recipient_user_id: Mapped[UUID] = mapped_column(Uuid)
    notification_type: Mapped[str] = mapped_column(String(10))
    message_key: Mapped[str] = mapped_column(String(60))
    entity_type: Mapped[str | None] = mapped_column(String(20))
    entity_id: Mapped[UUID | None] = mapped_column(Uuid)
    alert_id: Mapped[UUID | None] = mapped_column(Uuid)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=NOW
    )


class NotificationDeliveryOrm(Base):
    __tablename__ = "notification_deliveries"
    __table_args__ = ALERTS

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, server_default=UUIDV7)
    clinic_id: Mapped[UUID] = mapped_column(Uuid)
    notification_id: Mapped[UUID] = mapped_column(Uuid)
    channel: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(20), server_default=text("'PENDING'"))
    attempts: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    last_error_code: Mapped[str | None] = mapped_column(String(40))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=NOW
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=NOW
    )


class PushSubscriptionOrm(Base):
    __tablename__ = "push_subscriptions"
    __table_args__ = ALERTS

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, server_default=UUIDV7)
    clinic_id: Mapped[UUID | None] = mapped_column(Uuid)
    user_id: Mapped[UUID] = mapped_column(Uuid)
    endpoint: Mapped[str] = mapped_column(String(2048))
    endpoint_hash: Mapped[str] = mapped_column(CHAR(64))
    p256dh: Mapped[str] = mapped_column(String(255))
    auth_ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    key_id: Mapped[str] = mapped_column(CHAR(16))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=NOW
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NotificationPreferenceOrm(Base):
    __tablename__ = "notification_preferences"
    __table_args__ = ALERTS

    user_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    clinic_id: Mapped[UUID | None] = mapped_column(Uuid)
    email_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    web_push_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    in_app_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    quiet_start: Mapped[time | None] = mapped_column(Time)
    quiet_end: Mapped[time | None] = mapped_column(Time)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=NOW
    )
