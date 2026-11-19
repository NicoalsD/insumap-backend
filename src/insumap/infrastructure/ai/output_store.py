"""Persists AI outputs and their audit rows in a system transaction (P09 over P11)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final, final, override

from sqlalchemy import text

from insumap.application.ai.ports import AiOutputStorePort, ForecastRecord
from insumap.application.common.ids import IdGenerator
from insumap.application.common.unit_of_work import (
    TransactionContext,
    TransactionFactory,
)
from insumap.infrastructure.persistence.orm import GlucoseForecastOrm
from insumap.infrastructure.persistence.transactions import CurrentSession

SYSTEM_ACCESS_LOG: Final = text(
    "INSERT INTO audit.data_access_log (clinic_id, patient_id, actor_user_id,"
    " actor_role, actor_type, resource_type, action, outcome, purpose, request_id,"
    " occurred_at)"
    " VALUES (:clinic_id,"
    " (SELECT p.id FROM clinic.patients AS p WHERE p.id = :patient_id),"
    " NULL, NULL, 'SYSTEM', 'AI_OUTPUTS', 'READ', 'GRANTED', 'AI_PROCESSING',"
    " :request_id, :occurred_at)"
)
"""The actor is the system: no user and no role, only the purpose of the read."""


@final
class SqlAiOutputStore(AiOutputStorePort):
    """One transaction in the system context writes the output and its audit row."""

    def __init__(
        self,
        current: CurrentSession,
        transactions: TransactionFactory,
        ids: IdGenerator,
    ) -> None:
        self._current = current
        self._transactions = transactions
        self._ids = ids

    @override
    def store_forecast(
        self, record: ForecastRecord, *, request_id: str | None, occurred_at: datetime
    ) -> None:
        output = record.output
        with self._transactions.open() as transaction:
            transaction.apply_context(TransactionContext.for_system(record.clinic_id))
            session = self._current.get()
            session.add(
                GlucoseForecastOrm(
                    id=self._ids.new_id(),
                    clinic_id=record.clinic_id,
                    patient_id=record.patient_id,
                    mode=record.mode.value,
                    based_on_reading_id=None,
                    points=[_point(point) for point in output.points],
                    hypo_probability=[
                        _risk(r.horizon_minutes, r.hypo_probability)
                        for r in output.risk
                    ],
                    hyper_probability=[
                        _risk(r.horizon_minutes, r.hyper_probability)
                        for r in output.risk
                    ],
                    target_profile_id=record.target_profile_id,
                    model_name=output.model_name,
                    model_version=output.model_version,
                    input_hash=output.input_hash,
                    explanation=_explanation(output),
                    is_fallback=output.is_fallback,
                    fallback_reason=None
                    if output.fallback_reason is None
                    else output.fallback_reason.value,
                    is_shadow=False,
                    generated_at=output.generated_at,
                    created_at=output.generated_at,
                )
            )
            session.execute(
                SYSTEM_ACCESS_LOG,
                {
                    "clinic_id": record.clinic_id,
                    "patient_id": record.patient_id,
                    "request_id": request_id,
                    "occurred_at": occurred_at,
                },
            )
            transaction.commit()


def _point(point: Any) -> dict[str, Any]:
    return {
        "horizon_minutes": point.horizon_minutes,
        "timestamp": point.timestamp.isoformat(),
        "p10": float(point.p10),
        "p50": float(point.p50),
        "p90": float(point.p90),
    }


def _risk(horizon: int, probability: Any) -> dict[str, Any]:
    return {"horizon_minutes": horizon, "probability": float(probability)}


def _explanation(output: Any) -> dict[str, Any]:
    explanation = output.explanation
    return {
        "summary": "" if explanation is None else explanation.summary,
        "factors": [] if explanation is None else list(explanation.factors),
        "data_refs": [] if explanation is None else list(explanation.data_refs),
    }
