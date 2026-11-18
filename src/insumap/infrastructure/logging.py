"""JSON logs on stdout with the request id and sensitive data masked."""

from __future__ import annotations

import json
import logging
import re
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Final, TextIO, final

from insumap.shared.request_context import current_request_id

REDACTED: Final = "[REDACTED]"
REDACTED_EMAIL: Final = "[REDACTED_EMAIL]"
REDACTED_JWT: Final = "[REDACTED_JWT]"
SENSITIVE_KEY_PARTS: Final = (
    "password",
    "passwd",
    "token",
    "authorization",
    "secret",
    "cookie",
    "api_key",
    "document_number",
    "email",
)
EMAIL_PATTERN: Final = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
JWT_PATTERN: Final = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*")
BEARER_PATTERN: Final = re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]+")
REQUEST_ID_ATTRIBUTE: Final = "request_id"
BASE_FIELDS: Final = frozenset(
    {"timestamp", "level", "logger", "message", REQUEST_ID_ATTRIBUTE, "exception"}
)
STANDARD_RECORD_ATTRIBUTES: Final = frozenset(
    vars(logging.LogRecord("", logging.NOTSET, "", 0, "", None, None))
) | {"message", "asctime", REQUEST_ID_ATTRIBUTE}
UVICORN_LOGGERS: Final = ("uvicorn", "uvicorn.error", "uvicorn.access")
TIMESTAMP_PRECISION: Final = "milliseconds"
LINE_END: Final = "\n"


@final
class SensitiveDataRedactor:
    """Masks secrets and personal data before they reach the logs.

    Values under keys such as ``password``, ``token``, ``authorization``,
    ``secret``, ``document_number`` or ``email`` are replaced, at any depth. Free
    text keeps its shape but emails, JWTs and bearer tokens inside it are masked.
    """

    def is_sensitive_key(self, key: str) -> bool:
        """Tell whether values under ``key`` must never be logged."""
        normalized = key.lower().replace("-", "_")
        return any(part in normalized for part in SENSITIVE_KEY_PARTS)

    def redact(self, key: str, value: object) -> object:
        """Return ``value`` with every sensitive part masked."""
        if self.is_sensitive_key(key):
            return REDACTED
        if isinstance(value, Mapping):
            return {
                str(inner_key): self.redact(str(inner_key), inner_value)
                for inner_key, inner_value in value.items()
            }
        if isinstance(value, list | tuple | set | frozenset):
            return [self.redact("", item) for item in value]
        if isinstance(value, str):
            return self.redact_text(value)
        return value

    def redact_text(self, text: str) -> str:
        """Mask emails, JWTs and bearer tokens inside free text."""
        text = JWT_PATTERN.sub(REDACTED_JWT, text)
        text = BEARER_PATTERN.sub(rf"\1 {REDACTED}", text)
        return EMAIL_PATTERN.sub(REDACTED_EMAIL, text)


class RedactionFilter(logging.Filter):
    """Masks sensitive data in the message, its arguments, extras and traceback.

    It is attached to the handler, so it also covers records propagated from
    libraries. The message is rendered first and then masked, because the
    arguments may carry the sensitive value.
    """

    def __init__(self, redactor: SensitiveDataRedactor | None = None) -> None:
        super().__init__()
        self._redactor = redactor or SensitiveDataRedactor()
        self._traceback_formatter = logging.Formatter()

    def filter(self, record: logging.LogRecord) -> bool:
        """Mask the record in place; never drops it."""
        for key, value in list(vars(record).items()):
            if key not in STANDARD_RECORD_ATTRIBUTES:
                setattr(record, key, self._redactor.redact(key, value))
        if isinstance(record.args, Mapping):
            record.args = {
                key: self._redactor.redact(str(key), value)
                for key, value in record.args.items()
            }
        elif record.args:
            record.args = tuple(self._redactor.redact("", arg) for arg in record.args)
        record.msg = self._redactor.redact_text(record.getMessage())
        record.args = None
        if record.exc_info and not record.exc_text:
            record.exc_text = self._traceback_formatter.formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = self._redactor.redact_text(record.exc_text)
        return True


class RequestIdFilter(logging.Filter):
    """Adds the id of the request being processed to every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Set ``record.request_id`` unless the caller already passed one."""
        if getattr(record, REQUEST_ID_ATTRIBUTE, None) is None:
            setattr(record, REQUEST_ID_ATTRIBUTE, current_request_id())
        return True


class JsonLogFormatter(logging.Formatter):
    """Formats a record as one JSON object on a single line.

    Base fields are ``timestamp`` (UTC, from the record), ``level``, ``logger``,
    ``message`` and ``request_id``; extras passed by the caller are added next to
    them and a traceback goes in ``exception``.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Return the JSON line of ``record``."""
        payload: dict[str, object] = {
            key: value
            for key, value in vars(record).items()
            if key not in STANDARD_RECORD_ATTRIBUTES and key not in BASE_FIELDS
        }
        payload.update(
            timestamp=datetime.fromtimestamp(record.created, UTC).isoformat(
                timespec=TIMESTAMP_PRECISION
            ),
            level=record.levelname,
            logger=record.name,
            message=record.getMessage(),
            request_id=getattr(record, REQUEST_ID_ATTRIBUTE, None),
        )
        if record.exc_text:
            payload["exception"] = record.exc_text
        elif record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


class JsonLineHandler(logging.Handler):
    """Writes each record as one line to a stream.

    Without an explicit stream it writes to the ``sys.stdout`` of the moment, so
    a replaced stdout (as test runners do) is always honored.
    """

    def __init__(self, stream: TextIO | None = None) -> None:
        super().__init__()
        self._stream = stream

    def emit(self, record: logging.LogRecord) -> None:
        """Write the formatted record followed by a new line."""
        try:
            stream = self._stream or sys.stdout
            stream.write(self.format(record) + LINE_END)
            stream.flush()
        except Exception:
            self.handleError(record)


@final
class JsonLoggingConfigurator:
    """Sends every log record to stdout as one JSON object per line.

    ``configure()`` installs one ``JsonLineHandler`` on the root logger, with the
    request id and redaction filters, and routes uvicorn's loggers through it.
    Calling it again replaces only the handler it installed before.
    """

    def __init__(self, level: str, stream: TextIO | None = None) -> None:
        self._level = level
        self._stream = stream

    def build_handler(self) -> JsonLineHandler:
        """Return a handler with the JSON format and both filters."""
        handler = JsonLineHandler(self._stream)
        handler.addFilter(RequestIdFilter())
        handler.addFilter(RedactionFilter())
        handler.setFormatter(JsonLogFormatter())
        return handler

    def configure(self) -> None:
        """Install the JSON handler on the root logger and set the level."""
        root = logging.getLogger()
        for handler in list(root.handlers):
            if isinstance(handler, JsonLineHandler):
                root.removeHandler(handler)
        root.addHandler(self.build_handler())
        root.setLevel(self._level)
        for name in UVICORN_LOGGERS:
            uvicorn_logger = logging.getLogger(name)
            uvicorn_logger.handlers.clear()
            uvicorn_logger.propagate = True
