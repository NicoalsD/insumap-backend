"""The educational assistant over the real app (API.md 8.10, IA6)."""

from typing import Any
from uuid import UUID

import pytest

from insumap.application.ai.assessments import (
    AiExplanation,
    ApprovedFragment,
    EscalationLevel,
)
from insumap.application.ai.ports import AssistantCall, RemoteAssistant
from insumap.domain.identity.consent import ConsentAction, ConsentRecord, ConsentScope
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role
from tests.api.identity_support import IdentityApi
from tests.support.identity_world import (
    CLINIC,
    NOTICE_ID,
    NOW,
    PASSWORD,
    PATIENT_ID,
    PATIENT_USER,
)

PATIENT_EMAIL = "paciente@example.test"
DOCTOR = UUID(int=920)
URL = "/api/v1/assistant/messages"
CONVERSATION = UUID(int=600)
DOC = ApprovedFragment(
    doc_id=UUID(int=501),
    title="Qué es la hipoglucemia",
    text="La hipoglucemia es una glucosa baja. Mide tu glucosa y avisa a tu equipo.",
)


def consent(
    scope: ConsentScope, number: int, action: ConsentAction = ConsentAction.ACCEPTED
) -> ConsentRecord:
    return ConsentRecord(
        consent_id=UUID(int=number),
        clinic_id=CLINIC.clinic_id,
        patient_id=PATIENT_ID,
        privacy_notice_version_id=NOTICE_ID,
        scope=scope,
        action=action,
        occurred_at=NOW,
        recorded_by=PATIENT_USER,
    )


@pytest.fixture
def api() -> IdentityApi:
    harness = IdentityApi()
    harness.world.permissions.by_role[Role.PATIENT] = frozenset(
        {PermissionCode.ASSISTANT_USE}
    )
    harness.world.consents.add([consent(ConsentScope.SENSITIVE_DATA_PROCESSING, 921)])
    harness.ai.knowledge.fragments.append(DOC)
    return harness


def patient(api: IdentityApi) -> dict[str, str]:
    login = api.client.post(
        "/api/v1/auth/login", json={"email": PATIENT_EMAIL, "password": PASSWORD}
    )
    return api.bearer(login.json()["access_token"])


def with_external_consent(
    api: IdentityApi, action: ConsentAction = ConsentAction.ACCEPTED
) -> None:
    api.world.consents.add([consent(ConsentScope.AI_EXTERNAL_PROCESSING, 922, action)])


def ask(
    api: IdentityApi, message: str = "¿Qué hago si tengo temblor y sudor?", **extra: Any
) -> Any:
    return api.client.post(
        URL, json={"message": message, **extra}, headers=patient(api)
    )


def test_without_the_external_consent_the_predefined_reply_is_given_and_no_data_leaves(
    api: IdentityApi,
) -> None:
    response = ask(api)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_fallback"] is True
    assert body["fallback_reason"] == "CIRCUIT_OPEN"
    assert body["escalation"]["level"] == "NONE"
    assert "emergencias" in body["reply_text"]
    assert api.ai.service.calls == []


def test_with_the_external_consent_the_service_reply_is_returned_with_its_citations(
    api: IdentityApi,
) -> None:
    with_external_consent(api)
    api.ai.service.reply = RemoteAssistant(
        model_name="assistant-llm",
        model_version="0.1.0+prompt-v2",
        input_hash="c" * 64,
        generated_at=NOW,
        is_fallback=False,
        fallback_reason=None,
        reply_text="Esos síntomas pueden indicar una glucosa baja.",
        citations=(str(DOC.doc_id),),
        escalation=EscalationLevel.CONTACT_DOCTOR,
        escalation_message="Avisaremos a tu equipo de atención.",
        guardrails_triggered=(),
        explanation=AiExplanation(summary="Material aprobado."),
    )

    response = ask(api, "¿Qué es la hipoglucemia?")

    body = response.json()
    assert response.status_code == 200
    assert body["is_fallback"] is False
    assert body["citations"] == [str(DOC.doc_id)]
    assert body["escalation"] == {
        "level": "CONTACT_DOCTOR",
        "message": "Avisaremos a tu equipo de atención.",
    }
    (call,) = api.ai.service.calls
    assert isinstance(call, AssistantCall)
    assert [fragment.doc_id for fragment in call.fragments] == [DOC.doc_id]


def test_the_patient_question_and_the_reply_are_kept_in_the_conversation(
    api: IdentityApi,
) -> None:
    with_external_consent(api)

    first = ask(api, conversation_id=str(CONVERSATION)).json()
    second = ask(
        api, "¿Y si no puedo tragar?", conversation_id=str(CONVERSATION)
    ).json()

    assert first["conversation_id"] == str(CONVERSATION)
    assert second["conversation_id"] == str(CONVERSATION)
    call = api.ai.service.calls[-1]
    assert isinstance(call, AssistantCall)
    history = call.history
    assert [turn.sender for turn in history] == ["PATIENT", "ASSISTANT"]


def test_a_new_conversation_gets_its_own_identifier(api: IdentityApi) -> None:
    first = ask(api).json()
    second = ask(api).json()

    assert first["conversation_id"] != second["conversation_id"]


def test_the_doctor_cannot_use_the_assistant(api: IdentityApi) -> None:
    token = api.staff_token(DOCTOR, Role.DOCTOR, frozenset())

    response = api.client.post(URL, json={"message": "Hola"}, headers=api.bearer(token))

    assert response.status_code == 403


def test_without_token_is_401(api: IdentityApi) -> None:
    response = api.client.post(URL, json={"message": "Hola"})

    assert response.status_code == 401


def test_without_the_sensitive_consent_the_patient_is_refused(api: IdentityApi) -> None:
    api.world.consents.records.clear()

    response = ask(api)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CONSENT_REQUIRED"


def test_the_body_is_validated(api: IdentityApi) -> None:
    empty = ask(api, message="")
    too_long = ask(api, message="x" * 1001)
    unknown = ask(api, patient_id=str(PATIENT_ID))

    assert empty.status_code == 422
    assert too_long.status_code == 422
    assert unknown.status_code == 422


def test_the_patient_is_limited_per_hour(api: IdentityApi) -> None:
    headers = patient(api)
    api.world.limiter.blocked = True

    response = api.client.post(URL, json={"message": "Hola"}, headers=headers)

    assert response.status_code == 429
    assert response.headers["Retry-After"]
