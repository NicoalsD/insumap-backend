"""Ports of the patient administration: the roster and the pending invitations.

Infrastructure implements them over PostgreSQL. They return read models built
for the administrator (identifiers, MRN and the last digits of the document),
never the encrypted document or clinical data.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from insumap.application.common.pagination import Page, PageRequest
from insumap.domain.identity.account_state import AccountStatus
from insumap.domain.identity.invitation import InvitationStatus


@dataclass(frozen=True, slots=True, kw_only=True)
class PatientAdministrativeView:
    """A patient as the clinic administrator sees it: no clinical data.

    ``document_last4`` is the only part of the document that leaves the database.
    ``invitation_status`` is the status of the latest invitation, if any.
    """

    patient_id: UUID
    clinic_id: UUID
    full_name: str
    mrn: str
    document_last4: str
    account_status: AccountStatus
    primary_doctor_id: UUID | None
    assigned_doctor_count: int
    invitation_status: InvitationStatus | None
    simulated: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class PatientRosterFilter:
    """Optional filters of ``GET /patients`` (``None`` or ``False`` means no filter)."""

    account_status: AccountStatus | None = None
    without_doctor: bool = False
    import_batch_id: UUID | None = None


class PatientRosterPort(ABC):
    """Administrative views of the patients of one clinic."""

    @abstractmethod
    def get(
        self, clinic_id: UUID, patient_id: UUID
    ) -> PatientAdministrativeView | None:
        """One patient of ``clinic_id``; any other patient gives ``None``."""

    @abstractmethod
    def list(
        self, clinic_id: UUID, filters: PatientRosterFilter, page: PageRequest
    ) -> Page[PatientAdministrativeView]:
        """A page of the patients of ``clinic_id``, by identifier."""


class PendingInvitationPort(ABC):
    """Invitations of a patient not used yet (``iam.credential_invitations``)."""

    @abstractmethod
    def revoke_pending(self, user_id: UUID, *, revoked_by: UUID, now: datetime) -> None:
        """Revoke every invitation of the account that is not used yet."""
