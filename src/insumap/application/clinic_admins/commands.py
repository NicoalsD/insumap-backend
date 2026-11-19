"""Decisions about the clinic administrators: the first one of a clinic (P13).

The command runs as a platform administrator, which has no clinic of its own,
so its audit row names the target clinic (``audit_subject``). The activation
code leaves only by email, after the commit, as in ``CreateStaffUserCommand``.

Pattern: P13 Command
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import ClassVar, Final, final, override
from uuid import UUID

from insumap.application.clinic_admins.ports import (
    ClinicAdminProvisioningPort,
    NewClinicAdmin,
)
from insumap.application.clinics.ports import ClinicRepositoryPort
from insumap.application.commands.base import AuditSubject, Command, CommandHandler
from insumap.application.commands.transactional import CurrentUnitOfWork
from insumap.application.identity.ports import CodeHasherPort, CodePurpose
from insumap.application.notifications.account_notifications import (
    StaffActivationNotification,
)
from insumap.application.notifications.notification import (
    NotificationChannel,
    PendingNotification,
    Recipient,
)
from insumap.application.users.ports import ActivationCodeGeneratorPort
from insumap.domain.clinic.clinic import MACHINE_NAME
from insumap.domain.common.errors import ResourceNotFoundError
from insumap.domain.identity.email import EmailAddress
from insumap.domain.identity.errors import InvalidStateTransitionError
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role
from insumap.shared.i18n import MessageCatalog
from insumap.shared.time import Clock

ADMIN_ENTITY: Final = "USER"
CREATE_ACTION: Final = "create_clinic_admin"


@dataclass(frozen=True, slots=True, kw_only=True)
class CreatedClinicAdmin:
    """What ``POST /clinics/{clinic_id}/admins`` answers: never the code."""

    user_id: UUID
    email: str
    role: Role
    invitation_expires_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateClinicAdminCommand(Command[CreatedClinicAdmin]):
    """The platform administrator registers the first CLINIC_ADMIN of a clinic."""

    audit_action: ClassVar[str] = "CLINIC_ADMIN_CREATED"
    audit_entity_type: ClassVar[str] = ADMIN_ENTITY

    clinic_id: UUID
    email: str
    full_name: str

    @override
    def audit_subject(self, result: CreatedClinicAdmin) -> AuditSubject:
        return AuditSubject(
            clinic_id=self.clinic_id,
            entity_id=result.user_id,
            changed_fields=("email", "full_name", "role"),
        )


@final
class CreateClinicAdminCommandHandler(
    CommandHandler[CreateClinicAdminCommand, CreatedClinicAdmin]
):
    """Creates the administrator of the target clinic and sends its activation code.

    The permission is checked before the clinic is looked up, so a missing
    permission is a ``403`` before a missing clinic is a ``404``. The account
    starts ``INVITED``; the code is stored only as its keyed hash.

    Pattern: P13 Command
    """

    def __init__(
        self,
        *,
        clinics: ClinicRepositoryPort,
        provisioning: ClinicAdminProvisioningPort,
        codes: ActivationCodeGeneratorPort,
        code_hasher: CodeHasherPort,
        channel: NotificationChannel,
        messages: MessageCatalog,
        clock: Clock,
        current: CurrentUnitOfWork,
        invitation_ttl: timedelta,
    ) -> None:
        self._clinics = clinics
        self._provisioning = provisioning
        self._codes = codes
        self._code_hasher = code_hasher
        self._channel = channel
        self._messages = messages
        self._clock = clock
        self._current = current
        self._ttl = invitation_ttl

    @override
    def handle(self, command: CreateClinicAdminCommand) -> CreatedClinicAdmin:
        command.actor.require(PermissionCode.CLINIC_ADMINS_MANAGE)
        clinic = self._clinics.get(command.clinic_id)
        if clinic is None:
            raise ResourceNotFoundError
        if not clinic.is_active:
            raise InvalidStateTransitionError(
                MACHINE_NAME, clinic.status.value, CREATE_ACTION
            )
        email = EmailAddress.from_input(command.email)
        now = self._clock.now()
        code = self._codes.generate()
        keyed = self._code_hasher.hash_for_storage(CodePurpose.ACTIVATION, code.value)
        expires_at = now + self._ttl
        provisioned = self._provisioning.create_first_admin(
            NewClinicAdmin(
                clinic_id=clinic.clinic_id,
                email=email.original,
                full_name=command.full_name,
                code_hash=keyed.value,
                code_key_id=keyed.key_id,
                expires_at=expires_at,
            )
        )
        pending = PendingNotification(
            notification=StaffActivationNotification(
                self._channel,
                self._messages,
                code=code.formatted(),
                days=self._ttl.days,
            ),
            recipient=Recipient(user_id=provisioned.user_id, address=email.original),
            is_demo=clinic.is_demo,
        )
        self._current.after_commit(pending.send)
        return CreatedClinicAdmin(
            user_id=provisioned.user_id,
            email=email.original,
            role=Role.CLINIC_ADMIN,
            invitation_expires_at=expires_at,
        )
