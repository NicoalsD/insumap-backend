"""Environment configuration of the API, read with pydantic-settings."""

from __future__ import annotations

from typing import Annotated, ClassVar, Literal, final

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

type AppEnv = Literal["local", "test", "production"]
type LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

PSYCOPG_SCHEME = "postgresql+psycopg"
ACCEPTED_DATABASE_SCHEMES = frozenset({"postgres", "postgresql", PSYCOPG_SCHEME})
SCHEME_SEPARATOR = "://"
LIST_SEPARATOR = ","
WILDCARD_ORIGIN = "*"
ALLOWED_ORIGIN_PREFIXES = ("http://", "https://")
TRAILING_SLASH = "/"


class Settings(BaseSettings):
    """Settings of the API, read from environment variables or a local ``.env``.

    Each variable maps to the field of the same name in upper case
    (``DATABASE_URL`` to ``database_url``). Secrets are ``SecretStr`` and have no
    default: if one is missing, building the settings fails and the API does not
    start. Validation errors never echo the rejected values.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
        hide_input_in_errors=True,
    )

    app_env: AppEnv = "local"
    log_level: LogLevel = "INFO"
    database_url: SecretStr
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    api_docs_enabled: bool = True

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, value: object) -> object:
        """Accept the level in any case (``info`` becomes ``INFO``)."""
        return value.upper() if isinstance(value, str) else value

    @field_validator("database_url")
    @classmethod
    def use_psycopg_driver(cls, value: SecretStr) -> SecretStr:
        """Require a PostgreSQL URL and point it at the psycopg 3 driver."""
        scheme, separator, rest = value.get_secret_value().partition(SCHEME_SEPARATOR)
        if not separator or not rest or scheme.lower() not in ACCEPTED_DATABASE_SCHEMES:
            raise ValueError("DATABASE_URL must be a postgresql:// URL")
        return SecretStr(f"{PSYCOPG_SCHEME}{SCHEME_SEPARATOR}{rest}")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_cors_origins(cls, value: object) -> object:
        """Read ``CORS_ORIGINS`` as a comma separated list, ignoring blanks."""
        if isinstance(value, str):
            return [
                item.strip() for item in value.split(LIST_SEPARATOR) if item.strip()
            ]
        return value

    @field_validator("cors_origins")
    @classmethod
    def require_explicit_origins(cls, origins: list[str]) -> list[str]:
        """Reject the wildcard and anything that is not an http(s) origin."""
        for origin in origins:
            if origin == WILDCARD_ORIGIN or not origin.startswith(
                ALLOWED_ORIGIN_PREFIXES
            ):
                raise ValueError("CORS_ORIGINS only accepts explicit http(s) origins")
        return [origin.rstrip(TRAILING_SLASH) for origin in origins]


@final
class SettingsHolder:
    """Keeps the settings read from the environment so they are loaded once.

    ``reset()`` forgets them, so tests can load them again after changing the
    environment.
    """

    _settings: ClassVar[Settings | None] = None

    @classmethod
    def get(cls) -> Settings:
        """Return the settings, reading the environment on first use."""
        if cls._settings is None:
            cls._settings = Settings()
        return cls._settings

    @classmethod
    def reset(cls) -> None:
        """Forget the loaded settings."""
        cls._settings = None


def get_settings() -> Settings:
    """Return the settings of the process, loaded once by ``SettingsHolder``."""
    return SettingsHolder.get()
