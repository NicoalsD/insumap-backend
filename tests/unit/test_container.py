from datetime import UTC, datetime

import pytest

from insumap.application.readiness import AlwaysReadyProbe
from insumap.container import Container
from insumap.shared.config import SettingsHolder
from insumap.shared.errors import ErrorCode
from insumap.shared.time import SystemClock
from tests.support.fixed_clock import FixedClock
from tests.support.settings import TEST_DATABASE_URL, make_settings


class NotReadyProbe:
    def is_ready(self) -> bool:
        return False


def test_builds_production_defaults_from_the_given_settings() -> None:
    settings = make_settings()

    container = Container(settings)

    assert container.settings is settings
    assert container.clock is SystemClock.instance()
    assert isinstance(container.readiness_probe, AlwaysReadyProbe)
    assert container.check_readiness.execute() is True
    assert all(
        code.default_message_key in container.message_catalog for code in ErrorCode
    )


def test_accepts_test_doubles_for_clock_and_probe() -> None:
    clock = FixedClock(datetime(2026, 1, 15, tzinfo=UTC))

    container = Container(make_settings(), clock=clock, readiness_probe=NotReadyProbe())

    assert container.clock is clock
    assert container.check_readiness.execute() is False


def test_reads_the_environment_when_no_settings_are_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setenv("APP_ENV", "test")
    SettingsHolder.reset()
    try:
        container = Container()
    finally:
        SettingsHolder.reset()

    assert container.settings.app_env == "test"
