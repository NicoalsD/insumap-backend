"""Opaque cursor pagination (``docs/API.md``, section 3).

Listings order by the UUIDv7 primary key, which grows with the creation time,
so the cursor is just the last key the client saw. The cursor is opaque to the
client: it is encoded, never composed or parsed by hand.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from insumap.shared.errors import ErrorCode, InsumapError

CURSOR_FIELD: Final = "query.cursor"


@dataclass(frozen=True, slots=True, kw_only=True)
class PageRequest:
    """``limit`` rows after the row the cursor points at (``None``: from the start)."""

    limit: int
    after: UUID | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Page[T]:
    """A page of rows and the cursor of the next one (``None`` on the last page)."""

    items: Sequence[T]
    next_cursor: str | None


def encode_cursor(key: UUID) -> str:
    """The opaque cursor that points after ``key``."""
    return base64.urlsafe_b64encode(key.bytes).decode().rstrip("=")


def decode_cursor(cursor: str | None) -> UUID | None:
    """The key a cursor points after; an invalid cursor is a ``422``."""
    if cursor is None:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        return UUID(bytes=base64.urlsafe_b64decode(padded.encode()))
    except (ValueError, binascii.Error):
        raise InsumapError(
            ErrorCode.VALIDATION_ERROR,
            detail={"errors": [{"field": CURSOR_FIELD, "type": "invalid_cursor"}]},
        ) from None


def build_page[T](
    rows: Sequence[T], *, limit: int, key: Callable[[T], UUID]
) -> Page[T]:
    """Cut ``rows`` (fetched with ``limit + 1``) into a page and its next cursor."""
    items = list(rows[:limit])
    more = len(rows) > limit
    return Page(
        items=items, next_cursor=encode_cursor(key(items[-1])) if more else None
    )
