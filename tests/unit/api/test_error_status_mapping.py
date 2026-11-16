from http import HTTPStatus

import pytest

from insumap.api.errors import STATUS_BY_CODE, code_for_http_status, status_for
from insumap.shared.errors import ErrorCode


def test_every_error_code_has_an_http_status() -> None:
    assert set(STATUS_BY_CODE) == set(ErrorCode)


@pytest.mark.parametrize(
    ("code", "status"),
    [
        (ErrorCode.VALIDATION_ERROR, HTTPStatus.UNPROCESSABLE_ENTITY),
        (ErrorCode.NOT_FOUND, HTTPStatus.NOT_FOUND),
        (ErrorCode.UNAUTHENTICATED, HTTPStatus.UNAUTHORIZED),
        (ErrorCode.FORBIDDEN, HTTPStatus.FORBIDDEN),
        (ErrorCode.CONFLICT, HTTPStatus.CONFLICT),
        (ErrorCode.RATE_LIMITED, HTTPStatus.TOO_MANY_REQUESTS),
        (ErrorCode.PAYLOAD_TOO_LARGE, HTTPStatus.REQUEST_ENTITY_TOO_LARGE),
        (ErrorCode.INTERNAL_ERROR, HTTPStatus.INTERNAL_SERVER_ERROR),
    ],
)
def test_status_for_each_code(code: ErrorCode, status: HTTPStatus) -> None:
    assert status_for(code) == status


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (HTTPStatus.NOT_FOUND, ErrorCode.NOT_FOUND),
        (HTTPStatus.METHOD_NOT_ALLOWED, ErrorCode.NOT_FOUND),
        (HTTPStatus.UNAUTHORIZED, ErrorCode.UNAUTHENTICATED),
        (HTTPStatus.BAD_REQUEST, ErrorCode.VALIDATION_ERROR),
        (HTTPStatus.UNSUPPORTED_MEDIA_TYPE, ErrorCode.VALIDATION_ERROR),
        (HTTPStatus.SERVICE_UNAVAILABLE, ErrorCode.INTERNAL_ERROR),
    ],
)
def test_code_for_framework_http_errors(status: HTTPStatus, code: ErrorCode) -> None:
    assert code_for_http_status(status) == code
