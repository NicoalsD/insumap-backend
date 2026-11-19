"""HMAC-SHA256 with a purpose subkey of ``APP_HMAC_KEY`` (security guide, 15.3).

Counter keys (login lockouts, rate limits) are keyed hashes, so the table never
holds an email or an address in clear text.
"""

from __future__ import annotations

import hashlib
import hmac
from enum import StrEnum
from typing import final

from insumap.infrastructure.security.keys import derive_subkey


class Subkey(StrEnum):
    """Purposes of ``APP_HMAC_KEY``; each one has its own HKDF subkey."""

    RATE_LIMIT = "rate-limit"
    PATIENT_DOCUMENT = "patient-document"
    SUBJECT_REF = "subject-ref"


@final
class SubkeyHasher:
    """HMAC-SHA256 of a message with the subkey of one purpose, derived once."""

    def __init__(self, root_key: bytes, *, subkey: Subkey) -> None:
        self._subkey = derive_subkey(
            root_key, f"insumap/app-hmac/{subkey.value}/v1".encode()
        )

    def hexdigest(self, message: str) -> str:
        """Hex digest of ``message`` (64 characters)."""
        return hmac.new(self._subkey, message.encode(), hashlib.sha256).hexdigest()
