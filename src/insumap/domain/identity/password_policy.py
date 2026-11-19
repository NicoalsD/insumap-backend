"""Policy for new passwords (``docs/Seguridad.md``, section 2.1).

Length is measured in Unicode code points after NFKC. There are no composition
rules. A password is rejected when it is in the list of common passwords or
when it contains a fragment of the personal data of its owner. The history of
the last passwords is checked by the use case through a port, with the hasher.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, final

from insumap.domain.identity.errors import PasswordPolicyError

NORMALIZATION_FORM: Final = "NFKC"
MIN_PERSONAL_FRAGMENT: Final = 4
"""Shortest fragment of personal data that a password may not contain."""


class PasswordViolation(StrEnum):
    """Stable code of each broken rule, sent in ``detail.errors[].code``."""

    TOO_SHORT = "PASSWORD_TOO_SHORT"
    TOO_LONG = "PASSWORD_TOO_LONG"
    TOO_COMMON = "PASSWORD_TOO_COMMON"
    CONTAINS_PERSONAL_DATA = "PASSWORD_CONTAINS_PERSONAL_DATA"
    REUSED = "PASSWORD_REUSED"


@dataclass(frozen=True, slots=True, kw_only=True)
class PersonalData:
    """Personal data a password may not contain (any field may be empty)."""

    email_local_part: str = ""
    full_name: str = ""
    document_number: str = ""


def normalize_password(plain: str) -> str:
    """Return the password in NFKC, the form that is measured and hashed."""
    return unicodedata.normalize(NORMALIZATION_FORM, plain)


@final
class PasswordPolicy:
    """Length, common password and personal data rules for a new password."""

    def __init__(
        self, *, min_length: int, max_length: int, common_passwords: Iterable[str]
    ) -> None:
        self._min_length = min_length
        self._max_length = max_length
        self._common = frozenset(
            normalize_password(word).casefold() for word in common_passwords
        )

    def violations(
        self, candidate: str, personal: PersonalData
    ) -> tuple[PasswordViolation, ...]:
        """Return every rule ``candidate`` breaks, in a stable order."""
        normalized = normalize_password(candidate)
        found: list[PasswordViolation] = []
        if len(normalized) < self._min_length:
            found.append(PasswordViolation.TOO_SHORT)
        if len(normalized) > self._max_length:
            found.append(PasswordViolation.TOO_LONG)
        folded = normalized.casefold()
        if folded in self._common:
            found.append(PasswordViolation.TOO_COMMON)
        if _contains_personal_data(folded, personal):
            found.append(PasswordViolation.CONTAINS_PERSONAL_DATA)
        return tuple(found)

    def ensure_acceptable(
        self, candidate: str, personal: PersonalData, *, reused: bool = False
    ) -> None:
        """Raise ``PasswordPolicyError`` listing every broken rule, if any."""
        found = list(self.violations(candidate, personal))
        if reused:
            found.append(PasswordViolation.REUSED)
        if found:
            raise PasswordPolicyError([violation.value for violation in found])


def _contains_personal_data(folded_password: str, personal: PersonalData) -> bool:
    for source in (
        personal.email_local_part,
        *personal.full_name.split(),
        personal.document_number,
    ):
        text = normalize_password(source).casefold()
        for start in range(len(text) - MIN_PERSONAL_FRAGMENT + 1):
            if text[start : start + MIN_PERSONAL_FRAGMENT] in folded_password:
                return True
    return False
