"""Environment configuration of the API, read with pydantic-settings."""

from __future__ import annotations

from typing import Annotated, ClassVar, Literal, final

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from insumap.shared.key_material import decode_key

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

    # Keys (32 bytes in base64). No defaults: without them the API does not start.
    jwt_secret: SecretStr
    jwt_secret_previous: SecretStr | None = None
    mfa_encryption_key: SecretStr
    mfa_encryption_key_previous: SecretStr | None = None
    code_hmac_key: SecretStr
    code_hmac_key_previous: SecretStr | None = None

    # Access tokens and refresh sessions (docs/Seguridad.md, section 2).
    jwt_issuer: str = Field(default="insumap-api", min_length=1)
    jwt_audience: str = Field(default="insumap-web", min_length=1)
    jwt_access_minutes: int = Field(default=15, ge=1)
    jwt_leeway_seconds: int = Field(default=30, ge=0)
    refresh_token_days: int = Field(default=30, ge=1)
    refresh_family_max_days: int = Field(default=90, ge=1)
    refresh_token_staff_hours: int = Field(default=12, ge=1)

    # Password hashing and history.
    argon2_memory_kib: int = Field(default=19456, ge=8)
    argon2_time_cost: int = Field(default=2, ge=1)
    argon2_parallelism: int = Field(default=1, ge=1)
    password_hash_max_concurrency: int = Field(default=4, ge=1)
    password_history_size: int = Field(default=5, ge=0)

    # Activation, second factor and rate limits.
    activation_max_attempts: int = Field(default=5, ge=1)
    activation_session_ttl_minutes: int = Field(default=15, ge=1)
    mfa_totp_valid_window: int = Field(default=1, ge=0)
    mfa_challenge_ttl_seconds: int = Field(default=300, ge=1)
    mfa_challenge_max_attempts: int = Field(default=5, ge=1)
    mfa_recovery_code_count: int = Field(default=10, ge=1)
    rate_limit_login_per_ip_per_minute: int = Field(default=20, ge=1)
    rate_limit_mfa_per_ip_per_minute: int = Field(default=20, ge=1)
    rate_limit_activation_per_ip_per_minute: int = Field(default=10, ge=1)
    rate_limit_activation_per_ip_per_hour: int = Field(default=50, ge=1)
    rate_limit_refresh_per_user_per_minute: int = Field(default=30, ge=1)

    # Patient records and exports (docs/API.md, section 5).
    rate_limit_records_per_user_per_minute: int = Field(default=120, ge=1)
    rate_limit_exports_per_user_per_hour: int = Field(default=20, ge=1)
    # Password reset, email verification and staff invitations (Seguridad.md 3.6).
    password_reset_ttl_minutes: int = Field(default=30, ge=1)
    email_verification_ttl_hours: int = Field(default=24, ge=1)
    staff_invitation_days: int = Field(default=7, ge=1)
    rate_limit_reset_request_per_ip_per_hour: int = Field(default=5, ge=1)
    rate_limit_reset_request_per_account_per_hour: int = Field(default=3, ge=1)
    rate_limit_reset_complete_per_ip_per_minute: int = Field(default=10, ge=1)
    web_app_base_url: str = Field(default="http://localhost:5173", min_length=1)

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

    @field_validator(
        "jwt_secret",
        "jwt_secret_previous",
        "mfa_encryption_key",
        "mfa_encryption_key_previous",
        "code_hmac_key",
        "code_hmac_key_previous",
    )
    @classmethod
    def require_a_32_byte_key(cls, value: SecretStr | None) -> SecretStr | None:
        """Keys are 32 bytes in base64; the error never repeats the value."""
        if value is not None:
            decode_key(value.get_secret_value())
        return value

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
