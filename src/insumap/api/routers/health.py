"""Liveness and readiness endpoints."""

from __future__ import annotations

from http import HTTPStatus
from typing import Final, Literal, final

from fastapi import APIRouter, Response
from pydantic import BaseModel, ConfigDict, Field

from insumap.api.tags import ApiTag
from insumap.application.readiness import CheckReadinessUseCase

STATUS_OK: Final = "ok"
STATUS_UNAVAILABLE: Final = "unavailable"


class HealthResponse(BaseModel):
    """State of the API for monitors and orchestrators."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "unavailable"] = Field(
        description="Estado de la API: 'ok' o 'unavailable'.", examples=[STATUS_OK]
    )


@final
class HealthRouter:
    """Builds ``GET /health`` (liveness) and ``GET /ready`` (readiness).

    Both endpoints are public and never reveal internal details.
    """

    def __init__(self, check_readiness: CheckReadinessUseCase) -> None:
        self._check_readiness = check_readiness
        self.router = APIRouter(tags=[ApiTag.HEALTH])
        self.router.add_api_route(
            "/health",
            self.get_health,
            methods=["GET"],
            response_model=HealthResponse,
            operation_id="get_health",
            summary="Consultar si la API está viva",
            description=(
                "Prueba de vida (liveness). Responde 200 mientras el proceso atiende "
                "peticiones. No revisa dependencias y no requiere autenticación."
            ),
        )
        self.router.add_api_route(
            "/ready",
            self.get_readiness,
            methods=["GET"],
            response_model=HealthResponse,
            operation_id="get_readiness",
            summary="Consultar si la API está lista",
            description=(
                "Prueba de disponibilidad (readiness). Responde 200 si la API puede "
                "recibir tráfico y 503 si una de sus dependencias no está lista. "
                "No requiere autenticación."
            ),
            responses={
                HTTPStatus.SERVICE_UNAVAILABLE: {
                    "model": HealthResponse,
                    "description": "Una dependencia de la API no está lista.",
                }
            },
        )

    def get_health(self) -> HealthResponse:
        """Answer that the process is alive."""
        return HealthResponse(status=STATUS_OK)

    def get_readiness(self, response: Response) -> HealthResponse:
        """Answer whether the API can receive traffic (503 when it cannot)."""
        if self._check_readiness.execute():
            return HealthResponse(status=STATUS_OK)
        response.status_code = HTTPStatus.SERVICE_UNAVAILABLE
        return HealthResponse(status=STATUS_UNAVAILABLE)
