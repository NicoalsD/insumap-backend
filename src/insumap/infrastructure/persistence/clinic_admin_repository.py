"""``iam.create_first_clinic_admin`` over PostgreSQL (API.md 8.3, ``db-v0.3.0``).

The function checks that the session is a PLATFORM_ADMIN and does the writes
under SECURITY DEFINER, so the adapter only calls it with bound parameters.
Its business errors are plain ``RAISE EXCEPTION`` messages (SQLSTATE P0001),
matched on the primary message, never on the whole text.
"""

from __future__ import annotations

from typing import Final, final, override

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from insumap.application.clinic_admins.commands import CREATE_ACTION
from insumap.application.clinic_admins.ports import (
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

EMAIL_INDEX: Final = "ux_users_email_normalized"
EMAIL_TAKEN: Final = "email_taken"
CLINIC_NOT_FOUND: Final = "clinic not found"
CLINIC_NOT_ACTIVE: Final = "clinic is not ACTIVE"


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
