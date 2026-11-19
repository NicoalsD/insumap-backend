"""Email verification: the emailed link, and its confirmation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, final

from insumap.application.common.unit_of_work import TransactionContext, UnitOfWorkPort
from insumap.application.identity.challenges import ChallengePolicy, ChallengeService
from insumap.application.identity.ports import UserRepositoryPort
from insumap.application.notifications.account_notifications import (
    EmailVerificationNotification,
)
from insumap.application.notifications.notification import (
    NotificationChannel,
    PendingNotification,
    Recipient,
)
from insumap.application.security.rate_limit import RateLimitCheck
from insumap.domain.identity.auth_challenge import ChallengePurpose
from insumap.domain.identity.errors import InvitationInvalidError
from insumap.domain.identity.user import UserAccount
from insumap.shared.i18n import MessageCatalog
from insumap.shared.time import Clock

TOKEN_FRAGMENT: Final = "#token="  # noqa: S105 - URL fragment key, not a secret
SECONDS_PER_HOUR: Final = 3600


def link_with_token(base_url: str, path: str, token: str) -> str:
    """``<base>/<path>#token=<token>``: the token stays in the fragment.

    A fragment is never sent to a server, so the token does not reach access
    logs or the ``Referer`` header.
    """
    return f"{base_url.rstrip('/')}/{path.strip('/')}{TOKEN_FRAGMENT}{token}"


@final
class EmailVerificationIssuer:
    """Stores a verification challenge and prepares the email that carries it.

    It runs inside the transaction of the use case; the email leaves only after
    the commit, through ``PendingNotification.send``.
    """

    def __init__(
        self,
        *,
        challenges: ChallengeService,
        policy: ChallengePolicy,
        channel: NotificationChannel,
        messages: MessageCatalog,
        link_base_url: str,
        link_path: str,
    ) -> None:
        self._challenges = challenges
        self._policy = policy
        self._channel = channel
        self._messages = messages
        self._link_base_url = link_base_url
        self._link_path = link_path

    def issue(self, account: UserAccount, address: str) -> PendingNotification:
        """Store the challenge and return the email to send after the commit."""
        token = self._challenges.issue(
            purpose=ChallengePurpose.EMAIL_VERIFICATION,
            policy=self._policy,
            user_id=account.user_id,
            clinic_id=account.clinic_id,
        )
        hours = int(self._policy.ttl.total_seconds() // SECONDS_PER_HOUR)
        return PendingNotification(
            notification=EmailVerificationNotification(
                self._channel,
                self._messages,
                link=link_with_token(self._link_base_url, self._link_path, token),
                hours=hours,
            ),
            recipient=Recipient(user_id=account.user_id, address=address),
            is_demo=account.clinic is not None and account.clinic.is_demo,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ConfirmEmailVerificationInput:
    """The token of the emailed link."""

    token: str
    client_ip: str


@final
class ConfirmEmailVerificationUseCase:
    """Marks the email as verified; every failure is the same ``410``."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        challenges: ChallengeService,
        users: UserRepositoryPort,
        rate_limit: RateLimitCheck,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._challenges = challenges
        self._users = users
        self._rate_limit = rate_limit
        self._clock = clock

    def execute(self, input: ConfirmEmailVerificationInput) -> None:
        """Consume the token and verify the email of its account."""
        self._rate_limit.ensure(input.client_ip)
        now = self._clock.now()
        with self._uow.begin(TransactionContext.anonymous()) as uow:
            challenge = self._challenges.find_usable(
                input.token, purpose=ChallengePurpose.EMAIL_VERIFICATION
            )
            if challenge is None:
                raise InvitationInvalidError
            uow.apply_context(
                TransactionContext(
                    user_id=challenge.user_id, clinic_id=challenge.clinic_id
                )
            )
            account = self._users.get(challenge.user_id)
            if account is None or account.email_normalized is None:
                raise InvitationInvalidError
            self._users.save(account.with_verified_email())
            self._challenges.save(challenge.consumed(now=now))
            uow.commit()
