from collections.abc import Iterator

import pytest
from pydantic import ValidationError

from insumap.shared.config import Settings, SettingsHolder, get_settings
from tests.support.settings import (
    TEST_DATABASE_URL,
    TEST_JWT_SECRET,
    TEST_JWT_SECRET_PREVIOUS,
    make_settings,
)

ENV_VARS = (
    "APP_ENV",
    "LOG_LEVEL",
    "DATABASE_URL",
    "CORS_ORIGINS",
    "API_DOCS_ENABLED",
    "ALLOWED_HOSTS",
)
URL_WITH_CREDENTIALS = (
    "postgresql://insumap_app:not-a-real-secret@db.example.test/insumap"
)


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


@pytest.fixture
def fresh_holder() -> Iterator[None]:
    SettingsHolder.reset()
    yield
    SettingsHolder.reset()


def test_defaults_apply_when_only_the_secret_is_set(
    clean_env: pytest.MonkeyPatch,
) -> None:
    clean_env.setenv("DATABASE_URL", TEST_DATABASE_URL)

    settings = Settings(_env_file=None)

    assert settings.app_env == "local"
    assert settings.log_level == "INFO"
    assert settings.cors_origins == []
    assert settings.api_docs_enabled is True


def test_reads_every_variable_from_the_environment(
    clean_env: pytest.MonkeyPatch,
) -> None:
    clean_env.setenv("APP_ENV", "production")
    clean_env.setenv("LOG_LEVEL", "warning")
    clean_env.setenv("DATABASE_URL", TEST_DATABASE_URL)
    clean_env.setenv("CORS_ORIGINS", "http://localhost:5173, https://app.example.test")
    clean_env.setenv("API_DOCS_ENABLED", "false")
    clean_env.setenv("ALLOWED_HOSTS", "API.example.test, *.example.test")

    settings = Settings(_env_file=None)

    assert settings.allowed_hosts == ["api.example.test", "*.example.test"]
    assert settings.app_env == "production"
    assert settings.log_level == "WARNING"
    assert settings.cors_origins == [
        "http://localhost:5173",
        "https://app.example.test",
    ]
    assert settings.api_docs_enabled is False


def test_missing_database_url_stops_the_startup(clean_env: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValidationError, match="database_url"):
        Settings(_env_file=None)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://insumap_app@localhost:5432/insumap",
        "postgres://insumap_app@localhost:5432/insumap",
        "postgresql+psycopg://insumap_app@localhost:5432/insumap",
    ],
)
def test_database_url_uses_the_psycopg_driver(url: str) -> None:
    settings = make_settings(database_url=url)

    assert settings.database_url.get_secret_value() == (
        "postgresql+psycopg://insumap_app@localhost:5432/insumap"
    )


@pytest.mark.parametrize(
    "url",
    [
        "mysql://insumap_app:not-a-real-secret@localhost/insumap",
        "postgresql+asyncpg://insumap_app:not-a-real-secret@localhost/insumap",
        "postgresql://",
        "insumap_app:not-a-real-secret@localhost/insumap",
    ],
)
def test_rejects_non_postgresql_urls_without_echoing_them(url: str) -> None:
    with pytest.raises(ValidationError) as raised:
        make_settings(database_url=url)

    assert "not-a-real-secret" not in str(raised.value)


def test_database_url_is_hidden_in_repr() -> None:
    settings = make_settings(database_url=URL_WITH_CREDENTIALS)

    assert "not-a-real-secret" not in repr(settings)
    assert "not-a-real-secret" not in str(settings.model_dump())


def test_rejects_unknown_app_env() -> None:
    with pytest.raises(ValidationError, match="app_env"):
        make_settings(app_env="staging")


@pytest.mark.parametrize("origins", ["*", "http://localhost:5173,*", "localhost:5173"])
def test_rejects_wildcard_or_malformed_cors_origins(origins: str) -> None:
    with pytest.raises(ValidationError, match="cors_origins"):
        make_settings(cors_origins=origins)


def test_cors_origins_drop_blanks_and_trailing_slashes() -> None:
    settings = make_settings(cors_origins=" ,https://app.example.test/, ")

    assert settings.cors_origins == ["https://app.example.test"]


def test_settings_are_immutable() -> None:
    settings = make_settings()

    with pytest.raises(ValidationError):
        settings.app_env = "production"  # type: ignore[misc]


def test_get_settings_loads_once_until_reset(
    clean_env: pytest.MonkeyPatch, fresh_holder: None
) -> None:
    clean_env.setenv("DATABASE_URL", TEST_DATABASE_URL)
    clean_env.setenv("APP_ENV", "test")

    first = get_settings()
    clean_env.setenv("ALLOWED_HOSTS", "api.example.test")
    clean_env.setenv("APP_ENV", "production")
    second = get_settings()
    SettingsHolder.reset()
    third = get_settings()

    assert first is second
    assert first.app_env == "test"
    assert third.app_env == "production"


@pytest.mark.parametrize(
    "name", ["JWT_SECRET", "MFA_ENCRYPTION_KEY", "CODE_HMAC_KEY", "APP_HMAC_KEY"]
)
def test_missing_key_stops_the_startup(
    clean_env: pytest.MonkeyPatch, name: str
) -> None:
    clean_env.setenv("DATABASE_URL", TEST_DATABASE_URL)
    clean_env.delenv(name)

    with pytest.raises(ValidationError) as caught:
        Settings(_env_file=None)

    assert name.lower() in str(caught.value)


@pytest.mark.parametrize("value", ["cambia-esto-jwt-secret", "c2hvcnQ="])
def test_keys_must_be_32_bytes_of_base64_and_are_never_echoed(value: str) -> None:
    with pytest.raises(ValidationError) as caught:
        make_settings(jwt_secret=value)

    assert value not in str(caught.value)


def test_previous_keys_are_optional_and_validated() -> None:
    assert make_settings().jwt_secret_previous is None
    assert make_settings(jwt_secret_previous=TEST_JWT_SECRET_PREVIOUS)
    with pytest.raises(ValidationError):
        make_settings(code_hmac_key_previous="nope")


def test_secrets_are_hidden_in_repr() -> None:
    assert TEST_JWT_SECRET not in repr(make_settings())


def test_security_defaults_follow_the_policy() -> None:
    settings = make_settings()

    assert settings.jwt_access_minutes == 15
    assert settings.refresh_token_days == 30
    assert settings.refresh_family_max_days == 90
    assert settings.refresh_token_staff_hours == 12
    assert settings.mfa_recovery_code_count == 10
    assert settings.mfa_challenge_ttl_seconds == 300
    assert settings.activation_session_ttl_minutes == 15
    assert Settings.model_fields["argon2_memory_kib"].default == 19456


@pytest.mark.parametrize("app_env", ["local", "test"])
def test_allowed_hosts_default_to_the_development_hosts(
    clean_env: pytest.MonkeyPatch, app_env: str
) -> None:
    clean_env.setenv("DATABASE_URL", TEST_DATABASE_URL)
    clean_env.setenv("APP_ENV", app_env)

    settings = Settings(_env_file=None)

    assert settings.allowed_hosts == ["localhost", "127.0.0.1", "testserver"]


def test_blank_allowed_hosts_fall_back_to_the_development_hosts(
    clean_env: pytest.MonkeyPatch,
) -> None:
    clean_env.setenv("DATABASE_URL", TEST_DATABASE_URL)
    clean_env.setenv("ALLOWED_HOSTS", " , ")

    assert Settings(_env_file=None).allowed_hosts == [
        "localhost",
        "127.0.0.1",
        "testserver",
    ]


def test_production_does_not_start_without_allowed_hosts(
    clean_env: pytest.MonkeyPatch,
) -> None:
    clean_env.setenv("DATABASE_URL", TEST_DATABASE_URL)
    clean_env.setenv("APP_ENV", "production")

    with pytest.raises(ValidationError, match="ALLOWED_HOSTS"):
        Settings(_env_file=None)


def test_a_bare_wildcard_host_is_rejected(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("DATABASE_URL", TEST_DATABASE_URL)
    clean_env.setenv("ALLOWED_HOSTS", "*")

    with pytest.raises(ValidationError, match="wildcard"):
        Settings(_env_file=None)
