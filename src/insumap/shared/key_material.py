"""Format and fingerprint of the 32 byte keys read from the environment."""

import base64
import binascii
import hashlib
from typing import Final

KEY_BYTES: Final = 32
FINGERPRINT_PREFIX: Final = b"insumap-key-id|"
FINGERPRINT_HEX_CHARS: Final = 16
BASE64_PADDING_UNIT: Final = 4
STANDARD_ALPHABET_FIX: Final = str.maketrans("-_", "+/")


def decode_key(encoded: str) -> bytes:
    """Decode standard or url-safe base64 into exactly ``KEY_BYTES`` bytes.

    The error never echoes the value.
    """
    text = encoded.strip().translate(STANDARD_ALPHABET_FIX)
    text += "=" * (-len(text) % BASE64_PADDING_UNIT)
    try:
        raw = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("the key is not valid base64") from None
    if len(raw) != KEY_BYTES:
        raise ValueError(f"the key must decode to {KEY_BYTES} bytes")
    return raw


def key_fingerprint(key: bytes) -> str:
    """Public identifier of a key (``key_id`` columns, JWT ``kid``)."""
    return hashlib.sha256(FINGERPRINT_PREFIX + key).hexdigest()[:FINGERPRINT_HEX_CHARS]
