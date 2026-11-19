"""Decisions about patient accounts: suspend, reactivate and deactivate (P13, P18).

Each command runs behind the transaction and the audit of ``CommandGuard`` (P09).
The state machine (``PatientAccountState``) decides which moves are allowed; a
refused move answers ``409 INVALID_STATE_TRANSITION``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Final, final, override
from uuid import UUID

from insumap.application.access.ports import PatientDirectoryPort
from insumap.application.commands.base import AuditSubject, Command, CommandHandler
from insumap.application.identity.ports import (
    RefreshTokenRepositoryPort,
    UserRepositoryPort,
)
from insumap.application.patients.ports import (
    PatientAdministrativeView,
    PatientRosterPort,
    PendingInvitationPort,
)
from insumap.application.users.access import clinic_of
from insumap.domain.common.errors import ResourceNotFoundError
from insumap.domain.common.reason import Reason
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.refresh_token import RevocationReason
from insumap.domain.identity.user import UserAccount
from insumap.shared.time import Clock

PATIENT_ENTITY: Final = "PATIENT"
STATUS_FIELDS: Final = ("status", "status_reason", "token_version")


@dataclass(frozen=True, slots=True, kw_only=True)
class SuspendPatientCommand(Command[PatientAdministrativeView]):
    """The clinic administrator blocks an active patient; its sessions end."""

    audit_action: ClassVar[str] = "PATIENT_SUSPENDED"
    audit_entity_type: ClassVar[str] = PATIENT_ENTITY

    patient_id: UUID
    reason: str

    @override
    def audit_subject(self, result: PatientAdministrativeView) -> AuditSubject:
        return AuditSubject(
            clinic_id=self.actor.clinic_id,
            entity_id=result.patient_id,
            reason=Reason.parse(self.reason).text,
            changed_fields=STATUS_FIELDS,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ReactivatePatientCommand(Command[PatientAdministrativeView]):
    """The clinic administrator lifts the suspension of a patient."""

    audit_action: ClassVar[str] = "PATIENT_REACTIVATED"
    audit_entity_type: ClassVar[str] = PATIENT_ENTITY

    patient_id: UUID
    reason: str | None

    @override
    def audit_subject(self, result: PatientAdministrativeView) -> AuditSubject:
        return AuditSubject(
            clinic_id=self.actor.clinic_id,
            entity_id=result.patient_id,
            reason=None if self.reason is None else Reason.parse(self.reason).text,
            changed_fields=STATUS_FIELDS,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class DeactivatePatientCommand(Command[PatientAdministrativeView]):
    """The clinic administrator closes a patient account for good."""

    audit_action: ClassVar[str] = "PATIENT_DEACTIVATED"
    audit_entity_type: ClassVar[str] = PATIENT_ENTITY

    patient_id: UUID
    reason: str

    @override
    def audit_subject(self, result: PatientAdministrativeView) -> AuditSubject:
        return AuditSubject(
            clinic_id=self.actor.clinic_id,
            entity_id=result.patient_id,
            reason=Reason.parse(self.reason).text,
            changed_fields=STATUS_FIELDS,
        )


def _load_account(
    patients: PatientDirectoryPort,
    users: UserRepositoryPort,
    clinic_id: UUID,
    patient_id: UUID,
) -> UserAccount:
    """The account of a patient of ``clinic_id``; anything else is not found."""
    patient = patients.find(patient_id)
    if patient is None or patient.clinic_id != clinic_id or patient.user_id is None:
        raise ResourceNotFoundError
    account = users.get(patient.user_id)
    if account is None:
        raise ResourceNotFoundError
    return account


def _current_view(
    roster: PatientRosterPort, clinic_id: UUID, patient_id: UUID
) -> PatientAdministrativeView:
    """The patient as it is after the change, read in the same transaction."""
    view = roster.get(clinic_id, patient_id)
    if view is None:
        raise ResourceNotFoundError
    return view


@final
class SuspendPatientCommandHandler(
    CommandHandler[SuspendPatientCommand, PatientAdministrativeView]
):
    """``ACTIVE -> SUSPENDED``: the token version moves and refresh tokens end.

    Pattern: P13 Command
    """

    def __init__(
        self,
        *,
        patients: PatientDirectoryPort,
        users: UserRepositoryPort,
        refresh_tokens: RefreshTokenRepositoryPort,
        roster: PatientRosterPort,
        clock: Clock,
    ) -> None:
        self._patients = patients
        self._users = users
        self._refresh_tokens = refresh_tokens
        self._roster = roster
        self._clock = clock

    @override
    def handle(self, command: SuspendPatientCommand) -> PatientAdministrativeView:
        actor = command.actor
        actor.require(PermissionCode.PATIENTS_MANAGE_STATUS)
        clinic_id = clinic_of(actor)
        reason = Reason.parse(command.reason)
        account = _load_account(
            self._patients, self._users, clinic_id, command.patient_id
        )
        now = self._clock.now()
        self._users.save(account.suspended(reason=reason.text).with_revoked_sessions())
        self._refresh_tokens.revoke_all_for_user(
            account.user_id, reason=RevocationReason.ACCOUNT_SUSPENDED, now=now
        )
        return _current_view(self._roster, clinic_id, command.patient_id)


@final
class ReactivatePatientCommandHandler(
    CommandHandler[ReactivatePatientCommand, PatientAdministrativeView]
):
    """``SUSPENDED -> ACTIVE``. The sessions were already ended by the suspension.

    Pattern: P13 Command
    """

    def __init__(
        self,
        *,
        patients: PatientDirectoryPort,
        users: UserRepositoryPort,
        roster: PatientRosterPort,
    ) -> None:
        self._patients = patients
        self._users = users
        self._roster = roster

    @override
    def handle(self, command: ReactivatePatientCommand) -> PatientAdministrativeView:
        actor = command.actor
        actor.require(PermissionCode.PATIENTS_MANAGE_STATUS)
        clinic_id = clinic_of(actor)
        if command.reason is not None:
            Reason.parse(command.reason)
        account = _load_account(
            self._patients, self._users, clinic_id, command.patient_id
        )
        self._users.save(account.reactivated())
        return _current_view(self._roster, clinic_id, command.patient_id)


@final
class DeactivatePatientCommandHandler(
    CommandHandler[DeactivatePatientCommand, PatientAdministrativeView]
):
    """Closes the account (terminal): sessions end and pending invitations are revoked.

    Pattern: P13 Command
    """

    def __init__(
        self,
        *,
        patients: PatientDirectoryPort,
        users: UserRepositoryPort,
        refresh_tokens: RefreshTokenRepositoryPort,
        invitations: PendingInvitationPort,
        roster: PatientRosterPort,
        clock: Clock,
    ) -> None:
        self._patients = patients
        self._users = users
        self._refresh_tokens = refresh_tokens
        self._invitations = invitations
        self._roster = roster
        self._clock = clock

    @override
    def handle(self, command: DeactivatePatientCommand) -> PatientAdministrativeView:
        actor = command.actor
        actor.require(PermissionCode.PATIENTS_MANAGE_STATUS)
        clinic_id = clinic_of(actor)
        reason = Reason.parse(command.reason)
        account = _load_account(
            self._patients, self._users, clinic_id, command.patient_id
        )
        now = self._clock.now()
        self._users.save(
            account.deactivated(reason=reason.text).with_revoked_sessions()
        )
        self._refresh_tokens.revoke_all_for_user(
            account.user_id, reason=RevocationReason.ACCOUNT_DEACTIVATED, now=now
        )
        self._invitations.revoke_pending(
            account.user_id, revoked_by=actor.user_id, now=now
        )
        return _current_view(self._roster, clinic_id, command.patient_id)
