"""Argon2id password hashing."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import final, override

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from insumap.application.identity.ports import PasswordHasherPort
from insumap.domain.identity.password_policy import normalize_password


@dataclass(frozen=True, slots=True, kw_only=True)
class PasswordHashingConfig:
    """Argon2id cost and how many hashes may run at once in this process."""

    memory_kib: int
    time_cost: int
    parallelism: int
    max_concurrency: int


@final
class Argon2PasswordHasher(PasswordHasherPort):
    """Argon2id over the NFKC form of the password.

    A semaphore bounds simultaneous hashes, so a burst of logins cannot use all
    the memory of the process.
    """

    def __init__(self, config: PasswordHashingConfig) -> None:
        self._hasher = PasswordHasher(
            memory_cost=config.memory_kib,
            time_cost=config.time_cost,
            parallelism=config.parallelism,
        )
        self._slots = threading.BoundedSemaphore(config.max_concurrency)

    @override
    def hash(self, plain: str) -> str:
        with self._slots:
            return self._hasher.hash(normalize_password(plain))

    @override
    def verify(self, password_hash: str, plain: str) -> bool:
        with self._slots:
            try:
                return self._hasher.verify(password_hash, normalize_password(plain))
            except (VerifyMismatchError, VerificationError, InvalidHashError):
                return False

    @override
    def needs_rehash(self, password_hash: str) -> bool:
        try:
            return self._hasher.check_needs_rehash(password_hash)
        except InvalidHashError:
            return True
