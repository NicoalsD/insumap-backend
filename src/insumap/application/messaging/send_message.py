"""``POST /messages``: append a message to the thread and tell the other side (P07).

The sender is the session user with its own role: the request cannot name the
sender. The message is stored in one transaction; the notification to the other
side is sent after the commit, so nothing leaves the system for a message that
did not persist (P17).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import final
from uuid import UUID

from insumap.application.access.ports import DataResource, PatientDirectoryPort
from insumap.application.care_team.ports import CareTeamRepositoryPort
from insumap.application.common.actor import Actor
from insumap.application.common.ids import IdGenerator
from insumap.application.common.patient_scope import PatientScope
from insumap.application.common.unit_of_work import TransactionContext, UnitOfWorkPort
from insumap.application.messaging.message_notifications import (
    MessageReceivedNotification,
)
from insumap.application.messaging.ports import (
    MessageThreadRepositoryPort,
    ThreadMessageRepositoryPort,
    ThreadReadRepositoryPort,
)
from insumap.application.notifications.notification import (
    NotificationChannel,
    PendingNotification,
    Recipient,
)
from insumap.application.security.rate_limit import RateLimitCheck
from insumap.domain.identity.errors import PermissionDeniedError
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role
from insumap.domain.messaging.events import MessageSent
from insumap.domain.messaging.message import MessageBody, SenderRole, ThreadMessage
from insumap.shared.i18n import MessageCatalog
from insumap.shared.time import Clock


@dataclass(frozen=True, slots=True, kw_only=True)
class SendMessageInput:
    """The caller, the patient (doctors only) and the text of the message."""

    actor: Actor
    patient_id: UUID | None
    body: str


@final
class SendMessageUseCase:
    """Appends a message of the session user to the thread of a patient.

    Pattern: P07 Bridge (notification to the other side), P17 Observer (event)
    """

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        scope: PatientScope,
        threads: MessageThreadRepositoryPort,
        messages: ThreadMessageRepositoryPort,
        read_marks: ThreadReadRepositoryPort,
        care_teams: CareTeamRepositoryPort,
        patients: PatientDirectoryPort,
        ids: IdGenerator,
        clock: Clock,
        in_app: NotificationChannel,
        catalog: MessageCatalog,
        rate_limit: RateLimitCheck,
    ) -> None:
        self._uow = uow
        self._scope = scope
        self._threads = threads
        self._messages = messages
        self._read_marks = read_marks
        self._care_teams = care_teams
        self._patients = patients
        self._ids = ids
        self._clock = clock
        self._in_app = in_app
        self._catalog = catalog
        self._rate_limit = rate_limit

    def execute(self, input: SendMessageInput) -> ThreadMessage:
        """Store the message, then notify the other side once it is committed."""
        actor = input.actor
        if actor.clinic_id is None:
            raise PermissionDeniedError
        # Counted per user before any write: the answer is a 429 with Retry-After.
        self._rate_limit.ensure(str(actor.user_id))
        # Validated before any write: a rejected text leaves no thread behind.
        body = MessageBody.parse(input.body)
        with self._uow.begin(TransactionContext.for_actor(actor)) as unit:
            patient_id = self._scope.enter(
                actor,
                input.patient_id,
                staff_permission=PermissionCode.MESSAGES_USE_ASSIGNED,
                own_permission=PermissionCode.MESSAGES_USE_OWN,
                resource=DataResource.MESSAGES,
            )
            at = self._clock.now()
            thread = self._threads.ensure(
                thread_id=self._ids.new_id(),
                clinic_id=actor.clinic_id,
                patient_id=patient_id,
            )
            message = thread.post(
                message_id=self._ids.new_id(),
                sender_user_id=actor.user_id,
                sender_role=_sender_role(actor),
                body=body,
                at=at,
            )
            self._messages.append(message)
            self._threads.touch(thread.thread_id, at=at)
            self._read_marks.mark_read(
                thread_id=thread.thread_id,
                user_id=actor.user_id,
                clinic_id=actor.clinic_id,
                at=at,
            )
            unit.collect(
                [
                    MessageSent(
                        event_id=self._ids.new_id(),
                        occurred_at=at,
                        message_id=message.message_id,
                        thread_id=thread.thread_id,
                        clinic_id=actor.clinic_id,
                        sender_role=message.sender_role,
                    )
                ]
            )
            unit.commit()
        for recipient in self._recipients(actor, patient_id, actor.clinic_id):
            PendingNotification(
                notification=MessageReceivedNotification(
                    self._in_app, self._catalog, thread_id=thread.thread_id
                ),
                recipient=recipient,
                is_demo=actor.clinic_is_demo,
            ).send()
        return message

    def _recipients(
        self, actor: Actor, patient_id: UUID, clinic_id: UUID
    ) -> list[Recipient]:
        """The other side: the open doctors for a patient, the patient for a doctor.

        Read in the SYSTEM context after the commit: a patient may not read the
        assignments under row level security, and the lookup is not the caller's.
        """
        with self._uow.begin(TransactionContext.for_system(clinic_id)) as unit:
            if actor.role is Role.PATIENT:
                team = self._care_teams.open_team(patient_id)
                recipients = [
                    Recipient(user_id=assignment.doctor_user_id, clinic_id=clinic_id)
                    for assignment in team.open_assignments
                ]
            else:
                # The message is already committed: a missing account means no one
                # to notify, never an error for the caller.
                patient = self._patients.find(patient_id)
                recipients = (
                    []
                    if patient is None or patient.user_id is None
                    else [Recipient(user_id=patient.user_id, clinic_id=clinic_id)]
                )
            unit.commit()
        return recipients


def _sender_role(actor: Actor) -> SenderRole:
    """The role the message is written with: the session role, never a request field."""
    if actor.role is Role.DOCTOR:
        return SenderRole.DOCTOR
    if actor.role is Role.PATIENT:
        return SenderRole.PATIENT
    raise PermissionDeniedError
