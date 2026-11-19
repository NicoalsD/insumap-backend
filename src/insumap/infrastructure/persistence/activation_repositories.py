"""Invitations, the imported patient data, privacy notices and consent."""

from __future__ import annotations

from collections.abc import Sequence
from typing import final, override
from uuid import UUID

from sqlalchemy import select, text, update

from insumap.application.identity.ports import (
    ActivationProfile,
    ActivationRepositoryPort,
    ConsentRepositoryPort,
    PrivacyNotice,
)
from insumap.domain.identity.consent import ConsentAction, ConsentRecord, ConsentScope
from insumap.domain.identity.invitation import (
    CredentialInvitation,
    InvitationPurpose,
    InvitationStatus,
)
from insumap.infrastructure.persistence.orm import (
    ClinicOrm,
    CredentialInvitationOrm,
    PatientConsentOrm,
    PatientOrm,
    PrivacyNoticeVersionOrm,
)
from insumap.infrastructure.persistence.transactions import CurrentSession

INVITATION_LOOKUP = text("SELECT * FROM iam.lookup_invitation_by_code_hash(:code_hash)")


@final
class ActivationRepository(ActivationRepositoryPort):
    """``iam.credential_invitations`` and the patient the code belongs to."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def find_invitation(
        self, code_hashes: Sequence[str]
    ) -> CredentialInvitation | None:
        for code_hash in code_hashes:
            row = (
                self._current.get()
                .execute(INVITATION_LOOKUP, {"code_hash": code_hash})
                .mappings()
                .first()
            )
            if row is not None:
                return CredentialInvitation(
                    invitation_id=row["invitation_id"],
                    user_id=row["user_id"],
                    clinic_id=row["clinic_id"],
                    patient_id=None,
                    purpose=InvitationPurpose(row["purpose"]),
                    status=InvitationStatus(row["status"]),
                    expires_at=row["expires_at"],
                    failed_attempts=row["failed_attempts"],
                )
        return None

    @override
    def get_invitation(self, invitation_id: UUID) -> CredentialInvitation | None:
        row = (
            self._current.get()
            .scalars(
                select(CredentialInvitationOrm).where(
                    CredentialInvitationOrm.id == invitation_id
                )
            )
            .first()
        )
        if row is None:
            return None
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
        )

    @override
    def save_invitation(self, invitation: CredentialInvitation) -> None:
        self._current.get().execute(
            update(CredentialInvitationOrm)
            .where(CredentialInvitationOrm.id == invitation.invitation_id)
            .values(
                status=invitation.status.value,
                failed_attempts=invitation.failed_attempts,
                verified_at=invitation.verified_at,
                used_at=invitation.used_at,
            )
        )

    @override
    def activation_profile(self, patient_id: UUID) -> ActivationProfile | None:
        row = (
            self._current.get()
            .execute(
                select(
                    PatientOrm.id,
                    ClinicOrm.name,
                    PatientOrm.birth_date,
                    PatientOrm.full_name,
                    PatientOrm.contact_email,
                )
                .join(ClinicOrm, ClinicOrm.id == PatientOrm.clinic_id)
                .where(PatientOrm.id == patient_id)
            )
            .first()
        )
        if row is None:
            return None
        return ActivationProfile(
            patient_id=row.id,
            clinic_name=row.name,
            birth_date=row.birth_date,
            full_name=row.full_name,
            contact_email=row.contact_email,
        )


@final
class ConsentRepository(ConsentRepositoryPort):
    """Privacy notice versions and the append-only ``patient_consents``."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def current_notice(self, clinic_id: UUID) -> PrivacyNotice | None:
        version_id = (
            self._current.get()
            .execute(
                select(PrivacyNoticeVersionOrm.id).where(
                    PrivacyNoticeVersionOrm.clinic_id == clinic_id,
                    PrivacyNoticeVersionOrm.is_current.is_(True),
                )
            )
            .scalar()
        )
        return (
            None
            if version_id is None
            else PrivacyNotice(version_id=version_id, clinic_id=clinic_id)
        )

    @override
    def add(self, records: Sequence[ConsentRecord]) -> None:
        session = self._current.get()
        session.add_all(
            PatientConsentOrm(
                id=record.consent_id,
                clinic_id=record.clinic_id,
                patient_id=record.patient_id,
                privacy_notice_version_id=record.privacy_notice_version_id,
                scope=record.scope.value,
                action=record.action.value,
                occurred_at=record.occurred_at,
                recorded_by=record.recorded_by,
            )
            for record in records
        )
        session.flush()

    @override
    def has_accepted_current(self, patient_id: UUID, clinic_id: UUID) -> bool:
        notice = self.current_notice(clinic_id)
        if notice is None:
            return False
        action = (
            self._current.get()
            .execute(
                select(PatientConsentOrm.action)
                .where(
                    PatientConsentOrm.patient_id == patient_id,
                    PatientConsentOrm.privacy_notice_version_id == notice.version_id,
                    PatientConsentOrm.scope
                    == ConsentScope.SENSITIVE_DATA_PROCESSING.value,
                )
                .order_by(
                    PatientConsentOrm.occurred_at.desc(), PatientConsentOrm.id.desc()
                )
                .limit(1)
            )
            .scalar()
        )
        return action == ConsentAction.ACCEPTED.value
