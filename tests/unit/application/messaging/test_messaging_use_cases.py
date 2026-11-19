"""Messages and their reads (RF-84, RF-85, P11, P07, P17) over in-memory doubles."""

from datetime import timedelta
from uuid import UUID

import pytest

from insumap.application.access.ports import DataResource
from insumap.application.common.pagination import (
    PageRequest,
    decode_cursor,
    encode_cursor,
)
from insumap.application.common.patient_scope import PatientScope
from insumap.application.messaging.list_messages import (
    ListMessagesInput,
    ListMessagesUseCase,
)
from insumap.application.messaging.message_notifications import MESSAGE_RECEIVED_KEY
from insumap.application.messaging.send_message import (
    SendMessageInput,
    SendMessageUseCase,
)
from insumap.application.monitoring.gate import AssignedPatientGate, OwnPatientGate
from insumap.application.security.rate_limit import (
    RateLimitCheck,
    RateLimitedError,
    RateLimitRule,
)
from insumap.domain.common.errors import ResourceNotFoundError
from insumap.domain.identity.errors import PermissionDeniedError
from insumap.domain.messaging.events import MessageSent
from insumap.domain.messaging.message import SenderRole
from insumap.infrastructure.security.rate_limiter import InMemoryRateLimiter
from insumap.shared.errors import ErrorCode, InsumapError
from insumap.shared.i18n import MessageCatalog
from tests.support.care_team_fakes import FakeCareTeams
from tests.support.fixed_clock import FixedClock
from tests.support.identity_fakes import FakeIds, FakeUnitOfWorkPort
from tests.support.messaging_fakes import (
    CLINIC,
    DOCTOR,
    NOW,
    OTHER_DOCTOR,
    OTHER_PATIENT,
    PATIENT,
    PATIENT_USER,
    FakeAssignedRecords,
    FakeMessages,
    FakePatients,
    FakeReadMarks,
    FakeThreads,
    admin_actor,
    assignment,
    doctor_actor,
    patient_actor,
)
from tests.support.monitoring_fakes import FakeConsentsGate
from tests.support.notifications import InMemoryChannel


class World:
    """One clinic: a patient with one assigned doctor, and the shared doubles."""

    def __init__(self) -> None:
        self.uow = FakeUnitOfWorkPort()
        self.threads = FakeThreads()
        self.messages = FakeMessages()
        self.read_marks = FakeReadMarks()
        self.records = FakeAssignedRecords((DOCTOR, PATIENT))
        self.teams = FakeCareTeams(assignment(DOCTOR))
        self.patients = FakePatients()
        self.channel = InMemoryChannel(external=False)
        self.clock = FixedClock(NOW)
        self.ids = FakeIds()
        self.catalog = MessageCatalog.load_spanish()
        self.scope = PatientScope(
            assigned=AssignedPatientGate(self.records),
            own=OwnPatientGate(FakeConsentsGate()),
        )

    def sender(self) -> SendMessageUseCase:
        return SendMessageUseCase(
            uow=self.uow,
            scope=self.scope,
            threads=self.threads,
            messages=self.messages,
            read_marks=self.read_marks,
            care_teams=self.teams,
            patients=self.patients,
            ids=self.ids,
            clock=self.clock,
            in_app=self.channel,
            catalog=self.catalog,
            rate_limit=RateLimitCheck(
                InMemoryRateLimiter(self.clock),
                RateLimitRule(
                    family="messages_user_minute",
                    limit=MESSAGES_PER_MINUTE,
                    window=timedelta(minutes=1),
                ),
            ),
        )

    def reader(self) -> ListMessagesUseCase:
        return ListMessagesUseCase(
            uow=self.uow,
            scope=self.scope,
            threads=self.threads,
            messages=self.messages,
            read_marks=self.read_marks,
            clock=self.clock,
            catalog=self.catalog,
        )


@pytest.fixture
def world() -> World:
    return World()


MESSAGES_PER_MINUTE = 30


def _first_page() -> PageRequest:
    return PageRequest(limit=20)


def test_patient_message_is_stored_with_session_role_and_normalized_text(
    world: World,
) -> None:
    message = world.sender().execute(
        SendMessageInput(actor=patient_actor(), patient_id=None, body="  Hola  ")
    )

    assert message.sender_role is SenderRole.PATIENT
    assert message.sender_user_id == PATIENT_USER
    assert message.body == "Hola"
    assert world.messages.rows == [message]
    assert world.threads.by_patient[PATIENT].thread_id == message.thread_id


def test_patient_message_notifies_each_open_doctor_in_app_without_text(
    world: World,
) -> None:
    world.teams = FakeCareTeams(assignment(DOCTOR), assignment(OTHER_DOCTOR))
    world.sender().execute(
        SendMessageInput(actor=patient_actor(), patient_id=None, body="Me duele")
    )

    recipients = sorted(d.recipient.user_id.int for d in world.channel.delivered)
    assert recipients == [DOCTOR.int, OTHER_DOCTOR.int]
    for delivered in world.channel.delivered:
        assert delivered.entry is not None
        assert delivered.entry.notification_type == "MESSAGE"
        assert delivered.entry.message_key == MESSAGE_RECEIVED_KEY
        assert "Me duele" not in delivered.body
        assert delivered.recipient.clinic_id == CLINIC


def test_doctor_message_names_an_assigned_patient_and_notifies_the_patient(
    world: World,
) -> None:
    message = world.sender().execute(
        SendMessageInput(
            actor=doctor_actor(), patient_id=PATIENT, body="Revisa tus datos"
        )
    )

    assert message.sender_role is SenderRole.DOCTOR
    assert message.sender_user_id == DOCTOR
    assert [d.recipient.user_id for d in world.channel.delivered] == [PATIENT_USER]


def test_doctor_without_patient_id_gets_a_validation_error(world: World) -> None:
    with pytest.raises(InsumapError) as error:
        world.sender().execute(
            SendMessageInput(actor=doctor_actor(), patient_id=None, body="Hola")
        )

    assert error.value.code is ErrorCode.VALIDATION_ERROR
    assert world.messages.rows == []


def test_doctor_of_an_unassigned_patient_gets_not_found(world: World) -> None:
    with pytest.raises(ResourceNotFoundError):
        world.sender().execute(
            SendMessageInput(
                actor=doctor_actor(), patient_id=OTHER_PATIENT, body="Hola"
            )
        )

    assert world.messages.rows == []
    assert world.channel.delivered == []


def test_patient_cannot_name_a_patient_in_the_request(world: World) -> None:
    with pytest.raises(InsumapError) as error:
        world.sender().execute(
            SendMessageInput(actor=patient_actor(), patient_id=PATIENT, body="Hola")
        )

    assert error.value.code is ErrorCode.VALIDATION_ERROR
    assert world.messages.rows == []


def test_clinic_admin_has_no_access_to_messages(world: World) -> None:
    with pytest.raises(PermissionDeniedError):
        world.sender().execute(
            SendMessageInput(actor=admin_actor(), patient_id=PATIENT, body="Hola")
        )


def test_blank_body_is_refused_before_any_write(world: World) -> None:
    with pytest.raises(InsumapError) as error:
        world.sender().execute(
            SendMessageInput(actor=patient_actor(), patient_id=None, body="   ")
        )

    assert error.value.code is ErrorCode.VALIDATION_ERROR
    assert world.threads.by_patient == {}
    assert world.messages.rows == []


def test_message_event_is_collected_for_publication_after_commit(world: World) -> None:
    world.sender().execute(
        SendMessageInput(actor=patient_actor(), patient_id=None, body="Hola")
    )

    (event,) = world.uow.published
    assert isinstance(event, MessageSent)
    assert event.sender_role is SenderRole.PATIENT
    assert event.clinic_id == CLINIC


def test_patient_reads_own_thread_newest_first_with_the_notice(world: World) -> None:
    sender = world.sender()
    first = sender.execute(
        SendMessageInput(actor=patient_actor(), patient_id=None, body="Primero")
    )
    second = sender.execute(
        SendMessageInput(actor=doctor_actor(), patient_id=PATIENT, body="Segundo")
    )

    listing = world.reader().execute(
        ListMessagesInput(actor=patient_actor(), patient_id=None, page=_first_page())
    )

    assert [m.message_id for m in listing.page.items] == [
        second.message_id,
        first.message_id,
    ]
    assert listing.emergency_notice == world.catalog.render(
        "messaging.emergency_notice"
    )
    assert world.read_marks.marks[(first.thread_id, PATIENT_USER)] == NOW


def test_reading_a_thread_nobody_wrote_in_is_an_empty_page(world: World) -> None:
    listing = world.reader().execute(
        ListMessagesInput(actor=patient_actor(), patient_id=None, page=_first_page())
    )

    assert listing.page.items == ()
    assert listing.page.next_cursor is None


def test_doctor_read_is_audited_and_committed(world: World) -> None:
    world.sender().execute(
        SendMessageInput(actor=patient_actor(), patient_id=None, body="Hola")
    )
    commits = world.uow.commits

    listing = world.reader().execute(
        ListMessagesInput(actor=doctor_actor(), patient_id=PATIENT, page=_first_page())
    )

    assert len(listing.page.items) == 1
    assert world.records.reads[-1] == (DOCTOR, PATIENT, DataResource.MESSAGES)
    assert world.uow.commits > commits


def test_doctor_reading_an_unassigned_thread_gets_not_found(world: World) -> None:
    with pytest.raises(ResourceNotFoundError):
        world.reader().execute(
            ListMessagesInput(
                actor=doctor_actor(), patient_id=OTHER_PATIENT, page=_first_page()
            )
        )


def test_patient_listing_cannot_name_a_patient(world: World) -> None:
    with pytest.raises(InsumapError) as error:
        world.reader().execute(
            ListMessagesInput(
                actor=patient_actor(), patient_id=PATIENT, page=_first_page()
            )
        )

    assert error.value.code is ErrorCode.VALIDATION_ERROR


def test_cursor_points_at_the_older_messages(world: World) -> None:
    sender = world.sender()
    for body in ("uno", "dos", "tres"):
        sender.execute(
            SendMessageInput(actor=patient_actor(), patient_id=None, body=body)
        )

    first = world.reader().execute(
        ListMessagesInput(
            actor=patient_actor(), patient_id=None, page=PageRequest(limit=2)
        )
    )
    assert first.page.next_cursor is not None
    older = world.reader().execute(
        ListMessagesInput(
            actor=patient_actor(),
            patient_id=None,
            page=PageRequest(limit=2, after=_decode(first.page.next_cursor)),
        )
    )

    assert [m.body for m in first.page.items] == ["tres", "dos"]
    assert [m.body for m in older.page.items] == ["uno"]
    assert older.page.next_cursor is None


def _decode(cursor: str) -> UUID:
    key = decode_cursor(cursor)
    assert key is not None
    return key


def test_cursor_round_trip_matches_the_encoder() -> None:
    key = UUID(int=42)

    assert _decode(encode_cursor(key)) == key


def test_messages_are_limited_per_user_per_minute_with_retry_after(
    world: World,
) -> None:
    sender = world.sender()
    for _ in range(MESSAGES_PER_MINUTE):
        sender.execute(
            SendMessageInput(actor=patient_actor(), patient_id=None, body="Hola")
        )

    with pytest.raises(RateLimitedError) as error:
        sender.execute(
            SendMessageInput(actor=patient_actor(), patient_id=None, body="Hola")
        )

    assert error.value.code is ErrorCode.RATE_LIMITED
    assert int(error.value.headers["Retry-After"]) >= 1
    assert len(world.messages.rows) == MESSAGES_PER_MINUTE


def test_the_limit_is_per_user_not_per_thread(world: World) -> None:
    sender = world.sender()
    for _ in range(MESSAGES_PER_MINUTE):
        sender.execute(
            SendMessageInput(actor=patient_actor(), patient_id=None, body="Hola")
        )

    # The doctor of the same thread has a bucket of their own.
    message = sender.execute(
        SendMessageInput(actor=doctor_actor(), patient_id=PATIENT, body="Hola")
    )

    assert message.sender_role is SenderRole.DOCTOR
