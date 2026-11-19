"""Ports of the messaging: threads, messages and read marks (row level security)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from insumap.application.common.pagination import Page, PageRequest
from insumap.domain.messaging.message import MessageThread, ThreadMessage


class MessageThreadRepositoryPort(ABC):
    """The thread of a patient: one per patient (``messaging.threads``)."""

    @abstractmethod
    def find_by_patient(self, patient_id: UUID) -> MessageThread | None:
        """The thread of the patient, or ``None`` if nobody wrote yet."""

    @abstractmethod
    def ensure(
        self, *, thread_id: UUID, clinic_id: UUID, patient_id: UUID
    ) -> MessageThread:
        """The thread of the patient, created with ``thread_id`` when missing."""

    @abstractmethod
    def touch(self, thread_id: UUID, *, at: datetime) -> None:
        """Record ``at`` as the time of the last message of the thread."""


class ThreadMessageRepositoryPort(ABC):
    """The messages of a thread; append-only (``messaging.messages``)."""

    @abstractmethod
    def append(self, message: ThreadMessage) -> None:
        """Insert the message in the current transaction; nothing is updated."""

    @abstractmethod
    def list_for_thread(
        self, thread_id: UUID, page: PageRequest
    ) -> Page[ThreadMessage]:
        """A page of messages, newest first; the cursor points at the last one seen."""


class ThreadReadRepositoryPort(ABC):
    """The last read time of each participant (``messaging.thread_reads``)."""

    @abstractmethod
    def mark_read(
        self, *, thread_id: UUID, user_id: UUID, clinic_id: UUID, at: datetime
    ) -> None:
        """Set the reader's last read time to ``at``, creating the mark if needed."""
