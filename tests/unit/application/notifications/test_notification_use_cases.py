"""The notification use cases over doubles: scope, consent, rules and the rows kept."""

from __future__ import annotations

from datetime import UTC, datetime, time
from uuid import UUID

import pytest

from insumap.application.common.actor import Actor
from insumap.application.common.pagination import PageRequest
from insumap.application.notifications.alert_notifications import ALERT_RAISED_KEY
from insumap.application.notifications.list_notifications import (
    ListNotificationsInput,
    ListNotificationsUseCase,
)
from insumap.application.notifications.mark_read import MarkNotificationReadUseCase
from insumap.application.notifications.ports import NotificationView
from insumap.application.notifications.preferences import (
    GetNotificationPreferencesUseCase,
    UpdateNotificationPreferencesInput,
    UpdateNotificationPreferencesUseCase,
)
from insumap.application.notifications.web_push import (
    RegisterWebPushInput,
    RegisterWebPushSubscriptionUseCase,
    RemoveWebPushSubscriptionUseCase,
)
from insumap.application.security.events import SecurityEventType
from insumap.domain.common.errors import ConflictError, ResourceNotFoundError
from insumap.domain.identity.errors import ConsentRequiredError, PermissionDeniedError
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role
from insumap.domain.notifications.errors import (
    InvalidNotificationSettingError,
    PushEndpointRejectedError,
)
from insumap.domain.notifications.preferences import Channel
from insumap.domain.notifications.push import PushEndpoint
from insumap.shared.i18n import MessageCatalog
from tests.support.fixed_clock import FixedClock
from tests.support.identity_fakes import (
    FakeCipher,
    FakeConsents,
    FakeIds,
    FakeSecurityEvents,
    FakeUnitOfWorkPort,
)
from tests.support.notification_fakes import (
    InMemoryNotificationStore,
    InMemoryPreferences,
    InMemoryPushSubscriptions,
)

MESSAGES = MessageCatalog.load_spanish()
NOW = datetime(2026, 11, 19, 10, 0, tzinfo=UTC)
LATER = datetime(2026, 11, 19, 11, 0, tzinfo=UTC)
CLINIC = UUID(int=60)
DOCTOR = UUID(int=61)
OTHER = UUID(int=62)
PATIENT_USER = UUID(int=63)
PATIENT = UUID(int=64)
GOOGLE = "https://fcm.googleapis.com/fcm/send/device-1"
HOSTS = ("fcm.googleapis.com",)
ALL_PERMISSIONS = frozenset(
    {
        PermissionCode.NOTIFICATIONS_READ_OWN,
        PermissionCode.NOTIFICATION_PREFERENCES_MANAGE_OWN,
    }
)


class ConsentedFake(FakeConsents):
    def has_accepted_current(self, patient_id: UUID, clinic_id: UUID) -> bool:
        return True


def staff(user_id: UUID = DOCTOR) -> Actor:
    return Actor(
        user_id=user_id,
        clinic_id=CLINIC,
        role=Role.DOCTOR,
        permissions=ALL_PERMISSIONS,
    )


def patient() -> Actor:
    return Actor(
        user_id=PATIENT_USER,
        clinic_id=CLINIC,
        role=Role.PATIENT,
        permissions=ALL_PERMISSIONS,
        patient_id=PATIENT,
    )


def view(number: int, *, recipient_read: bool = False) -> NotificationView:
    return NotificationView(
        notification_id=UUID(int=1000 + number),
        notification_type="ALERT",
        message_key=ALERT_RAISED_KEY,
        entity_type="ALERT",
        entity_id=UUID(int=2000 + number),
        created_at=NOW,
        read_at=NOW if recipient_read else None,
    )


def store_with(*rows: tuple[NotificationView, UUID]) -> InMemoryNotificationStore:
    store = InMemoryNotificationStore()
    for row, recipient in rows:
        store.add(row, recipient=recipient)
    return store


# Listing and reading.


def test_the_listing_shows_only_the_callers_notifications_with_their_text() -> None:
    store = store_with((view(1), DOCTOR), (view(2), OTHER))
    use_case = ListNotificationsUseCase(
        uow=FakeUnitOfWorkPort(),
        consents=FakeConsents(),
        notifications=store,
        messages=MESSAGES,
    )

    page = use_case.execute(
        ListNotificationsInput(
            actor=staff(), unread_only=False, page=PageRequest(limit=10)
        )
    )

    [item] = page.items
    assert item.notification_id == UUID(int=1001)
    assert item.title == MESSAGES.render(f"{ALERT_RAISED_KEY}.title")
    assert item.body == MESSAGES.render(f"{ALERT_RAISED_KEY}.body")
    assert page.next_cursor is None


def test_unread_only_hides_the_read_ones() -> None:
    store = store_with(
        (view(1, recipient_read=True), DOCTOR),
        (view(2), DOCTOR),
    )
    use_case = ListNotificationsUseCase(
        uow=FakeUnitOfWorkPort(),
        consents=FakeConsents(),
        notifications=store,
        messages=MESSAGES,
    )

    page = use_case.execute(
        ListNotificationsInput(
            actor=staff(), unread_only=True, page=PageRequest(limit=10)
        )
    )

    assert [item.notification_id for item in page.items] == [UUID(int=1002)]


def test_a_patient_without_current_consent_cannot_list() -> None:
    use_case = ListNotificationsUseCase(
        uow=FakeUnitOfWorkPort(),
        consents=FakeConsents(),
        notifications=InMemoryNotificationStore(),
        messages=MESSAGES,
    )

    with pytest.raises(ConsentRequiredError):
        use_case.execute(
            ListNotificationsInput(
                actor=patient(), unread_only=False, page=PageRequest(limit=10)
            )
        )


def test_a_patient_with_consent_lists_the_own_notifications() -> None:
    store = store_with((view(1), PATIENT_USER))
    use_case = ListNotificationsUseCase(
        uow=FakeUnitOfWorkPort(),
        consents=ConsentedFake(),
        notifications=store,
        messages=MESSAGES,
    )

    page = use_case.execute(
        ListNotificationsInput(
            actor=patient(), unread_only=False, page=PageRequest(limit=10)
        )
    )

    assert len(page.items) == 1


def test_a_role_without_the_permission_is_denied() -> None:
    actor = Actor(
        user_id=DOCTOR, clinic_id=CLINIC, role=Role.DOCTOR, permissions=frozenset()
    )
    use_case = ListNotificationsUseCase(
        uow=FakeUnitOfWorkPort(),
        consents=FakeConsents(),
        notifications=InMemoryNotificationStore(),
        messages=MESSAGES,
    )

    with pytest.raises(PermissionDeniedError):
        use_case.execute(
            ListNotificationsInput(
                actor=actor, unread_only=False, page=PageRequest(limit=10)
            )
        )


def test_marking_read_sets_the_time_once_and_keeps_the_first_one() -> None:
    store = store_with((view(1), DOCTOR))
    clock = FixedClock(NOW)
    use_case = MarkNotificationReadUseCase(
        uow=FakeUnitOfWorkPort(),
        consents=FakeConsents(),
        notifications=store,
        clock=clock,
    )

    use_case.execute(staff(), UUID(int=1001))
    clock.advance(LATER - NOW)
    use_case.execute(staff(), UUID(int=1001))

    assert store.rows[UUID(int=1001)].read_at == NOW


def test_another_persons_notification_is_not_found() -> None:
    store = store_with((view(1), OTHER))
    use_case = MarkNotificationReadUseCase(
        uow=FakeUnitOfWorkPort(),
        consents=FakeConsents(),
        notifications=store,
        clock=FixedClock(NOW),
    )

    with pytest.raises(ResourceNotFoundError):
        use_case.execute(staff(), UUID(int=1001))
    assert store.rows[UUID(int=1001)].read_at is None


# Preferences.


def test_the_preferences_default_to_every_channel_before_any_choice() -> None:
    use_case = GetNotificationPreferencesUseCase(
        uow=FakeUnitOfWorkPort(),
        consents=FakeConsents(),
        store=InMemoryPreferences(),
    )

    preferences = use_case.execute(staff())

    assert preferences.enabled == frozenset(Channel)
    assert preferences.quiet_hours is None


def test_reading_the_preferences_writes_nothing() -> None:
    store = InMemoryPreferences()
    GetNotificationPreferencesUseCase(
        uow=FakeUnitOfWorkPort(), consents=FakeConsents(), store=store
    ).execute(staff())

    assert store.by_user == {}


def test_updating_the_preferences_stores_the_channels_and_the_silence() -> None:
    store = InMemoryPreferences()
    use_case = UpdateNotificationPreferencesUseCase(
        uow=FakeUnitOfWorkPort(),
        consents=FakeConsents(),
        store=store,
        clock=FixedClock(NOW),
    )

    saved = use_case.execute(
        UpdateNotificationPreferencesInput(
            actor=staff(),
            channels={
                Channel.EMAIL: True,
                Channel.WEB_PUSH: False,
                Channel.IN_APP: True,
            },
            quiet_start=time(22, 0),
            quiet_end=time(6, 0),
        )
    )

    assert saved.enabled == frozenset({Channel.EMAIL, Channel.IN_APP})
    assert saved.quiet_hours is not None
    assert store.by_user[DOCTOR] == saved
    assert saved.updated_at == NOW


def test_clearing_the_silence_removes_the_window() -> None:
    store = InMemoryPreferences()
    use_case = UpdateNotificationPreferencesUseCase(
        uow=FakeUnitOfWorkPort(),
        consents=FakeConsents(),
        store=store,
        clock=FixedClock(NOW),
    )
    use_case.execute(
        UpdateNotificationPreferencesInput(
            actor=staff(),
            channels={channel: True for channel in Channel},
            quiet_start=time(22, 0),
            quiet_end=time(6, 0),
        )
    )

    cleared = use_case.execute(
        UpdateNotificationPreferencesInput(
            actor=staff(),
            channels={channel: True for channel in Channel},
            quiet_start=None,
            quiet_end=None,
        )
    )

    assert cleared.quiet_hours is None


def test_an_empty_silence_window_is_refused_before_anything_is_stored() -> None:
    store = InMemoryPreferences()
    use_case = UpdateNotificationPreferencesUseCase(
        uow=FakeUnitOfWorkPort(),
        consents=FakeConsents(),
        store=store,
        clock=FixedClock(NOW),
    )

    with pytest.raises(InvalidNotificationSettingError):
        use_case.execute(
            UpdateNotificationPreferencesInput(
                actor=staff(),
                channels={channel: True for channel in Channel},
                quiet_start=time(7, 0),
                quiet_end=time(7, 0),
            )
        )
    assert store.by_user == {}


# Web Push subscriptions.


def register(
    *, subscriptions: InMemoryPushSubscriptions, events: FakeSecurityEvents
) -> RegisterWebPushSubscriptionUseCase:
    return RegisterWebPushSubscriptionUseCase(
        uow=FakeUnitOfWorkPort(),
        consents=FakeConsents(),
        subscriptions=subscriptions,
        security_events=events,
        cipher=FakeCipher(),
        ids=FakeIds(),
        clock=FixedClock(NOW),
        allowed_hosts=HOSTS,
    )


def test_a_subscription_is_stored_with_its_auth_secret_encrypted_and_bound() -> None:
    subscriptions = InMemoryPushSubscriptions()
    use_case = register(subscriptions=subscriptions, events=FakeSecurityEvents())

    use_case.execute(
        RegisterWebPushInput(
            actor=staff(), endpoint=GOOGLE, p256dh="BPubKey_1", auth="SecretAuth"
        )
    )

    record = subscriptions.by_user[DOCTOR]
    endpoint_hash = PushEndpoint.parse(GOOGLE, allowed_hosts=HOSTS).endpoint_hash
    assert record.endpoint == GOOGLE
    assert record.endpoint_hash == endpoint_hash
    assert record.p256dh == "BPubKey_1"
    assert record.key_id == "key-1"
    assert record.auth_ciphertext == (
        f"push_subscription:{DOCTOR}:{endpoint_hash}#SecretAuth".encode()
    )


def test_a_new_subscription_replaces_the_previous_one_of_the_same_person() -> None:
    subscriptions = InMemoryPushSubscriptions()
    use_case = register(subscriptions=subscriptions, events=FakeSecurityEvents())
    use_case.execute(
        RegisterWebPushInput(actor=staff(), endpoint=GOOGLE, p256dh="A", auth="B")
    )

    use_case.execute(
        RegisterWebPushInput(
            actor=staff(),
            endpoint="https://fcm.googleapis.com/fcm/send/device-2",
            p256dh="C",
            auth="D",
        )
    )

    assert len(subscriptions.by_user) == 1
    assert subscriptions.by_user[DOCTOR].p256dh == "C"


def test_an_endpoint_outside_the_allowlist_is_recorded_and_refused() -> None:
    events = FakeSecurityEvents()
    subscriptions = InMemoryPushSubscriptions()
    use_case = register(subscriptions=subscriptions, events=events)

    with pytest.raises(PushEndpointRejectedError):
        use_case.execute(
            RegisterWebPushInput(
                actor=staff(),
                endpoint="https://evil.example.test/push",
                p256dh="A",
                auth="B",
            )
        )

    assert subscriptions.by_user == {}
    [event] = events.events
    assert event.event_type is SecurityEventType.PUSH_ENDPOINT_REJECTED
    assert event.user_id == DOCTOR


def test_an_endpoint_that_belongs_to_another_account_is_a_conflict() -> None:
    subscriptions = InMemoryPushSubscriptions()
    subscriptions.taken.add(
        PushEndpoint.parse(GOOGLE, allowed_hosts=HOSTS).endpoint_hash
    )
    use_case = register(subscriptions=subscriptions, events=FakeSecurityEvents())

    with pytest.raises(ConflictError):
        use_case.execute(
            RegisterWebPushInput(actor=staff(), endpoint=GOOGLE, p256dh="A", auth="B")
        )


def test_removing_the_subscription_leaves_the_others_untouched() -> None:
    subscriptions = InMemoryPushSubscriptions()
    register(subscriptions=subscriptions, events=FakeSecurityEvents()).execute(
        RegisterWebPushInput(actor=staff(), endpoint=GOOGLE, p256dh="A", auth="B")
    )
    subscriptions.by_user[OTHER] = subscriptions.by_user[DOCTOR]

    RemoveWebPushSubscriptionUseCase(
        uow=FakeUnitOfWorkPort(),
        consents=FakeConsents(),
        subscriptions=subscriptions,
    ).execute(staff())

    assert DOCTOR not in subscriptions.by_user
    assert OTHER in subscriptions.by_user
