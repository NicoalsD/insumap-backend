"""Patient contacts and activation invitations, under row level security."""

from __future__ import annotations

from datetime import datetime
from typing import Final, final, override
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from insumap.application.credentials.ports import (
    CredentialInvitationPort,
    NewPatientInvitation,
    PatientContact,
    PatientContactPort,
)
from insumap.domain.common.errors import ConflictError
from insumap.domain.identity.invitation import (
    OPEN_STATUSES,
    CredentialInvitation,
    InvitationPurpose,
    InvitationStatus,
)
from insumap.infrastructure.persistence.orm import (
    CredentialInvitationOrm,
    PatientOrm,
)
from insumap.infrastructure.persistence.transactions import CurrentSession

OPEN_INVITATION_REASON: Final = "open_invitation"
"""Reason of the ``409`` when another open invitation won the unique index."""


def _invitation(row: CredentialInvitationOrm) -> CredentialInvitation:
    return CredentialInvitation(
        invitation_id=row.id,
        user_id=row.user_id,
        clinic_id=row.clinic_id,
        patient_id=row.patient_id,
        purpose=InvitationPurpose(row.purpose),
        status=InvitationStatus(row.status),
        expires_at=row.expires_at,
        failed_attempts=row.failed_attempts,
        verified_at=row.verified_at,
        used_at=row.used_at,
        revoked_at=row.revoked_at,
    )


@final
class PatientContactRepository(PatientContactPort):
    """``clinic.patients`` rows the credential flow reads."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def find(self, patient_id: UUID) -> PatientContact | None:
        row = (
            self._current.get()
            .execute(
                select(
                    PatientOrm.id,
                    PatientOrm.clinic_id,
                    PatientOrm.user_id,
                    PatientOrm.contact_email,
                ).where(PatientOrm.id == patient_id)
            )
            .first()
        )
        if row is None:
            return None
        return PatientContact(
            patient_id=row.id,
            clinic_id=row.clinic_id,
            user_id=row.user_id,
            contact_email=row.contact_email,
        )


@final
class CredentialInvitationRepository(CredentialInvitationPort):
    """``iam.credential_invitations`` rows of purpose ``PATIENT_ACTIVATION``."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def find_open_for_user(self, user_id: UUID) -> CredentialInvitation | None:
        row = (
            self._current.get()
            .scalars(
                select(CredentialInvitationOrm).where(
                    CredentialInvitationOrm.user_id == user_id,
                    CredentialInvitationOrm.purpose
                    == InvitationPurpose.PATIENT_ACTIVATION.value,
                    CredentialInvitationOrm.status.in_(
                        sorted(status.value for status in OPEN_STATUSES)
                    ),
                )
            )
            .first()
        )
        return None if row is None else _invitation(row)

    @override
    def get(self, invitation_id: UUID) -> CredentialInvitation | None:
        row = (
            self._current.get()
            .scalars(
                select(CredentialInvitationOrm).where(
                    CredentialInvitationOrm.id == invitation_id
                )
            )
            .first()
        )
        return None if row is None else _invitation(row)

    @override
    def add(self, invitation: NewPatientInvitation) -> None:
        session = self._current.get()
        session.add(
            CredentialInvitationOrm(
                id=invitation.invitation_id,
                clinic_id=invitation.clinic_id,
                user_id=invitation.user_id,
                patient_id=invitation.patient_id,
                purpose=InvitationPurpose.PATIENT_ACTIVATION.value,
                channel=invitation.channel.value,
                status=InvitationStatus.PENDING.value,
                code_hash=invitation.code_hash,
                code_key_id=invitation.code_key_id,
                failed_attempts=0,
                expires_at=invitation.expires_at,
                issued_by=invitation.issued_by,
                issued_at=invitation.issued_at,
                delivery_status=invitation.delivery_status.value,
            )
        )
        try:
            session.flush()
        except IntegrityError as error:
            # Only the open-invitation index can clash here; the code hash is random.
            raise ConflictError(OPEN_INVITATION_REASON) from error

    @override
    def mark_revoked(
        self, invitation_id: UUID, *, revoked_at: datetime, revoked_by: UUID
    ) -> None:
        self._current.get().execute(
            update(CredentialInvitationOrm)
            .where(CredentialInvitationOrm.id == invitation_id)
            .values(
                status=InvitationStatus.REVOKED.value,
                revoked_at=revoked_at,
                revoked_by=revoked_by,
            )
        )

    @override
    def link_replacement(self, invitation_id: UUID, replaced_by_id: UUID) -> None:
        self._current.get().execute(
            update(CredentialInvitationOrm)
            .where(CredentialInvitationOrm.id == invitation_id)
            .values(replaced_by_id=replaced_by_id)
        )
