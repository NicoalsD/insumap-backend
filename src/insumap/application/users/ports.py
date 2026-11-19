"""Ports of the staff use cases (``/api/v1/users``). Infrastructure implements them.

They speak in domain types and in the read models below, never in ORM rows or
wire models. Account, membership and MFA writes reuse the identity ports.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from insumap.application.common.pagination import Page, PageRequest
from insumap.domain.identity.codes import ActivationCode
from insumap.domain.identity.roles import Role


@dataclass(frozen=True, slots=True, kw_only=True)
class StaffMember:
    """A staff member of a clinic as its administrators see it: no clinical data."""

    user_id: UUID
    clinic_id: UUID
    email: str | None
    full_name: str
    role: Role
    is_active: bool
    professional_license: str | None
    specialty: str | None
    mfa_enabled: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class StaffFilter:
    """Optional filters of ``GET /users`` (``None`` means no filter)."""

    role: Role | None = None
    is_active: bool | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class NewStaffMember:
    """Everything a new staff account needs: user, membership and profile rows."""

    user_id: UUID
    membership_id: UUID
    clinic_id: UUID
    email: str
    email_normalized: str
    full_name: str
    role: Role
    professional_license: str | None
    specialty: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class NewStaffInvitation:
    """A ``STAFF_ACTIVATION`` invitation; only the keyed hash of the code is kept."""

    invitation_id: UUID
    user_id: UUID
    clinic_id: UUID
    code_hash: str
    code_key_id: str
    expires_at: datetime
    issued_by: UUID
    issued_at: datetime


class StaffDirectoryPort(ABC):
    """Staff accounts of a clinic: profiles, memberships and listings."""

    @abstractmethod
    def get(self, clinic_id: UUID, user_id: UUID) -> StaffMember | None:
        """One staff member of ``clinic_id``; others give ``None``."""

    @abstractmethod
    def list(
        self, clinic_id: UUID, filters: StaffFilter, page: PageRequest
    ) -> Page[StaffMember]:
        """A page of the staff of ``clinic_id``, by identifier."""

    @abstractmethod
    def create(self, member: NewStaffMember, *, now: datetime) -> None:
        """Insert the user, its membership and its profile, in that order."""

    @abstractmethod
    def update_profile(
        self,
        user_id: UUID,
        *,
        full_name: str,
        professional_license: str | None,
        specialty: str | None,
        now: datetime,
    ) -> None:
        """Replace the profile fields of a staff member."""

    @abstractmethod
    def end_membership(self, user_id: UUID, *, reason: str, now: datetime) -> None:
        """End the membership of a staff member (``is_active`` false)."""


class StaffInvitationPort(ABC):
    """Invitations of the staff (``iam.credential_invitations``)."""

    @abstractmethod
    def add(self, invitation: NewStaffInvitation) -> None:
        """Store a new ``STAFF_ACTIVATION`` invitation, pending delivery by email."""


class LoginLockoutPort(ABC):
    """Login lockouts kept in ``iam.login_lockouts``, keyed by HMAC."""

    @abstractmethod
    def clear_account(self, email_normalized: str, *, now: datetime) -> None:
        """Lift the account-wide lock of an email (the ``ACCOUNT`` scope)."""


class ActivationCodeGeneratorPort(ABC):
    """Random activation codes, 80 bits each (Crockford base32)."""

    @abstractmethod
    def generate(self) -> ActivationCode:
        """Return a new normalized activation code."""
