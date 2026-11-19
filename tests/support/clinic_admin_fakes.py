"""In-memory provisioning of clinic administrators, as the database functions do it."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final, override
from uuid import UUID

from insumap.application.clinic_admins.ports import (
    ClinicAdminAccessReset,
    ClinicAdminContact,
    ClinicAdminProvisioningPort,
    NewClinicAdmin,
    ProvisionedClinicAdmin,
)
from insumap.domain.common.errors import ConflictError, ResourceNotFoundError
from insumap.domain.identity.errors import InvalidStateTransitionError

EMAIL_TAKEN: Final = "email_taken"
FIRST_USER: Final = 5000
FIRST_INVITATION: Final = 6000
RESET_INVITATION: Final = 7000


@dataclass(slots=True)
class _Admin:
    clinic_id: UUID
    email: str
    full_name: str
    status: str = "INVITED"


@dataclass(slots=True)
class FakeClinicAdminProvisioning(ClinicAdminProvisioningPort):
    """Keeps what it was asked to write; a repeated e-mail is a ``ConflictError``.

    Administrators seeded with ``seed`` or created by ``create_first_admin`` can
    be reset; ``reset_access`` sets them back to ``INVITED`` as the database does.
    """

    created: list[NewClinicAdmin] = field(default_factory=list)
    resets: list[ClinicAdminAccessReset] = field(default_factory=list)
    _emails: set[str] = field(default_factory=set)
    _admins: dict[UUID, _Admin] = field(default_factory=dict)

    def seed(
        self,
        *,
        user_id: UUID,
        clinic_id: UUID,
        email: str,
        full_name: str = "Admin sembrado",
        status: str = "ACTIVE",
    ) -> None:
        """An administrator that already exists in the database."""
        self._emails.add(email.strip().lower())
        self._admins[user_id] = _Admin(clinic_id, email, full_name, status)

    def status_of(self, user_id: UUID) -> str:
        return self._admins[user_id].status

    @override
    def create_first_admin(self, admin: NewClinicAdmin) -> ProvisionedClinicAdmin:
        key = admin.email.strip().lower()
        if key in self._emails:
            raise ConflictError(EMAIL_TAKEN)
        self._emails.add(key)
        self.created.append(admin)
        ordinal = len(self.created)
        user_id = UUID(int=FIRST_USER + ordinal)
        self._admins[user_id] = _Admin(
            admin.clinic_id, admin.email, admin.full_name, "INVITED"
        )
        return ProvisionedClinicAdmin(
            user_id=user_id,
            invitation_id=UUID(int=FIRST_INVITATION + ordinal),
        )

    @override
    def reset_access(self, reset: ClinicAdminAccessReset) -> UUID:
        admin = self._admins.get(reset.user_id)
        if admin is None or admin.clinic_id != reset.clinic_id:
            raise ResourceNotFoundError
        if admin.status not in {"ACTIVE", "INVITED"}:
            raise InvalidStateTransitionError("clinic_admin", admin.status, "reset")
        admin.status = "INVITED"
        self.resets.append(reset)
        return UUID(int=RESET_INVITATION + len(self.resets))

    @override
    def contact(self, clinic_id: UUID, user_id: UUID) -> ClinicAdminContact:
        admin = self._admins.get(user_id)
        if admin is None or admin.clinic_id != clinic_id:
            raise ResourceNotFoundError
        return ClinicAdminContact(email=admin.email, full_name=admin.full_name)
