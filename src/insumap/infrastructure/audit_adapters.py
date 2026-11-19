"""The adapters behind the audit ports, built over the session holder."""

from __future__ import annotations

from dataclasses import dataclass

from insumap.application.audit.ports import (
    AuditChainPort,
    AuditLogReadPort,
    DataAccessReadPort,
    SecurityEventReadPort,
)
from insumap.infrastructure.persistence.audit_repositories import (
    AuditChainRepository,
    AuditLogReadRepository,
    DataAccessReadRepository,
    SecurityEventReadRepository,
)
from insumap.infrastructure.persistence.transactions import CurrentSession


@dataclass(frozen=True, slots=True, kw_only=True)
class AuditAdapters:
    """Ports of the audit slice (API.md 8.13), wired by ``Container``.

    Tests pass their own doubles; production gets ``build_audit_adapters``.
    """

    audit_log: AuditLogReadPort
    data_access: DataAccessReadPort
    security_events: SecurityEventReadPort
    chain: AuditChainPort


def build_audit_adapters(*, current: CurrentSession) -> AuditAdapters:
    """Build the production adapters over the session holder of the process."""
    return AuditAdapters(
        audit_log=AuditLogReadRepository(current),
        data_access=DataAccessReadRepository(current),
        security_events=SecurityEventReadRepository(current),
        chain=AuditChainRepository(current),
    )
