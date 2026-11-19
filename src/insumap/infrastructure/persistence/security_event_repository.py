"""Security events (``iam.security_events``, append-only)."""

from __future__ import annotations

from typing import final, override

from insumap.application.security.events import SecurityEvent, SecurityEventPort
from insumap.infrastructure.persistence.orm import SecurityEventOrm
from insumap.infrastructure.persistence.transactions import CurrentSession


@final
class SecurityEventRepository(SecurityEventPort):
    """Stores identifiers only: no secrets, emails or names."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def record(self, event: SecurityEvent) -> None:
        session = self._current.get()
        session.add(
            SecurityEventOrm(
                event_type=event.event_type.value,
                severity=event.event_type.severity.value,
                user_id=event.user_id,
                clinic_id=event.clinic_id,
                details={},
            )
        )
        session.flush()
