"""Staff directory, staff invitations and login lockouts over PostgreSQL.

Every write runs inside the transaction of the command, under row level
security: ``CLINIC_ADMIN`` of the session clinic. Inserts supply their
identifiers, and each table is flushed before the rows that reference it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final, final, override
from uuid import UUID

from sqlalchemy import Row, select, update
from sqlalchemy.exc import IntegrityError

from insumap.application.common.pagination import Page, PageRequest, build_page
from insumap.application.users.ports import (
    LoginLockoutPort,
    NewStaffInvitation,
    NewStaffMember,
    StaffDirectoryPort,
    StaffFilter,
    StaffInvitationPort,
    StaffMember,
)
from insumap.domain.common.errors import ConflictError
from insumap.domain.identity.account_state import AccountStatus
from insumap.domain.identity.invitation import InvitationPurpose, InvitationStatus
from insumap.domain.identity.roles import Role
from insumap.domain.staff.profile import STAFF_ROLES
from insumap.infrastructure.persistence.orm import (
    CredentialInvitationOrm,
    LoginLockoutOrm,
    MembershipOrm,
    MfaFactorOrm,
    RoleOrm,
    StaffProfileOrm,
    UserOrm,
)
from insumap.infrastructure.persistence.transactions import CurrentSession
from insumap.infrastructure.security.subkey_hasher import SubkeyHasher

STAFF_CODES: Final = tuple(sorted(role.value for role in STAFF_ROLES))
ACTIVE_STATUS: Final = AccountStatus.ACTIVE.value
INVITED_STATUS: Final = AccountStatus.INVITED.value
TOTP: Final = "TOTP"
EMAIL_CHANNEL: Final = "EMAIL"
EMAIL_INDEX: Final = "ux_users_email_normalized"
LICENSE_INDEX: Final = "ux_staff_profiles_clinic_license"
EMAIL_TAKEN: Final = "email_taken"
LICENSE_TAKEN: Final = "professional_license_taken"
ACCOUNT_SCOPE: Final = "ACCOUNT"
"""Lockout scope of an email, whatever the IP (``iam.login_lockouts.scope``)."""

MFA_ENABLED = (
    select(MfaFactorOrm.id)
    .where(
        MfaFactorOrm.user_id == UserOrm.id,
        MfaFactorOrm.factor_type == TOTP,
        MfaFactorOrm.revoked_at.is_(None),
        MfaFactorOrm.confirmed_at.is_not(None),
    )
    .exists()
    .label("mfa_enabled")
)


def _conflict_reason(error: IntegrityError) -> str | None:
    """The business reason of a unique index violation, or ``None`` if unknown."""
    message = str(error.orig)
    if EMAIL_INDEX in message:
        return EMAIL_TAKEN
    if LICENSE_INDEX in message:
        return LICENSE_TAKEN
    return None


def _staff_statement() -> Any:
    """Staff rows with their membership, role, profile and MFA state."""
    return (
        select(
            UserOrm.id,
            UserOrm.email,
            UserOrm.status,
            MembershipOrm.clinic_id,
            RoleOrm.code,
            StaffProfileOrm.full_name,
            StaffProfileOrm.professional_license,
            StaffProfileOrm.specialty,
            MFA_ENABLED,
        )
        .join(MembershipOrm, MembershipOrm.user_id == UserOrm.id)
        .join(RoleOrm, RoleOrm.id == MembershipOrm.role_id)
        .join(StaffProfileOrm, StaffProfileOrm.user_id == UserOrm.id)
        .where(RoleOrm.code.in_(STAFF_CODES))
    )


def _member(row: Row[Any]) -> StaffMember:
    """Map a staff row (see ``_staff_statement``) to its read model."""
    return StaffMember(
        user_id=row.id,
        clinic_id=row.clinic_id,
        email=row.email,
        full_name=row.full_name,
        role=Role(row.code),
        is_active=row.status == ACTIVE_STATUS,
        professional_license=row.professional_license,
        specialty=row.specialty,
        mfa_enabled=bool(row.mfa_enabled),
    )


@final
class StaffDirectoryRepository(StaffDirectoryPort):
    """``iam.users``, ``iam.memberships`` and ``clinic.staff_profiles`` of staff."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def get(self, clinic_id: UUID, user_id: UUID) -> StaffMember | None:
        row = (
            self._current.get()
            .execute(
                _staff_statement().where(
                    UserOrm.id == user_id, MembershipOrm.clinic_id == clinic_id
                )
            )
            .first()
        )
        return None if row is None else _member(row)

    @override
    def list(
        self, clinic_id: UUID, filters: StaffFilter, page: PageRequest
    ) -> Page[StaffMember]:
        statement = _staff_statement().where(MembershipOrm.clinic_id == clinic_id)
        if filters.role is not None:
            statement = statement.where(RoleOrm.code == filters.role.value)
        if filters.is_active is not None:
            statement = statement.where(
                UserOrm.status == ACTIVE_STATUS
                if filters.is_active
                else UserOrm.status != ACTIVE_STATUS
            )
        if page.after is not None:
            statement = statement.where(UserOrm.id > page.after)
        rows = (
            self._current.get()
            .execute(statement.order_by(UserOrm.id).limit(page.limit + 1))
            .all()
        )
        return build_page(
            [_member(row) for row in rows],
            limit=page.limit,
            key=lambda member: member.user_id,
        )

    @override
    def create(self, member: NewStaffMember, *, now: datetime) -> None:
        session = self._current.get()
        role_id = session.execute(
            select(RoleOrm.id).where(RoleOrm.code == member.role.value)
        ).scalar_one()
        try:
            session.add(
                UserOrm(
                    id=member.user_id,
                    email=member.email,
                    email_normalized=member.email_normalized,
                    token_version=0,
                    status=INVITED_STATUS,
                    status_changed_at=now,
                    updated_at=now,
                )
            )
            session.flush()
            session.add(
                MembershipOrm(
                    id=member.membership_id,
                    user_id=member.user_id,
                    clinic_id=member.clinic_id,
                    role_id=role_id,
                    is_active=True,
                    updated_at=now,
                )
            )
            session.flush()
            session.add(
                StaffProfileOrm(
                    user_id=member.user_id,
                    clinic_id=member.clinic_id,
                    full_name=member.full_name,
                    professional_license=member.professional_license,
                    specialty=member.specialty,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.flush()
        except IntegrityError as error:
            reason = _conflict_reason(error)
            if reason is None:
                raise
            raise ConflictError(reason) from None

    @override
    def update_profile(
        self,
        user_id: UUID,
        *,
        full_name: str,
        professional_license: str | None,
        specialty: str | None,
        now: datetime,
    ) -> None:
        try:
            self._current.get().execute(
                update(StaffProfileOrm)
                .where(StaffProfileOrm.user_id == user_id)
                .values(
                    full_name=full_name,
                    professional_license=professional_license,
                    specialty=specialty,
                    updated_at=now,
                )
            )
        except IntegrityError as error:
            reason = _conflict_reason(error)
            if reason is None:
                raise
            raise ConflictError(reason) from None

    @override
    def end_membership(self, user_id: UUID, *, reason: str, now: datetime) -> None:
        self._current.get().execute(
            update(MembershipOrm)
            .where(MembershipOrm.user_id == user_id)
            .values(is_active=False, ended_at=now, ended_reason=reason, updated_at=now)
        )


@final
class StaffInvitationRepository(StaffInvitationPort):
    """``iam.credential_invitations`` rows of purpose ``STAFF_ACTIVATION``."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def add(self, invitation: NewStaffInvitation) -> None:
        session = self._current.get()
        session.add(
            CredentialInvitationOrm(
                id=invitation.invitation_id,
                clinic_id=invitation.clinic_id,
                user_id=invitation.user_id,
                patient_id=None,
                purpose=InvitationPurpose.STAFF_ACTIVATION.value,
                channel=EMAIL_CHANNEL,
                status=InvitationStatus.PENDING.value,
                code_hash=invitation.code_hash,
                code_key_id=invitation.code_key_id,
                failed_attempts=0,
                expires_at=invitation.expires_at,
                issued_by=invitation.issued_by,
                issued_at=invitation.issued_at,
                delivery_status="PENDING",
            )
        )
        session.flush()


@final
class LoginLockoutRepository(LoginLockoutPort):
    """``iam.login_lockouts`` (RLS-4: no clinic context, column grants only).

    The key of a row is ``HMAC-SHA256(rate-limit subkey of APP_HMAC_KEY,
    "ACCOUNT:" + email_normalized)``: a scope and a value, never the email.
    """

    def __init__(self, current: CurrentSession, hasher: SubkeyHasher) -> None:
        self._current = current
        self._hasher = hasher

    @override
    def clear_account(self, email_normalized: str, *, now: datetime) -> None:
        key = self._hasher.hexdigest(f"{ACCOUNT_SCOPE}:{email_normalized}")
        self._current.get().execute(
            update(LoginLockoutOrm)
            .where(
                LoginLockoutOrm.scope == ACCOUNT_SCOPE,
                LoginLockoutOrm.key_hmac == key,
            )
            .values(level=0, locked_until=None, reset_at=now, updated_at=now)
        )
