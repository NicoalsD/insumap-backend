"""Text typed by people: normalized and bounded before it is stored."""

from __future__ import annotations

import unicodedata
from typing import Final

from insumap.shared.errors import ErrorCode, InsumapError

NORMALIZATION_FORM: Final = "NFKC"
BLANK: Final = "blank"
TOO_LONG: Final = "too_long"


def clean_text(raw: str, *, field: str, max_length: int) -> str:
    """NFKC and trimmed; a blank or over long text is a ``422`` on ``field``."""
    text = unicodedata.normalize(NORMALIZATION_FORM, raw).strip()
    if not text:
        raise invalid_field(field, BLANK)
    if len(text) > max_length:
        raise invalid_field(field, TOO_LONG)
    return text


def invalid_field(field: str, kind: str) -> InsumapError:
    """The canonical ``422`` for one invalid body field."""
    return InsumapError(
        ErrorCode.VALIDATION_ERROR,
        detail={"errors": [{"field": field, "type": kind}]},
    )
