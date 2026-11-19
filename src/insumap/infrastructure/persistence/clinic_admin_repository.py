"""``iam.create_first_clinic_admin`` and the access reset over PostgreSQL (API.md 8.3).

The functions check that the session is a PLATFORM_ADMIN and do the writes
under SECURITY DEFINER, so the adapter only calls them with bound parameters.
Their business errors are plain ``RAISE EXCEPTION`` messages (SQLSTATE P0001),
matched on the primary message, never on the whole text.
"""

from __future__ import annotations

import re
from typing import Final, final, override
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from insumap.application.clinic_admins.commands import (
    ADMIN_MACHINE,
    CREATE_ACTION,
    RESET_ACTION,
)
from insumap.application.clinic_admins.ports import (
    ClinicAdminAccessReset,
    ClinicAdminContact,
    ClinicAdminProvisioningPort,
    NewClinicAdmin,
    ProvisionedClinicAdmin,
)
from insumap.domain.clinic.clinic import MACHINE_NAME, ClinicStatus
from insumap.domain.common.errors import ConflictError, ResourceNotFoundError
from insumap.domain.identity.errors import InvalidStateTransitionError
from insumap.infrastructure.persistence.transactions import CurrentSession

CREATE_FIRST_CLINIC_ADMIN = text(
    "SELECT user_id, invitation_id FROM iam.create_first_clinic_admin("
    "p_clinic_id => :clinic_id, p_email => :email, p_full_name => :full_name, "
    "p_code_hash => CAST(:code_hash AS char(64)), "
    "p_code_key_id => CAST(:code_key_id AS char(16)), "
    "p_expires_at => :expires_at)"
)
"""Named arguments and explicit casts: the signature in ``db-v0.3.0``."""

RESET_ACCESS = text(
    "SELECT iam.reset_clinic_admin_access("
    "p_clinic_id => :clinic_id, p_user_id => :user_id, "
    "p_code_hash => CAST(:code_hash AS char(64)), "
    "p_code_key_id => CAST(:code_key_id AS char(16)), "
    "p_expires_at => :expires_at) AS invitation_id"
)
"""``iam.reset_clinic_admin_access`` (``db-v0.5.0``): returns the new invitation id."""

CLINIC_ADMIN_CONTACT = text(
    "SELECT email, full_name FROM iam.clinic_admin_contact("
    "p_clinic_id => :clinic_id, p_user_id => :user_id)"
)
"""``iam.clinic_admin_contact`` (``db-v0.5.0``): PLATFORM_ADMIN reads it only."""

EMAIL_INDEX: Final = "ux_users_email_normalized"
EMAIL_TAKEN: Final = "email_taken"
CLINIC_NOT_FOUND: Final = "clinic not found"
CLINIC_NOT_ACTIVE: Final = "clinic is not ACTIVE"
NOT_FOUND: Final = "not found"
STATUS_NOT_RESETTABLE: Final = re.compile(r"^user status (\S+) cannot be reset$")


def _primary_message(error: DBAPIError) -> str:
    """The primary message of the server error, or an empty text if unknown."""
    diag = getattr(error.orig, "diag", None)
    message = getattr(diag, "message_primary", None)
    return message if isinstance(message, str) else ""


@final
class ClinicAdminProvisioningRepository(ClinicAdminProvisioningPort):
    """The first clinic administrator, created by the database function."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def create_first_admin(self, admin: NewClinicAdmin) -> ProvisionedClinicAdmin:
        try:
            row = (
                self._current.get()
                .execute(
                    CREATE_FIRST_CLINIC_ADMIN,
                    {
                        "clinic_id": admin.clinic_id,
                        "email": admin.email,
                        "full_name": admin.full_name,
                        "code_hash": admin.code_hash,
                        "code_key_id": admin.code_key_id,
                        "expires_at": admin.expires_at,
                    },
                )
                .one()
            )
        except IntegrityError as error:
            # The function raises unique_violation as is: the e-mail is taken.
            if EMAIL_INDEX in str(error.orig):
                raise ConflictError(EMAIL_TAKEN) from None
            raise
        except DBAPIError as error:
            message = _primary_message(error)
            if message == CLINIC_NOT_FOUND:
                raise ResourceNotFoundError from None
            if message == CLINIC_NOT_ACTIVE:
                raise InvalidStateTransitionError(
                    MACHINE_NAME, ClinicStatus.SUSPENDED.value, CREATE_ACTION
                ) from None
            raise
        return ProvisionedClinicAdmin(
            user_id=row.user_id, invitation_id=row.invitation_id
        )

    @override
    def reset_access(self, reset: ClinicAdminAccessReset) -> UUID:
        try:
            invitation_id: UUID = (
                self._current.get()
                .execute(
                    RESET_ACCESS,
                    {
                        "clinic_id": reset.clinic_id,
                        "user_id": reset.user_id,
                        "code_hash": reset.code_hash,
                        "code_key_id": reset.code_key_id,
                        "expires_at": reset.expires_at,
                    },
                )
                .scalar_one()
            )
        except DBAPIError as error:
            message = _primary_message(error)
            if message == NOT_FOUND:
                raise ResourceNotFoundError from None
            status = STATUS_NOT_RESETTABLE.match(message)
            if status is not None:
                raise InvalidStateTransitionError(
                    ADMIN_MACHINE, status.group(1), RESET_ACTION
                ) from None
            raise
        return invitation_id

    @override
    def contact(self, clinic_id: UUID, user_id: UUID) -> ClinicAdminContact:
        try:
            row = (
                self._current.get()
                .execute(
                    CLINIC_ADMIN_CONTACT,
                    {"clinic_id": clinic_id, "user_id": user_id},
                )
                .one()
            )
        except DBAPIError as error:
            if _primary_message(error) == NOT_FOUND:
                raise ResourceNotFoundError from None
            raise
        return ClinicAdminContact(email=row.email, full_name=row.full_name)
