"""Settings for tests, isolated from the environment and from any local .env."""

from typing import Any

from insumap.shared.config import Settings

TEST_DATABASE_URL = "postgresql://insumap_app@localhost:5432/insumap_test"


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "app_env": "test",
        "log_level": "INFO",
        "database_url": TEST_DATABASE_URL,
        "cors_origins": [],
        "api_docs_enabled": True,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)
