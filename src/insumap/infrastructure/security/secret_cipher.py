"""AES-256-GCM for the secrets the system must read back (the TOTP secret)."""

from __future__ import annotations

import secrets
from typing import Final, final, override

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from insumap.application.identity.ports import EncryptedSecret, SecretCipherPort
from insumap.infrastructure.security.keys import KeyRing

NONCE_BYTES: Final = 12
TAG_BYTES: Final = 16


class SecretDecryptionError(Exception):
    """Wrong binding, altered ciphertext or retired key. Never carries the value."""


@final
class AesGcmSecretCipher(SecretCipherPort):
    """Stores ``nonce || ciphertext || tag`` bound to its row by the AAD."""

    def __init__(self, keys: KeyRing) -> None:
        self._keys = keys

    @override
    def encrypt(self, plain: str, *, associated_data: str) -> EncryptedSecret:
        nonce = secrets.token_bytes(NONCE_BYTES)
        sealed = AESGCM(self._keys.current_key()).encrypt(
            nonce, plain.encode(), associated_data.encode()
        )
        return EncryptedSecret(
            ciphertext=nonce + sealed, key_id=self._keys.current_key_id
        )

    @override
    def decrypt(self, secret: EncryptedSecret, *, associated_data: str) -> str:
        blob = secret.ciphertext
        if len(blob) < NONCE_BYTES + TAG_BYTES:
            raise SecretDecryptionError
        try:
            key = self._keys.verification_key(secret.key_id)
            return (
                AESGCM(key)
                .decrypt(
                    blob[:NONCE_BYTES], blob[NONCE_BYTES:], associated_data.encode()
                )
                .decode()
            )
        except (KeyError, InvalidTag, UnicodeDecodeError):
            raise SecretDecryptionError from None
