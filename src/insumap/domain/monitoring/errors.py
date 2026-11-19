"""Business errors of the patient records. Messages live in ``messages_es``."""

from __future__ import annotations

from typing import final

from insumap.shared.errors import ErrorCode, InsumapError


@final
class ReasonRequiredError(InsumapError):
    """A correction or annulment without a reason of the allowed length."""

    def __init__(self) -> None:
        super().__init__(ErrorCode.REASON_REQUIRED)


@final
class GlucoseOutOfRangeError(InsumapError):
    """The value is outside the measurable range of the clinic: nothing is saved."""

    def __init__(self) -> None:
        super().__init__(ErrorCode.GLUCOSE_OUT_OF_RANGE)


@final
class ReadingInFutureError(InsumapError):
    """The timestamp is past the future tolerance."""

    def __init__(self) -> None:
        super().__init__(ErrorCode.READING_IN_FUTURE)


@final
class ReadingTooOldError(InsumapError):
    """The timestamp is older than the maximum delay."""

    def __init__(self) -> None:
        super().__init__(ErrorCode.READING_TOO_OLD)


@final
class UnsupportedMediaTypeError(InsumapError):
    """The request content type is not accepted by the endpoint."""

    def __init__(self) -> None:
        super().__init__(ErrorCode.UNSUPPORTED_MEDIA_TYPE)
