"""The audit adapter skips actions without a clinic (they are security events)."""

from typing import Any, cast
from uuid import UUID

from sqlalchemy.orm import Session

from insumap.application.commands.auditing import AuditEntry
from insumap.domain.identity.roles import Role
from insumap.infrastructure.audit.sql_audit_log import SqlAuditLog
from insumap.infrastructure.persistence.transactions import CurrentSession
from tests.support.identity_world import NOW


class RecordingSession:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def execute(self, statement: object, params: dict[str, Any]) -> None:
        del statement
        self.calls.append(params)


def record(session: RecordingSession, audit_entry: AuditEntry) -> None:
    current = CurrentSession()
    with current.bind(cast("Session", session)):
        SqlAuditLog(current).record(audit_entry)


def entry(clinic_id: UUID | None) -> AuditEntry:
    return AuditEntry(
        clinic_id=clinic_id,
        actor_user_id=UUID(int=1),
        actor_role=Role.PLATFORM_ADMIN,
        action="PASSWORD_CHANGED",
        entity_type="USER",
        entity_id=UUID(int=1),
        reason=None,
        changed_fields=(),
        request_id=None,
        occurred_at=NOW,
    )


def test_action_without_clinic_writes_no_audit_row() -> None:
    session = RecordingSession()

    record(session, entry(None))

    assert session.calls == []


def test_action_with_clinic_calls_the_definer_function() -> None:
    session = RecordingSession()

    record(session, entry(UUID(int=10)))

    assert session.calls[0]["clinic_id"] == UUID(int=10)
    assert session.calls[0]["action"] == "PASSWORD_CHANGED"
