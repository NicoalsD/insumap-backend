import pytest

from insumap.domain.identity import errors
from insumap.shared.errors import ErrorCode, InsumapError


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (errors.InvalidCredentialsError(), ErrorCode.INVALID_CREDENTIALS),
        (errors.UnauthenticatedError(), ErrorCode.UNAUTHENTICATED),
        (errors.SessionRevokedError(), ErrorCode.SESSION_REVOKED),
        (errors.AccountNotActiveError(), ErrorCode.ACCOUNT_NOT_ACTIVE),
        (errors.ClinicSuspendedError(), ErrorCode.CLINIC_SUSPENDED),
        (errors.MfaRequiredError(), ErrorCode.MFA_REQUIRED),
        (errors.PermissionDeniedError(), ErrorCode.FORBIDDEN),
        (errors.InvitationInvalidError(), ErrorCode.INVITATION_INVALID),
        (errors.ConsentRequiredError(), ErrorCode.CONSENT_REQUIRED),
        (errors.ConsentVersionOutdatedError(), ErrorCode.CONSENT_VERSION_OUTDATED),
        (errors.EmailUnavailableError(), ErrorCode.EMAIL_UNAVAILABLE),
    ],
)
def test_each_error_carries_its_code_and_default_message(
    error: InsumapError, code: ErrorCode
) -> None:
    assert error.code is code
    assert error.message_key == code.default_message_key
    assert error.detail == {}
