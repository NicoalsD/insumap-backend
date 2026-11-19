"""Use cases that issue patient codes: one patient, or a batch of up to 100.

Both check the permission and the clinic's rate limits before any command runs
(API.md section 5). A batch counts each patient against the issue limit before
the first code is created, so a limit hit never leaves a half issued batch whose
printed codes would be lost with the response. Each patient is then issued by
its own command, in its own transaction and audit row; a patient that cannot be
issued is reported in its item and the rest go on.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import final
from uuid import UUID

from insumap.application.commands.base import CommandBus
from insumap.application.common.actor import Actor
from insumap.application.credentials.commands import (
    IssueCredentialsCommand,
    IssuedCredential,
)
from insumap.application.security.rate_limit import RateLimitCheck
from insumap.application.users.access import clinic_of
from insumap.domain.identity.invitation import InvitationChannel
from insumap.domain.identity.permissions import PermissionCode
from insumap.shared.errors import ErrorCode, InsumapError


@dataclass(frozen=True, slots=True, kw_only=True)
class IssueCredentialInput:
    """One patient, the channel and the caller."""

    actor: Actor
    patient_id: UUID
    channel: InvitationChannel


@dataclass(frozen=True, slots=True, kw_only=True)
class IssueCredentialsBatchInput:
    """Several patients, one channel and the caller."""

    actor: Actor
    patient_ids: tuple[UUID, ...]
    channel: InvitationChannel


@dataclass(frozen=True, slots=True, kw_only=True)
class BatchItemResult:
    """The outcome for one patient of a batch.

    ``issued`` is set when the code was created; otherwise ``error_code`` says why.
    """

    patient_id: UUID
    issued: IssuedCredential | None
    error_code: ErrorCode | None


@final
class IssueCredentialUseCase:
    """Issues or re-issues the code of one imported patient.

    Backs ``POST /patients/{patient_id}/credential-invitations``.
    """

    def __init__(self, *, commands: CommandBus, issue_limit: RateLimitCheck) -> None:
        self._commands = commands
        self._issue_limit = issue_limit

    def execute(self, input: IssueCredentialInput) -> IssuedCredential:
        """Return the new invitation, with the code only for ``PRINT``."""
        input.actor.require(PermissionCode.CREDENTIALS_ISSUE)
        self._issue_limit.ensure(_clinic_subject(input.actor))
        return self._commands.dispatch(
            IssueCredentialsCommand(
                actor=input.actor,
                patient_id=input.patient_id,
                channel=input.channel,
            )
        )


@final
class IssueCredentialsBatchUseCase:
    """Issues codes for several patients, reporting each outcome.

    Backs ``POST /credential-invitations/batch``.
    """

    def __init__(
        self,
        *,
        commands: CommandBus,
        issue_limit: RateLimitCheck,
        batch_limit: RateLimitCheck,
    ) -> None:
        self._commands = commands
        self._issue_limit = issue_limit
        self._batch_limit = batch_limit

    def execute(self, input: IssueCredentialsBatchInput) -> list[BatchItemResult]:
        """One result per patient, in the order sent."""
        input.actor.require(PermissionCode.CREDENTIALS_ISSUE)
        subject = _clinic_subject(input.actor)
        self._batch_limit.ensure(subject)
        for _ in input.patient_ids:
            self._issue_limit.ensure(subject)
        return [
            self._issue_one(input.actor, pid, input.channel)
            for pid in input.patient_ids
        ]

    def _issue_one(
        self, actor: Actor, patient_id: UUID, channel: InvitationChannel
    ) -> BatchItemResult:
        try:
            issued = self._commands.dispatch(
                IssueCredentialsCommand(
                    actor=actor, patient_id=patient_id, channel=channel
                )
            )
        except InsumapError as error:
            return BatchItemResult(
                patient_id=patient_id, issued=None, error_code=error.code
            )
        return BatchItemResult(patient_id=patient_id, issued=issued, error_code=None)


def _clinic_subject(actor: Actor) -> str:
    """Rate limit subject: the clinic of the token, never a value from the request."""
    return f"clinic:{clinic_of(actor)}"
