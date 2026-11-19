"""Vocabulary of a session: login outcomes and authentication methods."""

from enum import StrEnum


class LoginStatus(StrEnum):
    """Outcome of a successful password check (API.md, section 2.3)."""

    AUTHENTICATED = "AUTHENTICATED"
    MFA_CHALLENGE = "MFA_CHALLENGE"
    MFA_ENROLLMENT_REQUIRED = "MFA_ENROLLMENT_REQUIRED"


class AuthenticationMethod(StrEnum):
    """Values of the ``amr`` claim."""

    PASSWORD = "pwd"  # noqa: S105 - enum value, not a secret
    ONE_TIME_PASSWORD = "otp"  # noqa: S105 - enum value, not a secret
