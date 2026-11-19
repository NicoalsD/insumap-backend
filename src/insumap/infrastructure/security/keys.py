"""Key rings: the current key and, during a rotation, the previous one."""

from __future__ import annotations

from typing import Final, final

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from pydantic import SecretStr

from insumap.shared.key_material import KEY_BYTES, decode_key, key_fingerprint

SUBKEY_BYTES: Final = KEY_BYTES


@final
class KeyRing:
    """The current key signs, encrypts and hashes; both verify and decrypt.

    A key is identified by its fingerprint, which is what ``kid`` and the
    ``key_id`` columns hold. A fingerprint that is no longer in the ring is a
    retired key. The previous key must differ from the current one.
    """

    def __init__(
        self, *, current: SecretStr, previous: SecretStr | None = None
    ) -> None:
        current_key = decode_key(current.get_secret_value())
        self._current_id = key_fingerprint(current_key)
        self._keys: dict[str, bytes] = {self._current_id: current_key}
        if previous is not None:
            previous_key = decode_key(previous.get_secret_value())
            previous_id = key_fingerprint(previous_key)
            if previous_id == self._current_id:
                raise ValueError("the previous key must differ from the current one")
            self._keys[previous_id] = previous_key

    @property
    def current_key_id(self) -> str:
        """Fingerprint of the key that writes."""
        return self._current_id

    def current_key(self) -> bytes:
        """The key used to sign, encrypt and hash."""
        return self._keys[self._current_id]

    def verification_key(self, key_id: str | None) -> bytes:
        """The key with this fingerprint; an unknown or missing one is ``KeyError``."""
        if key_id is None or key_id not in self._keys:
            raise KeyError("unknown key id")
        return self._keys[key_id]

    def all_keys(self) -> tuple[tuple[str, bytes], ...]:
        """Every key as ``(key_id, key)``, the current one first."""
        return tuple(self._keys.items())


def derive_subkey(root_key: bytes, info: bytes) -> bytes:
    """HKDF-SHA256 without salt: one subkey per purpose of a root key."""
    return HKDF(
        algorithm=hashes.SHA256(), length=SUBKEY_BYTES, salt=None, info=info
    ).derive(root_key)
