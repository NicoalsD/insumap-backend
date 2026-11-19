"""Public metadata endpoints: the technical limits the frontend validates with."""

from __future__ import annotations

from typing import Final, final

from fastapi import APIRouter, Response
from pydantic import BaseModel, ConfigDict, Field

from insumap.api.paths import API_V1_PREFIX
from insumap.api.tags import ApiTag
from insumap.shared.field_limits import FieldLimits

CACHE_CONTROL_HEADER: Final = "Cache-Control"
FIELD_LIMITS_MAX_AGE_SECONDS: Final = 300
"""Seconds a client may cache the field limits (API.md, section 1.3)."""
FIELD_LIMITS_CACHE_CONTROL: Final = f"public, max-age={FIELD_LIMITS_MAX_AGE_SECONDS}"

type LimitValue = int | str


def published_field_limits() -> dict[str, LimitValue]:
    """Return every constant of ``FieldLimits`` with its name in snake_case.

    The response grows with ``FieldLimits``: a new constant is published without
    touching this module.
    """
    return {
        name.lower(): value
        for name, value in vars(FieldLimits).items()
        if name.isupper() and isinstance(value, int | str)
    }


class FieldLimitsResponse(BaseModel):
    """Technical limits of the API, one entry per ``FieldLimits`` constant."""

    model_config = ConfigDict(extra="forbid")

    limits: dict[str, LimitValue] = Field(
        description=(
            "Límites técnicos de `FieldLimits` en snake_case: longitudes, patrones, "
            "tamaños de cuerpo y de página. No contiene datos personales."
        ),
        examples=[{"email_max_length": 254, "password_min_length": 12}],
    )


@final
class MetaRouter:
    """Builds ``GET /api/v1/meta/field-limits``, public and cacheable."""

    def __init__(self) -> None:
        self.router = APIRouter(prefix=f"{API_V1_PREFIX}/meta", tags=[ApiTag.META])
        self.router.add_api_route(
            "/field-limits",
            self.get_field_limits,
            methods=["GET"],
            response_model=FieldLimitsResponse,
            operation_id="get_field_limits",
            summary="Consultar los límites de los campos",
            description=(
                "Devuelve los límites técnicos de `FieldLimits` (longitudes, patrones "
                "y tamaños) para que el frontend valide con los mismos valores que la "
                "API. Es público y se puede guardar en caché por 5 minutos."
            ),
        )

    def get_field_limits(self, response: Response) -> FieldLimitsResponse:
        """Return the published limits with a public cache header."""
        response.headers[CACHE_CONTROL_HEADER] = FIELD_LIMITS_CACHE_CONTROL
        return FieldLimitsResponse(limits=published_field_limits())
