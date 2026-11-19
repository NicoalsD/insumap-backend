"""Decisions about patient credentials: issue or re-issue, and revoke (P13).

Issuing moves the imported account to ``INVITED`` (P18) and stores only the
keyed hash of a new single-use code. The code itself leaves the handler in the
command result (printed by the clinic, shown once) or in the activation email,
which is sent after the commit. Nothing here logs the code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import ClassVar, Final, final, override
from uuid import UUID

from insumap.application.commands.base import AuditSubject, Command, CommandHandler
from insumap.application.commands.transactional import CurrentUnitOfWork
from insumap.application.common.ids import IdGenerator
from insumap.application.credentials.ports import (
    CredentialInvitationPort,
    NewPatientInvitation,
    PatientContactPort,
)
from insumap.application.identity.ports import (
    CodeHasherPort,
    CodePurpose,
    UserRepositoryPort,
)
from insumap.application.notifications.account_notifications import (
    PatientActivationNotification,
)
from insumap.application.notifications.notification import (
    NotificationChannel,
    PendingNotification,
    Recipient,
)
from insumap.application.users.access import clinic_of
from insumap.application.users.ports import ActivationCodeGeneratorPort
from insumap.domain.common.errors import ResourceNotFoundError
from insumap.domain.common.text import invalid_field
from insumap.domain.identity.invitation import (
    DeliveryStatus,
    InvitationChannel,
    InvitationPurpose,
)
from insumap.domain.identity.permissions import PermissionCode
from insumap.shared.i18n import MessageCatalog
from insumap.shared.time import Clock

CREDENTIAL_ENTITY: Final = "CREDENTIAL_INVITATION"
CONTACT_EMAIL_FIELD: Final = "body.channel"
MISSING_CONTACT_EMAIL: Final = "missing_contact_email"


@dataclass(frozen=True, slots=True, kw_only=True)
class IssuedCredential:
    """What the clinic gets back for one issued code.

    ``activation_code`` is set only for the ``PRINT`` channel and only in this
    result: the API shows it once and never stores it. It is left out of
    ``repr`` so a stray log line cannot carry it.
    """

    invitation_id: UUID
    patient_id: UUID
    channel: InvitationChannel
    delivery_status: DeliveryStatus
    expires_at: datetime
    activation_code: str | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True, kw_only=True)
class IssueCredentialsCommand(Command[IssuedCredential]):
    """The clinic administrator issues, or re-issues, the code of an imported patient.

    Re-issuing revokes the open invitation, so the previous code stops working.

    Pattern: P13 Command
    """

    audit_action: ClassVar[str] = "CREDENTIALS_ISSUED"
    audit_entity_type: ClassVar[str] = CREDENTIAL_ENTITY

    patient_id: UUID
    channel: InvitationChannel

    @override
    def audit_subject(self, result: IssuedCredential) -> AuditSubject:
        return AuditSubject(
            clinic_id=self.actor.clinic_id,
            entity_id=result.invitation_id,
            changed_fields=("status", "expires_at"),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class RevokeCredentialInvitationCommand(Command[None]):
    """The clinic administrator withdraws an open invitation.

    The account returns to ``IMPORTED``.

    Pattern: P13 Command
    """

    audit_action: ClassVar[str] = "CREDENTIAL_INVITATION_REVOKED"
    audit_entity_type: ClassVar[str] = CREDENTIAL_ENTITY

    invitation_id: UUID

    @override
    def audit_subject(self, result: None) -> AuditSubject:
        del result
        return AuditSubject(
            clinic_id=self.actor.clinic_id,
            entity_id=self.invitation_id,
            changed_fields=("status", "account_status"),
        )


@final
class IssueCredentialsCommandHandler(
    CommandHandler[IssueCredentialsCommand, IssuedCredential]
):
    """Stores the new invitation, revokes the open one and moves the account to INVITED.

    Pattern: P13 Command
    """

    def __init__(
        self,
        *,
        contacts: PatientContactPort,
        users: UserRepositoryPort,
        invitations: CredentialInvitationPort,
        codes: ActivationCodeGeneratorPort,
        code_hasher: CodeHasherPort,
        channel: NotificationChannel,
        messages: MessageCatalog,
        base_url: str,
        ids: IdGenerator,
        clock: Clock,
        current: CurrentUnitOfWork,
        code_ttl: timedelta,
    ) -> None:
        self._contacts = contacts
        self._users = users
        self._invitations = invitations
        self._codes = codes
        self._code_hasher = code_hasher
        self._channel = channel
        self._messages = messages
        self._base_url = base_url
        self._ids = ids
        self._clock = clock
        self._current = current
        self._ttl = code_ttl

    @override
    def handle(self, command: IssueCredentialsCommand) -> IssuedCredential:
        actor = command.actor
        actor.require(PermissionCode.CREDENTIALS_ISSUE)
        clinic_id = clinic_of(actor)
        patient = self._contacts.find(command.patient_id)
        if patient is None or patient.clinic_id != clinic_id:
            raise ResourceNotFoundError
        contact_email = (patient.contact_email or "").strip()
        if command.channel is InvitationChannel.EMAIL and not contact_email:
            raise invalid_field(CONTACT_EMAIL_FIELD, MISSING_CONTACT_EMAIL)
        account = self._users.get(patient.user_id)
        if (
            account is None
            or account.patient_id != patient.patient_id
            or account.clinic_id != clinic_id
        ):
            raise ResourceNotFoundError
        # Refuses ACTIVE, SUSPENDED and DEACTIVATED accounts (INVALID_STATE_TRANSITION).
        invited = account.invited()

        now = self._clock.now()
        previous = self._invitations.find_open_for_user(account.user_id)
        code = self._codes.generate()
        keyed = self._code_hasher.hash_for_storage(CodePurpose.ACTIVATION, code.value)
        invitation_id = self._ids.new_id()
        expires_at = now + self._ttl
        delivery = (
            DeliveryStatus.PENDING
            if command.channel is InvitationChannel.EMAIL
            else DeliveryStatus.NOT_APPLICABLE
        )

        # The open invitation goes first: the unique index allows one per account.
        if previous is not None:
            self._invitations.mark_revoked(
                previous.invitation_id, revoked_at=now, revoked_by=actor.user_id
            )
        self._invitations.add(
            NewPatientInvitation(
                invitation_id=invitation_id,
                clinic_id=clinic_id,
                user_id=account.user_id,
                patient_id=patient.patient_id,
                channel=command.channel,
                delivery_status=delivery,
                code_hash=keyed.value,
                code_key_id=keyed.key_id,
                expires_at=expires_at,
                issued_by=actor.user_id,
                issued_at=now,
            )
        )
        if previous is not None:
            self._invitations.link_replacement(previous.invitation_id, invitation_id)
        self._users.save(invited)

        if command.channel is InvitationChannel.EMAIL:
            pending = PendingNotification(
                notification=PatientActivationNotification(
                    self._channel,
                    self._messages,
                    base_url=self._base_url,
                    code=code.formatted(),
                    days=self._ttl.days,
                ),
                recipient=Recipient(user_id=account.user_id, address=contact_email),
                is_demo=account.clinic is not None and account.clinic.is_demo,
            )
            self._current.after_commit(pending.send)

        return IssuedCredential(
            invitation_id=invitation_id,
            patient_id=patient.patient_id,
            channel=command.channel,
            delivery_status=delivery,
            expires_at=expires_at,
            activation_code=(
                code.formatted() if command.channel is InvitationChannel.PRINT else None
            ),
        )


@final
class RevokeCredentialInvitationCommandHandler(
    CommandHandler[RevokeCredentialInvitationCommand, None]
):
    """Revokes the open activation invitation and returns the account to IMPORTED.

    Only patient activation invitations are revoked here; anything else, or an
    invitation of another clinic, is a ``404``.

    Pattern: P13 Command
    """

    def __init__(
        self,
        *,
        users: UserRepositoryPort,
        invitations: CredentialInvitationPort,
        clock: Clock,
    ) -> None:
        self._users = users
        self._invitations = invitations
        self._clock = clock

    @override
    def handle(self, command: RevokeCredentialInvitationCommand) -> None:
        actor = command.actor
        actor.require(PermissionCode.CREDENTIALS_REVOKE)
        clinic_id = clinic_of(actor)
        invitation = self._invitations.get(command.invitation_id)
        if (
            invitation is None
            or invitation.clinic_id != clinic_id
            or invitation.purpose is not InvitationPurpose.PATIENT_ACTIVATION
            or invitation.patient_id is None
        ):
            raise ResourceNotFoundError
        now = self._clock.now()
        # Refuses a closed invitation (INVALID_STATE_TRANSITION) before any write.
        revoked = invitation.revoke(now=now)
        account = self._users.get(invitation.user_id)
        if account is None or account.clinic_id != clinic_id:
            raise ResourceNotFoundError
        reverted = account.reverted_to_imported()
        self._invitations.mark_revoked(
            revoked.invitation_id, revoked_at=now, revoked_by=actor.user_id
        )
        self._users.save(reverted)
