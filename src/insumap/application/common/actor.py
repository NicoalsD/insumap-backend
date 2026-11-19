"""The authenticated actor of a request, built from a validated access token."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from insumap.domain.identity.errors import PermissionDeniedError
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role


@dataclass(frozen=True, slots=True, kw_only=True)
class Actor:
    """Who is calling, with the permissions the database grants to the role.

    ``clinic_id``, ``user_id`` and ``role`` come only from the validated token
    and the account row, never from the path, the body or a header.
    """

    user_id: UUID
    clinic_id: UUID | None
    role: Role
    permissions: frozenset[PermissionCode] = field(default=frozenset())
    patient_id: UUID | None = None
    session_id: UUID | None = None
    requires_mfa: bool = False
    mfa_verified: bool = False

    def require(self, permission: PermissionCode) -> None:
        """Deny by default: the permission must have been granted."""
        if permission not in self.permissions:
            raise PermissionDeniedError

    def own_patient_id(self) -> UUID:
        """The patient of the token, never one received in the request (V3)."""
        if self.patient_id is None:
            raise PermissionDeniedError
        return self.patient_id
