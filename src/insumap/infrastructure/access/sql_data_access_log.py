"""``audit.data_access_log``: one row per read of clinical data."""

from __future__ import annotations

from typing import final, override

from sqlalchemy import text

from insumap.application.access.ports import DataAccessLogPort, DataAccessRecord
from insumap.application.common.unit_of_work import (
    TransactionContext,
    TransactionFactory,
)
from insumap.infrastructure.persistence.transactions import CurrentSession

ACTOR_TYPE_USER = "USER"
ACTION_READ = "READ"
INSERT_ROW = text(
    "INSERT INTO audit.data_access_log (clinic_id, patient_id, actor_user_id,"
    " actor_role, actor_type, resource_type, action, outcome, purpose, request_id)"
    " VALUES (:clinic_id,"
    " (SELECT p.id FROM clinic.patients AS p WHERE p.id = :patient_id),"
    " :actor_user_id, :actor_role, :actor_type, :resource_type, :action,"
    " :outcome, :purpose, :request_id)"
)
"""Parameterized, without ``RETURNING`` (only an administrator may read the log back).
The patient id goes through a lookup so that a denied read of a patient that does
not exist, or belongs to another clinic, leaves the column empty instead of
breaking the foreign key."""


@final
class SqlDataAccessLog(DataAccessLogPort):
    """Granted reads join the transaction of the read; denied ones commit alone."""

    def __init__(
        self, current: CurrentSession, transactions: TransactionFactory
    ) -> None:
        self._current = current
        self._transactions = transactions

    @override
    def record_granted(self, record: DataAccessRecord) -> None:
        self._current.get().execute(INSERT_ROW, self._params(record))

    @override
    def record_denied(self, record: DataAccessRecord) -> None:
        with self._transactions.open() as transaction:
            transaction.apply_context(
                TransactionContext(
                    user_id=record.actor_user_id,
                    clinic_id=record.clinic_id,
                    role=record.actor_role,
                )
            )
            self._current.get().execute(INSERT_ROW, self._params(record))
            transaction.commit()

    @staticmethod
    def _params(record: DataAccessRecord) -> dict[str, object]:
        return {
            "clinic_id": record.clinic_id,
            "patient_id": record.patient_id,
            "actor_user_id": record.actor_user_id,
            "actor_role": record.actor_role.value,
            "actor_type": ACTOR_TYPE_USER,
            "resource_type": record.resource.value,
            "action": ACTION_READ,
            "outcome": record.outcome.value,
            "purpose": record.purpose.value,
            "request_id": record.request_id,
        }
