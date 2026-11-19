"""Human typed codes: activation codes and MFA recovery codes.

Both use the Crockford base32 alphabet, which leaves out ``I``, ``L``, ``O`` and
``U``. Input is normalized before it is hashed: trimmed, upper case, without
spaces or dashes, ``O`` read as ``0`` and ``I`` or ``L`` read as ``1``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Self

from insumap.shared.field_limits import FieldLimits

CROCKFORD_ALPHABET: Final = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
CONFUSABLE_CHARACTERS: Final = str.maketrans({"O": "0", "I": "1", "L": "1"})
GROUP_SEPARATOR: Final = "-"
_ALPHABET_SET: Final = frozenset(CROCKFORD_ALPHABET)


def normalize_crockford(raw: str, *, length: int) -> str | None:
    """Return the canonical code, or ``None`` if ``raw`` cannot be one."""
    cleaned = (
        "".join(raw.split())
        .replace(GROUP_SEPARATOR, "")
        .upper()
        .translate(CONFUSABLE_CHARACTERS)
    )
    if len(cleaned) != length or not set(cleaned) <= _ALPHABET_SET:
        return None
    return cleaned


def format_in_groups(code: str, *, group_size: int) -> str:
    """Return ``code`` split in dash separated groups (``XXXX-XXXX-...``)."""
    return GROUP_SEPARATOR.join(
        code[start : start + group_size] for start in range(0, len(code), group_size)
    )


@dataclass(frozen=True, slots=True)
class ActivationCode:
    """A normalized activation code: 16 Crockford characters (80 bits)."""

    value: str

    @classmethod
    def parse(cls, raw: str) -> Self | None:
        """Normalize user input; ``None`` if it is not a well formed code."""
        normalized = normalize_crockford(raw, length=FieldLimits.ACTIVATION_CODE_LENGTH)
        return None if normalized is None else cls(normalized)

    def formatted(self) -> str:
        """``XXXX-XXXX-XXXX-XXXX``, as printed on the activation sheet."""
        return format_in_groups(
            self.value, group_size=FieldLimits.ACTIVATION_CODE_GROUP_SIZE
        )


@dataclass(frozen=True, slots=True)
class RecoveryCode:
    """A normalized MFA recovery code: 10 Crockford characters (50 bits)."""

    value: str

    @classmethod
    def parse(cls, raw: str) -> Self | None:
        """Normalize user input; ``None`` if it is not a well formed code."""
        normalized = normalize_crockford(raw, length=FieldLimits.RECOVERY_CODE_LENGTH)
        return None if normalized is None else cls(normalized)

    def formatted(self) -> str:
        """``XXXXX-XXXXX``, as shown once after the MFA enrollment."""
        return format_in_groups(
            self.value, group_size=FieldLimits.RECOVERY_CODE_GROUP_SIZE
        )
