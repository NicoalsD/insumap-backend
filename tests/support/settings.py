"""Settings for tests, isolated from the environment and from any local .env."""

import base64
from typing import Any

from insumap.shared.config import Settings

TEST_DATABASE_URL = "postgresql://insumap_app@localhost:5432/insumap_test"


def _test_key(label: str) -> str:
    """A 32 byte base64 key for tests only; it protects nothing."""
    return base64.b64encode(label.encode().ljust(32, b"-")[:32]).decode()


TEST_JWT_SECRET = _test_key("test-jwt-secret")
TEST_JWT_SECRET_PREVIOUS = _test_key("test-jwt-secret-previous")
TEST_MFA_ENCRYPTION_KEY = _test_key("test-mfa-encryption-key")
TEST_CODE_HMAC_KEY = _test_key("test-code-hmac-key")
TEST_SECRET_ENV = {
    "JWT_SECRET": TEST_JWT_SECRET,
    "MFA_ENCRYPTION_KEY": TEST_MFA_ENCRYPTION_KEY,
    "CODE_HMAC_KEY": TEST_CODE_HMAC_KEY,
}
LOW_ARGON2 = {"argon2_memory_kib": 8, "argon2_time_cost": 1}
"""Cheap Argon2id parameters for the fast suite; one test checks the real ones."""


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "app_env": "test",
        "log_level": "INFO",
        "database_url": TEST_DATABASE_URL,
        "cors_origins": [],
        "api_docs_enabled": True,
        "jwt_secret": TEST_JWT_SECRET,
        "mfa_encryption_key": TEST_MFA_ENCRYPTION_KEY,
        "code_hmac_key": TEST_CODE_HMAC_KEY,
        **LOW_ARGON2,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)
