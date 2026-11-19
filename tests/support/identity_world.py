"""A fully wired identity slice over in-memory doubles, with seeded accounts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from insumap.application.identity.activation import (
    ActivationPolicy,
    CompleteActivationUseCase,
    VerifyActivationCodeUseCase,
)
from insumap.application.identity.authenticate import AuthenticateActorUseCase
from insumap.application.identity.challenges import ChallengePolicy, ChallengeService
from insumap.application.identity.current_user import GetCurrentUserUseCase
from insumap.application.identity.login import LoginUseCase
from insumap.application.identity.mfa import (
    ConfirmMfaEnrollmentUseCase,
    StartMfaEnrollmentUseCase,
    VerifyMfaChallengeUseCase,
)
from insumap.application.identity.passwords import NewPasswordService, PasswordRules
from insumap.application.identity.ports import (
    ActivationProfile,
    PrivacyNotice,
    TotpFactor,
)
from insumap.application.identity.second_factor import (
    SecondFactorVerifier,
    totp_secret_binding,
)
from insumap.application.identity.session import SessionIssuer, SessionLifetimes
from insumap.application.identity.sessions import (
    LogoutAllUseCase,
    LogoutUseCase,
    RefreshSessionUseCase,
)
from insumap.application.security.rate_limit import RateLimitCheck, RateLimitRule
from insumap.domain.identity.account_state import AccountStatus
from insumap.domain.identity.invitation import (
    CredentialInvitation,
    InvitationPurpose,
    InvitationStatus,
)
from insumap.domain.identity.password_policy import PasswordPolicy
from insumap.domain.identity.refresh_token import RefreshTokenLifetime
from insumap.domain.identity.roles import Role
from insumap.domain.identity.user import ClinicSummary, UserAccount
from insumap.infrastructure.identity_adapters import IdentityAdapters
from tests.support.fixed_clock import FixedClock
from tests.support.identity_fakes import (
    HASH_PREFIX,
    FakeActivations,
    FakeChallenges,
    FakeCipher,
    FakeCodeHasher,
    FakeConsents,
    FakeFactors,
    FakeHasher,
    FakeHistory,
    FakeIds,
    FakeOpaque,
    FakePermissions,
    FakeRateLimiter,
    FakeRecoveryCodes,
    FakeRefreshTokens,
    FakeSecurityEvents,
    FakeTokens,
    FakeTotp,
    FakeUnitOfWorkPort,
    FakeUsers,
)

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
PASSWORD = "correct horse battery staple"
NEW_PASSWORD = "another long passphrase 2026"
ACTIVATION_CODE = "ABCD-EFGH-JKMN-PQRS"
BIRTH_DATE = date(1980, 5, 17)
MINUTE = timedelta(minutes=1)
RULE = RateLimitRule(family="test", limit=100, window=MINUTE)

CLINIC = ClinicSummary(
    clinic_id=UUID(int=10), name="Clínica Demo", is_demo=True, is_active=True
)
PATIENT_ID = UUID(int=21)
PATIENT_USER = UUID(int=20)
DOCTOR_USER = UUID(int=30)
ENROLLING_DOCTOR = UUID(int=31)
INVITED_USER = UUID(int=40)
INVITED_PATIENT = UUID(int=41)
INVITATION_ID = UUID(int=50)
STAFF_INVITED_USER = UUID(int=42)
STAFF_INVITATION_ID = UUID(int=51)
STAFF_CODE = "WXYZ-2345-6789-ABCD"
STAFF_EMAIL = "nuevo.medico@example.test"
NOTICE_ID = UUID(int=60)


def make_account(
    user_id: UUID,
    email: str | None,
    *,
    role: Role = Role.PATIENT,
    status: AccountStatus = AccountStatus.ACTIVE,
    password: str | None = PASSWORD,
    patient_id: UUID | None = None,
) -> UserAccount:
    return UserAccount(
        user_id=user_id,
        email=email,
        email_normalized=None if email is None else email.lower(),
        full_name="Persona de Prueba",
        password_hash=None if password is None else f"{HASH_PREFIX}{password}",
        status=status,
        token_version=0,
        role=role,
        requires_mfa=role is not Role.PATIENT,
        membership_active=True,
        clinic=CLINIC,
        patient_id=patient_id,
    )


@dataclass
class IdentityWorld:
    clock: FixedClock = field(default_factory=lambda: FixedClock(NOW))

    def __post_init__(self) -> None:
        self.uow = FakeUnitOfWorkPort()
        self.users = FakeUsers()
        self.permissions = FakePermissions()
        self.hasher = FakeHasher()
        self.history = FakeHistory()
        self.tokens = FakeTokens()
        self.opaque = FakeOpaque()
        self.refresh_tokens = FakeRefreshTokens(self.users)
        self.challenge_repo = FakeChallenges()
        self.totp = FakeTotp()
        self.cipher = FakeCipher()
        self.code_hasher = FakeCodeHasher()
        self.factors = FakeFactors()
        self.activations = FakeActivations()
        self.consents = FakeConsents()
        self.events = FakeSecurityEvents()
        self.limiter = FakeRateLimiter()
        self.ids = FakeIds()
        self._seed()
        self._wire()

    def _seed(self) -> None:
        self.users.add(
            make_account(PATIENT_USER, "paciente@example.test", patient_id=PATIENT_ID)
        )
        self.users.add(
            make_account(DOCTOR_USER, "medico@example.test", role=Role.DOCTOR)
        )
        self.users.add(
            make_account(ENROLLING_DOCTOR, "nuevo@example.test", role=Role.DOCTOR)
        )
        self.factors.add_totp(
            TotpFactor(
                factor_id=UUID(int=70),
                user_id=DOCTOR_USER,
                secret=self.cipher.encrypt(
                    "SECRET0",
                    associated_data=totp_secret_binding(UUID(int=70), DOCTOR_USER),
                ),
                last_used_step=None,
                confirmed_at=NOW,
            ),
            now=NOW,
        )
        self.users.add(
            make_account(
                INVITED_USER,
                None,
                status=AccountStatus.INVITED,
                password=None,
                patient_id=INVITED_PATIENT,
            )
        )
        self.activations.add(
            "hmac-ACTIVATION-ABCDEFGHJKMNPQRS",
            CredentialInvitation(
                invitation_id=INVITATION_ID,
                user_id=INVITED_USER,
                clinic_id=CLINIC.clinic_id,
                patient_id=INVITED_PATIENT,
                purpose=InvitationPurpose.PATIENT_ACTIVATION,
                status=InvitationStatus.PENDING,
                expires_at=NOW + timedelta(days=7),
                failed_attempts=0,
            ),
        )
        self.users.add(
            make_account(
                STAFF_INVITED_USER,
                STAFF_EMAIL,
                role=Role.DOCTOR,
                status=AccountStatus.INVITED,
                password=None,
            )
        )
        self.activations.add(
            "hmac-ACTIVATION-WXYZ23456789ABCD",
            CredentialInvitation(
                invitation_id=STAFF_INVITATION_ID,
                user_id=STAFF_INVITED_USER,
                clinic_id=CLINIC.clinic_id,
                patient_id=None,
                purpose=InvitationPurpose.STAFF_ACTIVATION,
                status=InvitationStatus.PENDING,
                expires_at=NOW + timedelta(days=7),
                failed_attempts=0,
            ),
        )
        self.activations.clinic_names[CLINIC.clinic_id] = CLINIC.name
        self.activations.profiles[INVITED_PATIENT] = ActivationProfile(
            patient_id=INVITED_PATIENT,
            clinic_name=CLINIC.name,
            birth_date=BIRTH_DATE,
            full_name="Ana Gómez Ruiz",
            contact_email="ana@example.test",
        )
        self.consents.notices[CLINIC.clinic_id] = PrivacyNotice(
            version_id=NOTICE_ID, clinic_id=CLINIC.clinic_id
        )

    def _wire(self) -> None:
        check = RateLimitCheck(self.limiter, RULE)
        lifetimes = SessionLifetimes(
            patient=RefreshTokenLifetime(
                token=timedelta(days=30), family=timedelta(days=90)
            ),
            staff=RefreshTokenLifetime(
                token=timedelta(hours=12), family=timedelta(hours=12)
            ),
        )
        mfa_policy = ChallengePolicy(ttl=5 * MINUTE, max_attempts=5)
        self.sessions = SessionIssuer(
            tokens=self.tokens,
            opaque=self.opaque,
            refresh_tokens=self.refresh_tokens,
            ids=self.ids,
            clock=self.clock,
            lifetimes=lifetimes,
        )
        self.challenges = ChallengeService(
            opaque=self.opaque,
            challenges=self.challenge_repo,
            ids=self.ids,
            clock=self.clock,
        )
        self.verifier = SecondFactorVerifier(
            factors=self.factors,
            totp=self.totp,
            cipher=self.cipher,
            code_hasher=self.code_hasher,
            clock=self.clock,
        )
        self.passwords = NewPasswordService(
            rules=PasswordRules(
                policy=PasswordPolicy(
                    min_length=12, max_length=128, common_passwords=["password1234"]
                ),
                history_size=5,
            ),
            hasher=self.hasher,
            history=self.history,
            clock=self.clock,
        )
        self.login = LoginUseCase(
            uow=self.uow,
            users=self.users,
            hasher=self.hasher,
            decoy_hash=f"{HASH_PREFIX}decoy",
            mfa_factors=self.factors,
            challenges=self.challenges,
            challenge_policy=mfa_policy,
            sessions=self.sessions,
            rate_limit=check,
        )
        self.verify_mfa = VerifyMfaChallengeUseCase(
            uow=self.uow,
            challenges=self.challenges,
            users=self.users,
            verifier=self.verifier,
            sessions=self.sessions,
            events=self.events,
            rate_limit=check,
            clock=self.clock,
        )
        self.start_enrollment = StartMfaEnrollmentUseCase(
            uow=self.uow,
            users=self.users,
            factors=self.factors,
            totp=self.totp,
            cipher=self.cipher,
            ids=self.ids,
            clock=self.clock,
        )
        self.confirm_enrollment = ConfirmMfaEnrollmentUseCase(
            uow=self.uow,
            users=self.users,
            factors=self.factors,
            verifier=self.verifier,
            recovery_codes=FakeRecoveryCodes(),
            recovery_code_count=10,
            code_hasher=self.code_hasher,
            sessions=self.sessions,
            rate_limit=check,
            clock=self.clock,
        )
        self.refresh = RefreshSessionUseCase(
            uow=self.uow,
            opaque=self.opaque,
            refresh_tokens=self.refresh_tokens,
            users=self.users,
            sessions=self.sessions,
            events=self.events,
            rate_limit=check,
            ids=self.ids,
            clock=self.clock,
        )
        self.logout = LogoutUseCase(
            uow=self.uow,
            opaque=self.opaque,
            refresh_tokens=self.refresh_tokens,
            clock=self.clock,
        )
        self.logout_all = LogoutAllUseCase(
            uow=self.uow,
            users=self.users,
            refresh_tokens=self.refresh_tokens,
            events=self.events,
            clock=self.clock,
        )
        self.current_user = GetCurrentUserUseCase(
            uow=self.uow,
            users=self.users,
            factors=self.factors,
            consents=self.consents,
        )
        self.authenticate = AuthenticateActorUseCase(
            uow=self.uow,
            tokens=self.tokens,
            users=self.users,
            permissions=self.permissions,
        )
        self.verify_activation = VerifyActivationCodeUseCase(
            uow=self.uow,
            code_hasher=self.code_hasher,
            activations=self.activations,
            consents=self.consents,
            challenges=self.challenges,
            events=self.events,
            policy=ActivationPolicy(
                max_attempts=5,
                session=ChallengePolicy(ttl=15 * MINUTE, max_attempts=5),
            ),
            rate_limit=check,
            clock=self.clock,
        )
        self.complete_activation = CompleteActivationUseCase(
            uow=self.uow,
            challenges=self.challenges,
            activations=self.activations,
            users=self.users,
            consents=self.consents,
            passwords=self.passwords,
            sessions=self.sessions,
            events=self.events,
            rate_limit=check,
            ids=self.ids,
            clock=self.clock,
        )

    def adapters(self) -> IdentityAdapters:
        """The doubles as the adapters a ``Container`` is built from."""
        return IdentityAdapters(
            unit_of_work=self.uow,
            users=self.users,
            permissions=self.permissions,
            password_history=self.history,
            refresh_tokens=self.refresh_tokens,
            challenges=self.challenge_repo,
            mfa_factors=self.factors,
            activations=self.activations,
            consents=self.consents,
            security_events=self.events,
            password_hasher=self.hasher,
            tokens=self.tokens,
            opaque_tokens=self.opaque,
            totp=self.totp,
            cipher=self.cipher,
            code_hasher=self.code_hasher,
            recovery_codes=FakeRecoveryCodes(),
            rate_limiter=self.limiter,
            ids=self.ids,
        )
