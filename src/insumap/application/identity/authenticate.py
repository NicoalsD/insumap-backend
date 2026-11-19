"""Turns a bearer token into the ``Actor`` of a request (deny by default)."""

from __future__ import annotations

from enum import StrEnum
from typing import final

from insumap.application.common.actor import Actor
from insumap.application.common.unit_of_work import TransactionContext, UnitOfWorkPort
from insumap.application.identity.ports import (
    PermissionRepositoryPort,
    TokenIssuerPort,
    UserRepositoryPort,
)
from insumap.domain.identity.errors import (
    ClinicSuspendedError,
    MfaRequiredError,
    SessionRevokedError,
)
from insumap.domain.identity.session import AuthenticationMethod


class SessionScope(StrEnum):
    """Which sessions a route accepts."""

    FULL = "FULL"
    """Every route by default: staff must have verified the second factor."""

    ENROLLMENT = "ENROLLMENT"
    """``/auth/mfa/enrollment*``: also the enrollment session of the staff."""

    ANY = "ANY"
    """``GET /auth/current-user`` and ``/auth/logout``: any valid session."""


@final
class AuthenticateActorUseCase:
    """Validates the token, then checks it against the account in the database.

    The account must be active, its token version must equal the ``tv`` claim
    and its clinic must be active. Permissions are read from the database for
    the role; the token never carries them.
    """

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        tokens: TokenIssuerPort,
        users: UserRepositoryPort,
        permissions: PermissionRepositoryPort,
    ) -> None:
        self._uow = uow
        self._tokens = tokens
        self._users = users
        self._permissions = permissions

    def execute(self, token: str, scope: SessionScope) -> Actor:
        """Return the actor of ``token`` or raise a 401 or 403 error."""
        claims = self._tokens.decode(token)
        context = TransactionContext(
            user_id=claims.user_id, clinic_id=claims.clinic_id, role=claims.role
        )
        with self._uow.begin(context):
            account = self._users.get(claims.user_id)
            if (
                account is None
                or not account.can_sign_in
                or account.token_version != claims.token_version
            ):
                raise SessionRevokedError
            if account.clinic_suspended:
                raise ClinicSuspendedError
            mfa_verified = AuthenticationMethod.ONE_TIME_PASSWORD.value in claims.amr
            if scope is SessionScope.FULL and account.requires_mfa and not mfa_verified:
                raise MfaRequiredError
            permissions = self._permissions.permissions_for_role(account.role)
        return Actor(
            user_id=account.user_id,
            clinic_id=account.clinic_id,
            role=account.role,
            permissions=permissions,
            patient_id=account.patient_id,
            session_id=claims.session_id,
            clinic_is_demo=account.clinic is not None and account.clinic.is_demo,
            requires_mfa=account.requires_mfa,
            mfa_verified=mfa_verified,
        )
