"""The request body of insumap-ai (Contrato-IA 8.1) and its canonical hash.

The body is built field by field from a ``ForecastCall``, a whitelist of what
may leave the backend. It is never built from an entity or an ORM row.
"""

from __future__ import annotations

import hashlib
import json
from typing import Final

from insumap.application.ai.ports import ForecastCall
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
