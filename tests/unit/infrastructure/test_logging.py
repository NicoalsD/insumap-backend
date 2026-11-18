import io
import json
import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest

from insumap.infrastructure.logging import (
    REDACTED,
    REDACTED_EMAIL,
    REDACTED_JWT,
    JsonLineHandler,
    JsonLoggingConfigurator,
    SensitiveDataRedactor,
)
from insumap.shared.request_context import bind_request_id, unbind_request_id

FAKE_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.c2lnbmF0dXJl"
EMAIL = "ana.perez@example.test"


@pytest.fixture
def stream() -> io.StringIO:
    return io.StringIO()


@pytest.fixture
def logger(stream: io.StringIO) -> Iterator[logging.Logger]:
    test_logger = logging.getLogger("tests.insumap.logging")
    test_logger.setLevel(logging.DEBUG)
    test_logger.propagate = False
    handler = JsonLoggingConfigurator("DEBUG", stream).build_handler()
    test_logger.addHandler(handler)
    yield test_logger
    test_logger.removeHandler(handler)


@pytest.fixture
def restore_root_logger() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


def lines(stream: io.StringIO) -> list[dict[str, Any]]:
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_writes_one_json_object_per_line(
    logger: logging.Logger, stream: io.StringIO
) -> None:
    logger.info("first")
    logger.warning("second %s", "line")

    first, second = lines(stream)
    assert first["message"] == "first"
    assert first["level"] == "INFO"
    assert first["logger"] == "tests.insumap.logging"
    assert first["request_id"] is None
    assert second["message"] == "second line"
    assert second["level"] == "WARNING"


def test_timestamp_is_utc_iso_8601_from_the_record(
    logger: logging.Logger, stream: io.StringIO
) -> None:
    logger.info("hello")

    timestamp = datetime.fromisoformat(lines(stream)[0]["timestamp"])
    assert timestamp.utcoffset() is not None
    assert timestamp.tzinfo == UTC


def test_includes_the_request_id_of_the_current_request(
    logger: logging.Logger, stream: io.StringIO
) -> None:
    token = bind_request_id("req-123")
    try:
        logger.info("inside")
    finally:
        unbind_request_id(token)
    logger.info("outside")

    inside, outside = lines(stream)
    assert inside["request_id"] == "req-123"
    assert outside["request_id"] is None


def test_explicit_request_id_wins_over_the_context(
    logger: logging.Logger, stream: io.StringIO
) -> None:
    logger.error("failed", extra={"request_id": "req-explicit"})

    assert lines(stream)[0]["request_id"] == "req-explicit"


def test_extras_are_logged_with_sensitive_keys_masked(
    logger: logging.Logger, stream: io.StringIO
) -> None:
    logger.info(
        "login attempt",
        extra={
            "clinic_id": 7,
            "password": "hunter2",
            "user_email": EMAIL,
            "document_number": "1234567890",
            "headers": {"Authorization": f"Bearer {FAKE_JWT}", "Accept": "json"},
            "tokens": [{"refresh_token": "opaque"}],
        },
    )

    record = lines(stream)[0]
    assert record["clinic_id"] == 7
    assert record["password"] == REDACTED
    assert record["user_email"] == REDACTED
    assert record["document_number"] == REDACTED
    assert record["headers"] == {"Authorization": REDACTED, "Accept": "json"}
    assert record["tokens"] == REDACTED
    assert "hunter2" not in stream.getvalue()


def test_emails_jwts_and_bearer_tokens_are_masked_in_messages(
    logger: logging.Logger, stream: io.StringIO
) -> None:
    logger.info("user %s sent %s", EMAIL, FAKE_JWT)
    logger.info("header was Bearer abc.def-123")

    first, second = lines(stream)
    assert first["message"] == f"user {REDACTED_EMAIL} sent {REDACTED_JWT}"
    assert second["message"] == f"header was Bearer {REDACTED}"


def test_mapping_arguments_are_masked_by_key(
    logger: logging.Logger, stream: io.StringIO
) -> None:
    logger.info("payload %s", {"password": "hunter2", "name": "Ana"})
    logger.info("%(password)s for %(clinic)s", {"password": "hunter2", "clinic": 7})

    first, second = lines(stream)
    assert "hunter2" not in stream.getvalue()
    assert REDACTED in first["message"]
    assert second["message"] == f"{REDACTED} for 7"


def test_tracebacks_are_logged_and_masked(
    logger: logging.Logger, stream: io.StringIO
) -> None:
    try:
        raise ValueError(f"duplicated {EMAIL}")
    except ValueError:
        logger.exception("could not import")

    record = lines(stream)[0]
    assert "ValueError" in record["exception"]
    assert REDACTED_EMAIL in record["exception"]
    assert EMAIL not in stream.getvalue()


def test_unserializable_extras_fall_back_to_their_text(
    logger: logging.Logger, stream: io.StringIO
) -> None:
    logger.info("at", extra={"when": datetime(2026, 1, 15, tzinfo=UTC)})

    assert lines(stream)[0]["when"] == "2026-01-15 00:00:00+00:00"


@pytest.mark.parametrize(
    "key",
    ["password", "new_password", "Authorization", "client-secret", "access_token"],
)
def test_sensitive_key_detection(key: str) -> None:
    assert SensitiveDataRedactor().is_sensitive_key(key)


def test_regular_keys_are_not_sensitive() -> None:
    assert not SensitiveDataRedactor().is_sensitive_key("clinic_id")


def test_configure_installs_a_single_handler_and_keeps_others(
    restore_root_logger: None,
) -> None:
    root = logging.getLogger()
    foreign = logging.NullHandler()
    root.addHandler(foreign)

    JsonLoggingConfigurator("WARNING").configure()
    JsonLoggingConfigurator("DEBUG").configure()

    ours = [
        handler for handler in root.handlers if isinstance(handler, JsonLineHandler)
    ]
    assert len(ours) == 1
    assert foreign in root.handlers
    assert root.level == logging.DEBUG


def test_configure_routes_uvicorn_logs_through_the_root(
    restore_root_logger: None,
) -> None:
    logging.getLogger("uvicorn.access").addHandler(logging.NullHandler())

    JsonLoggingConfigurator("INFO").configure()

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        assert logging.getLogger(name).handlers == []
        assert logging.getLogger(name).propagate is True


def test_handler_writes_to_the_current_stdout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    handler = JsonLoggingConfigurator("INFO").build_handler()
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "to stdout", None, None)

    handler.handle(record)

    assert json.loads(capsys.readouterr().out)["message"] == "to stdout"


def test_handler_reports_write_failures_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed = io.StringIO()
    closed.close()
    reported: list[logging.LogRecord] = []
    handler = JsonLineHandler(closed)
    monkeypatch.setattr(handler, "handleError", reported.append)
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "lost", None, None)

    handler.emit(record)

    assert reported == [record]
