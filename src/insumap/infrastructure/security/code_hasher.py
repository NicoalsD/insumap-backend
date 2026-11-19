"""Keyed HMAC of the codes people type (activation and recovery)."""

from __future__ import annotations

import hashlib
import hmac
from typing import final, override

from insumap.application.identity.ports import CodeHasherPort, CodePurpose, KeyedHash
from insumap.infrastructure.security.keys import KeyRing, derive_subkey

INFO_TEMPLATE = "insumap/code-hmac/{purpose}/v1"


def _subkey(root_key: bytes, purpose: CodePurpose) -> bytes:
    info = INFO_TEMPLATE.format(purpose=purpose.value.lower())
    return derive_subkey(root_key, info.encode())


def _hmac_hex(subkey: bytes, code: str) -> str:
    return hmac.new(subkey, code.encode(), hashlib.sha256).hexdigest()


@final
class HmacCodeHasher(CodeHasherPort):
    """HMAC-SHA256 with one HKDF subkey per purpose of the code key.

    A code is stored with the current key and looked up with every key of the
    ring, current first, so a rotation never locks out a pending code.
    """

    def __init__(self, keys: KeyRing) -> None:
        self._keys = keys

    @override
    def hash_for_storage(self, purpose: CodePurpose, code: str) -> KeyedHash:
        subkey = _subkey(self._keys.current_key(), purpose)
        return KeyedHash(
            value=_hmac_hex(subkey, code), key_id=self._keys.current_key_id
        )

    @override
    def hashes_for_lookup(self, purpose: CodePurpose, code: str) -> list[str]:
        return [
            _hmac_hex(_subkey(key, purpose), code) for _, key in self._keys.all_keys()
        ]
