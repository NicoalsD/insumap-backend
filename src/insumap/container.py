"""Composition root: the only place where the dependencies of the API are built."""

from __future__ import annotations

import secrets
from datetime import timedelta
from typing import final

from insumap.api.errors import ApiExceptionHandlers, ErrorResponseFactory
from insumap.api.routers.auth import AuthRouter
from insumap.api.routers.health import HealthRouter
from insumap.api.routers.meta import MetaRouter
from insumap.api.security import ActorGuard, RefreshCookie, RefreshCsrfGuard
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
from insumap.application.identity.csrf import RefreshRequestGuard
from insumap.application.identity.current_user import GetCurrentUserUseCase
from insumap.application.identity.login import LoginUseCase
from insumap.application.identity.mfa import (
    ConfirmMfaEnrollmentUseCase,
    StartMfaEnrollmentUseCase,
    VerifyMfaChallengeUseCase,
)
from insumap.application.identity.passwords import NewPasswordService, PasswordRules
from insumap.application.identity.second_factor import SecondFactorVerifier
from insumap.application.identity.session import SessionIssuer, SessionLifetimes
from insumap.application.identity.sessions import (
    LogoutAllUseCase,
    LogoutUseCase,
    RefreshSessionUseCase,
)
from insumap.application.readiness import (
    AlwaysReadyProbe,
    CheckReadinessUseCase,
    ReadinessProbe,
)
from insumap.application.security.rate_limit import RateLimitCheck, RateLimitRule
from insumap.domain.identity.password_policy import PasswordPolicy
from insumap.domain.identity.refresh_token import RefreshTokenLifetime
from insumap.infrastructure.identity_adapters import (
    IdentityAdapters,
    build_engine,
    build_identity_adapters,
    load_common_passwords,
)
from insumap.infrastructure.logging import JsonLoggingConfigurator
from insumap.shared.config import Settings, get_settings
from insumap.shared.field_limits import FieldLimits
from insumap.shared.i18n import MessageCatalog
from insumap.shared.time import Clock, SystemClock


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
        adapters = identity_adapters or build_identity_adapters(
            self.settings,
            clock=self.clock,
            publisher=self.event_publisher,
            engine=build_engine(self.settings),
        )
        self.auth_router = self._build_auth_router(adapters)

    def _build_auth_router(self, adapters: IdentityAdapters) -> AuthRouter:
        """Wire the identity use cases over ``adapters`` and mount their router."""
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
        authenticate = AuthenticateActorUseCase(
            uow=adapters.unit_of_work,
            tokens=adapters.tokens,
            users=adapters.users,
            permissions=adapters.permissions,
        )
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
            ),
            session_actor=ActorGuard(authenticate, SessionScope.FULL),
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
