"""The adapters behind the clinic, staff, care team and audit ports."""

from __future__ import annotations

from dataclasses import dataclass

from insumap.application.access.ports import PatientDirectoryPort
from insumap.application.care_team.ports import CareTeamRepositoryPort, StaffLookupPort
from insumap.application.commands.auditing import AuditLogPort
from insumap.application.notifications.notification import NotificationChannel
from insumap.application.users.ports import (
    ActivationCodeGeneratorPort,
    LoginLockoutPort,
    StaffDirectoryPort,
    StaffInvitationPort,
)
from insumap.infrastructure.audit.sql_audit_log import SqlAuditLog
from insumap.infrastructure.notifications.logging_channel import LoggingEmailChannel
from insumap.infrastructure.persistence.care_team_repository import (
    CareTeamRepository,
    PatientDirectoryRepository,
    StaffLookupRepository,
)
from insumap.infrastructure.persistence.staff_repositories import (
    LoginLockoutRepository,
    StaffDirectoryRepository,
    StaffInvitationRepository,
)
from insumap.infrastructure.persistence.transactions import CurrentSession
from insumap.infrastructure.security.activation_codes import (
    CrockfordActivationCodeGenerator,
)
from insumap.infrastructure.security.subkey_hasher import Subkey, SubkeyHasher


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
    staff_directory: StaffDirectoryPort
    staff_invitations: StaffInvitationPort
    login_lockouts: LoginLockoutPort
    activation_codes: ActivationCodeGeneratorPort


def build_platform_adapters(
    *, current: CurrentSession, app_hmac_key: bytes
) -> PlatformAdapters:
    """Build the production adapters over the session holder of the process."""
    return PlatformAdapters(
        audit_log=SqlAuditLog(current),
        email_channel=LoggingEmailChannel(),
        care_teams=CareTeamRepository(current),
        patients=PatientDirectoryRepository(current),
        staff=StaffLookupRepository(current),
        staff_directory=StaffDirectoryRepository(current),
        staff_invitations=StaffInvitationRepository(current),
        login_lockouts=LoginLockoutRepository(
            current, SubkeyHasher(app_hmac_key, subkey=Subkey.RATE_LIMIT)
        ),
        activation_codes=CrockfordActivationCodeGenerator(),
    )
