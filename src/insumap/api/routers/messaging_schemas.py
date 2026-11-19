"""Bodies of the messaging and follow-up endpoints (API.md 8.12)."""

from __future__ import annotations

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field

from insumap.api.routers.common import StrictRequest
from insumap.application.messaging.send_message import SentMessage
from insumap.domain.follow_ups.follow_up import (
    FollowUp,
    FollowUpOutcome,
    FollowUpStatus,
)
from insumap.domain.messaging.message import SenderRole, ThreadMessage
from insumap.shared.field_limits import FieldLimits

RESULT_NOTE_FIELD = Field(
    min_length=FieldLimits.REASON_MIN_LENGTH,
    max_length=FieldLimits.REASON_MAX_LENGTH,
    description="Resultado del control, en texto plano (queda en la auditoría).",
)


class SendMessageRequest(StrictRequest):
    """The text of the message; the patient id is only for doctors."""

    body: str = Field(
        min_length=1,
        max_length=FieldLimits.MESSAGE_BODY_MAX_LENGTH,
        description="Texto plano del mensaje. No es un canal de emergencias.",
    )
    patient_id: UUID | None = Field(
        default=None,
        description="Solo el médico: paciente asignado. El paciente no lo envía.",
    )


class MessageResponse(BaseModel):
    """One message of a thread."""

    id: UUID
    sender_role: SenderRole
    body: str
    sent_at: datetime
    simulated: bool

    @classmethod
    def of(cls, message: ThreadMessage, *, simulated: bool) -> Self:
        return cls(
            id=message.message_id,
            sender_role=message.sender_role,
            body=message.body,
            sent_at=message.sent_at,
            simulated=simulated,
        )


class SentMessageResponse(MessageResponse):
    """The stored message of a send, with the alarm words its text carries."""

    alarm_keywords_detected: list[str] = Field(
        description=(
            "Palabras de alarma halladas en el texto, sin el texto. Vacía si no hay "
            "ninguna; con palabras, la app sugiere llamar a urgencias."
        )
    )

    @classmethod
    def of_sent(cls, sent: SentMessage, *, simulated: bool) -> Self:
        message = sent.message
        return cls(
            id=message.message_id,
            sender_role=message.sender_role,
            body=message.body,
            sent_at=message.sent_at,
            simulated=simulated,
            alarm_keywords_detected=list(sent.alarm_keywords),
        )


class MessageListResponse(BaseModel):
    """A page of messages, newest first, with the notice of the thread."""

    items: list[MessageResponse]
    next_cursor: str | None = Field(
        description="Cursor de la página siguiente; `null` en la última."
    )
    emergency_notice: str = Field(
        description="Aviso permanente: el hilo no es un canal de emergencias."
    )


class CreateFollowUpRequest(StrictRequest):
    """A control of an assigned patient, in a future date with its zone."""

    patient_id: UUID
    scheduled_at: AwareDatetime = Field(
        description="Fecha futura del control, con zona horaria."
    )


class CloseFollowUpRequest(StrictRequest):
    """How the control ended and what the team recorded."""

    outcome: FollowUpOutcome = Field(
        description="`DONE` si se atendió; `MISSED` si no asistió."
    )
    result_note: str = RESULT_NOTE_FIELD


class FollowUpResponse(BaseModel):
    """A control with its status and, once closed, its result."""

    id: UUID
    patient_id: UUID
    status: FollowUpStatus
    scheduled_at: datetime
    result_note: str | None
    closed_at: datetime | None
    simulated: bool

    @classmethod
    def of(cls, follow_up: FollowUp, *, simulated: bool) -> Self:
        return cls(
            id=follow_up.follow_up_id,
            patient_id=follow_up.patient_id,
            status=follow_up.status,
            scheduled_at=follow_up.scheduled_for,
            result_note=follow_up.result_note,
            closed_at=follow_up.closed_at,
            simulated=simulated,
        )
