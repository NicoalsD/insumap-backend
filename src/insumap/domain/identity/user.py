"""User accounts: identity, credentials, role and session version."""

from __future__ import annotations

from dataclasses import dataclass, replace
from uuid import UUID

from insumap.domain.identity.account_state import AccountStatus, PatientAccountState
from insumap.domain.identity.email import EmailAddress
from insumap.domain.identity.roles import Role


@dataclass(frozen=True, slots=True, kw_only=True)
class ClinicSummary:
    """The clinic of a user's membership, as needed by the session."""

    clinic_id: UUID
    name: str
    is_demo: bool
    is_active: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class UserAccount:
    """A person with an account: staff or patient, with one membership.

    ``token_version`` is the ``tv`` claim of every access token: increasing it
    ends every open session at once. ``requires_mfa`` comes from the role in
    the database (``iam.roles.requires_mfa``), never from the role name.
    """

    user_id: UUID
    email: str | None
    email_normalized: str | None
    full_name: str | None
    password_hash: str | None
    status: AccountStatus
    token_version: int
    role: Role
    requires_mfa: bool
    membership_active: bool
    clinic: ClinicSummary | None
    patient_id: UUID | None = None
    email_verified: bool = False
    status_reason: str | None = None
    """Why the account was last suspended or deactivated (``status_reason``)."""

    @property
    def state(self) -> PatientAccountState:
        """The account state object (P18) of the persisted status."""
        return PatientAccountState.from_status(self.status)

    @property
    def clinic_id(self) -> UUID | None:
        """Clinic of the membership; ``None`` only for ``PLATFORM_ADMIN``."""
        return None if self.clinic is None else self.clinic.clinic_id

    @property
    def can_sign_in(self) -> bool:
        """``True`` if the account and its membership are active."""
        return self.membership_active and self.state.can_sign_in

    @property
    def clinic_suspended(self) -> bool:
        """``True`` if the clinic of the membership is suspended."""
        return self.clinic is not None and not self.clinic.is_active

    def with_revoked_sessions(self) -> UserAccount:
        """This account with ``token_version + 1``: every access token dies."""
        return replace(self, token_version=self.token_version + 1)

    def deactivated(self, *, reason: str) -> UserAccount:
        """This account closed for good (``-> DEACTIVATED``), with its reason.

        The state object refuses it when the account is already deactivated.
        """
        next_state = self.state.deactivate()
        return replace(self, status=next_state.status, status_reason=reason)

    def with_password_hash(self, password_hash: str) -> UserAccount:
        """This account with a new password hash (rehash or change)."""
        return replace(self, password_hash=password_hash)

    def with_verified_email(self) -> UserAccount:
        """This account once its email was confirmed with the emailed link."""
        return replace(self, email_verified=True)

    def activated(self, *, password_hash: str, email: EmailAddress) -> UserAccount:
        """The account after a successful activation (``INVITED -> ACTIVE``).

        The email stays unverified until the holder confirms it with the link.
        """
        next_state = self.state.activate()
        return replace(
            self,
            status=next_state.status,
            password_hash=password_hash,
            email=email.original,
            email_normalized=email.normalized,
            email_verified=False,
        )
