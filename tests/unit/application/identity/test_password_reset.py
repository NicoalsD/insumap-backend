"""Forgotten password and email verification, from request to confirmation."""

from dataclasses import replace
from datetime import timedelta
from uuid import UUID

import pytest

from insumap.application.identity.challenges import ChallengePolicy
from insumap.application.identity.email_verification import (
    ConfirmEmailVerificationInput,
    ConfirmEmailVerificationUseCase,
    EmailVerificationIssuer,
)
from insumap.application.identity.password_reset import (
    CompletePasswordResetInput,
    CompletePasswordResetUseCase,
    PasswordResetPolicy,
    RequestPasswordResetInput,
    RequestPasswordResetUseCase,
)
from insumap.application.security.events import SecurityEventType
from insumap.application.security.rate_limit import (
    RateLimitCheck,
    RateLimitedError,
    RateLimitRule,
)
from insumap.domain.identity.account_state import AccountStatus
from insumap.domain.identity.errors import InvitationInvalidError, PasswordPolicyError
from insumap.domain.identity.refresh_token import RevocationReason
from insumap.infrastructure.security.rate_limiter import InMemoryRateLimiter
from insumap.shared.i18n import MessageCatalog
from tests.support.identity_fakes import HASH_PREFIX
from tests.support.identity_world import (
    CLINIC,
    MINUTE,
    NEW_PASSWORD,
    PATIENT_USER,
    RULE,
    IdentityWorld,
)
from tests.support.notifications import InMemoryChannel

MESSAGES = MessageCatalog.load_spanish()
EMAIL = "paciente@example.test"
IP = "203.0.113.9"
BASE = "https://app.example.test"
HOUR = timedelta(hours=1)
IP_RULE = RateLimitRule(family="reset_ip", limit=5, window=HOUR)
EMAIL_RULE = RateLimitRule(family="reset_email", limit=3, window=HOUR)


class Mailroom:
    """The use cases of the slice over one world and one in-memory channel."""

    def __init__(self, *, verified: bool = True, counting: bool = False) -> None:
        self.world = IdentityWorld()
        self.mail = InMemoryChannel()
        account = self.world.users.accounts[PATIENT_USER]
        self.world.users.add(replace(account, email_verified=verified))
        policy = PasswordResetPolicy(
            ttl=30 * MINUTE,
            max_attempts=5,
            link_base_url=BASE,
            link_path="reset-password",
        )
        self.request = RequestPasswordResetUseCase(
            uow=self.world.uow,
            users=self.world.users,
            challenges=self.world.challenges,
            events=self.world.events,
            limiter=InMemoryRateLimiter(self.world.clock)
            if counting
            else self.world.limiter,
            ip_rule=IP_RULE,
            email_rule=EMAIL_RULE,
            policy=policy,
            channel=self.mail,
            messages=MESSAGES,
        )
        self.complete = CompletePasswordResetUseCase(
            uow=self.world.uow,
            challenges=self.world.challenges,
            users=self.world.users,
            passwords=self.world.passwords,
            refresh_tokens=self.world.refresh_tokens,
            events=self.world.events,
            rate_limit=RateLimitCheck(self.world.limiter, RULE),
            channel=self.mail,
            messages=MESSAGES,
            clock=self.world.clock,
        )
        self.issuer = EmailVerificationIssuer(
            challenges=self.world.challenges,
            policy=ChallengePolicy(ttl=timedelta(hours=24), max_attempts=5),
            channel=self.mail,
            messages=MESSAGES,
            link_base_url=BASE,
            link_path="verify-email",
        )
        self.confirm = ConfirmEmailVerificationUseCase(
            uow=self.world.uow,
            challenges=self.world.challenges,
            users=self.world.users,
            rate_limit=RateLimitCheck(self.world.limiter, RULE),
            clock=self.world.clock,
        )

    def ask(self, email: str = EMAIL) -> None:
        self.request.execute(RequestPasswordResetInput(email=email, client_ip=IP))

    def token(self) -> str:
        return self.mail.delivered[-1].token()

    def finish(self, token: str, password: str = NEW_PASSWORD) -> None:
        self.complete.execute(
            CompletePasswordResetInput(token=token, new_password=password, client_ip=IP)
        )


# Request.


def test_a_verified_active_account_receives_a_single_use_link_in_the_fragment() -> None:
    room = Mailroom()

    room.ask()

    [message] = room.mail.delivered
    assert message.recipient.user_id == PATIENT_USER
    assert message.recipient.address == EMAIL
    assert f"{BASE}/reset-password#token=" in message.body
    assert "30 minutos" in message.body
    assert "Datos simulados." in message.body
    assert [e.event_type for e in room.world.events.events] == [
        SecurityEventType.PASSWORD_RESET_REQUESTED
    ]


def test_the_email_is_normalized_before_the_lookup() -> None:
    room = Mailroom()

    room.ask("  Paciente@Example.TEST ")

    assert len(room.mail.delivered) == 1


@pytest.mark.parametrize(
    "case", ["unknown", "unverified", "suspended", "invited", "clinic_suspended"]
)
def test_every_other_account_ends_quietly_without_an_email(case: str) -> None:
    room = Mailroom(verified=case != "unverified")
    account = room.world.users.accounts[PATIENT_USER]
    email = EMAIL
    if case == "unknown":
        email = "nadie@example.test"
    if case == "suspended":
        room.world.users.add(replace(account, status=AccountStatus.SUSPENDED))
    if case == "invited":
        room.world.users.add(replace(account, status=AccountStatus.INVITED))
    if case == "clinic_suspended":
        room.world.users.add(replace(account, clinic=replace(CLINIC, is_active=False)))

    room.ask(email)

    assert room.mail.delivered == []
    assert room.world.events.events == []


def test_requests_over_the_ip_or_email_limit_are_ignored_without_an_error() -> None:
    room = Mailroom(counting=True)

    for _ in range(4):
        room.ask()

    assert len(room.mail.delivered) == 3

    other_ip = Mailroom(counting=True)
    for index in range(6):
        other_ip.request.execute(
            RequestPasswordResetInput(email=f"x{index}@example.test", client_ip=IP)
        )
    other_ip.ask()
    assert other_ip.mail.delivered == []


def test_the_email_limit_counts_a_digest_not_the_address() -> None:
    room = Mailroom()

    room.ask()

    subjects = [subject for _, subject in room.world.limiter.hits]
    assert EMAIL not in subjects
    assert IP in subjects


def test_a_failing_channel_does_not_fail_the_request() -> None:
    room = Mailroom()
    room.mail.fail = True

    room.ask()

    assert room.world.events.events


# Completion.


def test_the_link_sets_the_password_ends_every_session_and_tells_the_holder() -> None:
    room = Mailroom()
    session = room.world.sessions.open_full_session(
        room.world.users.accounts[PATIENT_USER]
    )
    assert session.session is not None
    room.ask()

    room.finish(room.token())

    account = room.world.users.accounts[PATIENT_USER]
    assert account.password_hash == f"{HASH_PREFIX}{NEW_PASSWORD}"
    assert account.token_version == 1
    assert all(
        t.revoked_reason is RevocationReason.PASSWORD_CHANGED
        for t in room.world.refresh_tokens.tokens.values()
    )
    assert SecurityEventType.PASSWORD_CHANGED in [
        e.event_type for e in room.world.events.events
    ]
    notice = room.mail.delivered[-1]
    assert "se restableció" in notice.body
    assert "http" not in notice.body


def test_a_link_works_once() -> None:
    room = Mailroom()
    room.ask()
    token = room.token()
    room.finish(token)

    with pytest.raises(InvitationInvalidError):
        room.finish(token, "yet another long passphrase")


def test_an_expired_or_unknown_link_is_the_single_error() -> None:
    room = Mailroom()
    room.ask()
    token = room.token()
    room.world.clock.advance(31 * MINUTE)

    with pytest.raises(InvitationInvalidError):
        room.finish(token)
    with pytest.raises(InvitationInvalidError):
        room.finish("no-such-token")


def test_a_weak_password_fails_with_422_and_keeps_the_link_usable() -> None:
    room = Mailroom()
    room.ask()
    token = room.token()

    with pytest.raises(PasswordPolicyError):
        room.finish(token, "short")
    room.finish(token)

    assert room.world.users.accounts[PATIENT_USER].token_version == 1


def test_an_account_that_stopped_being_active_cannot_finish() -> None:
    room = Mailroom()
    room.ask()
    token = room.token()
    account = room.world.users.accounts[PATIENT_USER]
    room.world.users.add(replace(account, status=AccountStatus.SUSPENDED))

    with pytest.raises(InvitationInvalidError):
        room.finish(token)


def test_completion_is_rate_limited_by_ip() -> None:
    room = Mailroom()
    room.world.limiter.blocked = True

    with pytest.raises(RateLimitedError):
        room.finish("anything")


def test_an_unverified_holder_gets_no_change_notice() -> None:
    room = Mailroom(verified=True)
    room.ask()
    token = room.token()
    account = room.world.users.accounts[PATIENT_USER]
    room.world.users.add(replace(account, email_verified=False))
    before = len(room.mail.delivered)

    room.finish(token)

    assert len(room.mail.delivered) == before


# Email verification.


def test_the_verification_link_marks_the_email_as_verified_once() -> None:
    room = Mailroom(verified=False)
    account = room.world.users.accounts[PATIENT_USER]
    pending = room.issuer.issue(account, EMAIL)
    pending.send()
    token = room.mail.delivered[0].token()
    assert "24 horas" in room.mail.delivered[0].body

    room.confirm.execute(ConfirmEmailVerificationInput(token=token, client_ip=IP))

    assert room.world.users.accounts[PATIENT_USER].email_verified is True
    with pytest.raises(InvitationInvalidError):
        room.confirm.execute(ConfirmEmailVerificationInput(token=token, client_ip=IP))


def test_a_reset_token_cannot_verify_an_email_and_the_other_way_round() -> None:
    room = Mailroom()
    room.ask()
    reset_token = room.token()
    account = room.world.users.accounts[PATIENT_USER]
    room.issuer.issue(account, EMAIL).send()
    verification_token = room.token()

    with pytest.raises(InvitationInvalidError):
        room.confirm.execute(
            ConfirmEmailVerificationInput(token=reset_token, client_ip=IP)
        )
    with pytest.raises(InvitationInvalidError):
        room.finish(verification_token)


def test_verification_is_rate_limited_and_rejects_unknown_tokens() -> None:
    room = Mailroom()

    with pytest.raises(InvitationInvalidError):
        room.confirm.execute(ConfirmEmailVerificationInput(token="nope", client_ip=IP))
    room.world.limiter.blocked = True
    with pytest.raises(RateLimitedError):
        room.confirm.execute(ConfirmEmailVerificationInput(token="nope", client_ip=IP))


def test_the_verification_link_belongs_to_the_account_that_asked() -> None:
    room = Mailroom(verified=False)
    account = room.world.users.accounts[PATIENT_USER]

    room.issuer.issue(account, EMAIL)

    [challenge] = room.world.challenge_repo.challenges.values()
    assert challenge.user_id == PATIENT_USER
    assert challenge.user_id != UUID(int=0)
