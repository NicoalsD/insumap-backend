"""Business errors of the identity module. Messages live in ``messages_es``."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final, final

from insumap.shared.errors import ErrorCode, InsumapError

ERRORS_DETAIL_KEY: Final = "errors"
PASSWORD_FIELD: Final = "body.new_password"  # noqa: S105 - field path, not a secret


@final
class InvalidCredentialsError(InsumapError):
    """Wrong email, password, TOTP or recovery code: one generic answer."""

    def __init__(self) -> None:
        super().__init__(ErrorCode.INVALID_CREDENTIALS)


@final
class UnauthenticatedError(InsumapError):
    """Missing, malformed, expired or unknown token or challenge."""

    def __init__(self) -> None:
        super().__init__(ErrorCode.UNAUTHENTICATED)


@final
class SessionRevokedError(InsumapError):
    """The session ended: token version changed, account inactive or reuse."""

    def __init__(self) -> None:
        super().__init__(ErrorCode.SESSION_REVOKED)


@final
class AccountNotActiveError(InsumapError):
    """Correct password, but the account is suspended or deactivated."""

    def __init__(self) -> None:
        super().__init__(ErrorCode.ACCOUNT_NOT_ACTIVE)


@final
class ClinicSuspendedError(InsumapError):
    """Correct password or open session, but the clinic is suspended."""

    def __init__(self) -> None:
        super().__init__(ErrorCode.CLINIC_SUSPENDED)


@final
class MfaRequiredError(InsumapError):
    """A staff session without a verified second factor."""

    def __init__(self) -> None:
        super().__init__(ErrorCode.MFA_REQUIRED)


@final
class PermissionDeniedError(InsumapError):
    """The role lacks the permission, or the action does not apply to it."""

    def __init__(self) -> None:
        super().__init__(ErrorCode.FORBIDDEN)


@final
class InvitationInvalidError(InsumapError):
    """The one error of every activation failure: nothing tells the cause apart."""

    def __init__(self) -> None:
        super().__init__(ErrorCode.INVITATION_INVALID)


@final
class ConsentRequiredError(InsumapError):
    """The privacy notice was not accepted."""

    def __init__(self) -> None:
        super().__init__(ErrorCode.CONSENT_REQUIRED)


@final
class ConsentVersionOutdatedError(InsumapError):
    """The accepted privacy notice version is not the current one."""

    def __init__(self) -> None:
        super().__init__(ErrorCode.CONSENT_VERSION_OUTDATED)


@final
class EmailUnavailableError(InsumapError):
    """The email already belongs to another account."""

    def __init__(self) -> None:
        super().__init__(ErrorCode.EMAIL_UNAVAILABLE)


@final
class InvalidStateTransitionError(InsumapError):
    """A state machine (P18) refused an action in its current state."""

    def __init__(self, machine: str, status: str, action: str) -> None:
        super().__init__(
            ErrorCode.INVALID_STATE_TRANSITION,
            detail={"machine": machine, "status": status, "action": action},
        )


@final
class PasswordPolicyError(InsumapError):
    """A new password breaks the policy; every violated rule is listed."""

    def __init__(self, violations: Sequence[str]) -> None:
        self.violations = tuple(violations)
        super().__init__(
            ErrorCode.VALIDATION_ERROR,
            detail={
                ERRORS_DETAIL_KEY: [
                    {"field": PASSWORD_FIELD, "type": "password_policy", "code": code}
                    for code in self.violations
                ]
            },
        )
