"""RFC 6238 one-time passwords with pyotp."""

from __future__ import annotations

import base64
import hmac
import secrets
from datetime import datetime
from typing import Final, final, override

import pyotp

from insumap.application.identity.ports import TotpPort

SECRET_BYTES: Final = 20
DIGITS: Final = 6
STEP_SECONDS: Final = 30
ISSUER: Final = "Insumap"


@final
class PyOtpTotp(TotpPort):
    """HMAC-SHA1, 6 digits, 30 second steps and a secret of 160 bits.

    ``valid_window`` steps on each side of the current one are accepted. A step
    at or before ``last_used_step`` is a replay and is refused.
    """

    def __init__(self, *, valid_window: int) -> None:
        self._window = valid_window

    @override
    def new_secret(self) -> str:
        return base64.b32encode(secrets.token_bytes(SECRET_BYTES)).decode()

    @override
    def provisioning_uri(self, secret: str, account_name: str) -> str:
        return pyotp.TOTP(
            secret, digits=DIGITS, interval=STEP_SECONDS
        ).provisioning_uri(name=account_name, issuer_name=ISSUER)

    @override
    def verify(
        self, secret: str, code: str, *, now: datetime, last_used_step: int | None
    ) -> int | None:
        totp = pyotp.TOTP(secret, digits=DIGITS, interval=STEP_SECONDS)
        current = int(now.timestamp()) // STEP_SECONDS
        accepted: int | None = None
        for step in range(current - self._window, current + self._window + 1):
            matches = hmac.compare_digest(totp.at(step * STEP_SECONDS), code)
            replayed = last_used_step is not None and step <= last_used_step
            if matches and not replayed and accepted is None:
                accepted = step
        return accepted
