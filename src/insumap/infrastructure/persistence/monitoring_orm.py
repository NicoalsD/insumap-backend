"""``*Orm`` of the ``monitoring`` and ``care`` tables the records module reads.

They only map tables of ``insumap-database`` (names from the data dictionary,
sections 6 and 7); nothing here creates or alters a table.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from insumap.infrastructure.persistence.orm import Base

MONITORING = {"schema": "monitoring"}
CARE = {"schema": "care"}
UUIDV7 = text("uuidv7()")
NOW = text("now()")


def _id() -> Mapped[UUID]:
    return mapped_column(Uuid, primary_key=True, server_default=UUIDV7)


def _ts(*, nullable: bool = False) -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=nullable)


class RecordColumnsMixin:
    """Columns every append-only patient record table shares."""

    id: Mapped[UUID] = _id()
    clinic_id: Mapped[UUID] = mapped_column(Uuid)
    patient_id: Mapped[UUID] = mapped_column(Uuid)
    recorded_by: Mapped[UUID] = mapped_column(Uuid)
    sync_batch_id: Mapped[UUID | None] = mapped_column(Uuid)
    received_at: Mapped[datetime] = _ts()
    entry_type: Mapped[str] = mapped_column(String(10))
    supersedes_id: Mapped[UUID | None] = mapped_column(Uuid)
    correction_reason: Mapped[str | None] = mapped_column(String(500))


class SyncBatchOrm(Base):
    __tablename__ = "sync_batches"
    __table_args__ = MONITORING

    id: Mapped[UUID] = _id()
    clinic_id: Mapped[UUID] = mapped_column(Uuid)
    patient_id: Mapped[UUID] = mapped_column(Uuid)
    source: Mapped[str] = mapped_column(String(13))
    submitted_by: Mapped[UUID] = mapped_column(Uuid)
    total_items: Mapped[int] = mapped_column(Integer)
    created_count: Mapped[int] = mapped_column(Integer)
    duplicate_count: Mapped[int] = mapped_column(Integer)
    rejected_count: Mapped[int] = mapped_column(Integer)
    file_sha256: Mapped[str | None] = mapped_column(String(64))
    received_at: Mapped[datetime] = _ts()


class GlucoseReadingOrm(RecordColumnsMixin, Base):
    __tablename__ = "glucose_readings"
    __table_args__ = MONITORING

    client_reading_id: Mapped[UUID] = mapped_column(Uuid)
    measured_at: Mapped[datetime] = _ts()
    value_mg_dl: Mapped[Decimal] = mapped_column(Numeric(5, 1))
    source: Mapped[str] = mapped_column(String(6))
    context: Mapped[str | None] = mapped_column(String(10))
    note: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(8))


class ReadingIssueOrm(Base):
    __tablename__ = "reading_issues"
    __table_args__ = MONITORING

    id: Mapped[UUID] = _id()
    clinic_id: Mapped[UUID] = mapped_column(Uuid)
    reading_id: Mapped[UUID] = mapped_column(Uuid)
    issue_code: Mapped[str] = mapped_column(String(32))
    detail: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )


class InsulinDoseOrm(RecordColumnsMixin, Base):
    __tablename__ = "insulin_doses"
    __table_args__ = MONITORING

    client_record_id: Mapped[UUID] = mapped_column(Uuid)
    administered_at: Mapped[datetime] = _ts()
    insulin_kind: Mapped[str] = mapped_column(String(10))
    product_name: Mapped[str] = mapped_column(String(80))
    units: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    plan_id: Mapped[UUID | None] = mapped_column(Uuid)
    source: Mapped[str] = mapped_column(String(6), server_default="MANUAL")
    note: Mapped[str | None] = mapped_column(String(500))
    injection_site: Mapped[str | None] = mapped_column(String(14))
    injection_spot: Mapped[int | None] = mapped_column(SmallInteger)


class MealOrm(RecordColumnsMixin, Base):
    __tablename__ = "meals"
    __table_args__ = MONITORING

    client_record_id: Mapped[UUID] = mapped_column(Uuid)
    eaten_at: Mapped[datetime] = _ts()
    meal_type: Mapped[str] = mapped_column(String(9))
    carbs_g: Mapped[Decimal] = mapped_column(Numeric(5, 1))
    note: Mapped[str | None] = mapped_column(String(500))


class PhysicalActivityOrm(RecordColumnsMixin, Base):
    __tablename__ = "physical_activities"
    __table_args__ = MONITORING

    client_record_id: Mapped[UUID] = mapped_column(Uuid)
    started_at: Mapped[datetime] = _ts()
    activity_type: Mapped[str] = mapped_column(String(40))
    duration_min: Mapped[int] = mapped_column(SmallInteger)
    intensity: Mapped[str] = mapped_column(String(8))
    note: Mapped[str | None] = mapped_column(String(500))


class SymptomOrm(RecordColumnsMixin, Base):
    __tablename__ = "symptoms"
    __table_args__ = MONITORING

    client_record_id: Mapped[UUID] = mapped_column(Uuid)
    occurred_at: Mapped[datetime] = _ts()
    symptom_id: Mapped[UUID] = mapped_column(Uuid)
    note: Mapped[str | None] = mapped_column(String(500))


class LabResultOrm(RecordColumnsMixin, Base):
    __tablename__ = "lab_results"
    __table_args__ = MONITORING

    client_record_id: Mapped[UUID] = mapped_column(Uuid)
    test_code: Mapped[str] = mapped_column(String(8))
    performed_on: Mapped[date] = mapped_column(Date)
    value: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    unit: Mapped[str] = mapped_column(String(9))
    value_pct: Mapped[Decimal] = mapped_column(Numeric(4, 1))
    origin: Mapped[str] = mapped_column(String(16))


class SymptomCatalogOrm(Base):
    __tablename__ = "symptom_catalog"
    __table_args__ = CARE

    id: Mapped[UUID] = _id()
    clinic_id: Mapped[UUID | None] = mapped_column(Uuid)
    code: Mapped[str] = mapped_column(String(32))
    label_es: Mapped[str] = mapped_column(String(80))
    is_alarm: Mapped[bool] = mapped_column(Boolean)
    is_active: Mapped[bool] = mapped_column(Boolean)


class ReadingValidationSettingsOrm(Base):
    __tablename__ = "reading_validation_settings"
    __table_args__ = CARE

    id: Mapped[UUID] = _id()
    clinic_id: Mapped[UUID | None] = mapped_column(Uuid)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(7))
    min_measurable_mg_dl: Mapped[Decimal] = mapped_column(Numeric(5, 1))
    max_measurable_mg_dl: Mapped[Decimal] = mapped_column(Numeric(5, 1))
    future_tolerance_seconds: Mapped[int] = mapped_column(Integer)
    max_reading_age_hours: Mapped[int] = mapped_column(Integer)
    duplicate_window_seconds: Mapped[int] = mapped_column(Integer)
    max_rate_mg_dl_per_min: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    unit_mismatch_ratio: Mapped[Decimal] = mapped_column(Numeric(5, 2))
