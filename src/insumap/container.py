"""Composition root: the only place where the dependencies of the API are built."""

from __future__ import annotations

import secrets
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Final, Never, final

from insumap.api.errors import ApiExceptionHandlers, ErrorResponseFactory
from insumap.api.routers.auth import AuthRouter
from insumap.api.routers.care_team import CareTeamRouter
from insumap.api.routers.clinics import ClinicRouter
from insumap.api.routers.health import HealthRouter
from insumap.api.routers.meta import MetaRouter
from insumap.api.routers.sites import SiteRouter
from insumap.api.security import ActorGuard, RefreshCookie, RefreshCsrfGuard
from insumap.application.care_team.commands import (
    AssignDoctorCommand,
    AssignDoctorCommandHandler,
    EndAssignmentCommand,
    EndAssignmentCommandHandler,
    ReassignDoctorCommand,
    ReassignDoctorCommandHandler,
    SetPrimaryDoctorCommand,
    SetPrimaryDoctorCommandHandler,
)
from insumap.application.care_team.list_assignments import (
    ListCareTeamAssignmentsUseCase,
)
from insumap.application.clinics.commands import (
    CreateClinicCommand,
    CreateClinicCommandHandler,
    ReactivateClinicCommand,
    ReactivateClinicCommandHandler,
    SuspendClinicCommand,
    SuspendClinicCommandHandler,
    UpdateClinicCommand,
    UpdateClinicCommandHandler,
)
from insumap.application.clinics.queries import (
    GetClinicUseCase,
    GetCurrentClinicUseCase,
    ListClinicsUseCase,
)
from insumap.application.commands.auditing import (
    AuditingCommandHandler,
    AuditLogPort,
)
from insumap.application.commands.base import (
    Command,
    CommandBus,
    CommandHandler,
    InMemoryCommandBus,
    Registration,
    bind,
)
from insumap.application.commands.transactional import (
    CurrentUnitOfWork,
    TransactionalCommandHandler,
)
from insumap.application.common.unit_of_work import UnitOfWorkPort
from insumap.application.events.publisher import (
    DomainEventPublisher,
    InProcessDomainEventPublisher,
)
from insumap.application.identity.activation import (
    ActivationPolicy,
    CompleteActivationUseCase,
    VerifyActivationCodeUseCase,
)
from insumap.application.identity.authenticate import (
    AuthenticateActorUseCase,
    SessionScope,
)
from insumap.application.identity.challenges import ChallengePolicy, ChallengeService
from insumap.application.identity.change_password import (
    ChangePasswordCommand,
    ChangePasswordCommandHandler,
)
from insumap.application.identity.csrf import RefreshRequestGuard
from insumap.application.identity.current_user import GetCurrentUserUseCase
from insumap.application.identity.email_verification import (
    ConfirmEmailVerificationUseCase,
    EmailVerificationIssuer,
)
from insumap.application.identity.login import LoginUseCase
from insumap.application.identity.mfa import (
    ConfirmMfaEnrollmentUseCase,
    StartMfaEnrollmentUseCase,
    VerifyMfaChallengeUseCase,
)
from insumap.application.identity.password_reset import (
    CompletePasswordResetUseCase,
    PasswordResetPolicy,
    RequestPasswordResetUseCase,
)
from insumap.application.identity.passwords import NewPasswordService, PasswordRules
from insumap.application.identity.recovery_codes import (
    RegenerateMfaRecoveryCodesCommand,
    RegenerateMfaRecoveryCodesCommandHandler,
)
from insumap.application.identity.second_factor import SecondFactorVerifier
from insumap.application.identity.session import SessionIssuer, SessionLifetimes
from insumap.application.identity.sessions import (
    LogoutAllUseCase,
    LogoutUseCase,
    RefreshSessionUseCase,
)
from insumap.application.notifications.notification import NotificationChannel
from insumap.application.readiness import (
    AlwaysReadyProbe,
    CheckReadinessUseCase,
    ReadinessProbe,
)
from insumap.application.security.rate_limit import RateLimitCheck, RateLimitRule
from insumap.application.sites.commands import (
    CreateSiteCommand,
    CreateSiteCommandHandler,
    SetUserSitesCommand,
    SetUserSitesCommandHandler,
    UpdateSiteCommand,
    UpdateSiteCommandHandler,
)
from insumap.application.sites.list_sites import ListSitesUseCase
from insumap.domain.identity.password_policy import PasswordPolicy
from insumap.domain.identity.refresh_token import RefreshTokenLifetime
from insumap.infrastructure.identity_adapters import (
    IdentityAdapters,
    build_engine,
    build_identity_adapters,
    load_common_passwords,
)
from insumap.infrastructure.logging import JsonLoggingConfigurator
from insumap.infrastructure.persistence.transactions import CurrentSession
from insumap.infrastructure.platform_adapters import (
    PlatformAdapters,
    build_platform_adapters,
)
from insumap.shared.config import Settings, get_settings
from insumap.shared.field_limits import FieldLimits
from insumap.shared.i18n import MessageCatalog
from insumap.shared.time import Clock, SystemClock

RESET_PASSWORD_PATH: Final = "reset-password"  # noqa: S105 - web route, not a secret
VERIFY_EMAIL_PATH: Final = "verify-email"
"""Routes of the web app the emailed links point at (``<base>/<path>#token=...``)."""

ALL_COMMAND_TYPES: Final[tuple[type[Command[Never]], ...]] = (
    RegenerateMfaRecoveryCodesCommand,
    ChangePasswordCommand,
    AssignDoctorCommand,
    SetPrimaryDoctorCommand,
    ReassignDoctorCommand,
    EndAssignmentCommand,
    CreateClinicCommand,
    UpdateClinicCommand,
    SuspendClinicCommand,
    ReactivateClinicCommand,
    CreateSiteCommand,
    UpdateSiteCommand,
    SetUserSitesCommand,
)
"""Every command of the API: a missing handler fails when the container is built."""


@dataclass(frozen=True, slots=True, kw_only=True)
class IdentityServices:
    """Objects shared by the identity use cases and the identity commands."""

    login_limit: RateLimitCheck
    mfa_limit: RateLimitCheck
    activation_limit: RateLimitCheck
    refresh_limit: RateLimitCheck
    sessions: SessionIssuer
    challenges: ChallengeService
    verifier: SecondFactorVerifier
    passwords: NewPasswordService
    email_verification: EmailVerificationIssuer
    reset_complete_limit: RateLimitCheck


@final
class CommandGuard:
    """Puts a command handler inside its transaction and its audit (P13 and P09).

    The order is fixed: the transaction wraps the audit decorator, which wraps
    the handler, so the audit row and the action commit or roll back together.
    """

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        audit_log: AuditLogPort,
        current: CurrentUnitOfWork,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._audit_log = audit_log
        self._current = current
        self._clock = clock

    def wrap[C: Command[Never], R](
        self, handler: CommandHandler[C, R]
    ) -> CommandHandler[C, R]:
        """Return ``handler`` decorated with the audit and the transaction."""
        return TransactionalCommandHandler(
            AuditingCommandHandler(handler, self._audit_log, self._clock),
            self._uow,
            self._current,
        )


@final
class Container:
    """Builds every long-lived dependency of the API once and wires them together.

    Settings, clock, message catalog, logging setup, readiness probe, use cases
    and routers are created here and nowhere else; ``create_app`` only mounts
    them. Tests pass their own settings, clock or probe through the constructor.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        clock: Clock | None = None,
        readiness_probe: ReadinessProbe | None = None,
        identity_adapters: IdentityAdapters | None = None,
        event_publisher: DomainEventPublisher | None = None,
        platform_adapters: PlatformAdapters | None = None,
        email_channel: NotificationChannel | None = None,
    ) -> None:
        self.settings: Settings = settings or get_settings()
        self.clock: Clock = clock or SystemClock.instance()
        self.message_catalog = MessageCatalog.load_spanish()
        self.logging_configurator = JsonLoggingConfigurator(self.settings.log_level)
        self.readiness_probe: ReadinessProbe = readiness_probe or AlwaysReadyProbe()

        self.check_readiness = CheckReadinessUseCase(self.readiness_probe)

        self.error_responses = ErrorResponseFactory(self.message_catalog)
        self.exception_handlers = ApiExceptionHandlers(self.error_responses)
        self.health_router = HealthRouter(self.check_readiness)
        self.meta_router = MetaRouter()

        self.event_publisher: DomainEventPublisher = (
            event_publisher or InProcessDomainEventPublisher()
        )
        current = CurrentSession()
        adapters = identity_adapters or build_identity_adapters(
            self.settings,
            clock=self.clock,
            publisher=self.event_publisher,
            engine=build_engine(self.settings),
            current=current,
        )
        platform = platform_adapters or build_platform_adapters(current=current)
        if email_channel is not None:
            platform = replace(platform, email_channel=email_channel)
        services = self._build_identity_services(adapters, platform)
        self._command_guard = CommandGuard(
            uow=adapters.unit_of_work,
            audit_log=platform.audit_log,
            current=CurrentUnitOfWork(),
            clock=self.clock,
        )
        registrations = [
            *self._identity_commands(adapters, services),
            *self._care_team_commands(adapters, platform),
            *self._clinic_commands(adapters, platform),
            *self._site_commands(adapters, platform),
        ]
        self.command_bus: CommandBus = InMemoryCommandBus(
            registrations, required=ALL_COMMAND_TYPES
        )
        self.auth_router = self._build_auth_router(adapters, services, platform)
        self.care_team_router = CareTeamRouter(
            commands=self.command_bus,
            list_assignments=ListCareTeamAssignmentsUseCase(
                uow=adapters.unit_of_work, teams=platform.care_teams
            ),
            staff_actor=self.full_session_actor,
        )
        self.clinic_router = ClinicRouter(
            commands=self.command_bus,
            list_clinics=ListClinicsUseCase(
                uow=adapters.unit_of_work, clinics=platform.clinics
            ),
            get_clinic=GetClinicUseCase(
                uow=adapters.unit_of_work, clinics=platform.clinics
            ),
            get_current_clinic=GetCurrentClinicUseCase(
                uow=adapters.unit_of_work, clinics=platform.clinics
            ),
            staff_actor=self.full_session_actor,
        )
        self.site_router = SiteRouter(
            commands=self.command_bus,
            list_sites=ListSitesUseCase(
                uow=adapters.unit_of_work, sites=platform.sites
            ),
            staff_actor=self.full_session_actor,
        )

    def _build_identity_services(
        self, adapters: IdentityAdapters, platform: PlatformAdapters
    ) -> IdentityServices:
        """The services several identity use cases and commands share."""
        settings, clock = self.settings, self.clock
        minute, hour = timedelta(minutes=1), timedelta(hours=1)
        login_limit = RateLimitCheck(
            adapters.rate_limiter,
            RateLimitRule(
                family="login_ip",
                limit=settings.rate_limit_login_per_ip_per_minute,
                window=minute,
            ),
        )
        mfa_limit = RateLimitCheck(
            adapters.rate_limiter,
            RateLimitRule(
                family="mfa_ip",
                limit=settings.rate_limit_mfa_per_ip_per_minute,
                window=minute,
            ),
        )
        activation_limit = RateLimitCheck(
            adapters.rate_limiter,
            RateLimitRule(
                family="activation_ip_minute",
                limit=settings.rate_limit_activation_per_ip_per_minute,
                window=minute,
            ),
            RateLimitRule(
                family="activation_ip_hour",
                limit=settings.rate_limit_activation_per_ip_per_hour,
                window=hour,
            ),
        )
        refresh_limit = RateLimitCheck(
            adapters.rate_limiter,
            RateLimitRule(
                family="refresh_user",
                limit=settings.rate_limit_refresh_per_user_per_minute,
                window=minute,
            ),
        )
        sessions = SessionIssuer(
            tokens=adapters.tokens,
            opaque=adapters.opaque_tokens,
            refresh_tokens=adapters.refresh_tokens,
            ids=adapters.ids,
            clock=clock,
            lifetimes=SessionLifetimes(
                patient=RefreshTokenLifetime(
                    token=timedelta(days=settings.refresh_token_days),
                    family=timedelta(days=settings.refresh_family_max_days),
                ),
                staff=RefreshTokenLifetime(
                    token=timedelta(hours=settings.refresh_token_staff_hours),
                    family=timedelta(hours=settings.refresh_token_staff_hours),
                ),
            ),
        )
        challenges = ChallengeService(
            opaque=adapters.opaque_tokens,
            challenges=adapters.challenges,
            ids=adapters.ids,
            clock=clock,
        )
        verifier = SecondFactorVerifier(
            factors=adapters.mfa_factors,
            totp=adapters.totp,
            cipher=adapters.cipher,
            code_hasher=adapters.code_hasher,
            clock=clock,
        )
        passwords = NewPasswordService(
            rules=PasswordRules(
                policy=PasswordPolicy(
                    min_length=FieldLimits.PASSWORD_MIN_LENGTH,
                    max_length=FieldLimits.PASSWORD_MAX_LENGTH,
                    common_passwords=load_common_passwords(),
                ),
                history_size=settings.password_history_size,
            ),
            hasher=adapters.password_hasher,
            history=adapters.password_history,
            clock=clock,
        )
        return IdentityServices(
            login_limit=login_limit,
            mfa_limit=mfa_limit,
            activation_limit=activation_limit,
            refresh_limit=refresh_limit,
            sessions=sessions,
            challenges=challenges,
            verifier=verifier,
            passwords=passwords,
            email_verification=EmailVerificationIssuer(
                challenges=challenges,
                policy=ChallengePolicy(
                    ttl=timedelta(hours=settings.email_verification_ttl_hours),
                    max_attempts=settings.activation_max_attempts,
                ),
                channel=platform.email_channel,
                messages=self.message_catalog,
                link_base_url=settings.web_app_base_url,
                link_path=VERIFY_EMAIL_PATH,
            ),
            reset_complete_limit=RateLimitCheck(
                adapters.rate_limiter,
                RateLimitRule(
                    family="reset_complete_ip",
                    limit=settings.rate_limit_reset_complete_per_ip_per_minute,
                    window=minute,
                ),
            ),
        )

    def _care_team_commands(
        self, adapters: IdentityAdapters, platform: PlatformAdapters
    ) -> list[Registration]:
        """The care team decisions (P13), each behind transaction and audit (P09)."""
        guard, clock = self._command_guard, self.clock
        teams, staff = platform.care_teams, platform.staff
        return [
            bind(
                AssignDoctorCommand,
                guard.wrap(
                    AssignDoctorCommandHandler(
                        patients=platform.patients,
                        staff=staff,
                        teams=teams,
                        ids=adapters.ids,
                        clock=clock,
                    )
                ),
            ),
            bind(
                SetPrimaryDoctorCommand,
                guard.wrap(SetPrimaryDoctorCommandHandler(teams=teams)),
            ),
            bind(
                ReassignDoctorCommand,
                guard.wrap(
                    ReassignDoctorCommandHandler(
                        staff=staff, teams=teams, ids=adapters.ids, clock=clock
                    )
                ),
            ),
            bind(
                EndAssignmentCommand,
                guard.wrap(EndAssignmentCommandHandler(teams=teams, clock=clock)),
            ),
        ]

    def _clinic_commands(
        self, adapters: IdentityAdapters, platform: PlatformAdapters
    ) -> list[Registration]:
        """The clinic decisions (P13, P18), each behind transaction and audit (P09)."""
        guard, clock, clinics = self._command_guard, self.clock, platform.clinics
        return [
            bind(
                CreateClinicCommand,
                guard.wrap(
                    CreateClinicCommandHandler(
                        clinics=clinics, ids=adapters.ids, clock=clock
                    )
                ),
            ),
            bind(
                UpdateClinicCommand,
                guard.wrap(UpdateClinicCommandHandler(clinics=clinics, clock=clock)),
            ),
            bind(
                SuspendClinicCommand,
                guard.wrap(SuspendClinicCommandHandler(clinics=clinics, clock=clock)),
            ),
            bind(
                ReactivateClinicCommand,
                guard.wrap(
                    ReactivateClinicCommandHandler(clinics=clinics, clock=clock)
                ),
            ),
        ]

    def _site_commands(
        self, adapters: IdentityAdapters, platform: PlatformAdapters
    ) -> list[Registration]:
        """The site decisions (P13), each behind transaction and audit (P09)."""
        guard, clock = self._command_guard, self.clock
        sites, staff_sites = platform.sites, platform.staff_sites
        return [
            bind(
                CreateSiteCommand,
                guard.wrap(
                    CreateSiteCommandHandler(sites=sites, ids=adapters.ids, clock=clock)
                ),
            ),
            bind(
                UpdateSiteCommand,
                guard.wrap(UpdateSiteCommandHandler(sites=sites, clock=clock)),
            ),
            bind(
                SetUserSitesCommand,
                guard.wrap(
                    SetUserSitesCommandHandler(
                        sites=sites, staff_sites=staff_sites, clock=clock
                    )
                ),
            ),
        ]

    def _identity_commands(
        self, adapters: IdentityAdapters, services: IdentityServices
    ) -> list[Registration]:
        """The commands of the identity module, each behind transaction and audit."""
        settings, clock = self.settings, self.clock
        guard = self._command_guard
        return [
            bind(
                RegenerateMfaRecoveryCodesCommand,
                guard.wrap(
                    RegenerateMfaRecoveryCodesCommandHandler(
                        factors=adapters.mfa_factors,
                        verifier=services.verifier,
                        generator=adapters.recovery_codes,
                        code_count=settings.mfa_recovery_code_count,
                        code_hasher=adapters.code_hasher,
                        rate_limit=services.mfa_limit,
                        clock=clock,
                    )
                ),
            ),
            bind(
                ChangePasswordCommand,
                guard.wrap(
                    ChangePasswordCommandHandler(
                        users=adapters.users,
                        hasher=adapters.password_hasher,
                        passwords=services.passwords,
                        refresh_tokens=adapters.refresh_tokens,
                        sessions=services.sessions,
                        consents=adapters.consents,
                        events=adapters.security_events,
                        rate_limit=services.login_limit,
                        clock=clock,
                    )
                ),
            ),
        ]

    def _build_auth_router(
        self,
        adapters: IdentityAdapters,
        services: IdentityServices,
        platform: PlatformAdapters,
    ) -> AuthRouter:
        """Wire the identity use cases over ``adapters`` and mount their router."""
        settings, clock = self.settings, self.clock
        login_limit, mfa_limit = services.login_limit, services.mfa_limit
        activation_limit = services.activation_limit
        refresh_limit = services.refresh_limit
        sessions, challenges = services.sessions, services.challenges
        verifier, passwords = services.verifier, services.passwords
        authenticate = AuthenticateActorUseCase(
            uow=adapters.unit_of_work,
            tokens=adapters.tokens,
            users=adapters.users,
            permissions=adapters.permissions,
        )
        self.full_session_actor = ActorGuard(authenticate, SessionScope.FULL)
        """Actor of every route but enrollment and the own session (C1, C2)."""
        login = LoginUseCase(
            uow=adapters.unit_of_work,
            users=adapters.users,
            hasher=adapters.password_hasher,
            decoy_hash=adapters.password_hasher.hash(secrets.token_urlsafe(24)),
            mfa_factors=adapters.mfa_factors,
            challenges=challenges,
            challenge_policy=ChallengePolicy(
                ttl=timedelta(seconds=settings.mfa_challenge_ttl_seconds),
                max_attempts=settings.mfa_challenge_max_attempts,
            ),
            sessions=sessions,
            rate_limit=login_limit,
        )
        return AuthRouter(
            commands=self.command_bus,
            clock=clock,
            cookie=RefreshCookie(),
            login=login,
            verify_mfa=VerifyMfaChallengeUseCase(
                uow=adapters.unit_of_work,
                challenges=challenges,
                users=adapters.users,
                verifier=verifier,
                sessions=sessions,
                events=adapters.security_events,
                rate_limit=mfa_limit,
                clock=clock,
            ),
            start_enrollment=StartMfaEnrollmentUseCase(
                uow=adapters.unit_of_work,
                users=adapters.users,
                factors=adapters.mfa_factors,
                totp=adapters.totp,
                cipher=adapters.cipher,
                ids=adapters.ids,
                clock=clock,
            ),
            confirm_enrollment=ConfirmMfaEnrollmentUseCase(
                uow=adapters.unit_of_work,
                users=adapters.users,
                factors=adapters.mfa_factors,
                verifier=verifier,
                recovery_codes=adapters.recovery_codes,
                recovery_code_count=settings.mfa_recovery_code_count,
                code_hasher=adapters.code_hasher,
                sessions=sessions,
                rate_limit=mfa_limit,
                clock=clock,
            ),
            current_user=GetCurrentUserUseCase(
                uow=adapters.unit_of_work,
                users=adapters.users,
                factors=adapters.mfa_factors,
                consents=adapters.consents,
            ),
            refresh=RefreshSessionUseCase(
                uow=adapters.unit_of_work,
                opaque=adapters.opaque_tokens,
                refresh_tokens=adapters.refresh_tokens,
                users=adapters.users,
                sessions=sessions,
                events=adapters.security_events,
                rate_limit=refresh_limit,
                ids=adapters.ids,
                clock=clock,
            ),
            logout=LogoutUseCase(
                uow=adapters.unit_of_work,
                opaque=adapters.opaque_tokens,
                refresh_tokens=adapters.refresh_tokens,
                clock=clock,
            ),
            logout_all=LogoutAllUseCase(
                uow=adapters.unit_of_work,
                users=adapters.users,
                refresh_tokens=adapters.refresh_tokens,
                events=adapters.security_events,
                clock=clock,
            ),
            verify_activation=VerifyActivationCodeUseCase(
                uow=adapters.unit_of_work,
                code_hasher=adapters.code_hasher,
                activations=adapters.activations,
                consents=adapters.consents,
                challenges=challenges,
                events=adapters.security_events,
                policy=ActivationPolicy(
                    max_attempts=settings.activation_max_attempts,
                    session=ChallengePolicy(
                        ttl=timedelta(minutes=settings.activation_session_ttl_minutes),
                        max_attempts=settings.activation_max_attempts,
                    ),
                ),
                rate_limit=activation_limit,
                clock=clock,
            ),
            complete_activation=CompleteActivationUseCase(
                uow=adapters.unit_of_work,
                challenges=challenges,
                activations=adapters.activations,
                users=adapters.users,
                consents=adapters.consents,
                passwords=passwords,
                sessions=sessions,
                events=adapters.security_events,
                rate_limit=activation_limit,
                ids=adapters.ids,
                clock=clock,
                email_verification=services.email_verification,
            ),
            request_reset=RequestPasswordResetUseCase(
                uow=adapters.unit_of_work,
                users=adapters.users,
                challenges=challenges,
                events=adapters.security_events,
                limiter=adapters.rate_limiter,
                ip_rule=RateLimitRule(
                    family="reset_request_ip",
                    limit=settings.rate_limit_reset_request_per_ip_per_hour,
                    window=timedelta(hours=1),
                ),
                email_rule=RateLimitRule(
                    family="reset_request_account",
                    limit=settings.rate_limit_reset_request_per_account_per_hour,
                    window=timedelta(hours=1),
                ),
                policy=PasswordResetPolicy(
                    ttl=timedelta(minutes=settings.password_reset_ttl_minutes),
                    max_attempts=settings.activation_max_attempts,
                    link_base_url=settings.web_app_base_url,
                    link_path=RESET_PASSWORD_PATH,
                ),
                channel=platform.email_channel,
                messages=self.message_catalog,
            ),
            complete_reset=CompletePasswordResetUseCase(
                uow=adapters.unit_of_work,
                challenges=challenges,
                users=adapters.users,
                passwords=passwords,
                refresh_tokens=adapters.refresh_tokens,
                events=adapters.security_events,
                rate_limit=services.reset_complete_limit,
                channel=platform.email_channel,
                messages=self.message_catalog,
                clock=clock,
            ),
            confirm_email=ConfirmEmailVerificationUseCase(
                uow=adapters.unit_of_work,
                challenges=challenges,
                users=adapters.users,
                rate_limit=services.reset_complete_limit,
                clock=clock,
            ),
            session_actor=self.full_session_actor,
            enrollment_actor=ActorGuard(authenticate, SessionScope.ENROLLMENT),
            any_actor=ActorGuard(authenticate, SessionScope.ANY),
            csrf_guard=RefreshCsrfGuard(
                RefreshRequestGuard(
                    allowed_origins=settings.cors_origins,
                    uow=adapters.unit_of_work,
                    events=adapters.security_events,
                )
            ),
        )
