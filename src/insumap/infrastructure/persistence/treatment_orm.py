"""``*Orm`` of the treatment tables (``care`` schema, API.md 8.7).

They only map the tables of ``insumap-database``; column names follow its
migrations and the data dictionary. Nothing here creates or alters a table.
"""

from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    DateTime,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Time,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from insumap.infrastructure.persistence.monitoring_orm import CARE, NOW, _id, _ts
from insumap.infrastructure.persistence.orm import Base


class ProtocolTemplateOrm(Base):
    __tablename__ = "protocol_templates"
    __table_args__ = CARE

    id: Mapped[UUID] = _id()
    clinic_id: Mapped[UUID | None] = mapped_column(Uuid)
    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(String(500))
    diabetes_type: Mapped[str | None] = mapped_column(String(5))
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(7))
    default_target_profile_id: Mapped[UUID | None] = mapped_column(Uuid)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_by: Mapped[UUID | None] = mapped_column(Uuid)
    activated_at: Mapped[datetime | None] = _ts(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=NOW
    )


class TreatmentPlanOrm(Base):
    __tablename__ = "treatment_plans"
    __table_args__ = CARE

    id: Mapped[UUID] = _id()
    clinic_id: Mapped[UUID] = mapped_column(Uuid)
    patient_id: Mapped[UUID] = mapped_column(Uuid)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(10))
    template_id: Mapped[UUID | None] = mapped_column(Uuid)
    previous_plan_id: Mapped[UUID | None] = mapped_column(Uuid)
    source_recommendation_id: Mapped[UUID | None] = mapped_column(Uuid)
    target_profile_id: Mapped[UUID] = mapped_column(Uuid)
    titration_rules: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True)
    )
    notes: Mapped[str | None] = mapped_column(String(1000))
    created_by: Mapped[UUID] = mapped_column(Uuid)
    activated_by: Mapped[UUID | None] = mapped_column(Uuid)
    activated_at: Mapped[datetime | None] = _ts(nullable=True)
    superseded_at: Mapped[datetime | None] = _ts(nullable=True)
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()
    lock_version: Mapped[int] = mapped_column(Integer)


class TreatmentPlanItemOrm(Base):
    __tablename__ = "treatment_plan_items"
    __table_args__ = CARE

    id: Mapped[UUID] = _id()
    clinic_id: Mapped[UUID] = mapped_column(Uuid)
    plan_id: Mapped[UUID] = mapped_column(Uuid)
    item_type: Mapped[str] = mapped_column(String(10))
    insulin_kind: Mapped[str | None] = mapped_column(String(10))
    name: Mapped[str] = mapped_column(String(120))
    dose_units: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    time_of_day: Mapped[time | None] = mapped_column(Time)
    days_of_week: Mapped[list[int] | None] = mapped_column(ARRAY(SmallInteger))
    instructions: Mapped[str | None] = mapped_column(String(500))
    sort_order: Mapped[int] = mapped_column(SmallInteger)


class TreatmentPlanSnapshotOrm(Base):
    __tablename__ = "treatment_plan_snapshots"
    __table_args__ = CARE

    id: Mapped[UUID] = _id()
    clinic_id: Mapped[UUID] = mapped_column(Uuid)
    plan_id: Mapped[UUID] = mapped_column(Uuid)
    snapshot_no: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    taken_by: Mapped[UUID] = mapped_column(Uuid)
    taken_at: Mapped[datetime] = _ts()
    reason: Mapped[str | None] = mapped_column(String(500))
