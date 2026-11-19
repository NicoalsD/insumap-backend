"""Email addresses used as login identifiers."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Final

NORMALIZATION_FORM: Final = "NFKC"


@dataclass(frozen=True, slots=True, kw_only=True)
class EmailAddress:
    """An email as typed and its normalized form (NFKC, trimmed, lower case).

    The normalized form is the login identifier (``iam.users.email_normalized``);
    the original is kept as typed (``iam.users.email``).
    """

    original: str
    normalized: str

    @classmethod
    def from_input(cls, raw: str) -> EmailAddress:
        """Build the address from user input."""
        trimmed = unicodedata.normalize(NORMALIZATION_FORM, raw).strip()
        return cls(original=trimmed, normalized=trimmed.lower())

    @property
    def local_part(self) -> str:
        """Text before the ``@`` of the normalized address."""
        return self.normalized.partition("@")[0]
