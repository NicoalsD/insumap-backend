"""The session's own account (``GET /auth/me``)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import final
from uuid import UUID

from insumap.application.common.actor import Actor
from insumap.application.common.unit_of_work import TransactionContext, UnitOfWorkPort
from insumap.application.identity.ports import (
    ConsentRepositoryPort,
    MfaFactorRepositoryPort,
    UserRepositoryPort,
)
from insumap.domain.identity.errors import SessionRevokedError
from insumap.domain.identity.roles import Role
from insumap.domain.identity.user import ClinicSummary


@dataclass(frozen=True, slots=True, kw_only=True)
class GetCurrentUserInput:
    """The authenticated actor (any valid session)."""

    actor: Actor


@dataclass(frozen=True, slots=True, kw_only=True)
class CurrentUserResult:
    """Account, role, clinic, permissions and pending steps of the session."""

    user_id: UUID
    email: str | None
    full_name: str | None
    role: Role
    clinic: ClinicSummary | None
    permissions: tuple[str, ...]
    mfa_enabled: bool
    consent_required: bool


@final
class GetCurrentUserUseCase:
    """Reads what the frontend needs to draw the session."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        users: UserRepositoryPort,
        factors: MfaFactorRepositoryPort,
        consents: ConsentRepositoryPort,
    ) -> None:
        self._uow = uow
        self._users = users
        self._factors = factors
        self._consents = consents

    def execute(self, input: GetCurrentUserInput) -> CurrentUserResult:
        """Return the account of the actor."""
        actor = input.actor
        with self._uow.begin(TransactionContext.for_actor(actor)):
            account = self._users.get(actor.user_id)
            if account is None:
                raise SessionRevokedError
            factor = self._factors.find_totp(actor.user_id)
            consent_required = (
                account.patient_id is not None
                and account.clinic_id is not None
                and not self._consents.has_accepted_current(
                    account.patient_id, account.clinic_id
                )
            )
        return CurrentUserResult(
            user_id=account.user_id,
            email=account.email,
            full_name=account.full_name,
            role=account.role,
            clinic=account.clinic,
            permissions=tuple(sorted(code.value for code in actor.permissions)),
            mfa_enabled=factor is not None and factor.is_confirmed,
            consent_required=consent_required,
        )
