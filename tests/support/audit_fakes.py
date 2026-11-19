"""In-memory doubles of the audit ports, for unit and API tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import override
from uuid import UUID

from insumap.application.access.ports import (
    AccessPurpose,
    DataAccessOutcome,
    DataResource,
)
from insumap.application.audit.ports import (
    AuditChainPort,
    AuditLogFilter,
    AuditLogReadPort,
    AuditLogRow,
    DataAccessFilter,
    DataAccessReadPort,
    DataAccessRow,
    SecurityEventFilter,
    SecurityEventKind,
    SecurityEventReadPort,
    SecurityEventRow,
)
from insumap.application.common.pagination import Page, PageRequest, build_page
from insumap.application.security.events import SecuritySeverity
from insumap.infrastructure.audit_adapters import AuditAdapters

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)


def _newest(rows: list[UUID], page: PageRequest) -> list[UUID]:
    ordered = sorted(rows, reverse=True)
    if page.after is not None:
        ordered = [key for key in ordered if key < page.after]
    return ordered[: page.limit + 1]


class FakeAuditLog(AuditLogReadPort):
    def __init__(self) -> None:
        self.rows: list[tuple[UUID, AuditLogRow]] = []  # (clinic_id, row)

    def add(self, clinic_id: UUID, row: AuditLogRow) -> None:
        self.rows.append((clinic_id, row))

    @override
    def list(
        self, clinic_id: UUID, filters: AuditLogFilter, page: PageRequest
    ) -> Page[AuditLogRow]:
        rows = {r.id: r for c, r in self.rows if c == clinic_id}
        selected = [
            rows[key]
            for key in _newest(list(rows), page)
            if filters.action is None or rows[key].action == filters.action
        ]
        return build_page(selected, limit=page.limit, key=lambda r: r.id)


class FakeDataAccess(DataAccessReadPort):
    def __init__(self) -> None:
        self.rows: list[tuple[UUID, DataAccessRow]] = []

    def add(self, clinic_id: UUID, row: DataAccessRow) -> None:
        self.rows.append((clinic_id, row))

    @override
    def list(
        self, clinic_id: UUID, filters: DataAccessFilter, page: PageRequest
    ) -> Page[DataAccessRow]:
        rows = {r.id: r for c, r in self.rows if c == clinic_id}
        selected = [
            rows[key]
            for key in _newest(list(rows), page)
            if filters.patient_id is None or rows[key].patient_id == filters.patient_id
        ]
        return build_page(selected, limit=page.limit, key=lambda r: r.id)


class FakeSecurityEvents(SecurityEventReadPort):
    def __init__(self) -> None:
        self.rows: list[SecurityEventRow] = []

    def add(self, row: SecurityEventRow) -> None:
        self.rows.append(row)

    @override
    def list(
        self, filters: SecurityEventFilter, page: PageRequest
    ) -> Page[SecurityEventRow]:
        rows = {r.id: r for r in self.rows}
        selected = [
            rows[key]
            for key in _newest(list(rows), page)
            if (filters.clinic_id is None or rows[key].clinic_id == filters.clinic_id)
            and (
                filters.event_type is None or rows[key].event_type == filters.event_type
            )
            and (filters.severity is None or rows[key].severity == filters.severity)
        ]
        return build_page(selected, limit=page.limit, key=lambda r: r.id)


class FakeChain(AuditChainPort):
    """``broken`` maps a clinic to the id of its first broken row."""

    def __init__(self) -> None:
        self.broken: dict[UUID, UUID] = {}
        self.checked: list[UUID] = []

    @override
    def first_broken_row(self, clinic_id: UUID) -> UUID | None:
        self.checked.append(clinic_id)
        return self.broken.get(clinic_id)


class AuditFakes:
    """All audit doubles, with the ``AuditAdapters`` they plug into."""

    def __init__(self) -> None:
        self.audit_log = FakeAuditLog()
        self.data_access = FakeDataAccess()
        self.security_events = FakeSecurityEvents()
        self.chain = FakeChain()

    def adapters(self) -> AuditAdapters:
        return AuditAdapters(
            audit_log=self.audit_log,
            data_access=self.data_access,
            security_events=self.security_events,
            chain=self.chain,
        )


def audit_row(row_id: UUID, *, action: str = "CREDENTIALS_ISSUED") -> AuditLogRow:
    return AuditLogRow(
        id=row_id,
        occurred_at=NOW,
        actor_user_id=None,
        actor_role="CLINIC_ADMIN",
        action=action,
        entity_type="PATIENT",
        entity_id=None,
        reason="Emisión de credenciales de prueba",
        changed_fields=("status",),
    )


def access_row(row_id: UUID, *, patient_id: UUID | None = None) -> DataAccessRow:
    return DataAccessRow(
        id=row_id,
        occurred_at=NOW,
        actor_user_id=None,
        actor_role="DOCTOR",
        patient_id=patient_id,
        resource_type=DataResource.GLUCOSE_READINGS,
        action="READ",
        outcome=DataAccessOutcome.GRANTED,
        purpose=AccessPurpose.CARE,
    )


def event_row(
    row_id: UUID,
    *,
    clinic_id: UUID | None,
    event_type: SecurityEventKind = SecurityEventKind.LOGIN_FAILED,
    severity: SecuritySeverity = SecuritySeverity.LOW,
) -> SecurityEventRow:
    return SecurityEventRow(
        id=row_id,
        event_type=event_type,
        severity=severity,
        user_id=None,
        clinic_id=clinic_id,
        occurred_at=NOW,
        ip_truncated="203.0.113.0/24",
    )
