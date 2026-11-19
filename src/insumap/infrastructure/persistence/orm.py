"""``*Orm`` classes: they only map tables of ``insumap-database``.

This repository never creates or alters tables. Names and types follow the
migrations of the schema tagged in ``db-schema.lock``.
"""

from __future__ import annotations

from datetime import date, datetime
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
    SmallInteger,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
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
    document_last4: Mapped[str] = mapped_column(String(4))
    import_batch_id: Mapped[UUID | None] = mapped_column(Uuid)


class PrivacyNoticeVersionOrm(Base):
    __tablename__ = "privacy_notice_versions"
    __table_args__ = CLINIC

    id: Mapped[UUID] = _id()
    clinic_id: Mapped[UUID] = mapped_column(Uuid)
    version: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
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
