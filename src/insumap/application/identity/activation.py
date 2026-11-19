"""Activation of an imported patient with a single-use code.

Step 1 checks the code and the birth date and opens an activation session.
Step 2 sets the password and the email, records the consent and activates the
account in one transaction; ``PatientActivated`` is published after commit.
Every failure of either step answers the same ``410 INVITATION_INVALID``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Final, final
from uuid import UUID

from insumap.application.common.ids import IdGenerator
from insumap.application.common.unit_of_work import TransactionContext, UnitOfWorkPort
from insumap.application.identity.challenges import ChallengePolicy, ChallengeService
from insumap.application.identity.passwords import NewPasswordService
from insumap.application.identity.ports import (
    ActivationRepositoryPort,
    CodeHasherPort,
    CodePurpose,
    ConsentRepositoryPort,
    UserRepositoryPort,
)
from insumap.application.identity.session import AuthenticationResult, SessionIssuer
from insumap.application.security.events import (
    SecurityEvent,
    SecurityEventPort,
    SecurityEventType,
)
from insumap.application.security.rate_limit import RateLimitCheck
from insumap.domain.identity.auth_challenge import ChallengePurpose
from insumap.domain.identity.codes import ActivationCode
from insumap.domain.identity.consent import ConsentAction, ConsentRecord, ConsentScope
from insumap.domain.identity.email import EmailAddress
from insumap.domain.identity.errors import (
    ConsentRequiredError,
    ConsentVersionOutdatedError,
    EmailUnavailableError,
    InvitationInvalidError,
)
from insumap.domain.identity.events import PatientActivated
from insumap.domain.identity.invitation import (
    CredentialInvitation,
    InvitationPurpose,
    InvitationStatus,
)
from insumap.domain.identity.password_policy import PersonalData
from insumap.shared.errors import ErrorCode, InsumapError
from insumap.shared.time import Clock

FILLER_CODE: Final = "0" * 16
"""Hashed when the input is malformed, so every attempt costs the same."""

EMAIL_FIELD: Final = "body.email"
MISSING: Final = "missing"


@dataclass(frozen=True, slots=True, kw_only=True)
class VerifyActivationCodeInput:
    """The code as typed and the birth date of the patient."""

    activation_code: str
    birth_date: date | None
    client_ip: str


@dataclass(frozen=True, slots=True, kw_only=True)
class VerifyActivationCodeResult:
    """The activation session; never the patient's name or other data."""

    activation_token: str
    clinic_name: str
    privacy_notice_version_id: UUID
    email_required: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class ActivationPolicy:
    """Failed birth dates before locking, and the activation session."""

    max_attempts: int
    session: ChallengePolicy


@final
class VerifyActivationCodeUseCase:
    """Step 1: code plus birth date opens a 15 minute activation session.

    A wrong birth date with a real code counts an attempt on the invitation
    (``LOCKED`` at the limit); that count is committed before answering.
    """

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        code_hasher: CodeHasherPort,
        activations: ActivationRepositoryPort,
        consents: ConsentRepositoryPort,
        challenges: ChallengeService,
        events: SecurityEventPort,
        policy: ActivationPolicy,
        rate_limit: RateLimitCheck,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._code_hasher = code_hasher
        self._activations = activations
        self._consents = consents
        self._challenges = challenges
        self._events = events
        self._policy = policy
        self._rate_limit = rate_limit
        self._clock = clock

    def execute(self, input: VerifyActivationCodeInput) -> VerifyActivationCodeResult:
        """Return the activation session or raise ``InvitationInvalidError``."""
        self._rate_limit.ensure(input.client_ip)
        code = ActivationCode.parse(input.activation_code)
        hashes = self._code_hasher.hashes_for_lookup(
            CodePurpose.ACTIVATION, FILLER_CODE if code is None else code.value
        )
        now = self._clock.now()
        with self._uow.begin(TransactionContext.anonymous()) as uow:
            found = self._activations.find_invitation(hashes)
            if (
                code is None
                or found is None
                or found.purpose is not InvitationPurpose.PATIENT_ACTIVATION
                or found.clinic_id is None
            ):
                raise InvitationInvalidError
            uow.apply_context(
                TransactionContext(user_id=found.user_id, clinic_id=found.clinic_id)
            )
            invitation = self._activations.get_invitation(found.invitation_id)
            if (
                invitation is None
                or invitation.patient_id is None
                or invitation.clinic_id is None
            ):
                raise InvitationInvalidError
            profile = self._activations.activation_profile(invitation.patient_id)
            notice = self._consents.current_notice(invitation.clinic_id)
            if profile is None or notice is None:
                raise InvitationInvalidError
            checked = invitation.verify_birth_date(
                matches=_same_date(profile.birth_date, input.birth_date),
                now=now,
                max_attempts=self._policy.max_attempts,
            )
            self._activations.save_invitation(checked)
            if checked.status is not InvitationStatus.VERIFIED:
                self._record_failure(checked)
                uow.commit()
                raise InvitationInvalidError
            token = self._challenges.issue(
                purpose=ChallengePurpose.ACTIVATION,
                policy=self._policy.session,
                user_id=invitation.user_id,
                clinic_id=invitation.clinic_id,
                invitation_id=invitation.invitation_id,
            )
            uow.commit()
        return VerifyActivationCodeResult(
            activation_token=token,
            clinic_name=profile.clinic_name,
            privacy_notice_version_id=notice.version_id,
            email_required=profile.contact_email is None,
        )

    def _record_failure(self, invitation: CredentialInvitation) -> None:
        self._events.record(
            SecurityEvent(
                event_type=(
                    SecurityEventType.ACTIVATION_LOCKED
                    if invitation.is_locked
                    else SecurityEventType.ACTIVATION_FAILED
                ),
                user_id=invitation.user_id,
                clinic_id=invitation.clinic_id,
            )
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ConsentInput:
    """The consent given with the activation."""

    privacy_notice_version_id: UUID
    accepted: bool
    ai_external_processing: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class CompleteActivationInput:
    """The activation session, the new password, the email and the consent."""

    activation_token: str
    new_password: str
    email: str | None
    consent: ConsentInput
    client_ip: str


@final
class CompleteActivationUseCase:
    """Step 2: the patient becomes ``ACTIVE`` with the consent, atomically."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        challenges: ChallengeService,
        activations: ActivationRepositoryPort,
        users: UserRepositoryPort,
        consents: ConsentRepositoryPort,
        passwords: NewPasswordService,
        sessions: SessionIssuer,
        events: SecurityEventPort,
        rate_limit: RateLimitCheck,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._challenges = challenges
        self._activations = activations
        self._users = users
        self._consents = consents
        self._passwords = passwords
        self._sessions = sessions
        self._events = events
        self._rate_limit = rate_limit
        self._ids = ids
        self._clock = clock

    def execute(self, input: CompleteActivationInput) -> AuthenticationResult:
        """Activate the account and open its first session."""
        self._rate_limit.ensure(input.client_ip)
        now = self._clock.now()
        with self._uow.begin(TransactionContext.anonymous()) as uow:
            challenge = self._challenges.find_usable(
                input.activation_token, purpose=ChallengePurpose.ACTIVATION
            )
            if challenge is None:
                raise InvitationInvalidError
            uow.apply_context(
                TransactionContext(
                    user_id=challenge.user_id, clinic_id=challenge.clinic_id
                )
            )
            invitation = (
                None
                if challenge.invitation_id is None
                else self._activations.get_invitation(challenge.invitation_id)
            )
            account = self._users.get(challenge.user_id)
            if (
                invitation is None
                or invitation.patient_id is None
                or invitation.clinic_id is None
                or account is None
            ):
                raise InvitationInvalidError
            profile = self._activations.activation_profile(invitation.patient_id)
            if profile is None:
                raise InvitationInvalidError
            if not input.consent.accepted:
                raise ConsentRequiredError
            notice = self._consents.current_notice(invitation.clinic_id)
            if (
                notice is None
                or notice.version_id != input.consent.privacy_notice_version_id
            ):
                raise ConsentVersionOutdatedError
            email = _email(input.email or profile.contact_email)
            if self._users.email_taken(
                email.normalized, except_user_id=account.user_id
            ):
                raise EmailUnavailableError
            password_hash = self._passwords.accepted_hash(
                account.user_id,
                input.new_password,
                PersonalData(
                    email_local_part=email.local_part, full_name=profile.full_name
                ),
            )
            used = invitation.use(now=now)
            activated = account.activated(password_hash=password_hash, email=email)
            self._users.save(activated)
            self._passwords.remember(account.user_id, password_hash)
            self._activations.save_invitation(used)
            self._challenges.save(challenge.consumed(now=now))
            self._consents.add(
                _consent_records(
                    input.consent,
                    ids=self._ids,
                    clinic_id=invitation.clinic_id,
                    patient_id=invitation.patient_id,
                    user_id=account.user_id,
                    now=now,
                )
            )
            self._events.record(
                SecurityEvent(
                    event_type=SecurityEventType.ACCOUNT_ACTIVATED,
                    user_id=account.user_id,
                    clinic_id=invitation.clinic_id,
                )
            )
            uow.collect(
                [
                    PatientActivated(
                        event_id=self._ids.new_id(),
                        occurred_at=now,
                        user_id=account.user_id,
                        patient_id=invitation.patient_id,
                        clinic_id=invitation.clinic_id,
                    )
                ]
            )
            result = self._sessions.open_full_session(activated)
            uow.commit()
        return result


def _same_date(expected: date, given: date | None) -> bool:
    return given is not None and given == expected


def _email(raw: str | None) -> EmailAddress:
    if not raw or not raw.strip():
        raise InsumapError(
            ErrorCode.VALIDATION_ERROR,
            detail={"errors": [{"field": EMAIL_FIELD, "type": MISSING}]},
        )
    return EmailAddress.from_input(raw)


def _consent_records(
    consent: ConsentInput,
    *,
    ids: IdGenerator,
    clinic_id: UUID,
    patient_id: UUID,
    user_id: UUID,
    now: datetime,
) -> list[ConsentRecord]:
    scopes = [ConsentScope.SENSITIVE_DATA_PROCESSING]
    if consent.ai_external_processing:
        scopes.append(ConsentScope.AI_EXTERNAL_PROCESSING)
    return [
        ConsentRecord(
            consent_id=ids.new_id(),
            clinic_id=clinic_id,
            patient_id=patient_id,
            privacy_notice_version_id=consent.privacy_notice_version_id,
            scope=scope,
            action=ConsentAction.ACCEPTED,
            occurred_at=now,
            recorded_by=user_id,
        )
        for scope in scopes
    ]
