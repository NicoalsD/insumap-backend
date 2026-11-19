"""Security events (``iam.security_events``), recorded without personal data."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class SecuritySeverity(StrEnum):
    """Severity of a security event (Seguridad.md, section 7.3)."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class SecurityEventType(StrEnum):
    """Events this slice records, with their documented severity."""

    REFRESH_TOKEN_REUSE_DETECTED = "REFRESH_TOKEN_REUSE_DETECTED"  # noqa: S105 - name
    MFA_FAILED = "MFA_FAILED"
    MFA_RECOVERY_CODE_USED = "MFA_RECOVERY_CODE_USED"
    ACTIVATION_LOCKED = "ACTIVATION_LOCKED"
    CSRF_CHECK_FAILED = "CSRF_CHECK_FAILED"
    LOGIN_FAILED = "LOGIN_FAILED"
    ACTIVATION_FAILED = "ACTIVATION_FAILED"
    ACCOUNT_ACTIVATED = "ACCOUNT_ACTIVATED"
    SESSIONS_REVOKED = "SESSIONS_REVOKED"

    @property
    def severity(self) -> SecuritySeverity:
        """Severity fixed by the security policy."""
        return _SEVERITY[self]


_SEVERITY = {
    SecurityEventType.REFRESH_TOKEN_REUSE_DETECTED: SecuritySeverity.HIGH,
    SecurityEventType.MFA_FAILED: SecuritySeverity.MEDIUM,
    SecurityEventType.MFA_RECOVERY_CODE_USED: SecuritySeverity.MEDIUM,
    SecurityEventType.ACTIVATION_LOCKED: SecuritySeverity.MEDIUM,
    SecurityEventType.CSRF_CHECK_FAILED: SecuritySeverity.MEDIUM,
    SecurityEventType.LOGIN_FAILED: SecuritySeverity.LOW,
    SecurityEventType.ACTIVATION_FAILED: SecuritySeverity.LOW,
    SecurityEventType.ACCOUNT_ACTIVATED: SecuritySeverity.LOW,
    SecurityEventType.SESSIONS_REVOKED: SecuritySeverity.LOW,
}


@dataclass(frozen=True, slots=True, kw_only=True)
class SecurityEvent:
    """One event: identifiers only, never secrets, emails or names."""

    event_type: SecurityEventType
    user_id: UUID | None = None
    clinic_id: UUID | None = None


class SecurityEventPort(ABC):
    """Records security events inside the current transaction."""

    @abstractmethod
    def record(self, event: SecurityEvent) -> None:
        """Store ``event``."""
