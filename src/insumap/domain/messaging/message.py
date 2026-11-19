"""Messages between a patient and the care team of the patient (RF-84, RF-85).

One thread per patient. Messages are append-only: nothing edits or deletes one,
and a correction is a new message. The body is plain text, normalized and
bounded like every free text. The thread shows a permanent notice that it is
not an emergency channel; that notice is text, so it lives in ``messages_es``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final, Self
from uuid import UUID

from insumap.domain.common.text import clean_text
from insumap.shared.field_limits import FieldLimits

BODY_FIELD: Final = "body.body"


class SenderRole(StrEnum):
    """Who wrote a message: the patient or a doctor of the care team."""

    PATIENT = "PATIENT"
    DOCTOR = "DOCTOR"


@dataclass(frozen=True, slots=True, kw_only=True)
class MessageBody:
    """The text of a message: trimmed, NFKC and between 1 and the maximum length."""

    text: str

    @classmethod
    def parse(cls, raw: str) -> Self:
        """Normalize ``raw``; a blank or too long text is a ``422``."""
        return cls(
            text=clean_text(
                raw, field=BODY_FIELD, max_length=FieldLimits.MESSAGE_BODY_MAX_LENGTH
            )
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ThreadMessage:
    """One message of a thread, as stored (``messaging.messages``)."""

    message_id: UUID
    clinic_id: UUID
    thread_id: UUID
    sender_user_id: UUID
    sender_role: SenderRole
    body: str
    sent_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class MessageThread:
    """The conversation of one patient with its care team (``messaging.threads``)."""

    thread_id: UUID
    clinic_id: UUID
    patient_id: UUID
    last_message_at: datetime | None = None

    def post(
        self,
        *,
        message_id: UUID,
        sender_user_id: UUID,
        sender_role: SenderRole,
        body: MessageBody,
        at: datetime,
    ) -> ThreadMessage:
        """A new message of ``sender_user_id`` in this thread, sent at ``at``."""
        return ThreadMessage(
            message_id=message_id,
            clinic_id=self.clinic_id,
            thread_id=self.thread_id,
            sender_user_id=sender_user_id,
            sender_role=sender_role,
            body=body.text,
            sent_at=at,
        )
