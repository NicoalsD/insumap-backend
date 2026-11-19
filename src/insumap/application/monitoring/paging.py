"""Cursor pagination of the record listings: an opaque, signed-free position."""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Final, final
from uuid import UUID

from insumap.shared.errors import ErrorCode, InsumapError

CURSOR_FIELD: Final = "query.cursor"


def invalid_cursor() -> InsumapError:
    """The canonical ``422`` of a cursor nobody issued."""
    return InsumapError(
        ErrorCode.VALIDATION_ERROR,
        detail={"errors": [{"field": CURSOR_FIELD, "type": "invalid_cursor"}]},
    )


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class Cursor:
    """Position after the last item of a page: (instant, id), newest first."""

    at: datetime
    id: UUID

    def encode(self) -> str:
        """The opaque text the client sends back."""
        raw = json.dumps({"at": self.at.isoformat(), "id": str(self.id)})
        return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")

    @classmethod
    def decode(cls, text: str) -> Cursor:
        """Read a cursor; anything that is not one is ``VALIDATION_ERROR``."""
        try:
            padded = text + "=" * (-len(text) % 4)
            data = json.loads(base64.urlsafe_b64decode(padded.encode()))
            at = datetime.fromisoformat(data["at"])
            if at.tzinfo is None:
                raise ValueError("naive instant")
            return cls(at=at, id=UUID(data["id"]))
        except (
            binascii.Error,
            ValueError,
            KeyError,
            TypeError,
            UnicodeDecodeError,
        ) as error:
            raise invalid_cursor() from error


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class PageQuery:
    """Filters and page of a listing; ``cursor`` is ``None`` on the first page."""

    limit: int
    cursor: Cursor | None = None
    start: datetime | None = None
    end: datetime | None = None


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class Page[T]:
    """One page and the cursor of the next one (``None`` on the last page)."""

    items: tuple[T, ...]
    next_cursor: str | None
