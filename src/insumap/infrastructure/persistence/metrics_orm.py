"""``*Orm`` of the target profile tables the metrics read (``care`` schema).

They only map tables of ``insumap-database``; nothing here creates or alters one.
"""

from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Time,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from insumap.infrastructure.persistence.monitoring_orm import CARE, _id, _ts
from insumap.infrastructure.persistence.orm import Base


class TargetProfileOrm(Base):
    __tablename__ = "target_profiles"
    __table_args__ = CARE

    id: Mapped[UUID] = _id()
    clinic_id: Mapped[UUID | None] = mapped_column(Uuid)
    code: Mapped[str] = mapped_column(String(40))
    population: Mapped[str] = mapped_column(String(20))
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(7))
    is_default: Mapped[bool] = mapped_column(Boolean)
    range_low_mg_dl: Mapped[Decimal] = mapped_column(Numeric(5, 1))
    range_high_mg_dl: Mapped[Decimal] = mapped_column(Numeric(5, 1))
    very_low_mg_dl: Mapped[Decimal] = mapped_column(Numeric(5, 1))
    very_high_mg_dl: Mapped[Decimal] = mapped_column(Numeric(5, 1))
    tir_min_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    tbr_l1_max_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    tbr_l2_max_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    tar_l1_max_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    tar_l2_max_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    cv_max_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    min_data_sufficiency_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    min_days: Mapped[int] = mapped_column(SmallInteger)
    max_gap_minutes: Mapped[int] = mapped_column(SmallInteger)
    hypo_episode_min_minutes: Mapped[int] = mapped_column(SmallInteger)
    min_readings_for_cv: Mapped[int] = mapped_column(Integer)
    min_readings_for_cv_smbg: Mapped[int] = mapped_column(Integer)
    night_start: Mapped[time] = mapped_column(Time)
    night_end: Mapped[time] = mapped_column(Time)


class PatientTargetAssignmentOrm(Base):
    __tablename__ = "patient_target_assignments"
    __table_args__ = CARE

    id: Mapped[UUID] = _id()
    clinic_id: Mapped[UUID] = mapped_column(Uuid)
    patient_id: Mapped[UUID] = mapped_column(Uuid)
    target_profile_id: Mapped[UUID] = mapped_column(Uuid)
    assigned_at: Mapped[datetime] = _ts()
    ended_at: Mapped[datetime | None] = _ts(nullable=True)
