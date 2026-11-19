"""``POST /assistant/messages``: the educational assistant of the patient (IA6).

The patient's own turn is written first, in the patient's transaction, so the
question survives even if the service fails. The approved material is searched
only when the ``ai_external_processing`` consent allows the call; without it the
reply is the predefined text and no data leaves the backend (API.md 8.10).
"""

from __future__ import annotations

import re
from typing import Final, final
from uuid import UUID

from insumap.application.ai.assessments import (
    ApprovedFragment,
    AssistantPort,
    AssistantRequest,
    AssistantResult,
    AssistantTurn,
)
from insumap.application.ai.records import (
    ApprovedKnowledgePort,
    AssistantConversationPort,
)
from insumap.application.common.actor import Actor
from insumap.application.common.ids import IdGenerator
from insumap.application.common.unit_of_work import TransactionContext, UnitOfWorkPort
from insumap.application.consents.ports import ConsentHistoryPort
from insumap.application.monitoring.gate import OwnPatientGate
from insumap.domain.identity.consent import ConsentAction, ConsentScope
from insumap.domain.identity.permissions import PermissionCode
from insumap.shared.field_limits import FieldLimits
from insumap.shared.time import Clock

KEYWORDS_MAX: Final = 5
KEYWORD_MIN_LENGTH: Final = 4
STOPWORDS: Final[frozenset[str]] = frozenset(
    {
        "para",
        "como",
        "que",
        "esto",
        "esta",
        "estoy",
        "tengo",
        "tener",
        "pero",
        "sobre",
        "cuando",
        "donde",
        "porque",
        "algo",
        "mucho",
        "mis",
        "por",
        "una",
        "unos",
        "unas",
        "del",
        "las",
        "los",
        "hay",
        "son",
        "ser",
        "debo",
        "puedo",
    }
)
WORD: Final = re.compile(r"[a-záéíóúñü]+")
CONTEXT_CHARS: Final = FieldLimits.AI_CONTEXT_DOC_CHARS_MAX


@final
class SendAssistantMessageUseCase:
    """The patient asks; the reply comes from the service, the material or the text."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        own_gate: OwnPatientGate,
        consents: ConsentHistoryPort,
        conversations: AssistantConversationPort,
        knowledge: ApprovedKnowledgePort,
        assistant: AssistantPort,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._own = own_gate
        self._consents = consents
        self._conversations = conversations
        self._knowledge = knowledge
        self._assistant = assistant
        self._ids = ids
        self._clock = clock

    def execute(
        self,
        actor: Actor,
        *,
        message: str,
        conversation_id: UUID | None,
    ) -> AssistantResult:
        """The reply to one message; the patient's turn is committed before the call."""
        request = self._prepare(actor, message, conversation_id)
        return self._assistant.reply(request)

    def _prepare(
        self, actor: Actor, message: str, conversation_id: UUID | None
    ) -> AssistantRequest:
        with self._uow.begin(TransactionContext.for_actor(actor)) as unit:
            scope = self._own.enter(actor, PermissionCode.ASSISTANT_USE)
            latest = self._consents.latest_per_scope(scope.patient_id).get(
                ConsentScope.AI_EXTERNAL_PROCESSING
            )
            consent_id = (
                latest.consent_id
                if latest is not None and latest.action is ConsentAction.ACCEPTED
                else None
            )
            conversation = conversation_id or self._ids.new_id()
            history: tuple[AssistantTurn, ...] = ()
            fragments: tuple[ApprovedFragment, ...] = ()
            if consent_id is not None:
                history = self._conversations.history(
                    scope.patient_id,
                    conversation,
                    limit=FieldLimits.AI_ASSISTANT_HISTORY_TURNS_MAX,
                )
                fragments = self._knowledge.search(
                    _keywords(message),
                    limit=FieldLimits.AI_CONTEXT_DOCS_MAX,
                    max_chars=CONTEXT_CHARS,
                )
            self._conversations.add_patient_message(
                clinic_id=scope.clinic_id,
                patient_id=scope.patient_id,
                conversation_id=conversation,
                content=message,
                sent_at=self._clock.now(),
            )
            unit.commit()  # the question is kept even if the service fails
        return AssistantRequest(
            clinic_id=scope.clinic_id,
            patient_id=scope.patient_id,
            conversation_id=conversation,
            message=message,
            history=history,
            fragments=fragments,
            external_consent_id=consent_id,
        )


def _keywords(message: str) -> tuple[str, ...]:
    """The distinct words that may match the material, in order of appearance."""
    seen: list[str] = []
    for word in WORD.findall(message.lower()):
        if len(word) < KEYWORD_MIN_LENGTH or word in STOPWORDS or word in seen:
            continue
        seen.append(word)
        if len(seen) == KEYWORDS_MAX:
            break
    return tuple(seen)
