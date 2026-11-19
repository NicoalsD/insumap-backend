"""In-memory doubles of the consent and privacy ports (API.md 8.13)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import override
from uuid import UUID

from insumap.application.common.pagination import Page, PageRequest, build_page
from insumap.application.consents.ports import (
    ConsentHistoryPort,
    PatientConsentStatus,
    PrivacyNoticeQueryPort,
    PrivacyNoticeView,
    PrivacyRequestPort,
)
from insumap.application.identity.ports import PrivacyNotice
from insumap.domain.identity.consent import (
    ConsentAction,
    ConsentRecord,
    ConsentScope,
    standing_of,
)
from insumap.domain.privacy.request import PrivacyRequest
from insumap.infrastructure.consents_adapters import ConsentsAdapters
from tests.support.access_fakes import InMemoryDataAccessLog


def _latest(records: Sequence[ConsentRecord]) -> dict[ConsentScope, ConsentRecord]:
    """The latest act per scope: by time, then by insertion (ids grow, like UUIDv7)."""
    latest: dict[ConsentScope, ConsentRecord] = {}
    for record in reversed(sorted(records, key=lambda r: r.occurred_at)):
        latest.setdefault(record.scope, record)
    return latest


class FakeConsentHistory(ConsentHistoryPort):
    """Reads the acts of a shared list, like the append-only table."""

    def __init__(
        self,
        records: list[ConsentRecord],
        notices: Mapping[UUID, PrivacyNotice],
        patient_ids: Sequence[UUID],
    ) -> None:
        self._records = records
        self._notices = notices
        self.patient_ids = list(patient_ids)

    def _of(self, patient_id: UUID) -> list[ConsentRecord]:
        return [r for r in self._records if r.patient_id == patient_id]

    @override
    def latest_per_scope(
        self, patient_id: UUID
    ) -> Mapping[ConsentScope, ConsentRecord]:
        return _latest(self._of(patient_id))

    @override
    def history(self, patient_id: UUID) -> list[ConsentRecord]:
        return sorted(self._of(patient_id), key=lambda r: r.occurred_at)

    @override
    def statuses(
        self, clinic_id: UUID, page: PageRequest
    ) -> Page[PatientConsentStatus]:
        ids = [
            pid for pid in self.patient_ids if page.after is None or pid > page.after
        ]
        ids.sort()
        window = build_page(ids[: page.limit + 1], limit=page.limit, key=lambda p: p)
        notice = self._notices.get(clinic_id)
        current = None if notice is None else notice.version_id
        items: list[PatientConsentStatus] = []
        for patient_id in window.items:
            sensitive = [
                r
                for r in self._of(patient_id)
                if r.scope is ConsentScope.SENSITIVE_DATA_PROCESSING
            ]
            latest = _latest(sensitive).get(ConsentScope.SENSITIVE_DATA_PROCESSING)
            items.append(
                PatientConsentStatus(
                    patient_id=patient_id,
                    standing=standing_of(latest, current),
                    privacy_notice_version_id=None
                    if latest is None
                    else latest.privacy_notice_version_id,
                    occurred_at=None if latest is None else latest.occurred_at,
                )
            )
        return Page(items=items, next_cursor=window.next_cursor)


class FakePrivacyNotices(PrivacyNoticeQueryPort):
    def __init__(self) -> None:
        self.views: dict[UUID, PrivacyNoticeView] = {}

    @override
    def find(self, notice_id: UUID) -> PrivacyNoticeView | None:
        return self.views.get(notice_id)


class FakePrivacyRequests(PrivacyRequestPort):
    def __init__(self) -> None:
        self.rows: dict[UUID, PrivacyRequest] = {}

    @override
    def get(self, request_id: UUID) -> PrivacyRequest | None:
        return self.rows.get(request_id)

    @override
    def list(self, patient_id: UUID | None, page: PageRequest) -> Page[PrivacyRequest]:
        rows = sorted(self.rows.values(), key=lambda r: r.request_id)
        if patient_id is not None:
            rows = [r for r in rows if r.patient_id == patient_id]
        if page.after is not None:
            rows = [r for r in rows if r.request_id > page.after]
        return build_page(
            rows[: page.limit + 1], limit=page.limit, key=lambda r: r.request_id
        )

    @override
    def add(self, request: PrivacyRequest) -> None:
        self.rows[request.request_id] = request

    @override
    def save(self, request: PrivacyRequest) -> None:
        self.rows[request.request_id] = request


class ConsentsWorld:
    """The doubles of the consent routes, sharing the acts of an identity world."""

    def __init__(
        self,
        *,
        records: list[ConsentRecord],
        notices: dict[UUID, PrivacyNotice],
        patient_ids: Sequence[UUID],
    ) -> None:
        self.history = FakeConsentHistory(records, notices, patient_ids)
        self.notices = FakePrivacyNotices()
        self.requests = FakePrivacyRequests()
        self.access_log = InMemoryDataAccessLog()

    def adapters(self) -> ConsentsAdapters:
        return ConsentsAdapters(
            history=self.history,
            notices=self.notices,
            requests=self.requests,
            access_log=self.access_log,
        )


__all__ = [
    "ConsentAction",
    "ConsentsWorld",
    "FakeConsentHistory",
    "FakePrivacyNotices",
    "FakePrivacyRequests",
]
