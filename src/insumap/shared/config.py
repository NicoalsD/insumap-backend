"""Environment configuration of the API, read with pydantic-settings."""

from __future__ import annotations

from typing import Annotated, ClassVar, Literal, Self, final

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from insumap.shared.key_material import decode_key

type AppEnv = Literal["local", "test", "production"]
type LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

PSYCOPG_SCHEME = "postgresql+psycopg"
ACCEPTED_DATABASE_SCHEMES = frozenset({"postgres", "postgresql", PSYCOPG_SCHEME})
SCHEME_SEPARATOR = "://"
LIST_SEPARATOR = ","
WILDCARD_ORIGIN = "*"
MIN_TOKEN_BYTES = 32
ALLOWED_ORIGIN_PREFIXES = ("http://", "https://")
TRAILING_SLASH = "/"
DEFAULT_PUSH_ENDPOINT_HOSTS = (
    "fcm.googleapis.com",
    "updates.push.services.mozilla.com",
    "web.push.apple.com",
    "*.notify.windows.com",
)
"""Push services of the major browsers (verify before a production release)."""


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
    app_hmac_key: SecretStr
    """Root of the keyed counters: lockouts and rate limits (``APP_HMAC_KEY``)."""

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
    privacy_request_due_days: int = Field(
        default=10,
        ge=1,
        description="Days to answer a privacy request (provisional, see docs).",
    )

    # Patient records and exports (docs/API.md, section 5).
    rate_limit_records_per_user_per_minute: int = Field(default=120, ge=1)
    rate_limit_exports_per_user_per_hour: int = Field(default=20, ge=1)
    # Reports: smaller counts are not shown, so no patient is singled out (API.md 8.11).
    report_small_count_threshold: int = Field(default=5, ge=1)
    # Password reset, email verification and staff invitations (Seguridad.md 3.6).
    password_reset_ttl_minutes: int = Field(default=30, ge=1)
    email_verification_ttl_hours: int = Field(default=24, ge=1)
    staff_invitation_days: int = Field(default=7, ge=1)
    rate_limit_reset_request_per_ip_per_hour: int = Field(default=5, ge=1)
    rate_limit_reset_request_per_account_per_hour: int = Field(default=3, ge=1)
    rate_limit_reset_complete_per_ip_per_minute: int = Field(default=10, ge=1)
    web_app_base_url: str = Field(default="http://localhost:5173", min_length=1)
    # Patient credentials (docs/Seguridad.md 3.2 and 3.3; docs/API.md section 5).
    activation_code_ttl_hours: int = Field(default=168, ge=1)
    rate_limit_credential_issue_per_clinic_per_hour: int = Field(default=300, ge=1)
    rate_limit_credential_batch_per_clinic_per_hour: int = Field(default=10, ge=1)

    # AI service (docs/Contrato-IA.md, sections 3.2 and 10.1). Optional: without
    # a URL the forecast answers only with the rule-based fallback.
    ai_enabled: bool = True
    ai_service_url: str | None = None
    ai_service_token: SecretStr | None = None
    """Service token (``AI_SERVICE_TOKEN``), at least 32 bytes when set."""
    ai_timeout_connect_seconds: float = Field(default=2.0, gt=0)
    ai_timeout_forecast_seconds: float = Field(default=3.0, gt=0)
    """API.md 8.8 says 3 s and Contrato-IA.md 3.2 says 5 s; the lower one is used."""
    ai_circuit_failure_threshold: int = Field(default=5, ge=1)
    ai_circuit_open_seconds: float = Field(default=30.0, gt=0)
    ai_timeout_risk_seconds: float = Field(default=3.0, gt=0)
    ai_timeout_summary_seconds: float = Field(default=30.0, gt=0)
    ai_timeout_assistant_seconds: float = Field(default=20.0, gt=0)
    """Contrato-IA.md 3.2: the summary and the assistant wait longer (LLM)."""
    llm_real_data_allowed: bool = False
    """``LLM_REAL_DATA_ALLOWED``: a non demo clinic gets the template unless true."""
    rate_limit_assistant_per_patient_per_hour: int = Field(default=20, ge=1)
    rate_limit_assistant_per_patient_per_day: int = Field(default=100, ge=1)
    rate_limit_summary_per_doctor_per_hour: int = Field(default=30, ge=1)

    # Web Push endpoints the browser may register (Seguridad.md 13.4). Hosts
    # only, no scheme; ``*.`` matches any subdomain. Not a secret.
    push_endpoint_allowed_hosts: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: list(DEFAULT_PUSH_ENDPOINT_HOSTS)
    )

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
        "app_hmac_key",
    )
    @classmethod
    def require_a_32_byte_key(cls, value: SecretStr | None) -> SecretStr | None:
        """Keys are 32 bytes in base64; the error never repeats the value."""
        if value is not None:
            decode_key(value.get_secret_value())
        return value

    @field_validator("ai_service_token")
    @classmethod
    def require_a_long_service_token(cls, value: SecretStr | None) -> SecretStr | None:
        """The service token has at least 32 bytes; the error never repeats it."""
        if (
            value is not None
            and len(value.get_secret_value().encode()) < MIN_TOKEN_BYTES
        ):
            raise ValueError("AI_SERVICE_TOKEN must have at least 32 bytes")
        return value

    @model_validator(mode="after")
    def require_https_ai_service_in_production(self) -> Self:
        """Production sends the service token only over TLS (Seguridad 18.4)."""
        url = self.ai_service_url
        insecure = url is not None and not url.startswith("https://")
        if self.app_env == "production" and insecure:
            raise ValueError("AI_SERVICE_URL must use https in production")
        return self

    @field_validator("push_endpoint_allowed_hosts", mode="before")
    @classmethod
    def split_push_hosts(cls, value: object) -> object:
        """Read ``PUSH_ENDPOINT_ALLOWED_HOSTS`` as a comma separated list."""
        if isinstance(value, str):
            return [
                item.strip().lower()
                for item in value.split(LIST_SEPARATOR)
                if item.strip()
            ]
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
