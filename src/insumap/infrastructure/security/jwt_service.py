"""Signed access tokens (JWT HS256) with ``kid`` and ``Clock`` based validity."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Final, final, override

import jwt
from jwt import InvalidTokenError

from insumap.application.identity.ports import (
    AccessClaims,
    AccessGrant,
    IssuedAccessToken,
    TokenIssuerPort,
)
from insumap.domain.identity.errors import UnauthenticatedError
from insumap.domain.identity.roles import Role
from insumap.infrastructure.security.keys import KeyRing
from insumap.shared.time import Clock

ALGORITHM: Final = "HS256"
REQUIRED_CLAIMS: Final = (
    "iss",
    "aud",
    "sub",
    "role",
    "tv",
    "amr",
    "jti",
    "iat",
    "nbf",
    "exp",
)
"""PyJWT treats a ``null`` as missing, so ``clinic_id`` and ``sid``, which may be
``null``, are required by key in ``_claims`` instead."""


@dataclass(frozen=True, slots=True, kw_only=True)
class JwtConfig:
    """Issuer, audience, lifetime and clock tolerance of the access tokens."""

    issuer: str
    audience: str
    access_ttl: timedelta
    leeway: timedelta


@final
class JwtTokenService(TokenIssuerPort):
    """Signs with the current key and verifies with the current or previous one.

    PyJWT would read the system clock for ``exp``, ``nbf`` and ``iat``; those
    checks are turned off and made here with the injected ``Clock``. Any failure
    is the same ``UnauthenticatedError``.
    """

    def __init__(self, *, keys: KeyRing, config: JwtConfig, clock: Clock) -> None:
        self._keys = keys
        self._config = config
        self._clock = clock

    @override
    def issue(self, grant: AccessGrant) -> IssuedAccessToken:
        now = self._clock.now()
        expires_at = now + self._config.access_ttl
        claims: dict[str, object] = {
            "iss": self._config.issuer,
            "aud": self._config.audience,
            "sub": str(grant.user_id),
            "role": grant.role.value,
            "clinic_id": None if grant.clinic_id is None else str(grant.clinic_id),
            "tv": grant.token_version,
            "sid": None if grant.session_id is None else str(grant.session_id),
            "amr": list(grant.amr),
            "jti": uuid.uuid4().hex,
            "iat": int(now.timestamp()),
            "nbf": int(now.timestamp()),
            "exp": int(expires_at.timestamp()),
        }
        token = jwt.encode(
            claims,
            self._keys.current_key(),
            algorithm=ALGORITHM,
            headers={"kid": self._keys.current_key_id},
        )
        return IssuedAccessToken(token=token, expires_at=expires_at)

    @override
    def decode(self, token: str) -> AccessClaims:
        try:
            header = jwt.get_unverified_header(token)
            key = self._keys.verification_key(header.get("kid"))
            payload = jwt.decode(
                token,
                key,
                algorithms=[ALGORITHM],
                issuer=self._config.issuer,
                audience=self._config.audience,
                options={
                    "require": list(REQUIRED_CLAIMS),
                    "verify_exp": False,
                    "verify_nbf": False,
                    "verify_iat": False,
                },
            )
            self._check_times(payload)
            return self._claims(payload)
        except (InvalidTokenError, KeyError, ValueError, TypeError):
            raise UnauthenticatedError from None

    def _check_times(self, payload: Mapping[str, object]) -> None:
        now = self._clock.now().timestamp()
        leeway = self._config.leeway.total_seconds()
        exp, nbf, iat = (_number(payload[name]) for name in ("exp", "nbf", "iat"))
        if now - leeway >= exp or nbf - leeway > now or iat - leeway > now:
            raise UnauthenticatedError

    @staticmethod
    def _claims(payload: Mapping[str, object]) -> AccessClaims:
        clinic, session, amr = payload["clinic_id"], payload["sid"], payload["amr"]
        if not isinstance(amr, list):
            raise TypeError("amr must be a list")
        return AccessClaims(
            user_id=uuid.UUID(str(payload["sub"])),
            role=Role(str(payload["role"])),
            clinic_id=None if clinic is None else uuid.UUID(str(clinic)),
            token_version=_integer(payload["tv"]),
            session_id=None if session is None else uuid.UUID(str(session)),
            amr=tuple(str(item) for item in amr),
            token_id=str(payload["jti"]),
        )


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError("time claims must be numbers")
    return float(value)


def _integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("tv must be an integer")
    return value
