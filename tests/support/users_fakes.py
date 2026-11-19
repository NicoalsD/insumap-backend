"""In-memory staff directory, invitations, lockouts and activation codes.

The directory reads the accounts of ``FakeUsers`` and the factors of
``FakeFactors``, so the staff view and the identity doubles never disagree.
Uniqueness that the database enforces with indexes is checked here too.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import override
from uuid import UUID

from insumap.application.common.pagination import Page, PageRequest, build_page
from insumap.application.users.ports import (
    ActivationCodeGeneratorPort,
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
from insumap.domain.identity.codes import ActivationCode
from insumap.domain.identity.user import ClinicSummary, UserAccount
from insumap.domain.staff.profile import is_staff_role
from tests.support.identity_fakes import FakeFactors, FakeUsers

EMAIL_TAKEN = "email_taken"
LICENSE_TAKEN = "professional_license_taken"


@dataclass
class FakeProfile:
    clinic_id: UUID
    full_name: str
    professional_license: str | None
    specialty: str | None


class FakeStaffDirectory(StaffDirectoryPort):
    """Staff of the clinics, seen through the account and factor doubles."""

    def __init__(self, users: FakeUsers, factors: FakeFactors) -> None:
        self._users = users
        self._factors = factors
        self.profiles: dict[UUID, FakeProfile] = {}
        self.created: list[NewStaffMember] = []

    def _view(self, account: UserAccount) -> StaffMember:
        assert account.clinic_id is not None
        profile = self.profiles.get(account.user_id)
        totp = self._factors.find_totp(account.user_id)
        return StaffMember(
            user_id=account.user_id,
            clinic_id=account.clinic_id,
            email=account.email,
            full_name=profile.full_name if profile else (account.full_name or ""),
            role=account.role,
            is_active=account.status is AccountStatus.ACTIVE,
            professional_license=None
            if profile is None
            else profile.professional_license,
            specialty=None if profile is None else profile.specialty,
            mfa_enabled=totp is not None and totp.is_confirmed,
        )

    def _staff_of(self, clinic_id: UUID) -> list[UserAccount]:
        return [
            account
            for account in self._users.accounts.values()
            if account.clinic_id == clinic_id and is_staff_role(account.role)
        ]

    def _license_taken(
        self, clinic_id: UUID, license_number: str, user_id: UUID
    ) -> bool:
        return any(
            profile.clinic_id == clinic_id
            and profile.professional_license == license_number
            and uid != user_id
            for uid, profile in self.profiles.items()
        )

    @override
    def get(self, clinic_id: UUID, user_id: UUID) -> StaffMember | None:
        account = self._users.accounts.get(user_id)
        if account is None or account.clinic_id != clinic_id:
            return None
        if not is_staff_role(account.role):
            return None
        return self._view(account)

    @override
    def list(
        self, clinic_id: UUID, filters: StaffFilter, page: PageRequest
    ) -> Page[StaffMember]:
        rows = sorted(
            (self._view(account) for account in self._staff_of(clinic_id)),
            key=lambda member: member.user_id,
        )
        rows = [
            member
            for member in rows
            if (page.after is None or member.user_id > page.after)
            and (filters.role is None or member.role is filters.role)
            and (filters.is_active is None or member.is_active == filters.is_active)
        ]
        return build_page(
            rows[: page.limit + 1], limit=page.limit, key=lambda m: m.user_id
        )

    @override
    def create(self, member: NewStaffMember, *, now: datetime) -> None:
        del now
        if any(
            account.email_normalized == member.email_normalized
            for account in self._users.accounts.values()
        ):
            raise ConflictError(EMAIL_TAKEN)
        if member.professional_license is not None and self._license_taken(
            member.clinic_id, member.professional_license, member.user_id
        ):
            raise ConflictError(LICENSE_TAKEN)
        self._users.add(
            UserAccount(
                user_id=member.user_id,
                email=member.email,
                email_normalized=member.email_normalized,
                full_name=member.full_name,
                password_hash=None,
                status=AccountStatus.INVITED,
                token_version=0,
                role=member.role,
                requires_mfa=True,
                membership_active=True,
                clinic=ClinicSummary(
                    clinic_id=member.clinic_id,
                    name="Clínica de Prueba",
                    is_demo=True,
                    is_active=True,
                ),
            )
        )
        self.profiles[member.user_id] = FakeProfile(
            clinic_id=member.clinic_id,
            full_name=member.full_name,
            professional_license=member.professional_license,
            specialty=member.specialty,
        )
        self.created.append(member)

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
        del now
        clinic_id = self._users.accounts[user_id].clinic_id
        assert clinic_id is not None
        if professional_license is not None and self._license_taken(
            clinic_id, professional_license, user_id
        ):
            raise ConflictError(LICENSE_TAKEN)
        self.profiles[user_id] = FakeProfile(
            clinic_id=clinic_id,
            full_name=full_name,
            professional_license=professional_license,
            specialty=specialty,
        )

    @override
    def end_membership(self, user_id: UUID, *, reason: str, now: datetime) -> None:
        del reason, now
        account = self._users.accounts[user_id]
        self._users.save(replace(account, membership_active=False))


class FakeStaffInvitations(StaffInvitationPort):
    def __init__(self) -> None:
        self.added: list[NewStaffInvitation] = []

    @override
    def add(self, invitation: NewStaffInvitation) -> None:
        self.added.append(invitation)


class FakeLoginLockouts(LoginLockoutPort):
    def __init__(self) -> None:
        self.cleared: list[str] = []

    @override
    def clear_account(self, email_normalized: str, *, now: datetime) -> None:
        del now
        self.cleared.append(email_normalized)


class FakeActivationCodes(ActivationCodeGeneratorPort):
    """Always the same code, so tests can read it from the email."""

    def __init__(self, value: str = "ABCDEFGHJKMNPQRS") -> None:
        self._value = value

    @override
    def generate(self) -> ActivationCode:
        return ActivationCode(self._value)
