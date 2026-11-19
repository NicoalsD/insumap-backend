"""A TestClient over the real app, container and use cases, with port doubles."""

from typing import Final
from uuid import UUID

from fastapi.testclient import TestClient

from insumap.application.identity.ports import TotpFactor
from insumap.application.identity.second_factor import totp_secret_binding
from insumap.container import Container
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role
from insumap.infrastructure.ai.unconfigured_forecast import (
    UnconfiguredGlucoseForecastAdapter,
)
from insumap.infrastructure.ai_adapters import AiAdapters
from insumap.infrastructure.clinic_admin_adapters import ClinicAdminAdapters
from insumap.infrastructure.credentials_adapters import CredentialsAdapters
from insumap.infrastructure.patient_adapters import PatientAdapters
from insumap.infrastructure.platform_adapters import PlatformAdapters
from insumap.infrastructure.targets_adapters import TargetsAdapters
from insumap.infrastructure.treatment_adapters import TreatmentAdapters
from insumap.main import create_app
from tests.support.access_fakes import FakeDirectory, InMemoryDataAccessLog
from tests.support.alerts_fakes import AlertsWorld
from tests.support.care_team_fakes import FakeCareTeams, FakeStaff
from tests.support.clinic_admin_fakes import FakeClinicAdminProvisioning
from tests.support.clinic_fakes import FakeClinics
from tests.support.commands import InMemoryAuditLog
from tests.support.credentials_fakes import (
    DistinctActivationCodes,
    FakeCredentialInvitations,
    FakePatientContacts,
)
from tests.support.identity_fakes import VALID_TOTP
from tests.support.identity_world import (
    CLINIC,
    NOW,
    PASSWORD,
    PATIENT_ID,
    PATIENT_USER,
    IdentityWorld,
    make_account,
)
from tests.support.monitoring_fakes import RecordsWorld, records_adapters
from tests.support.notification_fakes import (
    InMemoryNotificationStore,
    InMemoryPreferences,
    InMemoryPushSubscriptions,
    notification_adapters,
)
from tests.support.notifications import InMemoryChannel
from tests.support.onboarding_fakes import OnboardingWorld
from tests.support.patient_fakes import FakePatientRoster, FakePendingInvitations
from tests.support.recommendation_fakes import FakeDrafts, InMemoryRecommendations
from tests.support.settings import make_settings
from tests.support.sites_fakes import FakeSites
from tests.support.targets_fakes import (
    FakeReminders,
    FakeTargetAssignments,
    FakeTargetCatalog,
)
from tests.support.treatment_fakes import (
    FakePlans,
    FakeSnapshots,
    FakeTargets,
    FakeTemplates,
)
from tests.support.users_fakes import (
    FakeLoginLockouts,
    FakeStaffDirectory,
    FakeStaffInvitations,
)

ORIGIN = "https://app.example.test"
CSRF_HEADERS = {"X-Requested-With": "insumap-web"}
FACTOR_ID_OFFSET: Final = 1000
TREATMENT_TARGET: Final = UUID(int=4040)


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
        self.alerts = AlertsWorld()
        self.recommendations = InMemoryRecommendations()
        self.login_lockouts = FakeLoginLockouts()
        self.onboarding = OnboardingWorld()
        self.templates = FakeTemplates()
        self.plans = FakePlans()
        self.snapshots = FakeSnapshots()
        self.targets = FakeTargets(TREATMENT_TARGET)
        self.catalog = FakeTargetCatalog()
        self.target_assignments = FakeTargetAssignments()
        self.reminders = FakeReminders()
        self.notification_store = InMemoryNotificationStore()
        self.preferences = InMemoryPreferences()
        self.push_subscriptions = InMemoryPushSubscriptions()
        self.clinic_admins = FakeClinicAdminProvisioning()
        self.patient_roster = FakePatientRoster(
            users=self.world.users, user_of={PATIENT_ID: PATIENT_USER}
        )
        self.patient_invitations = FakePendingInvitations()
        self.patient_log = InMemoryDataAccessLog()
        self.credential_contacts = FakePatientContacts()
        self.credential_invitations = FakeCredentialInvitations()
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
                activation_codes=DistinctActivationCodes(),
            ),
            monitoring_adapters=records_adapters(self.records),
            onboarding_adapters=self.onboarding.adapters(),
            alert_adapters=self.alerts.adapters(),
            ai_adapters=AiAdapters(
                forecasts=UnconfiguredGlucoseForecastAdapter(),
                recommendations=self.recommendations,
                drafts=FakeDrafts(),
            ),
            treatment_adapters=TreatmentAdapters(
                templates=self.templates,
                plans=self.plans,
                snapshots=self.snapshots,
                targets=self.targets,
            ),
            targets_adapters=TargetsAdapters(
                catalog=self.catalog,
                assignments=self.target_assignments,
                reminders=self.reminders,
            ),
            notification_adapters=notification_adapters(
                store=self.notification_store,
                preferences=self.preferences,
                subscriptions=self.push_subscriptions,
            ),
            clinic_admin_adapters=ClinicAdminAdapters(provisioning=self.clinic_admins),
            patient_adapters=PatientAdapters(
                roster=self.patient_roster,
                invitations=self.patient_invitations,
                access_log=self.patient_log,
            ),
            credentials_adapters=CredentialsAdapters(
                patient_contacts=self.credential_contacts,
                invitations=self.credential_invitations,
            ),
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
