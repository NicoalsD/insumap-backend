"""Path prefixes of the API."""

from typing import Final

API_V1_PREFIX: Final = "/api/v1"
"""Prefix of every versioned endpoint; ``/health`` and ``/ready`` live outside."""

AUTH_PREFIX: Final = f"{API_V1_PREFIX}/auth"
"""Prefix of the authentication endpoints; the refresh cookie is scoped to it."""
