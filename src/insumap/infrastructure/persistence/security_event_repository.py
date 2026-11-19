"""Security events (``iam.security_events``, append-only)."""

from __future__ import annotations

from typing import final, override

from sqlalchemy import text

from insumap.application.security.events import SecurityEvent, SecurityEventPort
from insumap.infrastructure.persistence.transactions import CurrentSession

RECORD_EVENT = text(
    "INSERT INTO iam.security_events (event_type, severity, user_id, clinic_id)"
    " VALUES (:event_type, :severity, :user_id, :clinic_id)"
)
"""Parameterized and without ``RETURNING`` (SQLAlchemy would add one for the id)."""


@final
class SecurityEventRepository(SecurityEventPort):
    """Stores identifiers only: no secrets, emails or names.

    A plain ``INSERT`` without ``RETURNING``: the app may write an event in any
    context but only an admin may read it back, and ``RETURNING`` would need
    the select policy too (RLS-7).
    """

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def record(self, event: SecurityEvent) -> None:
        self._current.get().execute(
            RECORD_EVENT,
            {
                "event_type": event.event_type.value,
                "severity": event.event_type.severity.value,
                "user_id": event.user_id,
                "clinic_id": event.clinic_id,
            },
        )
