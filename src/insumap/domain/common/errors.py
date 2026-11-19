"""Business errors every module shares. Messages live in ``messages_es``."""

from __future__ import annotations

from typing import final

from insumap.shared.errors import ErrorCode, InsumapError


@final
class ResourceNotFoundError(InsumapError):
    """The resource does not exist, belongs to another clinic or is not visible.

    One error, one body: it never tells apart a missing resource from one the
    caller may not see (for example a patient who is not assigned).
    """

    def __init__(self) -> None:
        super().__init__(ErrorCode.NOT_FOUND)


@final
class ConflictError(InsumapError):
    """The request clashes with the current state of the resource (``409``)."""

    def __init__(self, reason: str) -> None:
        super().__init__(ErrorCode.CONFLICT, detail={"reason": reason})


@final
class ReasonRequiredError(InsumapError):
    """A reason of the allowed length is required (suspensions, withdrawals...)."""

    def __init__(self) -> None:
        super().__init__(ErrorCode.REASON_REQUIRED)
