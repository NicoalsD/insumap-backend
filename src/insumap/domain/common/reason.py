"""The reason that accompanies a decision (RF-70)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self

from insumap.domain.common.errors import ReasonRequiredError
from insumap.shared.field_limits import FieldLimits


@dataclass(frozen=True, slots=True)
class Reason:
    """A trimmed text of ``REASON_MIN_LENGTH`` to ``REASON_MAX_LENGTH`` characters."""

    text: str

    @classmethod
    def parse(cls, raw: str | None) -> Self:
        """Trim ``raw`` and check its length; raise ``ReasonRequiredError``."""
        text = (raw or "").strip()
        if (
            not FieldLimits.REASON_MIN_LENGTH
            <= len(text)
            <= FieldLimits.REASON_MAX_LENGTH
        ):
            raise ReasonRequiredError
        return cls(text)
