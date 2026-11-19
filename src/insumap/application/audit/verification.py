"""``POST /audit-log/verifications``: recalculates the hash chain of the clinic.

A broken chain is a critical security event (``AUDIT_CHAIN_BROKEN``). The use case
commits, so the event stays even though the verification itself only reads.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import final

from insumap.application.audit.ports import AuditChainPort, ChainVerification
from insumap.application.common.actor import Actor
from insumap.application.common.unit_of_work import TransactionContext, UnitOfWorkPort
from insumap.application.security.events import (
    SecurityEvent,
    SecurityEventPort,
    SecurityEventType,
)
from insumap.application.users.access import clinic_of
from insumap.domain.identity.permissions import PermissionCode


@dataclass(frozen=True, slots=True, kw_only=True)
class VerifyAuditChainInput:
    """The caller, who must be able to read the audit of the clinic."""

    actor: Actor


@final
class VerifyAuditChainUseCase:
    """Checks the chain of the caller's clinic; the clinic comes from the token.

    The database function trusts its argument, so the clinic is never taken from
    the request: it is the clinic of the token, passed as a bound parameter.
    """

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        chain: AuditChainPort,
        events: SecurityEventPort,
    ) -> None:
        self._uow = uow
        self._chain = chain
        self._events = events

    def execute(self, input: VerifyAuditChainInput) -> ChainVerification:
        """Only ``audit.read``; a broken chain also records a critical event."""
        input.actor.require(PermissionCode.AUDIT_READ)
        clinic_id = clinic_of(input.actor)
        with self._uow.begin(TransactionContext.for_actor(input.actor)) as unit:
            broken = self._chain.first_broken_row(clinic_id)
            if broken is not None:
                self._events.record(
                    SecurityEvent(
                        event_type=SecurityEventType.AUDIT_CHAIN_BROKEN,
                        user_id=input.actor.user_id,
                        clinic_id=clinic_id,
                    )
                )
            unit.commit()
        return ChainVerification(first_inconsistent_row_id=broken)
