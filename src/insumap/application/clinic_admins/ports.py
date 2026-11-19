"""Ports of the clinic administrator use cases. Infrastructure implements them.

A platform administrator has no clinic in its session, so row level security
does not let it write the clinic's accounts. The database functions of
``iam`` do those writes under ``SECURITY DEFINER`` (``insumap-database``,
``db-v0.3.0``), and the port only calls them.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True, kw_only=True)
class NewClinicAdmin:
    """The first administrator of a clinic; only the keyed hash of the code goes in."""

    clinic_id: UUID
    email: str
    full_name: str
    code_hash: str
    code_key_id: str
    expires_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class ProvisionedClinicAdmin:
    """What the database created: the account and its activation invitation."""

    user_id: UUID
    invitation_id: UUID


class ClinicAdminProvisioningPort(ABC):
    """Writes of the first clinic administrator (``iam`` function, db-v0.3.0)."""

    @abstractmethod
    def create_first_admin(self, admin: NewClinicAdmin) -> ProvisionedClinicAdmin:
        """Create the account (``INVITED``), its membership, profile and invitation.

        A repeated email raises ``ConflictError``. A clinic that does not exist
        raises ``ResourceNotFoundError``; one that is not ``ACTIVE`` raises
        ``InvalidStateTransitionError``.
        """
