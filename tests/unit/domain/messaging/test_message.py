"""Message bodies and threads (RF-84, RF-85): plain text, normalized, bounded."""

from uuid import UUID

import pytest

from insumap.domain.messaging.message import MessageBody, MessageThread, SenderRole
from insumap.shared.errors import ErrorCode, InsumapError
from insumap.shared.field_limits import FieldLimits
from tests.support.messaging_fakes import CLINIC, NOW, PATIENT


def test_body_is_trimmed_and_nfkc_normalized() -> None:
    body = MessageBody.parse("  \uff28ola  ")

    assert body.text == "Hola"


@pytest.mark.parametrize("raw", ["", "   \n\t "])
def test_blank_body_is_a_validation_error(raw: str) -> None:
    with pytest.raises(InsumapError) as error:
        MessageBody.parse(raw)

    assert error.value.code is ErrorCode.VALIDATION_ERROR


def test_body_at_the_limit_is_accepted_and_one_more_is_refused() -> None:
    assert len(MessageBody.parse("x" * FieldLimits.MESSAGE_BODY_MAX_LENGTH).text) == (
        FieldLimits.MESSAGE_BODY_MAX_LENGTH
    )
    with pytest.raises(InsumapError) as error:
        MessageBody.parse("x" * (FieldLimits.MESSAGE_BODY_MAX_LENGTH + 1))

    assert error.value.code is ErrorCode.VALIDATION_ERROR


def test_thread_post_builds_an_append_only_message_of_the_thread() -> None:
    thread = MessageThread(thread_id=UUID(int=1), clinic_id=CLINIC, patient_id=PATIENT)

    message = thread.post(
        message_id=UUID(int=2),
        sender_user_id=UUID(int=3),
        sender_role=SenderRole.DOCTOR,
        body=MessageBody.parse("Hola"),
        at=NOW,
    )

    assert message.thread_id == thread.thread_id
    assert message.clinic_id == CLINIC
    assert message.sender_role is SenderRole.DOCTOR
    assert message.sent_at == NOW
