"""Audit of every read of clinical data (P09)."""

from __future__ import annotations

from typing import Final, final, override
from uuid import UUID

from insumap.application.access.ports import (
    AccessPurpose,
    DataAccessLogPort,
    DataAccessOutcome,
    DataAccessRecord,
    DataResource,
    PatientRecord,
    PatientRecordPort,
)
from insumap.application.common.actor import Actor
from insumap.shared.errors import ErrorCode, InsumapError
from insumap.shared.request_context import current_request_id
from insumap.shared.time import Clock

DENIAL_CODES: Final = frozenset({ErrorCode.NOT_FOUND, ErrorCode.FORBIDDEN})
"""Errors that mean "you may not read this": they leave a ``DENIED`` row."""


@final
class PhiAccessAuditDecorator(PatientRecordPort):
    """Audits every read of clinical data, granted or denied.

    It wraps the proxy (``PhiAccessAuditDecorator(PatientRecordAccessProxy(...))``),
    so the denied accesses are logged too. A granted read is written in the
    transaction of the read and, if the write fails, the read fails. A denied
    read is written by ``record_denied`` in its own short transaction, because
    the one of the request rolls back when the error propagates.

    Pattern: P09 Decorator
    """

    def __init__(
        self, inner: PatientRecordPort, log: DataAccessLogPort, clock: Clock
    ) -> None:
        self._inner = inner
        self._log = log
        self._clock = clock

    @override
    def read_record(
        self,
        actor: Actor,
        patient_id: UUID,
        purpose: AccessPurpose,
        resource: DataResource,
    ) -> PatientRecord:
        try:
            record = self._inner.read_record(actor, patient_id, purpose, resource)
        except InsumapError as error:
            if error.code in DENIAL_CODES:
                self._log.record_denied(
                    self._entry(
                        actor, patient_id, purpose, resource, DataAccessOutcome.DENIED
                    )
                )
            raise
        self._log.record_granted(
            self._entry(actor, patient_id, purpose, resource, DataAccessOutcome.GRANTED)
        )
        return record

    def _entry(
        self,
        actor: Actor,
        patient_id: UUID,
        purpose: AccessPurpose,
        resource: DataResource,
        outcome: DataAccessOutcome,
    ) -> DataAccessRecord:
        return DataAccessRecord(
            occurred_at=self._clock.now(),
            clinic_id=actor.clinic_id,
            actor_user_id=actor.user_id,
            actor_role=actor.role,
            patient_id=patient_id,
            resource=resource,
            purpose=purpose,
            outcome=outcome,
            request_id=current_request_id(),
        )
