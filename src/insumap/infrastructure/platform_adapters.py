"""The adapters behind the clinic, staff, care team and audit ports."""

from __future__ import annotations

from dataclasses import dataclass

from insumap.application.access.ports import PatientDirectoryPort
from insumap.application.care_team.ports import CareTeamRepositoryPort, StaffLookupPort
from insumap.application.commands.auditing import AuditLogPort
from insumap.application.notifications.notification import NotificationChannel
from insumap.infrastructure.audit.sql_audit_log import SqlAuditLog
from insumap.infrastructure.notifications.logging_channel import LoggingEmailChannel
from insumap.infrastructure.persistence.care_team_repository import (
    CareTeamRepository,
    PatientDirectoryRepository,
    StaffLookupRepository,
)
from insumap.infrastructure.persistence.transactions import CurrentSession


@dataclass(frozen=True, slots=True, kw_only=True)
class PlatformAdapters:
    """Ports of the clinics, staff and care team slices, wired by ``Container``.

    Tests pass their own doubles; production gets ``build_platform_adapters``.
    """

    audit_log: AuditLogPort
    email_channel: NotificationChannel
    care_teams: CareTeamRepositoryPort
    patients: PatientDirectoryPort
    staff: StaffLookupPort


def build_platform_adapters(*, current: CurrentSession) -> PlatformAdapters:
    """Build the production adapters over the session holder of the process."""
    return PlatformAdapters(
        audit_log=SqlAuditLog(current),
        email_channel=LoggingEmailChannel(),
        care_teams=CareTeamRepository(current),
        patients=PatientDirectoryRepository(current),
        staff=StaffLookupRepository(current),
    )
