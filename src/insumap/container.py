"""Composition root: the only place where the dependencies of the API are built."""

from __future__ import annotations

import secrets
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Final, Never, final

from insumap.api.errors import ApiExceptionHandlers, ErrorResponseFactory
from insumap.api.routers.alerts import AlertRouter
from insumap.api.routers.audit import AuditRouter
from insumap.api.routers.auth import AuthRouter
from insumap.api.routers.care_team import CareTeamRouter
from insumap.api.routers.clinics import ClinicRouter
from insumap.api.routers.consents import ConsentRouter
from insumap.api.routers.credentials import CredentialRouter
from insumap.api.routers.health import HealthRouter
from insumap.api.routers.imports import ImportRouter
from insumap.api.routers.messaging import MessagingRouter
from insumap.api.routers.meta import MetaRouter
from insumap.api.routers.metrics import MetricsRouter
from insumap.api.routers.notifications import NotificationRouter
from insumap.api.routers.patients import PatientRouter
from insumap.api.routers.recommendations import RecommendationRouter
from insumap.api.routers.records import RecordsRouter
from insumap.api.routers.reminders import ReminderRouter
from insumap.api.routers.sites import SiteRouter
from insumap.api.routers.targets import TargetProfileRouter
from insumap.api.routers.treatment import TreatmentRouter
from insumap.api.routers.users import UserRouter
from insumap.api.security import ActorGuard, RefreshCookie, RefreshCsrfGuard
from insumap.application.ai.commands import (
    ApproveRecommendationCommand,
    ApproveRecommendationCommandHandler,
    ModifyRecommendationCommand,
    ModifyRecommendationCommandHandler,
    RejectRecommendationCommand,
    RejectRecommendationCommandHandler,
)
from insumap.application.ai.queries import (
    GetRecommendationUseCase,
    ListRecommendationsUseCase,
)
from insumap.application.alerts.commands import (
    AcknowledgeAlertCommand,
    AcknowledgeAlertCommandHandler,
    CreateAlertRuleCommand,
    CreateAlertRuleCommandHandler,
    CreateAlertRuleVersionCommand,
    CreateAlertRuleVersionCommandHandler,
    ResolveAlertCommand,
    ResolveAlertCommandHandler,
)
from insumap.application.alerts.evaluation import EvaluateAlertRulesOnReading
from insumap.application.alerts.queries import (
    GetAlertRuleUseCase,
    GetAlertSummaryUseCase,
    GetAlertUseCase,
    ListAlertRulesUseCase,
    ListAlertsUseCase,
)
from insumap.application.audit.queries import (
    ListAuditLogUseCase,
    ListDataAccessUseCase,
    ListSecurityEventsUseCase,
)
from insumap.application.audit.verification import VerifyAuditChainUseCase
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
from insumap.application.clinic_admins.commands import (
    CreateClinicAdminCommand,
    CreateClinicAdminCommandHandler,
    ResetClinicAdminAccessCommand,
    ResetClinicAdminAccessCommandHandler,
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
from insumap.application.common.patient_scope import PatientScope
from insumap.application.common.unit_of_work import UnitOfWorkPort
from insumap.application.consents.commands import (
    AcceptConsentCommand,
    AcceptConsentCommandHandler,
    WithdrawConsentCommand,
    WithdrawConsentCommandHandler,
)
from insumap.application.consents.gate import OwnConsentGate
from insumap.application.consents.privacy_requests import (
    CreatePrivacyRequestCommand,
    CreatePrivacyRequestCommandHandler,
    ExportPrivacyRequestUseCase,
    ListPrivacyRequestsUseCase,
    ResolvePrivacyRequestCommand,
    ResolvePrivacyRequestCommandHandler,
)
from insumap.application.consents.queries import (
    GetOwnConsentUseCase,
    GetPrivacyNoticeUseCase,
    ListConsentStatusesUseCase,
)
from insumap.application.credentials.commands import (
    IssueCredentialsCommand,
    IssueCredentialsCommandHandler,
    RevokeCredentialInvitationCommand,
    RevokeCredentialInvitationCommandHandler,
)
from insumap.application.credentials.issuance import (
    IssueCredentialsBatchUseCase,
    IssueCredentialUseCase,
)
from insumap.application.events.publisher import (
    DomainEventPublisher,
    InProcessDomainEventPublisher,
)
from insumap.application.follow_ups.commands import (
    CloseFollowUpCommand,
    CloseFollowUpCommandHandler,
    CreateFollowUpCommand,
    CreateFollowUpCommandHandler,
)
from insumap.application.follow_ups.queries import ListFollowUpsUseCase
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
from insumap.application.messaging.list_messages import ListMessagesUseCase
from insumap.application.messaging.send_message import SendMessageUseCase
from insumap.application.metrics.forecast import GetForecastUseCase
from insumap.application.metrics.metrics import (
    ComputeGlycemicMetricsUseCase,
    GetAgpUseCase,
)
from insumap.application.monitoring.corrections import (
    AnnulRecordUseCase,
    CorrectRecordUseCase,
)
from insumap.application.monitoring.gate import AssignedPatientGate, OwnPatientGate
from insumap.application.monitoring.glucose import (
    GlucoseReadingRecorder,
    ImportCgmReadingsUseCase,
    RecordGlucoseReadingsBatchUseCase,
    RecordGlucoseReadingUseCase,
)
from insumap.application.monitoring.profile import GetOwnPatientProfileUseCase
from insumap.application.monitoring.queries import (
    ExportTimelineUseCase,
    GetTimelineUseCase,
    ListRecordsUseCase,
)
from insumap.application.monitoring.records import (
    RecordActivityUseCase,
    RecordInsulinDoseUseCase,
    RecordMealUseCase,
    RecordOwnLabResultUseCase,
    RecordPatientLabResultUseCase,
    RecordSymptomUseCase,
    RecordWriter,
)
from insumap.application.notifications.list_notifications import (
    ListNotificationsUseCase,
)
from insumap.application.notifications.mark_read import MarkNotificationReadUseCase
from insumap.application.notifications.notification import NotificationChannel
from insumap.application.notifications.preferences import (
    GetNotificationPreferencesUseCase,
    UpdateNotificationPreferencesUseCase,
)
from insumap.application.notifications.web_push import (
    RegisterWebPushSubscriptionUseCase,
    RemoveWebPushSubscriptionUseCase,
)
from insumap.application.onboarding.commands import (
    ConfirmImportCommand,
    ConfirmImportCommandHandler,
    PreviewImportCommand,
    PreviewImportCommandHandler,
)
from insumap.application.onboarding.pipeline import PatientImportPipeline
from insumap.application.onboarding.queries import (
    DownloadCsvTemplateUseCase,
    ExportImportErrorsUseCase,
    GetImportBatchUseCase,
    ListImportBatchesUseCase,
    ListImportRowsUseCase,
)
from insumap.application.patients.commands import (
    DeactivatePatientCommand,
    DeactivatePatientCommandHandler,
    ReactivatePatientCommand,
    ReactivatePatientCommandHandler,
    SuspendPatientCommand,
    SuspendPatientCommandHandler,
)
from insumap.application.patients.queries import (
    GetPatientUseCase,
    ListPatientsUseCase,
)
from insumap.application.readiness import (
    AlwaysReadyProbe,
    CheckReadinessUseCase,
    ReadinessProbe,
)
from insumap.application.reminders.commands import (
    CreateReminderCommand,
    CreateReminderCommandHandler,
    UpdateOwnReminderCommand,
    UpdateOwnReminderCommandHandler,
    UpdatePatientReminderCommand,
    UpdatePatientReminderCommandHandler,
)
from insumap.application.reminders.queries import (
    ListOwnRemindersUseCase,
    ListPatientRemindersUseCase,
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
from insumap.application.targets.commands import (
    AssignTargetProfileCommand,
    AssignTargetProfileCommandHandler,
    CreateTargetProfileCommand,
    CreateTargetProfileCommandHandler,
    CreateTargetProfileVersionCommand,
    CreateTargetProfileVersionCommandHandler,
)
from insumap.application.targets.queries import (
    GetTargetProfileUseCase,
    ListTargetProfilesUseCase,
)
from insumap.application.treatment.plan_commands import (
    ActivateTreatmentPlanCommand,
    ActivateTreatmentPlanCommandHandler,
    CreateTreatmentPlanCommand,
    CreateTreatmentPlanCommandHandler,
    CreateTreatmentPlanVersionCommand,
    CreateTreatmentPlanVersionCommandHandler,
    RestoreTreatmentPlanCommand,
    RestoreTreatmentPlanCommandHandler,
    UpdateTreatmentPlanCommand,
    UpdateTreatmentPlanCommandHandler,
    make_scope,
)
from insumap.application.treatment.queries import (
    GetOwnTreatmentPlanUseCase,
    GetProtocolTemplateUseCase,
    GetTreatmentPlanUseCase,
    ListProtocolTemplatesUseCase,
    ListTreatmentPlanSnapshotsUseCase,
    ListTreatmentPlansUseCase,
)
from insumap.application.treatment.snapshots import PlanSnapshotCaretaker
from insumap.application.treatment.template_commands import (
    CreateProtocolTemplateCommand,
    CreateProtocolTemplateCommandHandler,
    CreateProtocolTemplateVersionCommand,
    CreateProtocolTemplateVersionCommandHandler,
    RetireProtocolTemplateCommand,
    RetireProtocolTemplateCommandHandler,
)
from insumap.application.users.commands import (
    CreateStaffUserCommand,
    CreateStaffUserCommandHandler,
    DeactivateStaffUserCommand,
    DeactivateStaffUserCommandHandler,
    ResetStaffMfaCommand,
    ResetStaffMfaCommandHandler,
    UnlockStaffUserCommand,
    UnlockStaffUserCommandHandler,
    UpdateStaffUserCommand,
    UpdateStaffUserCommandHandler,
)
from insumap.application.users.queries import GetStaffUseCase, ListStaffUseCase
from insumap.domain.identity.password_policy import PasswordPolicy
from insumap.domain.identity.refresh_token import RefreshTokenLifetime
from insumap.domain.metrics.target_strategy import GlycemicTargetStrategyRegistry
from insumap.domain.monitoring.events import GlucoseReadingRecorded
from insumap.domain.monitoring.validation import build_validation_chain
from insumap.domain.onboarding.vocabulary import SourceFormat
from insumap.infrastructure.ai_adapters import (
    AiAdapters,
    build_ai_adapters,
)
from insumap.infrastructure.alerts_adapters import (
    AlertsAdapters,
    build_alerts_adapters,
)
from insumap.infrastructure.audit_adapters import (
    AuditAdapters,
    build_audit_adapters,
)
from insumap.infrastructure.clinic_admin_adapters import (
    ClinicAdminAdapters,
    build_clinic_admin_adapters,
)
from insumap.infrastructure.consents_adapters import (
    ConsentsAdapters,
    build_consents_adapters,
)
from insumap.infrastructure.credentials_adapters import (
    CredentialsAdapters,
    build_credentials_adapters,
)
from insumap.infrastructure.identity_adapters import (
    IdentityAdapters,
    build_engine,
    build_identity_adapters,
    load_common_passwords,
)
from insumap.infrastructure.integration.csv.pipeline import CsvPatientImportPipeline
from insumap.infrastructure.integration.fhir.pipeline import FhirPatientImportPipeline
from insumap.infrastructure.logging import JsonLoggingConfigurator
from insumap.infrastructure.messaging_adapters import (
    MessagingAdapters,
    build_messaging_adapters,
)
from insumap.infrastructure.monitoring_adapters import (
    MonitoringAdapters,
    build_monitoring_adapters,
)
from insumap.infrastructure.notification_adapters import (
    NotificationAdapters,
    build_notification_adapters,
)
from insumap.infrastructure.onboarding.adapters import (
    OnboardingAdapters,
    build_onboarding_adapters,
)
from insumap.infrastructure.patient_adapters import (
    PatientAdapters,
    build_patient_adapters,
)
from insumap.infrastructure.persistence.transactions import (
    CurrentSession,
    SqlTransactionFactory,
)
from insumap.infrastructure.platform_adapters import (
    PlatformAdapters,
    build_platform_adapters,
)
from insumap.infrastructure.security.keys import KeyRing
from insumap.infrastructure.targets_adapters import (
    TargetsAdapters,
    build_targets_adapters,
)
from insumap.infrastructure.treatment_adapters import (
    TreatmentAdapters,
    build_treatment_adapters,
)
from insumap.shared.config import Settings, get_settings
from insumap.shared.field_limits import FieldLimits
from insumap.shared.i18n import MessageCatalog
from insumap.shared.key_material import decode_key
from insumap.shared.time import Clock, SystemClock

RESET_PASSWORD_PATH: Final = "reset-password"  # noqa: S105 - web route, not a secret
VERIFY_EMAIL_PATH: Final = "verify-email"
"""Routes of the web app the emailed links point at (``<base>/<path>#token=...``)."""

ALL_COMMAND_TYPES: Final[tuple[type[Command[Never]], ...]] = (
    AcceptConsentCommand,
    WithdrawConsentCommand,
    CreatePrivacyRequestCommand,
    ResolvePrivacyRequestCommand,
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
    CreateStaffUserCommand,
    UpdateStaffUserCommand,
    DeactivateStaffUserCommand,
    UnlockStaffUserCommand,
    ResetStaffMfaCommand,
    PreviewImportCommand,
    ConfirmImportCommand,
    CreateAlertRuleCommand,
    CreateAlertRuleVersionCommand,
    AcknowledgeAlertCommand,
    ResolveAlertCommand,
    CreateProtocolTemplateCommand,
    CreateProtocolTemplateVersionCommand,
    RetireProtocolTemplateCommand,
    CreateTreatmentPlanCommand,
    UpdateTreatmentPlanCommand,
    ActivateTreatmentPlanCommand,
    CreateTreatmentPlanVersionCommand,
    RestoreTreatmentPlanCommand,
    CreateTargetProfileCommand,
    CreateTargetProfileVersionCommand,
    AssignTargetProfileCommand,
    CreateReminderCommand,
    UpdatePatientReminderCommand,
    UpdateOwnReminderCommand,
    CreateClinicAdminCommand,
    ApproveRecommendationCommand,
    ModifyRecommendationCommand,
    RejectRecommendationCommand,
    ResetClinicAdminAccessCommand,
    SuspendPatientCommand,
    ReactivatePatientCommand,
    DeactivatePatientCommand,
    IssueCredentialsCommand,
    RevokeCredentialInvitationCommand,
    CreateFollowUpCommand,
    CloseFollowUpCommand,
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

    def __init__(  # noqa: PLR0913, PLR0915 - composition root wires every module
        self,
        settings: Settings | None = None,
        *,
        clock: Clock | None = None,
        readiness_probe: ReadinessProbe | None = None,
        identity_adapters: IdentityAdapters | None = None,
        event_publisher: DomainEventPublisher | None = None,
        platform_adapters: PlatformAdapters | None = None,
        monitoring_adapters: MonitoringAdapters | None = None,
        targets_adapters: TargetsAdapters | None = None,
        credentials_adapters: CredentialsAdapters | None = None,
        email_channel: NotificationChannel | None = None,
        onboarding_adapters: OnboardingAdapters | None = None,
        alert_adapters: AlertsAdapters | None = None,
        treatment_adapters: TreatmentAdapters | None = None,
        notification_adapters: NotificationAdapters | None = None,
        clinic_admin_adapters: ClinicAdminAdapters | None = None,
        patient_adapters: PatientAdapters | None = None,
        ai_adapters: AiAdapters | None = None,
        consents_adapters: ConsentsAdapters | None = None,
        audit_adapters: AuditAdapters | None = None,
        messaging_adapters: MessagingAdapters | None = None,
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
        engine = build_engine(self.settings)
        adapters = identity_adapters or build_identity_adapters(
            self.settings,
            clock=self.clock,
            publisher=self.event_publisher,
            engine=engine,
            current=current,
        )
        platform = platform_adapters or build_platform_adapters(
            current=current,
            app_hmac_key=decode_key(self.settings.app_hmac_key.get_secret_value()),
        )
        targets = targets_adapters or build_targets_adapters(current=current)
        ai = ai_adapters or build_ai_adapters(
            settings=self.settings,
            clock=self.clock,
            current=current,
            transactions=SqlTransactionFactory(engine, current),
            ids=adapters.ids,
            app_hmac_key=decode_key(self.settings.app_hmac_key.get_secret_value()),
        )
        monitoring = monitoring_adapters or build_monitoring_adapters(
            current=current,
            clock=self.clock,
            transactions=SqlTransactionFactory(engine, current),
            forecasts=ai.forecasts,
        )
        patient_ports = patient_adapters or build_patient_adapters(
            current=current, transactions=SqlTransactionFactory(engine, current)
        )
        clinic_admins = clinic_admin_adapters or build_clinic_admin_adapters(
            current=current
        )
        consents = consents_adapters or build_consents_adapters(
            current=current, transactions=SqlTransactionFactory(engine, current)
        )
        if email_channel is not None:
            platform = replace(platform, email_channel=email_channel)
        onboarding = onboarding_adapters or build_onboarding_adapters(
            current=current,
            clock=self.clock,
            app_hmac_key=decode_key(self.settings.app_hmac_key.get_secret_value()),
            encryption=KeyRing(
                current=self.settings.mfa_encryption_key,
                previous=self.settings.mfa_encryption_key_previous,
            ),
        )
        alerts = alert_adapters or build_alerts_adapters(current=current)
        treatment = treatment_adapters or build_treatment_adapters(
            current=current, metrics_targets=monitoring.targets
        )
        notifications = notification_adapters or build_notification_adapters(
            current=current,
            unit_of_work=adapters.unit_of_work,
            ids=adapters.ids,
            clock=self.clock,
        )
        credentials = credentials_adapters or build_credentials_adapters(
            current=current
        )
        messaging = messaging_adapters or build_messaging_adapters(current=current)
        audit = audit_adapters or build_audit_adapters(current=current)
        services = self._build_identity_services(adapters, platform)
        unit_of_work = CurrentUnitOfWork()
        self._command_guard = CommandGuard(
            uow=adapters.unit_of_work,
            audit_log=platform.audit_log,
            current=unit_of_work,
            clock=self.clock,
        )
        registrations = [
            *self._identity_commands(adapters, services),
            *self._care_team_commands(adapters, platform),
            *self._messaging_commands(adapters, monitoring, messaging),
            *self._clinic_commands(adapters, platform),
            *self._site_commands(adapters, platform),
            *self._users_commands(adapters, platform, unit_of_work),
            *self._onboarding_commands(adapters, onboarding, unit_of_work),
            *self._alert_commands(adapters, monitoring, alerts),
            *self._recommendation_commands(adapters, monitoring, ai, unit_of_work),
            *self._treatment_commands(adapters, treatment, monitoring),
            *self._targets_commands(adapters, monitoring, targets),
            *self._clinic_admin_commands(
                adapters, platform, clinic_admins, unit_of_work
            ),
            *self._patient_commands(adapters, platform, patient_ports),
            *self._credential_commands(adapters, platform, unit_of_work, credentials),
            *self._consent_commands(adapters, consents, unit_of_work),
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
        self.consent_router = self._build_consent_router(adapters, consents, monitoring)
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
        self.user_router = UserRouter(
            commands=self.command_bus,
            list_staff=ListStaffUseCase(
                uow=adapters.unit_of_work, directory=platform.staff_directory
            ),
            get_staff=GetStaffUseCase(
                uow=adapters.unit_of_work, directory=platform.staff_directory
            ),
            staff_actor=self.full_session_actor,
        )
        self.credential_router = CredentialRouter(
            commands=self.command_bus,
            issue=IssueCredentialUseCase(
                commands=self.command_bus,
                issue_limit=self._credential_issue_limit(adapters),
            ),
            issue_batch=IssueCredentialsBatchUseCase(
                commands=self.command_bus,
                issue_limit=self._credential_issue_limit(adapters),
                batch_limit=self._credential_batch_limit(adapters),
            ),
            staff_actor=self.full_session_actor,
        )
        self.records_router = self._build_records_router(adapters, monitoring)
        self.metrics_router = self._build_metrics_router(adapters, monitoring)
        self.import_router = self._build_import_router(adapters, onboarding)
        self._subscribe_alert_evaluation(adapters, alerts)
        self.alerts_router = self._build_alerts_router(adapters, monitoring, alerts)
        self.recommendation_router = self._build_recommendation_router(
            adapters, monitoring, ai
        )
        self.target_profile_router = self._build_target_profile_router(
            adapters, targets
        )
        self.reminder_router = self._build_reminder_router(
            adapters, monitoring, targets
        )
        self.notification_router = self._build_notification_router(
            adapters, notifications
        )
        self.patient_router = self._build_patient_router(
            adapters, monitoring, patient_ports
        )
        self.treatment_router = self._build_treatment_router(
            adapters, monitoring, treatment
        )
        self.audit_router = self._build_audit_router(adapters, audit)
        self.messaging_router = self._build_messaging_router(
            adapters, monitoring, messaging, notifications
        )

    def _treatment_commands(
        self,
        adapters: IdentityAdapters,
        treatment: TreatmentAdapters,
        monitoring: MonitoringAdapters,
    ) -> list[Registration]:
        """The treatment decisions (P13), each behind transaction and audit (P09)."""
        guard, clock, ids = self._command_guard, self.clock, adapters.ids
        gate = AssignedPatientGate(monitoring.patient_records)
        scope = make_scope(treatment.plans, gate)
        caretaker = PlanSnapshotCaretaker(treatment.snapshots)
        plans, templates = treatment.plans, treatment.templates
        return [
            bind(
                CreateProtocolTemplateCommand,
                guard.wrap(
                    CreateProtocolTemplateCommandHandler(
                        templates=templates, ids=ids, clock=clock
                    )
                ),
            ),
            bind(
                CreateProtocolTemplateVersionCommand,
                guard.wrap(
                    CreateProtocolTemplateVersionCommandHandler(
                        templates=templates, ids=ids, clock=clock
                    )
                ),
            ),
            bind(
                RetireProtocolTemplateCommand,
                guard.wrap(RetireProtocolTemplateCommandHandler(templates=templates)),
            ),
            bind(
                CreateTreatmentPlanCommand,
                guard.wrap(
                    CreateTreatmentPlanCommandHandler(
                        gate=gate,
                        plans=plans,
                        templates=templates,
                        targets=treatment.targets,
                        ids=ids,
                        clock=clock,
                    )
                ),
            ),
            bind(
                UpdateTreatmentPlanCommand,
                guard.wrap(
                    UpdateTreatmentPlanCommandHandler(
                        scope=scope,
                        plans=plans,
                        snapshots=caretaker,
                        ids=ids,
                        clock=clock,
                    )
                ),
            ),
            bind(
                ActivateTreatmentPlanCommand,
                guard.wrap(
                    ActivateTreatmentPlanCommandHandler(
                        scope=scope,
                        plans=plans,
                        templates=templates,
                        snapshots=caretaker,
                        clock=clock,
                    )
                ),
            ),
            bind(
                CreateTreatmentPlanVersionCommand,
                guard.wrap(
                    CreateTreatmentPlanVersionCommandHandler(
                        scope=scope, plans=plans, ids=ids, clock=clock
                    )
                ),
            ),
            bind(
                RestoreTreatmentPlanCommand,
                guard.wrap(
                    RestoreTreatmentPlanCommandHandler(
                        scope=scope,
                        plans=plans,
                        snapshots=treatment.snapshots,
                        ids=ids,
                        clock=clock,
                    )
                ),
            ),
        ]

    def _build_treatment_router(
        self,
        adapters: IdentityAdapters,
        monitoring: MonitoringAdapters,
        treatment: TreatmentAdapters,
    ) -> TreatmentRouter:
        """Wire the treatment reads (API.md 8.7); the writes go through the bus."""
        uow = adapters.unit_of_work
        gate = AssignedPatientGate(monitoring.patient_records)
        own = OwnPatientGate(adapters.consents)
        return TreatmentRouter(
            commands=self.command_bus,
            list_templates=ListProtocolTemplatesUseCase(
                uow=uow, templates=treatment.templates
            ),
            get_template=GetProtocolTemplateUseCase(
                uow=uow, templates=treatment.templates
            ),
            list_plans=ListTreatmentPlansUseCase(
                uow=uow, gate=gate, plans=treatment.plans
            ),
            get_plan=GetTreatmentPlanUseCase(uow=uow, gate=gate, plans=treatment.plans),
            list_snapshots=ListTreatmentPlanSnapshotsUseCase(
                uow=uow,
                gate=gate,
                plans=treatment.plans,
                snapshots=treatment.snapshots,
            ),
            get_own_plan=GetOwnTreatmentPlanUseCase(
                uow=uow, gate=own, plans=treatment.plans
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

    def _onboarding_commands(
        self,
        adapters: IdentityAdapters,
        onboarding: OnboardingAdapters,
        current: CurrentUnitOfWork,
    ) -> list[Registration]:
        """The patient import decisions (P13), behind transaction and audit (P09)."""
        guard, clock = self._command_guard, self.clock
        pipelines = self._import_pipelines(adapters, onboarding)
        return [
            bind(
                PreviewImportCommand,
                guard.wrap(
                    PreviewImportCommandHandler(
                        pipelines=pipelines,
                        staged=onboarding.staged,
                        current=current,
                    )
                ),
            ),
            bind(
                ConfirmImportCommand,
                guard.wrap(
                    ConfirmImportCommandHandler(
                        batches=onboarding.batches,
                        accounts=onboarding.accounts,
                        staged=onboarding.staged,
                        current=current,
                        ids=adapters.ids,
                        clock=clock,
                    )
                ),
            ),
        ]

    def _import_pipelines(
        self, adapters: IdentityAdapters, onboarding: OnboardingAdapters
    ) -> dict[SourceFormat, PatientImportPipeline]:
        """One P20 pipeline per P03 family; the command picks by source format."""
        return {
            SourceFormat.FHIR: FhirPatientImportPipeline(
                batches=onboarding.batches,
                vault=onboarding.vault,
                ids=adapters.ids,
                clock=self.clock,
            ),
            SourceFormat.CSV: CsvPatientImportPipeline(
                batches=onboarding.batches,
                vault=onboarding.vault,
                ids=adapters.ids,
                clock=self.clock,
            ),
        }

    def _build_import_router(
        self, adapters: IdentityAdapters, onboarding: OnboardingAdapters
    ) -> ImportRouter:
        """Wire the patient import endpoints (API.md 8.4)."""
        uow = adapters.unit_of_work
        return ImportRouter(
            commands=self.command_bus,
            list_batches=ListImportBatchesUseCase(uow=uow, batches=onboarding.batches),
            get_batch=GetImportBatchUseCase(uow=uow, batches=onboarding.batches),
            list_rows=ListImportRowsUseCase(uow=uow, batches=onboarding.batches),
            export_errors=ExportImportErrorsUseCase(
                uow=uow, batches=onboarding.batches
            ),
            csv_template=DownloadCsvTemplateUseCase(),
            staff_actor=self.full_session_actor,
        )

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

    def _clinic_admin_commands(
        self,
        adapters: IdentityAdapters,
        platform: PlatformAdapters,
        clinic_admins: ClinicAdminAdapters,
        current: CurrentUnitOfWork,
    ) -> list[Registration]:
        """Clinic administrator decisions (P13), behind transaction and audit (P09)."""
        guard, clock = self._command_guard, self.clock
        return [
            bind(
                CreateClinicAdminCommand,
                guard.wrap(
                    CreateClinicAdminCommandHandler(
                        clinics=platform.clinics,
                        provisioning=clinic_admins.provisioning,
                        codes=platform.activation_codes,
                        code_hasher=adapters.code_hasher,
                        channel=platform.email_channel,
                        messages=self.message_catalog,
                        clock=clock,
                        current=current,
                        invitation_ttl=timedelta(
                            days=self.settings.staff_invitation_days
                        ),
                    )
                ),
            ),
            bind(
                ResetClinicAdminAccessCommand,
                guard.wrap(
                    ResetClinicAdminAccessCommandHandler(
                        clinics=platform.clinics,
                        provisioning=clinic_admins.provisioning,
                        codes=platform.activation_codes,
                        code_hasher=adapters.code_hasher,
                        channel=platform.email_channel,
                        messages=self.message_catalog,
                        clock=clock,
                        current=current,
                        invitation_ttl=timedelta(
                            days=self.settings.staff_invitation_days
                        ),
                    )
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

    def _users_commands(
        self,
        adapters: IdentityAdapters,
        platform: PlatformAdapters,
        current: CurrentUnitOfWork,
    ) -> list[Registration]:
        """The staff decisions (P13), each behind transaction and audit (P09)."""
        guard, clock = self._command_guard, self.clock
        directory, users = platform.staff_directory, adapters.users
        return [
            bind(
                CreateStaffUserCommand,
                guard.wrap(
                    CreateStaffUserCommandHandler(
                        users=users,
                        directory=directory,
                        invitations=platform.staff_invitations,
                        codes=platform.activation_codes,
                        code_hasher=adapters.code_hasher,
                        channel=platform.email_channel,
                        messages=self.message_catalog,
                        ids=adapters.ids,
                        clock=clock,
                        current=current,
                        invitation_ttl=timedelta(
                            days=self.settings.staff_invitation_days
                        ),
                    )
                ),
            ),
            bind(
                UpdateStaffUserCommand,
                guard.wrap(
                    UpdateStaffUserCommandHandler(directory=directory, clock=clock)
                ),
            ),
            bind(
                DeactivateStaffUserCommand,
                guard.wrap(
                    DeactivateStaffUserCommandHandler(
                        users=users,
                        directory=directory,
                        refresh_tokens=adapters.refresh_tokens,
                        care_teams=platform.care_teams,
                        clock=clock,
                    )
                ),
            ),
            bind(
                UnlockStaffUserCommand,
                guard.wrap(
                    UnlockStaffUserCommandHandler(
                        users=users,
                        lockouts=platform.login_lockouts,
                        events=adapters.security_events,
                        clock=clock,
                    )
                ),
            ),
            bind(
                ResetStaffMfaCommand,
                guard.wrap(
                    ResetStaffMfaCommandHandler(
                        users=users,
                        factors=adapters.mfa_factors,
                        refresh_tokens=adapters.refresh_tokens,
                        events=adapters.security_events,
                        channel=platform.email_channel,
                        messages=self.message_catalog,
                        current=current,
                        clock=clock,
                    )
                ),
            ),
        ]

    def _patient_commands(
        self,
        adapters: IdentityAdapters,
        platform: PlatformAdapters,
        ports: PatientAdapters,
    ) -> list[Registration]:
        """The patient account decisions (P13, P18), behind transaction and audit."""
        guard, clock = self._command_guard, self.clock
        directory, users = platform.patients, adapters.users
        tokens, roster = adapters.refresh_tokens, ports.roster
        return [
            bind(
                SuspendPatientCommand,
                guard.wrap(
                    SuspendPatientCommandHandler(
                        patients=directory,
                        users=users,
                        refresh_tokens=tokens,
                        roster=roster,
                        clock=clock,
                    )
                ),
            ),
            bind(
                ReactivatePatientCommand,
                guard.wrap(
                    ReactivatePatientCommandHandler(
                        patients=directory, users=users, roster=roster
                    )
                ),
            ),
            bind(
                DeactivatePatientCommand,
                guard.wrap(
                    DeactivatePatientCommandHandler(
                        patients=directory,
                        users=users,
                        refresh_tokens=tokens,
                        invitations=ports.invitations,
                        roster=roster,
                        clock=clock,
                    )
                ),
            ),
        ]

    def _consent_commands(
        self,
        adapters: IdentityAdapters,
        ports: ConsentsAdapters,
        events: CurrentUnitOfWork,
    ) -> list[Registration]:
        """The consent and privacy decisions (P13), behind transaction and audit."""
        guard, clock = self._command_guard, self.clock
        own_consent = OwnConsentGate()
        return [
            bind(
                AcceptConsentCommand,
                guard.wrap(
                    AcceptConsentCommandHandler(
                        gate=own_consent,
                        consents=adapters.consents,
                        history=ports.history,
                        ids=adapters.ids,
                        clock=clock,
                    )
                ),
            ),
            bind(
                WithdrawConsentCommand,
                guard.wrap(
                    WithdrawConsentCommandHandler(
                        gate=own_consent,
                        consents=adapters.consents,
                        history=ports.history,
                        ids=adapters.ids,
                        clock=clock,
                        events=events,
                    )
                ),
            ),
            bind(
                CreatePrivacyRequestCommand,
                guard.wrap(
                    CreatePrivacyRequestCommandHandler(
                        gate=OwnPatientGate(adapters.consents),
                        requests=ports.requests,
                        ids=adapters.ids,
                        clock=clock,
                        due_days=self.settings.privacy_request_due_days,
                    )
                ),
            ),
            bind(
                ResolvePrivacyRequestCommand,
                guard.wrap(
                    ResolvePrivacyRequestCommandHandler(
                        requests=ports.requests, clock=clock
                    )
                ),
            ),
        ]

    def _build_consent_router(
        self,
        adapters: IdentityAdapters,
        ports: ConsentsAdapters,
        monitoring: MonitoringAdapters,
    ) -> ConsentRouter:
        """Wire the consent and privacy routes (API.md 8.13) over ``ports``."""
        uow, clock = adapters.unit_of_work, self.clock
        return ConsentRouter(
            commands=self.command_bus,
            notice=GetPrivacyNoticeUseCase(uow=uow, notices=ports.notices),
            own_consent=GetOwnConsentUseCase(
                uow=uow,
                gate=OwnConsentGate(),
                consents=adapters.consents,
                history=ports.history,
            ),
            list_statuses=ListConsentStatusesUseCase(
                uow=uow,
                history=ports.history,
                access_log=ports.access_log,
                clock=clock,
            ),
            list_requests=ListPrivacyRequestsUseCase(uow=uow, requests=ports.requests),
            export_request=ExportPrivacyRequestUseCase(
                uow=uow,
                gate=OwnPatientGate(adapters.consents),
                requests=ports.requests,
                history=ports.history,
                timeline=monitoring.timeline,
                access_log=ports.access_log,
                clock=clock,
            ),
            session_actor=self.full_session_actor,
        )

    def _credential_issue_limit(self, adapters: IdentityAdapters) -> RateLimitCheck:
        """300 code issues per clinic and hour (API.md section 5)."""
        return RateLimitCheck(
            adapters.rate_limiter,
            RateLimitRule(
                family="credential_issue_clinic",
                limit=self.settings.rate_limit_credential_issue_per_clinic_per_hour,
                window=timedelta(hours=1),
            ),
        )

    def _credential_batch_limit(self, adapters: IdentityAdapters) -> RateLimitCheck:
        """10 credential batches per clinic and hour (API.md section 5)."""
        return RateLimitCheck(
            adapters.rate_limiter,
            RateLimitRule(
                family="credential_batch_clinic",
                limit=self.settings.rate_limit_credential_batch_per_clinic_per_hour,
                window=timedelta(hours=1),
            ),
        )

    def _credential_commands(
        self,
        adapters: IdentityAdapters,
        platform: PlatformAdapters,
        current: CurrentUnitOfWork,
        credentials: CredentialsAdapters,
    ) -> list[Registration]:
        """The patient credential decisions (P13), with transaction and audit (P09)."""
        guard, clock = self._command_guard, self.clock
        return [
            bind(
                IssueCredentialsCommand,
                guard.wrap(
                    IssueCredentialsCommandHandler(
                        contacts=credentials.patient_contacts,
                        users=adapters.users,
                        invitations=credentials.invitations,
                        codes=platform.activation_codes,
                        code_hasher=adapters.code_hasher,
                        channel=platform.email_channel,
                        messages=self.message_catalog,
                        base_url=self.settings.web_app_base_url,
                        ids=adapters.ids,
                        clock=clock,
                        current=current,
                        code_ttl=timedelta(
                            hours=self.settings.activation_code_ttl_hours
                        ),
                    )
                ),
            ),
            bind(
                RevokeCredentialInvitationCommand,
                guard.wrap(
                    RevokeCredentialInvitationCommandHandler(
                        users=adapters.users,
                        invitations=credentials.invitations,
                        clock=clock,
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

    def _alert_commands(
        self,
        adapters: IdentityAdapters,
        monitoring: MonitoringAdapters,
        alerts: AlertsAdapters,
    ) -> list[Registration]:
        """The alert decisions (P13), each behind transaction and audit (P09)."""
        guard, clock, ids = self._command_guard, self.clock, adapters.ids
        own = OwnPatientGate(adapters.consents)
        assigned = AssignedPatientGate(monitoring.patient_records)
        return [
            bind(
                CreateAlertRuleCommand,
                guard.wrap(
                    CreateAlertRuleCommandHandler(
                        rules=alerts.rules, ids=ids, clock=clock
                    )
                ),
            ),
            bind(
                CreateAlertRuleVersionCommand,
                guard.wrap(
                    CreateAlertRuleVersionCommandHandler(
                        rules=alerts.rules, ids=ids, clock=clock
                    )
                ),
            ),
            bind(
                AcknowledgeAlertCommand,
                guard.wrap(
                    AcknowledgeAlertCommandHandler(
                        alerts=alerts.alerts,
                        own_gate=own,
                        assigned_gate=assigned,
                        ids=ids,
                        clock=clock,
                    )
                ),
            ),
            bind(
                ResolveAlertCommand,
                guard.wrap(
                    ResolveAlertCommandHandler(
                        alerts=alerts.alerts,
                        assigned_gate=assigned,
                        ids=ids,
                        clock=clock,
                    )
                ),
            ),
        ]

    def _recommendation_commands(
        self,
        adapters: IdentityAdapters,
        monitoring: MonitoringAdapters,
        ai: AiAdapters,
        unit_of_work: CurrentUnitOfWork,
    ) -> list[Registration]:
        """The doctor's decisions on recommendations (P13), audited (P09)."""
        guard, clock, ids = self._command_guard, self.clock, adapters.ids
        assigned = AssignedPatientGate(monitoring.patient_records)
        recommendations = ai.recommendations
        return [
            bind(
                ApproveRecommendationCommand,
                guard.wrap(
                    ApproveRecommendationCommandHandler(
                        recommendations=recommendations,
                        assigned_gate=assigned,
                        drafts=ai.drafts,
                        clock=clock,
                        current=unit_of_work,
                        ids=ids,
                    )
                ),
            ),
            bind(
                ModifyRecommendationCommand,
                guard.wrap(
                    ModifyRecommendationCommandHandler(
                        recommendations=recommendations,
                        assigned_gate=assigned,
                        drafts=ai.drafts,
                        clock=clock,
                        current=unit_of_work,
                        ids=ids,
                    )
                ),
            ),
            bind(
                RejectRecommendationCommand,
                guard.wrap(
                    RejectRecommendationCommandHandler(
                        recommendations=recommendations,
                        assigned_gate=assigned,
                        clock=clock,
                        current=unit_of_work,
                        ids=ids,
                    )
                ),
            ),
        ]

    def _subscribe_alert_evaluation(
        self, adapters: IdentityAdapters, alerts: AlertsAdapters
    ) -> None:
        """Evaluate the rules after each committed reading (P17), if in-process."""
        publisher = self.event_publisher
        if not isinstance(publisher, InProcessDomainEventPublisher):
            return
        publisher.subscribe(
            GlucoseReadingRecorded,
            EvaluateAlertRulesOnReading(
                uow=adapters.unit_of_work,
                rules=alerts.rules,
                alerts=alerts.alerts,
                history=alerts.history,
                ids=adapters.ids,
                clock=self.clock,
            ),
        )

    def _build_alerts_router(
        self,
        adapters: IdentityAdapters,
        monitoring: MonitoringAdapters,
        alerts: AlertsAdapters,
    ) -> AlertRouter:
        """Wire the rules and alerts reads (API.md 8.9) over the scoped gates."""
        uow = adapters.unit_of_work
        own = OwnPatientGate(adapters.consents)
        assigned = AssignedPatientGate(monitoring.patient_records)
        return AlertRouter(
            commands=self.command_bus,
            list_rules=ListAlertRulesUseCase(uow=uow, rules=alerts.rules),
            get_rule=GetAlertRuleUseCase(uow=uow, rules=alerts.rules),
            list_alerts=ListAlertsUseCase(
                uow=uow, own_gate=own, assigned_gate=assigned, alerts=alerts.alerts
            ),
            get_summary=GetAlertSummaryUseCase(uow=uow, summary=alerts.summary),
            get_alert=GetAlertUseCase(
                uow=uow, own_gate=own, assigned_gate=assigned, alerts=alerts.alerts
            ),
            session_actor=self.full_session_actor,
        )

    def _build_recommendation_router(
        self,
        adapters: IdentityAdapters,
        monitoring: MonitoringAdapters,
        ai: AiAdapters,
    ) -> RecommendationRouter:
        """Wire the recommendation reads (API.md 8.10) over the assigned gate."""
        uow = adapters.unit_of_work
        assigned = AssignedPatientGate(monitoring.patient_records)
        return RecommendationRouter(
            commands=self.command_bus,
            list_recommendations=ListRecommendationsUseCase(
                uow=uow, assigned_gate=assigned, recommendations=ai.recommendations
            ),
            get_recommendation=GetRecommendationUseCase(
                uow=uow, assigned_gate=assigned, recommendations=ai.recommendations
            ),
            session_actor=self.full_session_actor,
        )

    def _build_records_router(
        self, adapters: IdentityAdapters, monitoring: MonitoringAdapters
    ) -> RecordsRouter:
        """Wire the patient record use cases (API.md 8.6) over ``monitoring``.

        Writes share the per-user records limit; exports have their own hourly
        limit. Reads are not rate limited by this slice.
        """
        settings, clock = self.settings, self.clock
        uow, ids, consents = adapters.unit_of_work, adapters.ids, adapters.consents
        limiter = adapters.rate_limiter
        writes = OwnPatientGate(
            consents,
            RateLimitCheck(
                limiter,
                RateLimitRule(
                    family="records_user_minute",
                    limit=settings.rate_limit_records_per_user_per_minute,
                    window=timedelta(minutes=1),
                ),
            ),
        )
        exports = OwnPatientGate(
            consents,
            RateLimitCheck(
                limiter,
                RateLimitRule(
                    family="exports_user_hour",
                    limit=settings.rate_limit_exports_per_user_per_hour,
                    window=timedelta(hours=1),
                ),
            ),
        )
        reads = OwnPatientGate(consents)
        assigned = AssignedPatientGate(monitoring.patient_records)
        writer = RecordWriter(monitoring.clinical_records)
        chain = build_validation_chain()
        recorder = GlucoseReadingRecorder(
            readings=monitoring.readings,
            chain=chain,
            settings=monitoring.validation,
            targets=monitoring.targets,
            ids=ids,
            clock=clock,
        )
        return RecordsRouter(
            record_reading=RecordGlucoseReadingUseCase(
                uow=uow, gate=writes, recorder=recorder
            ),
            record_batch=RecordGlucoseReadingsBatchUseCase(
                uow=uow,
                gate=writes,
                recorder=recorder,
                batches=monitoring.sync_batches,
                ids=ids,
                clock=clock,
            ),
            import_cgm=ImportCgmReadingsUseCase(
                uow=uow,
                gate=writes,
                recorder=recorder,
                batches=monitoring.sync_batches,
                source=monitoring.cgm,
                ids=ids,
                clock=clock,
            ),
            record_dose=RecordInsulinDoseUseCase(
                uow=uow,
                gate=writes,
                writer=writer,
                plans=monitoring.active_plans,
                ids=ids,
                clock=clock,
            ),
            record_meal=RecordMealUseCase(
                uow=uow, gate=writes, writer=writer, ids=ids, clock=clock
            ),
            record_activity=RecordActivityUseCase(
                uow=uow, gate=writes, writer=writer, ids=ids, clock=clock
            ),
            record_symptom=RecordSymptomUseCase(
                uow=uow,
                gate=writes,
                writer=writer,
                catalog=monitoring.symptoms,
                ids=ids,
                clock=clock,
            ),
            record_own_lab=RecordOwnLabResultUseCase(
                uow=uow, gate=writes, writer=writer, ids=ids, clock=clock
            ),
            record_patient_lab=RecordPatientLabResultUseCase(
                uow=uow, gate=assigned, writer=writer, ids=ids, clock=clock
            ),
            correct=CorrectRecordUseCase(
                uow=uow,
                gate=writes,
                readings=monitoring.readings,
                records=monitoring.clinical_records,
                catalog=monitoring.symptoms,
                recorder=recorder,
                chain=chain,
                ids=ids,
                clock=clock,
            ),
            annul=AnnulRecordUseCase(
                uow=uow,
                gate=writes,
                readings=monitoring.readings,
                records=monitoring.clinical_records,
                ids=ids,
                clock=clock,
            ),
            list_records=ListRecordsUseCase(
                uow=uow,
                own_gate=reads,
                assigned_gate=assigned,
                readings=monitoring.readings,
                records=monitoring.clinical_records,
            ),
            timeline=GetTimelineUseCase(
                uow=uow,
                own_gate=reads,
                assigned_gate=assigned,
                timeline=monitoring.timeline,
            ),
            export_timeline=ExportTimelineUseCase(
                uow=uow,
                own_gate=exports,
                assigned_gate=assigned,
                timeline=monitoring.timeline,
                exporters=monitoring.exporters,
            ),
            session_actor=self.full_session_actor,
        )

    def _build_metrics_router(
        self, adapters: IdentityAdapters, monitoring: MonitoringAdapters
    ) -> MetricsRouter:
        """Wire the glycemic metrics, AGP and forecast use cases (API.md 8.8)."""
        uow, clock = adapters.unit_of_work, self.clock
        own = OwnPatientGate(adapters.consents)
        assigned = AssignedPatientGate(monitoring.patient_records)
        return MetricsRouter(
            metrics=ComputeGlycemicMetricsUseCase(
                uow=uow,
                own_gate=own,
                assigned_gate=assigned,
                targets=monitoring.targets,
                series=monitoring.series,
                strategies=GlycemicTargetStrategyRegistry(),
                clock=clock,
            ),
            agp=GetAgpUseCase(
                uow=uow,
                own_gate=own,
                assigned_gate=assigned,
                targets=monitoring.targets,
                series=monitoring.series,
                clock=clock,
            ),
            forecast=GetForecastUseCase(
                uow=uow,
                own_gate=own,
                assigned_gate=assigned,
                targets=monitoring.targets,
                series=monitoring.series,
                forecasts=monitoring.forecasts,
                clock=clock,
            ),
            session_actor=self.full_session_actor,
        )

    def _targets_commands(
        self,
        adapters: IdentityAdapters,
        monitoring: MonitoringAdapters,
        targets: TargetsAdapters,
    ) -> list[Registration]:
        """Goals and reminders decisions (P13), each behind transaction and audit."""
        guard, clock, ids = self._command_guard, self.clock, adapters.ids
        assigned = AssignedPatientGate(monitoring.patient_records)
        own = OwnPatientGate(adapters.consents)
        catalog, reminders = targets.catalog, targets.reminders
        return [
            bind(
                CreateTargetProfileCommand,
                guard.wrap(
                    CreateTargetProfileCommandHandler(
                        catalog=catalog, ids=ids, clock=clock
                    )
                ),
            ),
            bind(
                CreateTargetProfileVersionCommand,
                guard.wrap(
                    CreateTargetProfileVersionCommandHandler(
                        catalog=catalog, ids=ids, clock=clock
                    )
                ),
            ),
            bind(
                AssignTargetProfileCommand,
                guard.wrap(
                    AssignTargetProfileCommandHandler(
                        gate=assigned,
                        catalog=catalog,
                        assignments=targets.assignments,
                        ids=ids,
                        clock=clock,
                    )
                ),
            ),
            bind(
                CreateReminderCommand,
                guard.wrap(
                    CreateReminderCommandHandler(
                        gate=assigned, reminders=reminders, ids=ids, clock=clock
                    )
                ),
            ),
            bind(
                UpdatePatientReminderCommand,
                guard.wrap(
                    UpdatePatientReminderCommandHandler(
                        gate=assigned, reminders=reminders, clock=clock
                    )
                ),
            ),
            bind(
                UpdateOwnReminderCommand,
                guard.wrap(
                    UpdateOwnReminderCommandHandler(
                        gate=own, reminders=reminders, clock=clock
                    )
                ),
            ),
        ]

    def _build_target_profile_router(
        self, adapters: IdentityAdapters, targets: TargetsAdapters
    ) -> TargetProfileRouter:
        """Wire the goals catalog, the versions and the assignment (API.md 8.7)."""
        uow = adapters.unit_of_work
        return TargetProfileRouter(
            commands=self.command_bus,
            list_profiles=ListTargetProfilesUseCase(uow=uow, catalog=targets.catalog),
            get_profile=GetTargetProfileUseCase(uow=uow, catalog=targets.catalog),
            session_actor=self.full_session_actor,
        )

    def _build_reminder_router(
        self,
        adapters: IdentityAdapters,
        monitoring: MonitoringAdapters,
        targets: TargetsAdapters,
    ) -> ReminderRouter:
        """Wire the reminders of the doctor (assigned) and of the patient (own)."""
        uow = adapters.unit_of_work
        return ReminderRouter(
            commands=self.command_bus,
            list_patient=ListPatientRemindersUseCase(
                uow=uow,
                gate=AssignedPatientGate(monitoring.patient_records),
                reminders=targets.reminders,
            ),
            list_own=ListOwnRemindersUseCase(
                uow=uow,
                gate=OwnPatientGate(adapters.consents),
                reminders=targets.reminders,
            ),
            session_actor=self.full_session_actor,
        )

    def _build_notification_router(
        self, adapters: IdentityAdapters, notifications: NotificationAdapters
    ) -> NotificationRouter:
        """Wire the notification use cases (API.md 8.9) over ``notifications``.

        The Web Push endpoints are checked against the configured allowlist; the
        auth secret is encrypted with the identity cipher.
        """
        uow, consents, clock = adapters.unit_of_work, adapters.consents, self.clock
        return NotificationRouter(
            list_notifications=ListNotificationsUseCase(
                uow=uow,
                consents=consents,
                notifications=notifications.notifications,
                messages=self.message_catalog,
            ),
            mark_read=MarkNotificationReadUseCase(
                uow=uow,
                consents=consents,
                notifications=notifications.notifications,
                clock=clock,
            ),
            get_preferences=GetNotificationPreferencesUseCase(
                uow=uow,
                consents=consents,
                store=notifications.preferences,
            ),
            update_preferences=UpdateNotificationPreferencesUseCase(
                uow=uow,
                consents=consents,
                store=notifications.preferences,
                clock=clock,
            ),
            register_push=RegisterWebPushSubscriptionUseCase(
                uow=uow,
                consents=consents,
                subscriptions=notifications.push_subscriptions,
                security_events=adapters.security_events,
                cipher=adapters.cipher,
                ids=adapters.ids,
                clock=clock,
                allowed_hosts=tuple(self.settings.push_endpoint_allowed_hosts),
            ),
            remove_push=RemoveWebPushSubscriptionUseCase(
                uow=uow,
                consents=consents,
                subscriptions=notifications.push_subscriptions,
            ),
            session_actor=self.full_session_actor,
        )

    def _build_patient_router(
        self,
        adapters: IdentityAdapters,
        monitoring: MonitoringAdapters,
        ports: PatientAdapters,
    ) -> PatientRouter:
        """Wire the patient administration (API.md 8.4) and the own profile (8.6).

        The own profile reuses the use case of the monitoring slice: it checks the
        permission, the consent and the patient of the token.
        """
        uow, clock = adapters.unit_of_work, self.clock
        return PatientRouter(
            commands=self.command_bus,
            list_patients=ListPatientsUseCase(
                uow=uow, roster=ports.roster, access_log=ports.access_log, clock=clock
            ),
            get_patient=GetPatientUseCase(
                uow=uow, roster=ports.roster, access_log=ports.access_log, clock=clock
            ),
            own_profile=GetOwnPatientProfileUseCase(
                uow=uow,
                gate=OwnPatientGate(adapters.consents),
                users=adapters.users,
                targets=monitoring.targets,
            ),
            session_actor=self.full_session_actor,
        )

    def _build_audit_router(
        self, adapters: IdentityAdapters, audit: AuditAdapters
    ) -> AuditRouter:
        """Wire the audit reads and the chain check (API.md 8.13) over the session."""
        uow = adapters.unit_of_work
        return AuditRouter(
            list_audit_log=ListAuditLogUseCase(uow=uow, reader=audit.audit_log),
            list_data_access=ListDataAccessUseCase(uow=uow, reader=audit.data_access),
            list_security_events=ListSecurityEventsUseCase(
                uow=uow, reader=audit.security_events
            ),
            verify_chain=VerifyAuditChainUseCase(
                uow=uow, chain=audit.chain, events=adapters.security_events
            ),
            session_actor=self.full_session_actor,
        )

    def _messaging_commands(
        self,
        adapters: IdentityAdapters,
        monitoring: MonitoringAdapters,
        messaging: MessagingAdapters,
    ) -> list[Registration]:
        """The follow-up decisions (P13), each behind transaction and audit (P09)."""
        guard, clock, ids = self._command_guard, self.clock, adapters.ids
        assigned = AssignedPatientGate(monitoring.patient_records)
        return [
            bind(
                CreateFollowUpCommand,
                guard.wrap(
                    CreateFollowUpCommandHandler(
                        gate=assigned,
                        follow_ups=messaging.follow_ups,
                        ids=ids,
                        clock=clock,
                        catalog=self.message_catalog,
                    )
                ),
            ),
            bind(
                CloseFollowUpCommand,
                guard.wrap(
                    CloseFollowUpCommandHandler(
                        gate=assigned, follow_ups=messaging.follow_ups, clock=clock
                    )
                ),
            ),
        ]

    def _build_messaging_router(
        self,
        adapters: IdentityAdapters,
        monitoring: MonitoringAdapters,
        messaging: MessagingAdapters,
        notifications: NotificationAdapters,
    ) -> MessagingRouter:
        """Wire the thread (API.md 8.12) over one patient scope and the P07 channel."""
        uow = adapters.unit_of_work
        scope = PatientScope(
            assigned=AssignedPatientGate(monitoring.patient_records),
            own=OwnPatientGate(adapters.consents),
        )
        return MessagingRouter(
            commands=self.command_bus,
            list_messages=ListMessagesUseCase(
                uow=uow,
                scope=scope,
                threads=messaging.threads,
                messages=messaging.messages,
                read_marks=messaging.read_marks,
                clock=self.clock,
                catalog=self.message_catalog,
            ),
            send_message=SendMessageUseCase(
                uow=uow,
                scope=scope,
                threads=messaging.threads,
                messages=messaging.messages,
                read_marks=messaging.read_marks,
                care_teams=messaging.care_teams,
                patients=messaging.patients,
                ids=adapters.ids,
                clock=self.clock,
                in_app=notifications.in_app,
                catalog=self.message_catalog,
            ),
            list_follow_ups=ListFollowUpsUseCase(
                uow=uow, scope=scope, follow_ups=messaging.follow_ups
            ),
            session_actor=self.full_session_actor,
        )
