"""The administrator's view of ``clinic.patients`` and its pending invitations.

Every query is scoped to one clinic twice: by the explicit ``clinic_id`` and by
row level security. The document is never selected: only its last digits.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final, final, override
from uuid import UUID

from sqlalchemy import Row, exists, func, select, update
from sqlalchemy.sql.selectable import ScalarSelect, Select

from insumap.application.common.pagination import Page, PageRequest, build_page
from insumap.application.patients.ports import (
    PatientAdministrativeView,
    PatientRosterFilter,
    PatientRosterPort,
    PendingInvitationPort,
)
from insumap.domain.identity.account_state import AccountStatus
from insumap.domain.identity.invitation import InvitationStatus
from insumap.infrastructure.persistence.orm import (
    CareAssignmentOrm,
    ClinicOrm,
    CredentialInvitationOrm,
    PatientOrm,
    UserOrm,
)
from insumap.infrastructure.persistence.transactions import CurrentSession

UNUSED_INVITATIONS: Final = (
    InvitationStatus.PENDING.value,
    InvitationStatus.VERIFIED.value,
)
"""Invitations that a deactivation revokes: the code was not used to activate."""


def _primary_doctor() -> ScalarSelect[Any]:
    return (
        select(CareAssignmentOrm.doctor_user_id)
        .where(
            CareAssignmentOrm.patient_id == PatientOrm.id,
            CareAssignmentOrm.is_primary.is_(True),
            CareAssignmentOrm.ended_at.is_(None),
        )
        .limit(1)
        .scalar_subquery()
    )


def _open_doctor_count() -> Any:
    return func.coalesce(
        select(func.count())
        .select_from(CareAssignmentOrm)
        .where(
            CareAssignmentOrm.patient_id == PatientOrm.id,
            CareAssignmentOrm.ended_at.is_(None),
        )
        .scalar_subquery(),
        0,
    )


def _latest_invitation_status() -> ScalarSelect[Any]:
    return (
        select(CredentialInvitationOrm.status)
        .where(CredentialInvitationOrm.patient_id == PatientOrm.id)
        .order_by(CredentialInvitationOrm.issued_at.desc(), CredentialInvitationOrm.id)
        .limit(1)
        .scalar_subquery()
    )


def _roster_statement() -> Select[Any]:
    return (
        select(
            PatientOrm.id.label("patient_id"),
            PatientOrm.clinic_id.label("clinic_id"),
            PatientOrm.full_name.label("full_name"),
            PatientOrm.mrn.label("mrn"),
            PatientOrm.document_last4.label("document_last4"),
            UserOrm.status.label("account_status"),
            _primary_doctor().label("primary_doctor_id"),
            _open_doctor_count().label("assigned_doctor_count"),
            _latest_invitation_status().label("invitation_status"),
            ClinicOrm.is_demo.label("simulated"),
        )
        .join(UserOrm, UserOrm.id == PatientOrm.user_id)
        .join(ClinicOrm, ClinicOrm.id == PatientOrm.clinic_id)
    )


def _view(row: Row[Any]) -> PatientAdministrativeView:
    values = row._mapping
    invitation = values["invitation_status"]
    return PatientAdministrativeView(
        patient_id=values["patient_id"],
        clinic_id=values["clinic_id"],
        full_name=values["full_name"],
        mrn=values["mrn"],
        document_last4=values["document_last4"],
        account_status=AccountStatus(values["account_status"]),
        primary_doctor_id=values["primary_doctor_id"],
        assigned_doctor_count=int(values["assigned_doctor_count"]),
        invitation_status=None if invitation is None else InvitationStatus(invitation),
        simulated=bool(values["simulated"]),
    )


@final
class PatientRosterRepository(PatientRosterPort):
    """Patients of one clinic with their team, account and invitation summary."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def get(
        self, clinic_id: UUID, patient_id: UUID
    ) -> PatientAdministrativeView | None:
        statement = _roster_statement().where(
            PatientOrm.id == patient_id, PatientOrm.clinic_id == clinic_id
        )
        row = self._current.get().execute(statement).first()
        return None if row is None else _view(row)

    @override
    def list(
        self, clinic_id: UUID, filters: PatientRosterFilter, page: PageRequest
    ) -> Page[PatientAdministrativeView]:
        statement = _roster_statement().where(PatientOrm.clinic_id == clinic_id)
        if page.after is not None:
            statement = statement.where(PatientOrm.id > page.after)
        if filters.account_status is not None:
            statement = statement.where(UserOrm.status == filters.account_status.value)
        if filters.without_doctor:
            statement = statement.where(
                ~exists().where(
                    CareAssignmentOrm.patient_id == PatientOrm.id,
                    CareAssignmentOrm.ended_at.is_(None),
                )
            )
        if filters.import_batch_id is not None:
            statement = statement.where(
                PatientOrm.import_batch_id == filters.import_batch_id
            )
        rows = (
            self._current.get()
            .execute(statement.order_by(PatientOrm.id).limit(page.limit + 1))
            .all()
        )
        return build_page(
            [_view(row) for row in rows],
            limit=page.limit,
            key=lambda view: view.patient_id,
        )


@final
class PendingInvitationRepository(PendingInvitationPort):
    """``iam.credential_invitations``: the invitations an account still holds."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def revoke_pending(self, user_id: UUID, *, revoked_by: UUID, now: datetime) -> None:
        self._current.get().execute(
            update(CredentialInvitationOrm)
            .where(
                CredentialInvitationOrm.user_id == user_id,
                CredentialInvitationOrm.status.in_(UNUSED_INVITATIONS),
            )
            .values(
                status=InvitationStatus.REVOKED.value,
                revoked_at=now,
                revoked_by=revoked_by,
            )
        )
