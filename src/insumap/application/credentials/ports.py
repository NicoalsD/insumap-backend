"""Ports of the credential use cases (``/api/v1/credential-invitations``).

Infrastructure implements them. They speak in domain types and in the read
models below, never in ORM rows or wire models. The patient account itself
goes through ``UserRepositoryPort`` (identity).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from insumap.domain.identity.invitation import (
    CredentialInvitation,
    DeliveryStatus,
    InvitationChannel,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class PatientContact:
    """The imported patient as the credential flow needs it. Never sent back.

    ``contact_email`` is the address the activation email goes to; it is
    personal data and never reaches a log or a response.
    """

    patient_id: UUID
    clinic_id: UUID
    user_id: UUID
    contact_email: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class NewPatientInvitation:
    """A ``PATIENT_ACTIVATION`` invitation; only the keyed hash of the code is kept."""

    invitation_id: UUID
    clinic_id: UUID
    user_id: UUID
    patient_id: UUID
    channel: InvitationChannel
    delivery_status: DeliveryStatus
    code_hash: str
    code_key_id: str
    expires_at: datetime
    issued_by: UUID
    issued_at: datetime


class PatientContactPort(ABC):
    """Finds an imported patient under row level security."""

    @abstractmethod
    def find(self, patient_id: UUID) -> PatientContact | None:
        """The patient, or ``None`` if it does not exist or is of another clinic."""


class CredentialInvitationPort(ABC):
    """Patient activation invitations (``iam.credential_invitations``)."""

    @abstractmethod
    def find_open_for_user(self, user_id: UUID) -> CredentialInvitation | None:
        """The open ``PATIENT_ACTIVATION`` invitation of an account, if any."""

    @abstractmethod
    def get(self, invitation_id: UUID) -> CredentialInvitation | None:
        """One invitation, of any status, or ``None`` if the session cannot see it."""

    @abstractmethod
    def add(self, invitation: NewPatientInvitation) -> None:
        """Store a new invitation as ``PENDING``.

        Raises ``ConflictError`` if the account already has an open invitation.
        """

    @abstractmethod
    def mark_revoked(
        self, invitation_id: UUID, *, revoked_at: datetime, revoked_by: UUID
    ) -> None:
        """Set ``REVOKED`` on an invitation, with who and when."""

    @abstractmethod
    def link_replacement(self, invitation_id: UUID, replaced_by_id: UUID) -> None:
        """Point a revoked invitation at the one that replaced it."""
