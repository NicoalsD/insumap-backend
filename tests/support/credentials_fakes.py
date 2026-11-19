"""In-memory patient contacts and activation invitations for the credential tests.

``FakeCredentialInvitations`` enforces what the database enforces: one open
``PATIENT_ACTIVATION`` invitation per account (the unique partial index) and a
single code hash. It keeps the columns the domain object does not carry
(channel, delivery, who revoked, what replaced it) so tests can check them.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import override
from uuid import UUID

from insumap.application.credentials.ports import (
    CredentialInvitationPort,
    NewPatientInvitation,
    PatientContact,
    PatientContactPort,
)
from insumap.application.users.ports import ActivationCodeGeneratorPort
from insumap.domain.common.errors import ConflictError
from insumap.domain.identity.codes import ActivationCode
from insumap.domain.identity.invitation import (
    CredentialInvitation,
    DeliveryStatus,
    InvitationChannel,
    InvitationPurpose,
    InvitationStatus,
)


class FakePatientContacts(PatientContactPort):
    """Imported patients by id, with the contact email the activation mail uses."""

    def __init__(self) -> None:
        self.patients: dict[UUID, PatientContact] = {}

    def add(self, contact: PatientContact) -> None:
        self.patients[contact.patient_id] = contact

    @override
    def find(self, patient_id: UUID) -> PatientContact | None:
        return self.patients.get(patient_id)


@dataclass(frozen=True, slots=True, kw_only=True)
class StoredInvitation:
    """One row of ``iam.credential_invitations`` as the fake keeps it."""

    invitation: CredentialInvitation
    channel: InvitationChannel
    delivery_status: DeliveryStatus
    code_hash: str
    revoked_by: UUID | None = None
    replaced_by_id: UUID | None = None


class FakeCredentialInvitations(CredentialInvitationPort):
    """Patient activation invitations, keyed by id."""

    def __init__(self) -> None:
        self.rows: dict[UUID, StoredInvitation] = {}

    def row(self, invitation_id: UUID) -> StoredInvitation:
        return self.rows[invitation_id]

    def open_for(self, user_id: UUID) -> list[StoredInvitation]:
        return [
            row
            for row in self.rows.values()
            if row.invitation.user_id == user_id and row.invitation.is_open
        ]

    @override
    def find_open_for_user(self, user_id: UUID) -> CredentialInvitation | None:
        open_rows = [
            row.invitation
            for row in self.rows.values()
            if row.invitation.user_id == user_id
            and row.invitation.purpose is InvitationPurpose.PATIENT_ACTIVATION
            and row.invitation.is_open
        ]
        assert len(open_rows) <= 1, "more than one open invitation per account"
        return open_rows[0] if open_rows else None

    @override
    def get(self, invitation_id: UUID) -> CredentialInvitation | None:
        row = self.rows.get(invitation_id)
        return None if row is None else row.invitation

    @override
    def add(self, invitation: NewPatientInvitation) -> None:
        if self.open_for(invitation.user_id):
            raise ConflictError("open_invitation")
        if any(row.code_hash == invitation.code_hash for row in self.rows.values()):
            raise ConflictError("code_hash")
        self.rows[invitation.invitation_id] = StoredInvitation(
            invitation=CredentialInvitation(
                invitation_id=invitation.invitation_id,
                user_id=invitation.user_id,
                clinic_id=invitation.clinic_id,
                patient_id=invitation.patient_id,
                purpose=InvitationPurpose.PATIENT_ACTIVATION,
                status=InvitationStatus.PENDING,
                expires_at=invitation.expires_at,
                failed_attempts=0,
            ),
            channel=invitation.channel,
            delivery_status=invitation.delivery_status,
            code_hash=invitation.code_hash,
        )

    @override
    def mark_revoked(
        self, invitation_id: UUID, *, revoked_at: datetime, revoked_by: UUID
    ) -> None:
        row = self.rows[invitation_id]
        self.rows[invitation_id] = replace(
            row,
            invitation=replace(
                row.invitation, status=InvitationStatus.REVOKED, revoked_at=revoked_at
            ),
            revoked_by=revoked_by,
        )

    @override
    def link_replacement(self, invitation_id: UUID, replaced_by_id: UUID) -> None:
        row = self.rows[invitation_id]
        self.rows[invitation_id] = replace(row, replaced_by_id=replaced_by_id)


class SequenceActivationCodes(ActivationCodeGeneratorPort):
    """Hands out the given codes in order, so a re-issue gets a different one."""

    def __init__(self, *values: str) -> None:
        self._values = list(values)

    @override
    def generate(self) -> ActivationCode:
        return ActivationCode(self._values.pop(0))
