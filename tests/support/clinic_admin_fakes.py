"""In-memory provisioning of the first clinic administrator, as the database does it."""

from __future__ import annotations

from typing import Final, override
from uuid import UUID

from insumap.application.clinic_admins.ports import (
    ClinicAdminProvisioningPort,
    NewClinicAdmin,
    ProvisionedClinicAdmin,
)
from insumap.domain.common.errors import ConflictError

EMAIL_TAKEN: Final = "email_taken"
FIRST_USER: Final = 5000
FIRST_INVITATION: Final = 6000


class FakeClinicAdminProvisioning(ClinicAdminProvisioningPort):
    """Keeps what it was asked to create; a repeated e-mail is a ``ConflictError``."""

    def __init__(self) -> None:
        self.created: list[NewClinicAdmin] = []
        self._emails: set[str] = set()

    @override
    def create_first_admin(self, admin: NewClinicAdmin) -> ProvisionedClinicAdmin:
        key = admin.email.strip().lower()
        if key in self._emails:
            raise ConflictError(EMAIL_TAKEN)
        self._emails.add(key)
        self.created.append(admin)
        ordinal = len(self.created)
        return ProvisionedClinicAdmin(
            user_id=UUID(int=FIRST_USER + ordinal),
            invitation_id=UUID(int=FIRST_INVITATION + ordinal),
        )
