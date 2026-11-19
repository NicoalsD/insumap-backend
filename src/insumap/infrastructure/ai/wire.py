"""The request body of insumap-ai (Contrato-IA 8.1) and its canonical hash.

The body is built field by field from a ``ForecastCall``, a whitelist of what
may leave the backend. It is never built from an entity or an ORM row.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Final

from insumap.application.ai.ports import (
    AssistantCall,
    ForecastCall,
    RiskCall,
    SummaryCall,
)
from insumap.application.metrics.forecast import ForecastMode

SHORT_TERM_ONLY_FIELDS: Final = ("horizons_minutes",)
QUANTILE_LEVELS: Final = (0.1, 0.5, 0.9)
"""The v1 contract accepts exactly these levels (Contrato-IA 8.1)."""


def forecast_body(call: ForecastCall) -> dict[str, object]:
    """The JSON body of ``POST /v1/glucose-forecasts``."""
    body: dict[str, object] = {
        "subject_ref": call.subject_ref,
        "mode": call.mode.value,
        "series": {
            "timestamps": [moment.isoformat() for moment in call.timestamps],
            "values_mg_dl": [float(value) for value in call.values_mg_dl],
            "interval_minutes": call.interval_minutes,
        },
        "quantile_levels": list(call.quantile_levels),
        "thresholds": {
            "low_mg_dl": float(call.low_mg_dl),
            "high_mg_dl": float(call.high_mg_dl),
        },
        "clinic_timezone": call.clinic_timezone,
        "night_window": {"start": call.night_start, "end": call.night_end},
    }
    if call.mode is ForecastMode.SHORT_TERM:
        body[SHORT_TERM_ONLY_FIELDS[0]] = list(call.horizons_minutes)
    return body


def canonical_hash(body: dict[str, object]) -> str:
    """SHA-256 of the canonical JSON of ``body`` (sorted keys, no spaces)."""
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


CONTRACT_DIABETES_TYPES: Final[dict[str, str]] = {
    "T1D": "T1D",
    "T2D": "T2D",
    "GDM": "GESTATIONAL",
}
"""Database codes to the contract enum. ``OTHER`` has no contract value (not sent)."""


def contract_diabetes_type(code: str) -> str | None:
    """The contract value of a database code, or ``None`` when the AI cannot take it."""
    return CONTRACT_DIABETES_TYPES.get(code)


def risk_body(call: RiskCall) -> dict[str, object]:
    """The JSON body of ``POST /v1/risk-assessments`` (IA2), field by field."""
    features = call.features
    return {
        "subject_ref": call.subject_ref,
        "assessment_type": "DETERIORATION",
        "window_days": call.window_days,
        "diabetes_type": call.diabetes_type,
        "features": {
            "tir_pct": _num(features.tir_pct),
            "tbr_l1_pct": _num(features.tbr_l1_pct),
            "tbr_l2_pct": _num(features.tbr_l2_pct),
            "tar_l1_pct": _num(features.tar_l1_pct),
            "tar_l2_pct": _num(features.tar_l2_pct),
            "mean_glucose_mg_dl": _num(features.mean_glucose_mg_dl),
            "gmi_pct": _num(features.gmi_pct),
            "cv_pct": _num(features.cv_pct),
            "data_sufficiency_pct": _num(features.data_sufficiency_pct),
            "hypo_events_count": features.hypo_events_count,
            "severe_hypo_events_count": None,
            "last_hba1c_pct": None,
            "hba1c_delta_pct": None,
            "tir_delta_vs_prior_pct": _num(features.tir_delta_vs_prior_pct),
            "readings_per_day_avg": _num(features.readings_per_day_avg),
            "days_since_last_reading": None,
            "open_alerts_count": None,
            "target_tir_pct": _num(call.target_tir_pct),
        },
    }


def summary_body(call: SummaryCall) -> dict[str, object]:
    """The JSON body of ``POST /v1/clinical-summaries`` (IA5): numbers and enums
    only."""
    metrics = call.metrics
    return {
        "subject_ref": call.subject_ref,
        "period": {
            "from": call.period_start.isoformat(),
            "to": call.period_end.isoformat(),
        },
        "language": "es",
        "diabetes_type": call.diabetes_type,
        "metrics": {
            "tir_pct": _num(metrics.tir_pct),
            "tbr_l1_pct": _num(metrics.tbr_l1_pct),
            "tbr_l2_pct": _num(metrics.tbr_l2_pct),
            "tar_l1_pct": _num(metrics.tar_l1_pct),
            "tar_l2_pct": _num(metrics.tar_l2_pct),
            "mean_glucose_mg_dl": _num(metrics.mean_glucose_mg_dl),
            "gmi_pct": _num(metrics.gmi_pct),
            "cv_pct": _num(metrics.cv_pct),
            "data_sufficiency_pct": _num(metrics.data_sufficiency_pct),
            "agp_percentiles": [],
        },
        "targets": {"tir_target_pct": _num(call.target_tir_pct)},
        "events": [],
        "adherence": {
            "readings_per_day_avg": _num(call.readings_per_day),
            "dose_logging_pct": None,
        },
        "plan_changes": [],
        "last_hba1c": None,
    }


def assistant_body(call: AssistantCall) -> dict[str, object]:
    """The JSON body of ``POST /v1/assistant-replies`` (IA6). Text is the patient's
    own."""
    return {
        "subject_ref": call.subject_ref,
        "message": call.message,
        "history": [{"role": turn.sender, "text": turn.text} for turn in call.history],
        "context_documents": [
            {
                "doc_id": str(fragment.doc_id),
                "title": fragment.title,
                "text": fragment.text,
            }
            for fragment in call.fragments
        ],
        "language": "es",
    }


def _num(value: Decimal | None) -> float | None:
    return None if value is None else float(value)
