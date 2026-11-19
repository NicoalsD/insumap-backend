"""Accounts, permissions and password history."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import final, override
from uuid import UUID

from sqlalchemy import case, exists, func, select, text, update
from sqlalchemy.exc import IntegrityError

from insumap.application.identity.ports import (
    LoginIdentity,
    PasswordHistoryPort,
    PermissionRepositoryPort,
    UserRepositoryPort,
)
from insumap.domain.identity.account_state import AccountStatus
from insumap.domain.identity.errors import EmailUnavailableError
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role
from insumap.domain.identity.user import ClinicSummary, UserAccount
from insumap.infrastructure.persistence.orm import (
    ClinicOrm,
    MembershipOrm,
    PasswordHistoryOrm,
    PatientOrm,
    PermissionOrm,
    RoleOrm,
    RolePermissionOrm,
    StaffProfileOrm,
    UserOrm,
)
from insumap.infrastructure.persistence.transactions import CurrentSession

ACTIVE_CLINIC = "ACTIVE"
UNIQUE_EMAIL_INDEX = "ux_users_email_normalized"
LOGIN_LOOKUP = text("SELECT * FROM iam.lookup_login_identity(:email)")


@final
class UserRepository(UserRepositoryPort):
    """``iam.users`` with its membership, role, clinic and display name."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def find_login_identity(self, email_normalized: str) -> LoginIdentity | None:
        row = (
            self._current.get()
            .execute(LOGIN_LOOKUP, {"email": email_normalized})
            .mappings()
            .first()
        )
        if row is None:
            return None
        role = row["role"]
        clinic_status = row["clinic_status"]
        return LoginIdentity(
            user_id=row["user_id"],
            status=AccountStatus(row["status"]),
            password_hash=row["password_hash"],
            token_version=row["token_version"],
            role=None if role is None else Role(role),
            clinic_id=row["clinic_id"],
            clinic_active=clinic_status is None or clinic_status == ACTIVE_CLINIC,
        )

    @override
    def get(self, user_id: UUID) -> UserAccount | None:
        statement = (
            select(
                UserOrm,
                MembershipOrm,
                RoleOrm,
                ClinicOrm,
                PatientOrm.id,
                func.coalesce(PatientOrm.full_name, StaffProfileOrm.full_name),
            )
            .join(MembershipOrm, MembershipOrm.user_id == UserOrm.id)
            .join(RoleOrm, RoleOrm.id == MembershipOrm.role_id)
            .outerjoin(ClinicOrm, ClinicOrm.id == MembershipOrm.clinic_id)
            .outerjoin(PatientOrm, PatientOrm.user_id == UserOrm.id)
            .outerjoin(StaffProfileOrm, StaffProfileOrm.user_id == UserOrm.id)
            .where(UserOrm.id == user_id)
        )
        row = self._current.get().execute(statement).first()
        if row is None:
            return None
        user, membership, role, clinic, patient_id, full_name = row
        if membership.clinic_id is not None and clinic is None:
            return None
        return UserAccount(
            user_id=user.id,
            email=user.email,
            email_normalized=user.email_normalized,
            full_name=full_name,
            password_hash=user.password_hash,
            status=AccountStatus(user.status),
            token_version=user.token_version,
            role=Role(role.code),
            requires_mfa=role.requires_mfa,
            membership_active=membership.is_active,
            clinic=None
            if clinic is None
            else ClinicSummary(
                clinic_id=clinic.id,
                name=clinic.name,
                is_demo=clinic.is_demo,
                is_active=clinic.status == ACTIVE_CLINIC,
            ),
            patient_id=patient_id,
        )

    @override
    def email_taken(self, email_normalized: str, *, except_user_id: UUID) -> bool:
        """Best effort: row level security hides other clinics' accounts.

        The unique index ``ux_users_email_normalized`` is what guarantees it;
        ``save`` turns its violation into ``EmailUnavailableError``.
        """
        statement = select(
            exists().where(
                UserOrm.email_normalized == email_normalized,
                UserOrm.id != except_user_id,
            )
        )
        return bool(self._current.get().execute(statement).scalar())

    @override
    def save(self, account: UserAccount) -> None:
        now = func.now()
        statement = (
            update(UserOrm)
            .where(UserOrm.id == account.user_id)
            .values(
                status=account.status.value,
                status_changed_at=case(
                    (UserOrm.status != account.status.value, now),
                    else_=UserOrm.status_changed_at,
                ),
                password_hash=account.password_hash,
                password_changed_at=case(
                    (
                        UserOrm.password_hash.is_distinct_from(account.password_hash),
                        now,
                    ),
                    else_=UserOrm.password_changed_at,
                ),
                token_version=account.token_version,
                email=func.coalesce(account.email, UserOrm.email),
                email_normalized=func.coalesce(
                    account.email_normalized, UserOrm.email_normalized
                ),
                updated_at=now,
            )
        )
        try:
            self._current.get().execute(statement)
        except IntegrityError as error:
            if UNIQUE_EMAIL_INDEX in str(error.orig):
                raise EmailUnavailableError from None
            raise


@final
class PermissionRepository(PermissionRepositoryPort):
    """The role to permission matrix of ``iam.role_permissions``."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def permissions_for_role(self, role: Role) -> frozenset[PermissionCode]:
        statement = (
            select(PermissionOrm.code)
            .join(
                RolePermissionOrm, RolePermissionOrm.permission_id == PermissionOrm.id
            )
            .join(RoleOrm, RoleOrm.id == RolePermissionOrm.role_id)
            .where(RoleOrm.code == role.value)
        )
        return PermissionCode.known(self._current.get().scalars(statement))


@final
class PasswordHistoryRepository(PasswordHistoryPort):
    """Hashes of previous passwords (``iam.password_history``)."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def recent_hashes(self, user_id: UUID, *, limit: int) -> Sequence[str]:
        statement = (
            select(PasswordHistoryOrm.password_hash)
            .where(PasswordHistoryOrm.user_id == user_id)
            .order_by(PasswordHistoryOrm.created_at.desc())
            .limit(limit)
        )
        return list(self._current.get().scalars(statement))

    @override
    def add(self, user_id: UUID, password_hash: str, *, now: datetime) -> None:
        self._current.get().add(
            PasswordHistoryOrm(
                user_id=user_id, password_hash=password_hash, created_at=now
            )
        )
