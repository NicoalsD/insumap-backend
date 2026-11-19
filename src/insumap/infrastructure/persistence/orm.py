"""``*Orm`` classes: they only map tables of ``insumap-database``.

This repository never creates or alters tables. Names and types follow the
migrations of the schema tagged in ``db-schema.lock``.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Integer,
    LargeBinary,
    Numeric,
    SmallInteger,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, CIDR, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

IAM = {"schema": "iam"}
CLINIC = {"schema": "clinic"}
UUIDV7 = text("uuidv7()")
NOW = text("now()")


class Base(DeclarativeBase):
    """Declarative base. Nothing calls ``metadata.create_all``."""


def _id() -> Mapped[UUID]:
    return mapped_column(Uuid, primary_key=True, server_default=UUIDV7)


def _timestamp(*, nullable: bool = False) -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=nullable)


class RoleOrm(Base):
    __tablename__ = "roles"
    __table_args__ = IAM

    id: Mapped[UUID] = _id()
    code: Mapped[str] = mapped_column(String(32))
    requires_mfa: Mapped[bool] = mapped_column(Boolean)


class PermissionOrm(Base):
    __tablename__ = "permissions"
    __table_args__ = IAM

    id: Mapped[UUID] = _id()
    code: Mapped[str] = mapped_column(String(64))


class RolePermissionOrm(Base):
    __tablename__ = "role_permissions"
    __table_args__ = IAM

    role_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    permission_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)


class UserOrm(Base):
    __tablename__ = "users"
    __table_args__ = IAM

    id: Mapped[UUID] = _id()
    email: Mapped[str | None] = mapped_column(String(254))
    email_normalized: Mapped[str | None] = mapped_column(String(254))
    email_verified_at: Mapped[datetime | None] = _timestamp(nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    password_changed_at: Mapped[datetime | None] = _timestamp(nullable=True)
    token_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    status_reason: Mapped[str | None] = mapped_column(String(500))
    status_changed_at: Mapped[datetime] = _timestamp()
    updated_at: Mapped[datetime] = _timestamp()


class MembershipOrm(Base):
    __tablename__ = "memberships"
    __table_args__ = IAM

    id: Mapped[UUID] = _id()
    user_id: Mapped[UUID] = mapped_column(Uuid)
    clinic_id: Mapped[UUID | None] = mapped_column(Uuid)
    role_id: Mapped[UUID] = mapped_column(Uuid)
    is_active: Mapped[bool] = mapped_column(Boolean)
    ended_at: Mapped[datetime | None] = _timestamp(nullable=True)
    ended_reason: Mapped[str | None] = mapped_column(String(500))
    updated_at: Mapped[datetime] = _timestamp()


class CredentialInvitationOrm(Base):
    __tablename__ = "credential_invitations"
    __table_args__ = IAM

    id: Mapped[UUID] = _id()
    clinic_id: Mapped[UUID | None] = mapped_column(Uuid)
    user_id: Mapped[UUID] = mapped_column(Uuid)
    patient_id: Mapped[UUID | None] = mapped_column(Uuid)
    purpose: Mapped[str] = mapped_column(String(20))
    channel: Mapped[str] = mapped_column(String(5))
    status: Mapped[str] = mapped_column(String(8))
    code_hash: Mapped[str] = mapped_column(CHAR(64))
    code_key_id: Mapped[str] = mapped_column(CHAR(16))
    failed_attempts: Mapped[int] = mapped_column(SmallInteger)
    expires_at: Mapped[datetime] = _timestamp()
    issued_by: Mapped[UUID] = mapped_column(Uuid)
    issued_at: Mapped[datetime] = _timestamp()
    verified_at: Mapped[datetime | None] = _timestamp(nullable=True)
    used_at: Mapped[datetime | None] = _timestamp(nullable=True)
    revoked_at: Mapped[datetime | None] = _timestamp(nullable=True)
    revoked_by: Mapped[UUID | None] = mapped_column(Uuid)
    replaced_by_id: Mapped[UUID | None] = mapped_column(Uuid)
    delivery_status: Mapped[str] = mapped_column(String(14))


class AuthChallengeOrm(Base):
    __tablename__ = "auth_challenges"
    __table_args__ = IAM

    id: Mapped[UUID] = _id()
    purpose: Mapped[str] = mapped_column(String(18))
    token_hash: Mapped[str] = mapped_column(CHAR(64))
    user_id: Mapped[UUID] = mapped_column(Uuid)
    clinic_id: Mapped[UUID | None] = mapped_column(Uuid)
    invitation_id: Mapped[UUID | None] = mapped_column(Uuid)
    attempts: Mapped[int] = mapped_column(SmallInteger)
    max_attempts: Mapped[int] = mapped_column(SmallInteger)
    expires_at: Mapped[datetime] = _timestamp()
    consumed_at: Mapped[datetime | None] = _timestamp(nullable=True)


class RefreshTokenOrm(Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = IAM

    id: Mapped[UUID] = _id()
    user_id: Mapped[UUID] = mapped_column(Uuid)
    clinic_id: Mapped[UUID | None] = mapped_column(Uuid)
    family_id: Mapped[UUID] = mapped_column(Uuid)
    token_hash: Mapped[str] = mapped_column(CHAR(64))
    issued_at: Mapped[datetime] = _timestamp()
    expires_at: Mapped[datetime] = _timestamp()
    family_expires_at: Mapped[datetime] = _timestamp()
    revoked_at: Mapped[datetime | None] = _timestamp(nullable=True)
    revoked_reason: Mapped[str | None] = mapped_column(String(20))
    replaced_by_id: Mapped[UUID | None] = mapped_column(Uuid)


class MfaFactorOrm(Base):
    __tablename__ = "mfa_factors"
    __table_args__ = IAM

    id: Mapped[UUID] = _id()
    user_id: Mapped[UUID] = mapped_column(Uuid)
    factor_type: Mapped[str] = mapped_column(String(13))
    secret_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    code_hash: Mapped[str | None] = mapped_column(CHAR(64))
    key_id: Mapped[str] = mapped_column(CHAR(16))
    last_used_step: Mapped[int | None] = mapped_column(BigInteger)
    confirmed_at: Mapped[datetime | None] = _timestamp(nullable=True)
    used_at: Mapped[datetime | None] = _timestamp(nullable=True)
    revoked_at: Mapped[datetime | None] = _timestamp(nullable=True)


class PasswordHistoryOrm(Base):
    __tablename__ = "password_history"
    __table_args__ = IAM

    id: Mapped[UUID] = _id()
    user_id: Mapped[UUID] = mapped_column(Uuid)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = _timestamp()


class SecurityEventOrm(Base):
    __tablename__ = "security_events"
    __table_args__ = IAM

    id: Mapped[UUID] = _id()
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=NOW
    )
    event_type: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(8))
    user_id: Mapped[UUID | None] = mapped_column(Uuid)
    clinic_id: Mapped[UUID | None] = mapped_column(Uuid)
    ip_truncated: Mapped[Any | None] = mapped_column(CIDR)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))


class ClinicOrm(Base):
    __tablename__ = "clinics"
    __table_args__ = CLINIC

    id: Mapped[UUID] = _id()
    name: Mapped[str] = mapped_column(String(120))
    tax_id: Mapped[str] = mapped_column(String(32))
    timezone: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(9))
    suspended_at: Mapped[datetime | None] = _timestamp(nullable=True)
    suspended_reason: Mapped[str | None] = mapped_column(String(500))
    is_demo: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = _timestamp()
    updated_at: Mapped[datetime] = _timestamp()
    lock_version: Mapped[int] = mapped_column(Integer)


class StaffProfileOrm(Base):
    __tablename__ = "staff_profiles"
    __table_args__ = CLINIC

    user_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    clinic_id: Mapped[UUID] = mapped_column(Uuid)
    full_name: Mapped[str] = mapped_column(String(120))
    professional_license: Mapped[str | None] = mapped_column(String(40))
    specialty: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = _timestamp()
    updated_at: Mapped[datetime] = _timestamp()


class PatientOrm(Base):
    __tablename__ = "patients"
    __table_args__ = CLINIC

    id: Mapped[UUID] = _id()
    clinic_id: Mapped[UUID] = mapped_column(Uuid)
    user_id: Mapped[UUID] = mapped_column(Uuid)
    full_name: Mapped[str] = mapped_column(String(120))
    birth_date: Mapped[date] = mapped_column(Date)
    diabetes_type: Mapped[str] = mapped_column(String(5))
    contact_email: Mapped[str | None] = mapped_column(String(254))
    mrn: Mapped[str] = mapped_column(String(40))
    sex: Mapped[str] = mapped_column(String(7))
    contact_phone: Mapped[str | None] = mapped_column(String(32))
    document_type: Mapped[str] = mapped_column(String(3))
    document_hash: Mapped[str] = mapped_column(CHAR(64))
    document_hash_key_id: Mapped[str] = mapped_column(CHAR(16))
    document_ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    document_key_id: Mapped[str] = mapped_column(CHAR(16))
    document_last4: Mapped[str] = mapped_column(String(4))
    import_batch_id: Mapped[UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = _timestamp()
    updated_at: Mapped[datetime] = _timestamp()
    lock_version: Mapped[int] = mapped_column(Integer)
    bmi: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    pregnancy_status: Mapped[str] = mapped_column(String(8), server_default="UNKNOWN")


class ImportBatchOrm(Base):
    """``clinic.import_batches``: one upload; the file itself is never stored."""

    __tablename__ = "import_batches"
    __table_args__ = CLINIC

    id: Mapped[UUID] = _id()
    clinic_id: Mapped[UUID] = mapped_column(Uuid)
    source_format: Mapped[str] = mapped_column(String(4))
    data_origin: Mapped[str] = mapped_column(String(9))
    status: Mapped[str] = mapped_column(String(10))
    file_sha256: Mapped[str] = mapped_column(CHAR(64))
    file_size_bytes: Mapped[int] = mapped_column(Integer)
    simulator_version: Mapped[str | None] = mapped_column(String(40))
    total_rows: Mapped[int] = mapped_column(Integer)
    valid_rows: Mapped[int] = mapped_column(Integer)
    warning_rows: Mapped[int] = mapped_column(Integer)
    error_rows: Mapped[int] = mapped_column(Integer)
    created_rows: Mapped[int] = mapped_column(Integer)
    skipped_rows: Mapped[int] = mapped_column(Integer)
    created_by: Mapped[UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = _timestamp()
    finished_at: Mapped[datetime | None] = _timestamp(nullable=True)


class ImportRowOrm(Base):
    """``clinic.import_rows``: the result of one row; the raw row is never stored."""

    __tablename__ = "import_rows"
    __table_args__ = CLINIC

    id: Mapped[UUID] = _id()
    clinic_id: Mapped[UUID] = mapped_column(Uuid)
    batch_id: Mapped[UUID] = mapped_column(Uuid)
    row_number: Mapped[int] = mapped_column(Integer)
    resource_type: Mapped[str | None] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(17))
    issue_codes: Mapped[list[str]] = mapped_column(ARRAY(String(40)))
    mrn: Mapped[str | None] = mapped_column(String(40))
    patient_id: Mapped[UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=NOW
    )


class PrivacyNoticeVersionOrm(Base):
    __tablename__ = "privacy_notice_versions"
    __table_args__ = CLINIC

    id: Mapped[UUID] = _id()
    clinic_id: Mapped[UUID] = mapped_column(Uuid)
    version: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    effective_from: Mapped[datetime] = _timestamp()
    is_current: Mapped[bool] = mapped_column(Boolean)


class PatientConsentOrm(Base):
    __tablename__ = "patient_consents"
    __table_args__ = CLINIC

    id: Mapped[UUID] = _id()
    clinic_id: Mapped[UUID] = mapped_column(Uuid)
    patient_id: Mapped[UUID] = mapped_column(Uuid)
    privacy_notice_version_id: Mapped[UUID] = mapped_column(Uuid)
    scope: Mapped[str] = mapped_column(String(26))
    action: Mapped[str] = mapped_column(String(9))
    occurred_at: Mapped[datetime] = _timestamp()
    recorded_by: Mapped[UUID] = mapped_column(Uuid)


class SiteOrm(Base):
    __tablename__ = "sites"
    __table_args__ = CLINIC

    id: Mapped[UUID] = _id()
    clinic_id: Mapped[UUID] = mapped_column(Uuid)
    name: Mapped[str] = mapped_column(String(120))
    is_active: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = _timestamp()
    updated_at: Mapped[datetime] = _timestamp()


class StaffSiteOrm(Base):
    __tablename__ = "staff_sites"
    __table_args__ = CLINIC

    user_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    site_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    clinic_id: Mapped[UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = _timestamp()


class CareAssignmentOrm(Base):
    __tablename__ = "care_team_assignments"
    __table_args__ = CLINIC

    id: Mapped[UUID] = _id()
    clinic_id: Mapped[UUID] = mapped_column(Uuid)
    patient_id: Mapped[UUID] = mapped_column(Uuid)
    doctor_user_id: Mapped[UUID] = mapped_column(Uuid)
    is_primary: Mapped[bool] = mapped_column(Boolean)
    assigned_by: Mapped[UUID] = mapped_column(Uuid)
    assigned_at: Mapped[datetime] = _timestamp()
    ended_at: Mapped[datetime | None] = _timestamp(nullable=True)
    ended_by: Mapped[UUID | None] = mapped_column(Uuid)
    end_reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=NOW
    )


class LoginLockoutOrm(Base):
    __tablename__ = "login_lockouts"
    __table_args__ = IAM

    id: Mapped[UUID] = _id()
    scope: Mapped[str] = mapped_column(String(7))
    key_hmac: Mapped[str] = mapped_column(CHAR(64))
    level: Mapped[int] = mapped_column(SmallInteger)
    locked_until: Mapped[datetime | None] = _timestamp(nullable=True)
    last_failure_at: Mapped[datetime | None] = _timestamp(nullable=True)
    reset_at: Mapped[datetime | None] = _timestamp(nullable=True)
    updated_at: Mapped[datetime] = _timestamp()


ALERTS = {"schema": "alerts"}


class AlertRuleOrm(Base):
    __tablename__ = "alert_rules"
    __table_args__ = ALERTS

    id: Mapped[UUID] = _id()
    clinic_id: Mapped[UUID | None] = mapped_column(Uuid)
    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(120))
    alert_type: Mapped[str] = mapped_column(String(14))
    level: Mapped[int | None] = mapped_column(SmallInteger)
    priority: Mapped[str] = mapped_column(String(8))
    definition: Mapped[dict[str, Any]] = mapped_column(JSONB)
    escalation: Mapped[list[Any]] = mapped_column(JSONB)
    bypass_quiet_hours: Mapped[bool] = mapped_column(Boolean)
    patient_notice: Mapped[str | None] = mapped_column(String(300))
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(7))
    change_reason: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[UUID | None] = mapped_column(Uuid)
    activated_at: Mapped[datetime | None] = _timestamp(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=NOW
    )


class AlertOrm(Base):
    __tablename__ = "alerts"
    __table_args__ = ALERTS

    id: Mapped[UUID] = _id()
    clinic_id: Mapped[UUID] = mapped_column(Uuid)
    patient_id: Mapped[UUID] = mapped_column(Uuid)
    rule_id: Mapped[UUID] = mapped_column(Uuid)
    alert_type: Mapped[str] = mapped_column(String(14))
    level: Mapped[int | None] = mapped_column(SmallInteger)
    priority: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(12))
    escalation_level: Mapped[int] = mapped_column(SmallInteger)
    next_escalation_at: Mapped[datetime | None] = _timestamp(nullable=True)
    opened_at: Mapped[datetime] = _timestamp()
    trigger_reading_id: Mapped[UUID | None] = mapped_column(Uuid)
    forecast_id: Mapped[UUID | None] = mapped_column(Uuid)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB)
    is_fallback: Mapped[bool] = mapped_column(Boolean)
    acknowledged_by: Mapped[UUID | None] = mapped_column(Uuid)
    acknowledged_at: Mapped[datetime | None] = _timestamp(nullable=True)
    resolved_by: Mapped[UUID | None] = mapped_column(Uuid)
    resolved_at: Mapped[datetime | None] = _timestamp(nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(String(500))
    updated_at: Mapped[datetime] = _timestamp()
    lock_version: Mapped[int] = mapped_column(Integer)


class AlertStatusHistoryOrm(Base):
    __tablename__ = "alert_status_history"
    __table_args__ = ALERTS

    id: Mapped[UUID] = _id()
    clinic_id: Mapped[UUID] = mapped_column(Uuid)
    alert_id: Mapped[UUID] = mapped_column(Uuid)
    from_status: Mapped[str | None] = mapped_column(String(12))
    to_status: Mapped[str] = mapped_column(String(12))
    escalation_level: Mapped[int] = mapped_column(SmallInteger)
    actor_user_id: Mapped[UUID | None] = mapped_column(Uuid)
    actor_type: Mapped[str] = mapped_column(String(6))
    note: Mapped[str | None] = mapped_column(String(500))
    occurred_at: Mapped[datetime] = _timestamp()


CARE_SCHEMA = {"schema": "care"}


class ClinicalNoteOrm(Base):
    """``care.clinical_notes``: append only; ``body`` is the text of the note."""

    __tablename__ = "clinical_notes"
    __table_args__ = CARE_SCHEMA

    id: Mapped[UUID] = _id()
    clinic_id: Mapped[UUID] = mapped_column(Uuid)
    patient_id: Mapped[UUID] = mapped_column(Uuid)
    author_user_id: Mapped[UUID] = mapped_column(Uuid)
    body: Mapped[str] = mapped_column(String(2000))
    supersedes_id: Mapped[UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = _timestamp()


class TriageReviewOrm(Base):
    """``care.triage_reviews``: append only; the latest row of a doctor wins."""

    __tablename__ = "triage_reviews"
    __table_args__ = CARE_SCHEMA

    id: Mapped[UUID] = _id()
    clinic_id: Mapped[UUID] = mapped_column(Uuid)
    patient_id: Mapped[UUID] = mapped_column(Uuid)
    reviewed_by: Mapped[UUID] = mapped_column(Uuid)
    risk_assessment_id: Mapped[UUID | None] = mapped_column(Uuid)
    window_days: Mapped[int] = mapped_column(SmallInteger)
    reviewed_at: Mapped[datetime] = _timestamp()


class ClinicSettingsOrm(Base):
    """``clinic.clinic_settings``: the global row has a null ``clinic_id``."""

    __tablename__ = "clinic_settings"
    __table_args__ = CLINIC

    id: Mapped[UUID] = _id()
    clinic_id: Mapped[UUID | None] = mapped_column(Uuid)
    recommendation_expiry_hours: Mapped[int] = mapped_column(Integer)
    forecast_refresh_minutes: Mapped[int] = mapped_column(Integer)
    dropout_inactivity_days: Mapped[int] = mapped_column(Integer)
    kpi_min_cell_size: Mapped[int] = mapped_column(Integer)
    updated_by: Mapped[UUID | None] = mapped_column(Uuid)
    updated_at: Mapped[datetime] = _timestamp()
    lock_version: Mapped[int] = mapped_column(Integer)


AI = {"schema": "ai"}


class GlucoseForecastOrm(Base):
    """``ai.glucose_forecasts``: append only (IA1 output)."""

    __tablename__ = "glucose_forecasts"
    __table_args__ = AI

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    clinic_id: Mapped[UUID] = mapped_column(Uuid)
    patient_id: Mapped[UUID] = mapped_column(Uuid)
    mode: Mapped[str] = mapped_column(String(10))
    based_on_reading_id: Mapped[UUID | None] = mapped_column(Uuid)
    points: Mapped[list[Any]] = mapped_column(JSONB)
    hypo_probability: Mapped[list[Any]] = mapped_column(JSONB)
    hyper_probability: Mapped[list[Any]] = mapped_column(JSONB)
    target_profile_id: Mapped[UUID] = mapped_column(Uuid)
    model_name: Mapped[str] = mapped_column(String(80))
    model_version: Mapped[str] = mapped_column(String(80))
    input_hash: Mapped[str] = mapped_column(CHAR(64))
    explanation: Mapped[dict[str, Any]] = mapped_column(JSONB)
    is_fallback: Mapped[bool] = mapped_column(Boolean)
    fallback_reason: Mapped[str | None] = mapped_column(String(17))
    is_shadow: Mapped[bool] = mapped_column(Boolean)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RecommendationOrm(Base):
    """``ai.recommendations``: mutable, its status moves; decisions are appended."""

    __tablename__ = "recommendations"
    __table_args__ = AI

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    clinic_id: Mapped[UUID] = mapped_column(Uuid)
    patient_id: Mapped[UUID] = mapped_column(Uuid)
    plan_id: Mapped[UUID] = mapped_column(Uuid)
    applied_plan_id: Mapped[UUID | None] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(21))
    action: Mapped[str] = mapped_column(String(8))
    suggestion: Mapped[dict[str, Any]] = mapped_column(JSONB)
    requires_doctor_approval: Mapped[bool] = mapped_column(Boolean)
    target_profile_id: Mapped[UUID] = mapped_column(Uuid)
    proposed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    model_name: Mapped[str] = mapped_column(String(80))
    model_version: Mapped[str] = mapped_column(String(80))
    input_hash: Mapped[str] = mapped_column(CHAR(64))
    explanation: Mapped[dict[str, Any]] = mapped_column(JSONB)
    is_fallback: Mapped[bool] = mapped_column(Boolean)
    fallback_reason: Mapped[str | None] = mapped_column(String(17))
    is_shadow: Mapped[bool] = mapped_column(Boolean)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lock_version: Mapped[int] = mapped_column(Integer)


class RecommendationDecisionOrm(Base):
    """``ai.recommendation_decisions``: append only, one row per transition."""

    __tablename__ = "recommendation_decisions"
    __table_args__ = AI

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    clinic_id: Mapped[UUID] = mapped_column(Uuid)
    recommendation_id: Mapped[UUID] = mapped_column(Uuid)
    decision: Mapped[str] = mapped_column(String(21))
    decided_by: Mapped[UUID | None] = mapped_column(Uuid)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(String(500))
    reason_code: Mapped[str | None] = mapped_column(String(40))
    original_suggestion: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    modified_suggestion: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    model_version: Mapped[str] = mapped_column(String(80))
    applied_plan_id: Mapped[UUID | None] = mapped_column(Uuid)


class RiskAssessmentOrm(Base):
    """``ai.risk_assessments``: append only (IA2 and IA7)."""

    __tablename__ = "risk_assessments"
    __table_args__ = AI

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    clinic_id: Mapped[UUID] = mapped_column(Uuid)
    patient_id: Mapped[UUID] = mapped_column(Uuid)
    assessment_type: Mapped[str] = mapped_column(String(13))
    risk_probability: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    risk_tier: Mapped[str | None] = mapped_column(String(8))
    calibrated: Mapped[bool] = mapped_column(Boolean)
    window_days: Mapped[int] = mapped_column(SmallInteger)
    metric_snapshot_id: Mapped[UUID | None] = mapped_column(Uuid)
    target_profile_id: Mapped[UUID] = mapped_column(Uuid)
    model_name: Mapped[str] = mapped_column(String(80))
    model_version: Mapped[str] = mapped_column(String(80))
    input_hash: Mapped[str] = mapped_column(CHAR(64))
    explanation: Mapped[dict[str, Any]] = mapped_column(JSONB)
    is_fallback: Mapped[bool] = mapped_column(Boolean)
    fallback_reason: Mapped[str | None] = mapped_column(String(17))
    is_shadow: Mapped[bool] = mapped_column(Boolean)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PatternFindingOrm(Base):
    """``ai.pattern_findings``: append only (IA3)."""

    __tablename__ = "pattern_findings"
    __table_args__ = AI

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    clinic_id: Mapped[UUID] = mapped_column(Uuid)
    patient_id: Mapped[UUID] = mapped_column(Uuid)
    pattern_type: Mapped[str] = mapped_column(String(24))
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB)
    model_name: Mapped[str] = mapped_column(String(80))
    model_version: Mapped[str] = mapped_column(String(80))
    input_hash: Mapped[str] = mapped_column(CHAR(64))
    explanation: Mapped[dict[str, Any]] = mapped_column(JSONB)
    is_fallback: Mapped[bool] = mapped_column(Boolean)
    fallback_reason: Mapped[str | None] = mapped_column(String(17))
    is_shadow: Mapped[bool] = mapped_column(Boolean)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PatternFindingReviewOrm(Base):
    """``ai.pattern_finding_reviews``: append only, the doctor dismisses a finding."""

    __tablename__ = "pattern_finding_reviews"
    __table_args__ = AI

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    clinic_id: Mapped[UUID] = mapped_column(Uuid)
    patient_id: Mapped[UUID] = mapped_column(Uuid)
    finding_id: Mapped[UUID] = mapped_column(Uuid)
    action: Mapped[str] = mapped_column(String(9))
    reason: Mapped[str] = mapped_column(String(500))
    reviewed_by: Mapped[UUID] = mapped_column(Uuid)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ClinicalSummaryOrm(Base):
    """``ai.clinical_summaries``: append only (IA5)."""

    __tablename__ = "clinical_summaries"
    __table_args__ = AI

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    clinic_id: Mapped[UUID] = mapped_column(Uuid)
    patient_id: Mapped[UUID] = mapped_column(Uuid)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sections: Mapped[dict[str, Any]] = mapped_column(JSONB)
    numeric_check_matched: Mapped[bool | None] = mapped_column(Boolean)
    requested_by: Mapped[UUID] = mapped_column(Uuid)
    model_name: Mapped[str] = mapped_column(String(80))
    model_version: Mapped[str] = mapped_column(String(80))
    input_hash: Mapped[str] = mapped_column(CHAR(64))
    explanation: Mapped[dict[str, Any]] = mapped_column(JSONB)
    is_fallback: Mapped[bool] = mapped_column(Boolean)
    fallback_reason: Mapped[str | None] = mapped_column(String(17))
    is_shadow: Mapped[bool] = mapped_column(Boolean)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AssistantMessageOrm(Base):
    """``ai.assistant_messages``: the patient's turns and the replies (IA6)."""

    __tablename__ = "assistant_messages"
    __table_args__ = AI

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    clinic_id: Mapped[UUID] = mapped_column(Uuid)
    patient_id: Mapped[UUID] = mapped_column(Uuid)
    conversation_id: Mapped[UUID] = mapped_column(Uuid)
    sender: Mapped[str] = mapped_column(String(9))
    content: Mapped[str] = mapped_column(String(1000))
    escalation_level: Mapped[str | None] = mapped_column(String(14))
    guardrails_triggered: Mapped[list[str]] = mapped_column(ARRAY(String(40)))
    context_doc_ids: Mapped[list[UUID]] = mapped_column(ARRAY(Uuid))
    external_consent_id: Mapped[UUID | None] = mapped_column(Uuid)
    model_name: Mapped[str | None] = mapped_column(String(80))
    model_version: Mapped[str | None] = mapped_column(String(80))
    input_hash: Mapped[str | None] = mapped_column(CHAR(64))
    explanation: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    is_fallback: Mapped[bool] = mapped_column(Boolean)
    fallback_reason: Mapped[str | None] = mapped_column(String(17))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class KnowledgeDocumentOrm(Base):
    """``ai.knowledge_documents``: clinic material; only APPROVED is used as context."""

    __tablename__ = "knowledge_documents"
    __table_args__ = AI

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    clinic_id: Mapped[UUID] = mapped_column(Uuid)
    title: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(8))
    approved_by: Mapped[UUID | None] = mapped_column(Uuid)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AiEvaluationOrm(Base):
    """``ai.ai_evaluations``: each use case against its fallback (read only here)."""

    __tablename__ = "ai_evaluations"
    __table_args__ = AI

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    clinic_id: Mapped[UUID | None] = mapped_column(Uuid)
    use_case: Mapped[str] = mapped_column(String(3))
    model_name: Mapped[str] = mapped_column(String(80))
    model_version: Mapped[str] = mapped_column(String(80))
    baseline_name: Mapped[str] = mapped_column(String(80))
    cohort_ref: Mapped[str] = mapped_column(String(80))
    sample_size: Mapped[int] = mapped_column(Integer)
    model_metrics: Mapped[dict[str, Any]] = mapped_column(JSONB)
    baseline_metrics: Mapped[dict[str, Any]] = mapped_column(JSONB)
    fallback_usage_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PrivacyRequestOrm(Base):
    """``clinic.privacy_requests``: requests of a patient, with status and deadline."""

    __tablename__ = "privacy_requests"
    __table_args__ = CLINIC

    id: Mapped[UUID] = _id()
    clinic_id: Mapped[UUID] = mapped_column(Uuid)
    patient_id: Mapped[UUID] = mapped_column(Uuid)
    request_type: Mapped[str] = mapped_column(String(18))
    status: Mapped[str] = mapped_column(String(11))
    description: Mapped[str | None] = mapped_column(String(500))
    requested_at: Mapped[datetime] = _timestamp()
    due_at: Mapped[datetime] = _timestamp()
    resolved_at: Mapped[datetime | None] = _timestamp(nullable=True)
    resolved_by: Mapped[UUID | None] = mapped_column(Uuid)
    resolution_note: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = _timestamp()
    updated_at: Mapped[datetime] = _timestamp()


AUDIT = {"schema": "audit"}


class AuditLogOrm(Base):
    """``audit.audit_log``: hash chained actions. The database computes the chain."""

    __tablename__ = "audit_log"
    __table_args__ = AUDIT

    id: Mapped[UUID] = _id()
    clinic_id: Mapped[UUID] = mapped_column(Uuid)
    chain_seq: Mapped[int] = mapped_column(BigInteger)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=NOW
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(Uuid)
    actor_role: Mapped[str | None] = mapped_column(String(14))
    actor_type: Mapped[str] = mapped_column(String(6))
    action: Mapped[str] = mapped_column(String(60))
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[UUID | None] = mapped_column(Uuid)
    entity_version: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(String(500))
    changed_fields: Mapped[list[str]] = mapped_column(ARRAY(String(80)))
    request_id: Mapped[str | None] = mapped_column(String(64))
    ip_hmac: Mapped[str | None] = mapped_column(CHAR(64))
    prev_hash: Mapped[str] = mapped_column(CHAR(64))
    row_hash: Mapped[str] = mapped_column(CHAR(64))


class DataAccessLogOrm(Base):
    """``audit.data_access_log``: one row per read of clinical data (P09)."""

    __tablename__ = "data_access_log"
    __table_args__ = AUDIT

    id: Mapped[UUID] = _id()
    clinic_id: Mapped[UUID] = mapped_column(Uuid)
    patient_id: Mapped[UUID | None] = mapped_column(Uuid)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=NOW
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(Uuid)
    actor_role: Mapped[str | None] = mapped_column(String(14))
    actor_type: Mapped[str] = mapped_column(String(6))
    resource_type: Mapped[str] = mapped_column(String(24))
    action: Mapped[str] = mapped_column(String(7))
    outcome: Mapped[str] = mapped_column(String(7))
    purpose: Mapped[str] = mapped_column(String(14))
    request_id: Mapped[str | None] = mapped_column(String(64))
    ip_hmac: Mapped[str | None] = mapped_column(CHAR(64))
