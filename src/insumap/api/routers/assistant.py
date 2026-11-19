"""``POST /assistant/messages``: the educational assistant of the patient (API.md
8.10, IA6).

The patient's own token gives the patient (never the body). The use case enforces the
permission, the rate limits and the sensitive-data consent (C3); the reply carries
the escalation level so the app can show the emergency notice.
"""

from http import HTTPStatus
from typing import Annotated, Any, Final, final
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from insumap.api.paths import API_V1_PREFIX
from insumap.api.routers.common import (
    ACCESS_EXTENSION,
    StrictRequest,
    access,
    error_responses,
)
from insumap.api.tags import ApiTag
from insumap.application.ai.assessments import AssistantResult
from insumap.application.ai.assistant import SendAssistantMessageUseCase
from insumap.application.common.actor import Actor
from insumap.domain.identity.permissions import PermissionCode
from insumap.shared.field_limits import FieldLimits

ASSISTANT_PATH: Final = "/assistant/messages"
ERRORS: Final = error_responses(
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
    HTTPStatus.UNPROCESSABLE_ENTITY,
)


class AssistantMessageRequest(StrictRequest):
    """The patient's question. It never carries the patient id."""

    message: str = Field(
        min_length=1,
        max_length=FieldLimits.AI_ASSISTANT_MESSAGE_MAX_LENGTH,
        description="Pregunta del paciente, en texto plano.",
    )
    conversation_id: UUID | None = Field(
        default=None,
        description="Conversación en curso. Sin valor se abre una conversación nueva.",
    )


class EscalationResponse(BaseModel):
    """Whether the patient should contact the team or go to emergency care."""

    level: str
    message: str | None


class AssistantReplyResponse(BaseModel):
    """The reply in plain text, with the material it uses and the escalation."""

    conversation_id: UUID
    reply_text: str
    citations: list[UUID]
    escalation: EscalationResponse
    guardrails_triggered: list[str]
    model_version: str | None
    is_fallback: bool
    fallback_reason: str | None

    @classmethod
    def of(cls, result: AssistantResult) -> "AssistantReplyResponse":
        return cls(
            conversation_id=result.conversation_id,
            reply_text=result.reply_text,
            citations=list(result.citations),
            escalation=EscalationResponse(
                level=result.escalation.value, message=result.escalation_message
            ),
            guardrails_triggered=list(result.guardrails_triggered),
            model_version=result.model_version,
            is_fallback=result.is_fallback,
            fallback_reason=None
            if result.fallback_reason is None
            else result.fallback_reason.value,
        )


@final
class AssistantRouter:
    """Builds the assistant route over its use case (API.md 8.10, IA6)."""

    def __init__(
        self, *, send: SendAssistantMessageUseCase, session_actor: Any
    ) -> None:
        self._send = send
        self._session_actor = session_actor
        self.router = APIRouter(prefix=API_V1_PREFIX, tags=[ApiTag.AI])
        self._add_routes()

    def _add_routes(self) -> None:
        session = Depends(self._session_actor)

        def send_assistant_message(
            body: AssistantMessageRequest,
            actor: Annotated[Actor, session],
        ) -> AssistantReplyResponse:
            result = self._send.execute(
                actor,
                message=body.message,
                conversation_id=body.conversation_id,
            )
            return AssistantReplyResponse.of(result)

        self.router.add_api_route(
            ASSISTANT_PATH,
            send_assistant_message,
            methods=["POST"],
            operation_id="send_assistant_message",
            summary="Preguntar al asistente educativo",
            description=(
                "Respuesta educativa con material aprobado por la clínica. No da dosis "
                "ni diagnósticos. Ante síntomas de alarma indica acudir a urgencias. "
                "Solo se usa la IA con el consentimiento de procesamiento externo."
            ),
            responses=ERRORS,
            openapi_extra={ACCESS_EXTENSION: access(PermissionCode.ASSISTANT_USE)},
        )
