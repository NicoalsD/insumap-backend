"""TOTP factors and recovery codes (``iam.mfa_factors``)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import final, override
from uuid import UUID

from sqlalchemy import case, func, select, update

from insumap.application.identity.ports import (
    EncryptedSecret,
    KeyedHash,
    MfaFactorRepositoryPort,
    TotpFactor,
)
from insumap.infrastructure.persistence.orm import MfaFactorOrm
from insumap.infrastructure.persistence.transactions import CurrentSession

TOTP = "TOTP"
RECOVERY_CODE = "RECOVERY_CODE"


@final
class MfaFactorRepository(MfaFactorRepositoryPort):
    """The secret is ciphertext; a recovery code is only its keyed hash."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def find_totp(self, user_id: UUID) -> TotpFactor | None:
        row = (
            self._current.get()
            .scalars(
                select(MfaFactorOrm).where(
                    MfaFactorOrm.user_id == user_id,
                    MfaFactorOrm.factor_type == TOTP,
                    MfaFactorOrm.revoked_at.is_(None),
                )
            )
            .first()
        )
        if row is None or row.secret_ciphertext is None:
            return None
        return TotpFactor(
            factor_id=row.id,
            user_id=row.user_id,
            secret=EncryptedSecret(ciphertext=row.secret_ciphertext, key_id=row.key_id),
            last_used_step=row.last_used_step,
            confirmed_at=row.confirmed_at,
        )

    @override
    def add_totp(self, factor: TotpFactor, *, now: datetime) -> None:
        self._current.get().add(
            MfaFactorOrm(
                id=factor.factor_id,
                user_id=factor.user_id,
                factor_type=TOTP,
                secret_ciphertext=factor.secret.ciphertext,
                key_id=factor.secret.key_id,
                confirmed_at=factor.confirmed_at,
            )
        )
        self._current.get().flush()

    @override
    def revoke_totp(self, factor_id: UUID, *, now: datetime) -> None:
        self._current.get().execute(
            update(MfaFactorOrm)
            .where(MfaFactorOrm.id == factor_id)
            .values(revoked_at=now)
        )

    @override
    def accept_step(
        self, factor_id: UUID, step: int, *, now: datetime, confirm: bool
    ) -> bool:
        confirmed = (
            func.coalesce(MfaFactorOrm.confirmed_at, now)
            if confirm
            else MfaFactorOrm.confirmed_at
        )
        result = self._current.get().execute(
            update(MfaFactorOrm)
            .where(
                MfaFactorOrm.id == factor_id,
                case(
                    (MfaFactorOrm.last_used_step.is_(None), True),
                    else_=MfaFactorOrm.last_used_step < step,
                ),
            )
            .values(last_used_step=step, confirmed_at=confirmed)
            .returning(MfaFactorOrm.id)
        )
        return result.first() is not None

    @override
    def replace_recovery_codes(
        self, user_id: UUID, codes: Sequence[KeyedHash], *, now: datetime
    ) -> None:
        session = self._current.get()
        session.execute(
            update(MfaFactorOrm)
            .where(
                MfaFactorOrm.user_id == user_id,
                MfaFactorOrm.factor_type == RECOVERY_CODE,
                MfaFactorOrm.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        session.add_all(
            MfaFactorOrm(
                user_id=user_id,
                factor_type=RECOVERY_CODE,
                code_hash=code.value,
                key_id=code.key_id,
            )
            for code in codes
        )
        session.flush()

    @override
    def consume_recovery_code(
        self, user_id: UUID, code_hashes: Sequence[str], *, now: datetime
    ) -> bool:
        result = self._current.get().execute(
            update(MfaFactorOrm)
            .where(
                MfaFactorOrm.user_id == user_id,
                MfaFactorOrm.factor_type == RECOVERY_CODE,
                MfaFactorOrm.code_hash.in_(list(code_hashes)),
                MfaFactorOrm.used_at.is_(None),
                MfaFactorOrm.revoked_at.is_(None),
            )
            .values(used_at=now)
            .returning(MfaFactorOrm.id)
        )
        return result.first() is not None
