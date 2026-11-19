"""Consent history, privacy notices and privacy requests in PostgreSQL (RLS applies)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import final, override
from uuid import UUID

from sqlalchemy import select

from insumap.application.common.pagination import Page, PageRequest, build_page
from insumap.application.consents.ports import (
    ConsentHistoryPort,
    PatientConsentStatus,
    PrivacyNoticeQueryPort,
    PrivacyNoticeView,
    PrivacyRequestPort,
)
from insumap.domain.identity.consent import (
    ConsentAction,
    ConsentRecord,
    ConsentScope,
    standing_of,
)
from insumap.domain.privacy.request import (
    PrivacyRequest,
    PrivacyRequestStatus,
    PrivacyRequestType,
)
from insumap.infrastructure.persistence.orm import (
    PatientConsentOrm,
    PatientOrm,
    PrivacyNoticeVersionOrm,
    PrivacyRequestOrm,
)
from insumap.infrastructure.persistence.transactions import CurrentSession

SENSITIVE = ConsentScope.SENSITIVE_DATA_PROCESSING.value


def _record(row: PatientConsentOrm) -> ConsentRecord:
    return ConsentRecord(
        consent_id=row.id,
        clinic_id=row.clinic_id,
        patient_id=row.patient_id,
        privacy_notice_version_id=row.privacy_notice_version_id,
        scope=ConsentScope(row.scope),
        action=ConsentAction(row.action),
        occurred_at=row.occurred_at,
        recorded_by=row.recorded_by,
    )


@final
class ConsentHistoryRepository(ConsentHistoryPort):
    """``clinic.patient_consents`` read under RLS (the patient or the clinic staff)."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def latest_per_scope(
        self, patient_id: UUID
    ) -> Mapping[ConsentScope, ConsentRecord]:
        rows = (
            self._current.get()
            .execute(
                select(PatientConsentOrm)
                .where(PatientConsentOrm.patient_id == patient_id)
                .order_by(
                    PatientConsentOrm.occurred_at.desc(), PatientConsentOrm.id.desc()
                )
            )
            .scalars()
            .all()
        )
        latest: dict[ConsentScope, ConsentRecord] = {}
        for row in rows:
            scope = ConsentScope(row.scope)
            latest.setdefault(scope, _record(row))
        return latest

    @override
    def history(self, patient_id: UUID) -> list[ConsentRecord]:
        rows = (
            self._current.get()
            .execute(
                select(PatientConsentOrm)
                .where(PatientConsentOrm.patient_id == patient_id)
                .order_by(PatientConsentOrm.occurred_at, PatientConsentOrm.id)
            )
            .scalars()
            .all()
        )
        return [_record(row) for row in rows]

    @override
    def statuses(
        self, clinic_id: UUID, page: PageRequest
    ) -> Page[PatientConsentStatus]:
        session = self._current.get()
        query = select(PatientOrm.id).where(PatientOrm.clinic_id == clinic_id)
        if page.after is not None:
            query = query.where(PatientOrm.id > page.after)
        ids = list(
            session.execute(query.order_by(PatientOrm.id).limit(page.limit + 1))
            .scalars()
            .all()
        )
        current = session.execute(
            select(PrivacyNoticeVersionOrm.id).where(
                PrivacyNoticeVersionOrm.clinic_id == clinic_id,
                PrivacyNoticeVersionOrm.is_current.is_(True),
            )
        ).scalar()
        page_ids = build_page(ids, limit=page.limit, key=lambda patient: patient)
        latest = self._latest_sensitive(page_ids.items)
        items = [
            _status(patient_id, latest.get(patient_id), current)
            for patient_id in page_ids.items
        ]
        return Page(items=items, next_cursor=page_ids.next_cursor)

    def _latest_sensitive(
        self, patient_ids: Sequence[UUID]
    ) -> dict[UUID, ConsentRecord]:
        if not patient_ids:
            return {}
        rows = (
            self._current.get()
            .execute(
                select(PatientConsentOrm)
                .where(
                    PatientConsentOrm.patient_id.in_(patient_ids),
                    PatientConsentOrm.scope == SENSITIVE,
                )
                .order_by(
                    PatientConsentOrm.occurred_at.desc(), PatientConsentOrm.id.desc()
                )
            )
            .scalars()
            .all()
        )
        latest: dict[UUID, ConsentRecord] = {}
        for row in rows:
            latest.setdefault(row.patient_id, _record(row))
        return latest


def _status(
    patient_id: UUID, record: ConsentRecord | None, current: UUID | None
) -> PatientConsentStatus:
    return PatientConsentStatus(
        patient_id=patient_id,
        standing=standing_of(record, current),
        privacy_notice_version_id=None
        if record is None
        else record.privacy_notice_version_id,
        occurred_at=None if record is None else record.occurred_at,
    )


@final
class PrivacyNoticeQueryRepository(PrivacyNoticeQueryPort):
    """``clinic.privacy_notice_versions`` by id. RLS hides it without a clinic."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def find(self, notice_id: UUID) -> PrivacyNoticeView | None:
        row = (
            self._current.get()
            .execute(
                select(PrivacyNoticeVersionOrm).where(
                    PrivacyNoticeVersionOrm.id == notice_id
                )
            )
            .scalar_one_or_none()
        )
        if row is None:
            return None
        return PrivacyNoticeView(
            version_id=row.id,
            clinic_id=row.clinic_id,
            version=row.version,
            content=row.content,
            effective_from=row.effective_from,
        )


def _request(row: PrivacyRequestOrm) -> PrivacyRequest:
    return PrivacyRequest(
        request_id=row.id,
        clinic_id=row.clinic_id,
        patient_id=row.patient_id,
        request_type=PrivacyRequestType(row.request_type),
        status=PrivacyRequestStatus(row.status),
        requested_at=row.requested_at,
        due_at=row.due_at,
        resolved_at=row.resolved_at,
        resolved_by=row.resolved_by,
        resolution_note=row.resolution_note,
    )


@final
class PrivacyRequestRepository(PrivacyRequestPort):
    """``clinic.privacy_requests`` under RLS: the patient's own or the clinic's."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def get(self, request_id: UUID) -> PrivacyRequest | None:
        row = (
            self._current.get()
            .execute(
                select(PrivacyRequestOrm).where(PrivacyRequestOrm.id == request_id)
            )
            .scalar_one_or_none()
        )
        return None if row is None else _request(row)

    @override
    def list(self, patient_id: UUID | None, page: PageRequest) -> Page[PrivacyRequest]:
        query = select(PrivacyRequestOrm)
        if patient_id is not None:
            query = query.where(PrivacyRequestOrm.patient_id == patient_id)
        if page.after is not None:
            query = query.where(PrivacyRequestOrm.id > page.after)
        rows = (
            self._current.get()
            .execute(query.order_by(PrivacyRequestOrm.id).limit(page.limit + 1))
            .scalars()
            .all()
        )
        result = build_page(
            [_request(row) for row in rows],
            limit=page.limit,
            key=lambda r: r.request_id,
        )
        return result

    @override
    def add(self, request: PrivacyRequest) -> None:
        self._current.get().add(
            PrivacyRequestOrm(
                id=request.request_id,
                clinic_id=request.clinic_id,
                patient_id=request.patient_id,
                request_type=request.request_type.value,
                status=request.status.value,
                description=None,
                requested_at=request.requested_at,
                due_at=request.due_at,
                created_at=request.requested_at,
                updated_at=request.requested_at,
            )
        )
        self._current.get().flush()

    @override
    def save(self, request: PrivacyRequest) -> None:
        row = self._current.get().get(PrivacyRequestOrm, request.request_id)
        if row is None:
            raise LookupError("privacy request vanished inside its transaction")
        row.status = request.status.value
        row.resolved_at = request.resolved_at
        row.resolved_by = request.resolved_by
        row.resolution_note = request.resolution_note
        row.updated_at = request.resolved_at or row.updated_at
        self._current.get().flush()
