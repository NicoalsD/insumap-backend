"""A TestClient over the real app, container and use cases, with port doubles."""

from typing import Final
from uuid import UUID

from fastapi.testclient import TestClient

from insumap.application.identity.ports import TotpFactor
from insumap.application.identity.second_factor import totp_secret_binding
from insumap.container import Container
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role
from insumap.infrastructure.platform_adapters import PlatformAdapters
from insumap.main import create_app
from tests.support.access_fakes import FakeDirectory
from tests.support.care_team_fakes import FakeCareTeams, FakeStaff
from tests.support.clinic_fakes import FakeClinics
from tests.support.commands import InMemoryAuditLog
from tests.support.identity_fakes import VALID_TOTP
from tests.support.identity_world import (
    CLINIC,
    NOW,
    PASSWORD,
    IdentityWorld,
    make_account,
)
from tests.support.monitoring_fakes import RecordsWorld, records_adapters
from tests.support.notifications import InMemoryChannel
from tests.support.onboarding_fakes import OnboardingWorld
from tests.support.settings import make_settings
from tests.support.sites_fakes import FakeSites
from tests.support.users_fakes import (
    FakeActivationCodes,
    FakeLoginLockouts,
    FakeStaffDirectory,
    FakeStaffInvitations,
)

ORIGIN = "https://app.example.test"
CSRF_HEADERS = {"X-Requested-With": "insumap-web"}
FACTOR_ID_OFFSET: Final = 1000


class IdentityApi:
    """The app, its client (https, so ``Secure`` cookies round trip) and the doubles."""

    def __init__(self) -> None:
        self.world = IdentityWorld()
        self.audit_log = InMemoryAuditLog()
        self.mail = InMemoryChannel()
        self.care_teams = FakeCareTeams()
        self.patients = FakeDirectory()
        self.staff = FakeStaff()
        self.clinics = FakeClinics()
        self.sites = FakeSites(clinic_id=CLINIC.clinic_id)
        self.records = RecordsWorld(
            clock=self.world.clock, uow=self.world.uow, ids=self.world.ids
        )
        self.staff_directory = FakeStaffDirectory(self.world.users, self.world.factors)
        self.staff_invitations = FakeStaffInvitations()
        self.login_lockouts = FakeLoginLockouts()
        self.onboarding = OnboardingWorld()
        settings = make_settings(cors_origins=[ORIGIN])
        container = Container(
            settings,
            clock=self.world.clock,
            identity_adapters=self.world.adapters(),
            platform_adapters=PlatformAdapters(
                audit_log=self.audit_log,
                email_channel=self.mail,
                care_teams=self.care_teams,
                patients=self.patients,
                staff=self.staff,
                clinics=self.clinics,
                sites=self.sites,
                staff_sites=self.sites,
                staff_directory=self.staff_directory,
                staff_invitations=self.staff_invitations,
                login_lockouts=self.login_lockouts,
                activation_codes=FakeActivationCodes(),
            ),
            monitoring_adapters=records_adapters(self.records),
            onboarding_adapters=self.onboarding.adapters(),
        )
        self.app = create_app(container)
        self.client = TestClient(
            self.app, base_url="https://testserver", raise_server_exceptions=False
        )

    def bearer(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def staff_token(
        self,
        user_id: UUID,
        role: Role,
        permissions: frozenset[PermissionCode],
    ) -> str:
        """Sign in a staff member with MFA verified and ``permissions`` for its role."""
        email = f"staff-{user_id.int}@example.test"
        self.world.users.add(make_account(user_id, email, role=role))
        factor_id = UUID(int=user_id.int + FACTOR_ID_OFFSET)
        self.world.factors.add_totp(
            TotpFactor(
                factor_id=factor_id,
                user_id=user_id,
                secret=self.world.cipher.encrypt(
                    "SECRET0",
                    associated_data=totp_secret_binding(factor_id, user_id),
                ),
                last_used_step=None,
                confirmed_at=NOW,
            ),
            now=NOW,
        )
        self.world.permissions.by_role[role] = permissions
        challenge = self.client.post(
            "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
        ).json()["challenge_token"]
        verified = self.client.post(
            "/api/v1/auth/mfa/verify",
            json={"challenge_token": challenge, "code": VALID_TOTP},
        )
        return str(verified.json()["access_token"])
