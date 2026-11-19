"""The pseudonym of a patient sent to ``insumap-ai`` (Contrato-IA 4.2, security 18.1).

It is the only patient identifier that leaves the backend for the AI. The value is
derived by ``HmacPseudonymizer`` (infrastructure); the domain only checks its shape.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

SUBJECT_REF_PATTERN: Final = re.compile(r"sub_[0-9a-f]{32}")
SUBJECT_REF_PREFIX: Final = "sub_"
SUBJECT_REF_HEX_CHARS: Final = 32


@dataclass(frozen=True, slots=True)
class SubjectRef:
    """A pseudonym that matches ``^sub_[0-9a-f]{32}$``."""

    value: str

    def __post_init__(self) -> None:
        if not SUBJECT_REF_PATTERN.fullmatch(self.value):
            raise ValueError("a subject ref must match ^sub_[0-9a-f]{32}$")
