"""Preferences of a person: channels and quiet hours (HU-35, RF-61, RF-62)."""

from datetime import UTC, datetime, time
from uuid import UUID

import pytest

from insumap.domain.notifications.errors import InvalidNotificationSettingError
from insumap.domain.notifications.preferences import (
    Channel,
    NotificationPreferences,
    QuietHours,
)

USER = UUID(int=1)
CLINIC = UUID(int=2)
AT = datetime(2026, 11, 19, 8, 0, tzinfo=UTC)


def test_a_person_without_saved_preferences_has_every_channel_and_no_silence() -> None:
    preferences = NotificationPreferences.defaults(user_id=USER, clinic_id=CLINIC)

    assert preferences.enabled == frozenset(Channel)
    assert preferences.quiet_hours is None
    assert preferences.updated_at is None


def test_a_window_may_cross_midnight() -> None:
    window = QuietHours(start=time(22, 0), end=time(6, 30))

    assert window.start > window.end


def test_a_window_that_starts_and_ends_at_the_same_time_is_refused() -> None:
    with pytest.raises(InvalidNotificationSettingError) as error:
        QuietHours(start=time(7, 0), end=time(7, 0))

    assert error.value.detail == {
        "errors": [{"field": "body.quiet_hours", "type": "empty_window"}]
    }


def test_update_replaces_the_channels_and_drops_the_missing_ones() -> None:
    before = NotificationPreferences.defaults(user_id=USER, clinic_id=CLINIC)

    after = before.updated(
        channels={Channel.EMAIL: False, Channel.WEB_PUSH: True, Channel.IN_APP: False},
        quiet_hours=None,
        at=AT,
    )

    assert after.enabled == frozenset({Channel.WEB_PUSH})
    assert not after.is_enabled(Channel.EMAIL)
    assert after.updated_at == AT


def test_update_keeps_the_owner_and_the_clinic() -> None:
    before = NotificationPreferences.defaults(user_id=USER, clinic_id=None)

    after = before.updated(
        channels={channel: True for channel in Channel},
        quiet_hours=QuietHours(start=time(22, 0), end=time(6, 0)),
        at=AT,
    )

    assert after.user_id == USER
    assert after.clinic_id is None
    assert after.quiet_hours == QuietHours(start=time(22, 0), end=time(6, 0))
