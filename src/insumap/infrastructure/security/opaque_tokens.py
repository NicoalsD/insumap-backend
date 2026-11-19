"""Opaque 256 bit tokens, stored only as SHA-256."""

from __future__ import annotations

import hashlib
import secrets
from typing import Final, final, override

from insumap.application.identity.ports import IssuedOpaqueToken, OpaqueTokenPort

TOKEN_BYTES: Final = 32


@final
class Sha256OpaqueTokens(OpaqueTokenPort):
    """Refresh, challenge and activation tokens: random, high entropy, hashed."""

    @override
    def new_token(self) -> IssuedOpaqueToken:
        plain = secrets.token_urlsafe(TOKEN_BYTES)
        return IssuedOpaqueToken(plain=plain, token_hash=self.hash(plain))

    @override
    def hash(self, plain: str) -> str:
        return hashlib.sha256(plain.encode()).hexdigest()
