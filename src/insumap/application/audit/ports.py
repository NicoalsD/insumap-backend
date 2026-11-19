"""Ports of the audit reads and of the chain check (API.md 8.13, M12).

The reads speak in these read models, never in ORM rows. They never carry clinical
values: the audit tables hold identifiers and field names only.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from insumap.application.access.ports import (
    AccessPurpose,
    DataAccessOutcome,
    DataResource,
)
from insumap.application.common.pagination import Page, PageRequest
from insumap.application.security.events import SecuritySeverity


class SecurityEventKind(StrEnum):
    """Every type the database accepts in ``iam.security_events`` (db-v0.4.0).

    This is the read side: the application may read a type it does not record
    itself (``SecurityEventType`` covers only the writes of this slice).
    """

    AUDIT_CHAIN_BROKEN = "AUDIT_CHAIN_BROKEN"
    REFRESH_TOKEN_REUSE_DETECTED = "REFRESH_TOKEN_REUSE_DETECTED"  # noqa: S105 - name
    ACCOUNT_LOCKED = "ACCOUNT_LOCKED"
    MFA_RESET = "MFA_RESET"
    LLM_DATA_POLICY_BLOCKED = "LLM_DATA_POLICY_BLOCKED"
    MFA_FAILED = "MFA_FAILED"
    MFA_RECOVERY_CODE_USED = "MFA_RECOVERY_CODE_USED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    PHI_ACCESS_DENIED = "PHI_ACCESS_DENIED"
    ACTIVATION_LOCKED = "ACTIVATION_LOCKED"
    PUSH_ENDPOINT_REJECTED = "PUSH_ENDPOINT_REJECTED"
    CSRF_CHECK_FAILED = "CSRF_CHECK_FAILED"
    LOGIN_FAILED = "LOGIN_FAILED"
    ACCOUNT_UNLOCKED = "ACCOUNT_UNLOCKED"
    ACTIVATION_FAILED = "ACTIVATION_FAILED"
    ACCOUNT_ACTIVATED = "ACCOUNT_ACTIVATED"
    ROLE_CHANGED = "ROLE_CHANGED"
    RATE_LIMITED = "RATE_LIMITED"
    PASSWORD_CHANGED = "PASSWORD_CHANGED"  # noqa: S105 - event name, not a secret
    PASSWORD_RESET_REQUESTED = "PASSWORD_RESET_REQUESTED"  # noqa: S105 - event name
    SESSIONS_REVOKED = "SESSIONS_REVOKED"
    IMPORT_REJECTED = "IMPORT_REJECTED"
    SECRET_ROTATED = "SECRET_ROTATED"  # noqa: S105 - event name, not a secret


@dataclass(frozen=True, slots=True, kw_only=True)
class AuditLogRow:
    """One action of ``audit.audit_log``, without the hash chain columns."""

    id: UUID
    occurred_at: datetime
    actor_user_id: UUID | None
    actor_role: str | None
    action: str
    entity_type: str
    entity_id: UUID | None
    reason: str | None
    changed_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class AuditLogFilter:
    """Optional filters of ``GET /audit-log`` (``None`` means no filter)."""

    user_id: UUID | None = None
    action: str | None = None
    occurred_from: datetime | None = None
    occurred_to: datetime | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class DataAccessRow:
    """One row of ``audit.data_access_log``: who read what, never the data."""

    id: UUID
    occurred_at: datetime
    actor_user_id: UUID | None
    actor_role: str | None
    patient_id: UUID | None
    resource_type: DataResource
    action: str
    outcome: DataAccessOutcome
    purpose: AccessPurpose


@dataclass(frozen=True, slots=True, kw_only=True)
class DataAccessFilter:
    """Optional filters of ``GET /audit-log/data-access``."""

    user_id: UUID | None = None
    patient_id: UUID | None = None
    resource_type: DataResource | None = None
    occurred_from: datetime | None = None
    occurred_to: datetime | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class SecurityEventRow:
    """One row of ``iam.security_events``: identifiers and the truncated address."""

    id: UUID
    event_type: SecurityEventKind
    severity: SecuritySeverity
    user_id: UUID | None
    clinic_id: UUID | None
    occurred_at: datetime
    ip_truncated: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class SecurityEventFilter:
    """Scope and filters of ``GET /security-events``.

    ``clinic_id`` is the scope: a clinic's events, or ``None`` for the whole
    platform (only ``audit.read_platform`` gets that).
    """

    clinic_id: UUID | None = None
    event_type: SecurityEventKind | None = None
    severity: SecuritySeverity | None = None
    occurred_from: datetime | None = None
    occurred_to: datetime | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ChainVerification:
    """Result of ``audit.verify_chain``: the first broken row, or none."""

    first_inconsistent_row_id: UUID | None

    @property
    def is_valid(self) -> bool:
        return self.first_inconsistent_row_id is None


class AuditLogReadPort(ABC):
    """Reads ``audit.audit_log`` of one clinic, newest first."""

    @abstractmethod
    def list(
        self, clinic_id: UUID, filters: AuditLogFilter, page: PageRequest
    ) -> Page[AuditLogRow]:
        """A page of the actions of ``clinic_id``."""


class DataAccessReadPort(ABC):
    """Reads ``audit.data_access_log`` of one clinic, newest first."""

    @abstractmethod
    def list(
        self, clinic_id: UUID, filters: DataAccessFilter, page: PageRequest
    ) -> Page[DataAccessRow]:
        """A page of the reads of clinical data made in ``clinic_id``."""


class SecurityEventReadPort(ABC):
    """Reads ``iam.security_events``, newest first; the scope is in the filter."""

    @abstractmethod
    def list(
        self, filters: SecurityEventFilter, page: PageRequest
    ) -> Page[SecurityEventRow]:
        """A page of security events inside the scope of ``filters``."""


class AuditChainPort(ABC):
    """Recalculates the hash chain of a clinic in the database (definer)."""

    @abstractmethod
    def first_broken_row(self, clinic_id: UUID) -> UUID | None:
        """First row whose chain does not match; ``None`` when the chain is intact."""
