"""``GET /messages``: the thread of a patient, newest first, and the read mark."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, final
from uuid import UUID

from insumap.application.access.ports import DataResource
from insumap.application.common.actor import Actor
from insumap.application.common.pagination import Page, PageRequest
from insumap.application.common.patient_scope import PatientScope
from insumap.application.common.unit_of_work import TransactionContext, UnitOfWorkPort
from insumap.application.messaging.ports import (
    MessageThreadRepositoryPort,
    ThreadMessageRepositoryPort,
    ThreadReadRepositoryPort,
)
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.messaging.message import ThreadMessage
from insumap.shared.i18n import MessageCatalog
from insumap.shared.time import Clock

EMERGENCY_NOTICE_KEY: Final = "messaging.emergency_notice"


@dataclass(frozen=True, slots=True, kw_only=True)
class ListMessagesInput:
    """The caller, the patient (doctors only) and the page asked for."""

    actor: Actor
    patient_id: UUID | None
    page: PageRequest


@dataclass(frozen=True, slots=True, kw_only=True)
class MessageListing:
    """A page of the thread and the notice that it is not an emergency channel."""

    page: Page[ThreadMessage]
    emergency_notice: str


@final
class ListMessagesUseCase:
    """Reads a thread; the doctor's read is audited and marks the thread as read.

    A patient who is not assigned to the doctor, or another clinic's patient,
    gets ``404``. A thread that nobody wrote in is an empty page.
    """

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        scope: PatientScope,
        threads: MessageThreadRepositoryPort,
        messages: ThreadMessageRepositoryPort,
        read_marks: ThreadReadRepositoryPort,
        clock: Clock,
        catalog: MessageCatalog,
    ) -> None:
        self._uow = uow
        self._scope = scope
        self._threads = threads
        self._messages = messages
        self._read_marks = read_marks
        self._clock = clock
        self._catalog = catalog

    def execute(self, input: ListMessagesInput) -> MessageListing:
        """The page of messages; the read is committed so its audit row stays."""
        actor = input.actor
        with self._uow.begin(TransactionContext.for_actor(actor)) as unit:
            patient_id = self._scope.enter(
                actor,
                input.patient_id,
                staff_permission=PermissionCode.MESSAGES_USE_ASSIGNED,
                own_permission=PermissionCode.MESSAGES_USE_OWN,
                resource=DataResource.MESSAGES,
            )
            thread = self._threads.find_by_patient(patient_id)
            if thread is None:
                page: Page[ThreadMessage] = Page(items=(), next_cursor=None)
            else:
                page = self._messages.list_for_thread(thread.thread_id, input.page)
                self._read_marks.mark_read(
                    thread_id=thread.thread_id,
                    user_id=actor.user_id,
                    clinic_id=thread.clinic_id,
                    at=self._clock.now(),
                )
            unit.commit()
        return MessageListing(
            page=page, emergency_notice=self._catalog.render(EMERGENCY_NOTICE_KEY)
        )
