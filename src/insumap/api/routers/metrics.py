"""Glycemic metrics, AGP and forecast endpoints (API.md 8.8)."""

from enum import StrEnum
from http import HTTPStatus
from typing import Annotated, Any, Final, final
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from insumap.api.paths import API_V1_PREFIX
from insumap.api.routers.common import ACCESS_EXTENSION, access, error_responses
from insumap.api.routers.metrics_schemas import (
    AgpResponse,
    ForecastResponse,
    MetricsResponse,
)
from insumap.api.tags import ApiTag
from insumap.application.common.actor import Actor
from insumap.application.metrics.forecast import (
    ForecastInput,
    ForecastMode,
    GetForecastUseCase,
)
from insumap.application.metrics.metrics import (
    AgpInput,
    ComputeGlycemicMetricsUseCase,
    GetAgpUseCase,
    MetricsInput,
    MetricWindow,
)
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.metrics.agp import AgpResolution
from insumap.shared.field_limits import FieldLimits

OWN_PREFIX: Final = "/patients/own"
ASSIGNED_PREFIX: Final = "/patients/{patient_id}"


class AgpResolutionParam(StrEnum):
    """The ``resolution`` of the AGP: one hour or 15 minutes."""

    HOUR = "hour"
    QUARTER_HOUR = "15min"


AGP_RESOLUTIONS: Final[dict[AgpResolutionParam, AgpResolution]] = {
    AgpResolutionParam.HOUR: AgpResolution.HOUR,
    AgpResolutionParam.QUARTER_HOUR: AgpResolution.QUARTER,
}

type WindowQuery = Annotated[
    MetricWindow,
    Query(description="Ventana de análisis: `24h`, `7d`, `14d` o `30d`."),
]
type ComparePreviousQuery = Annotated[
    bool,
    Query(description="Incluir la misma métrica de la ventana anterior."),
]
type ForecastModeQuery = Annotated[
    ForecastMode,
    Query(description="`SHORT_TERM` (horizonte corto) u `OVERNIGHT` (noche)."),
]
type AgpDaysQuery = Annotated[
    int | None,
    Query(
        ge=1,
        le=FieldLimits.AGP_DAYS_MAX,
        description="Días locales que se superponen. Sin valor, los días mínimos "
        "del perfil de metas del paciente.",
    ),
]
type AgpResolutionQuery = Annotated[
    AgpResolutionParam,
    Query(description="Franjas de `hour` (una hora) o `15min`."),
]

METRICS_ERRORS: Final = error_responses(
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
    HTTPStatus.NOT_FOUND,
    HTTPStatus.UNPROCESSABLE_ENTITY,
)
OWN_ERRORS: Final = error_responses(
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
    HTTPStatus.UNPROCESSABLE_ENTITY,
)


@final
class MetricsRouter:
    """Builds the metrics and forecast routes over their use cases.

    The patient's own routes are declared first: ``/patients/own/...`` would
    otherwise match ``/patients/{patient_id}/...`` and fail the UUID.
    """

    def __init__(
        self,
        *,
        metrics: ComputeGlycemicMetricsUseCase,
        agp: GetAgpUseCase,
        forecast: GetForecastUseCase,
        session_actor: Any,
    ) -> None:
        self._metrics = metrics
        self._agp = agp
        self._forecast = forecast
        self._actor_guard = session_actor
        self.router = APIRouter(prefix=API_V1_PREFIX, tags=[ApiTag.METRICS])
        self._add_routes()

    def _add_routes(self) -> None:
        add = self.router.add_api_route
        guard = Depends(self._actor_guard)

        def get_own_metrics(
            actor: Annotated[Actor, guard],
            window: WindowQuery = MetricWindow.LAST_14_DAYS,
            compare_previous: ComparePreviousQuery = True,
        ) -> MetricsResponse:
            return MetricsResponse.of(
                self._metrics.execute(
                    MetricsInput(
                        actor=actor, window=window, compare_previous=compare_previous
                    )
                )
            )

        def get_own_forecast(
            actor: Annotated[Actor, guard],
            mode: ForecastModeQuery = ForecastMode.SHORT_TERM,
        ) -> ForecastResponse:
            return ForecastResponse.of(
                self._forecast.execute(ForecastInput(actor=actor, mode=mode))
            )

        def get_patient_metrics(
            patient_id: UUID,
            actor: Annotated[Actor, guard],
            window: WindowQuery = MetricWindow.LAST_14_DAYS,
            compare_previous: ComparePreviousQuery = True,
        ) -> MetricsResponse:
            return MetricsResponse.of(
                self._metrics.execute(
                    MetricsInput(
                        actor=actor,
                        window=window,
                        compare_previous=compare_previous,
                        patient_id=patient_id,
                    )
                )
            )

        def get_patient_agp(
            patient_id: UUID,
            actor: Annotated[Actor, guard],
            days: AgpDaysQuery = None,
            resolution: AgpResolutionQuery = AgpResolutionParam.HOUR,
        ) -> AgpResponse:
            return AgpResponse.of(
                self._agp.execute(
                    AgpInput(
                        actor=actor,
                        days=days,
                        resolution=AGP_RESOLUTIONS[resolution],
                        patient_id=patient_id,
                    )
                )
            )

        def get_patient_forecast(
            patient_id: UUID,
            actor: Annotated[Actor, guard],
            mode: ForecastModeQuery = ForecastMode.SHORT_TERM,
        ) -> ForecastResponse:
            return ForecastResponse.of(
                self._forecast.execute(
                    ForecastInput(actor=actor, mode=mode, patient_id=patient_id)
                )
            )

        metrics_read = {ACCESS_EXTENSION: access(PermissionCode.METRICS_READ_OWN)}
        metrics_assigned = {
            ACCESS_EXTENSION: access(PermissionCode.METRICS_READ_ASSIGNED)
        }
        forecast_own = {ACCESS_EXTENSION: access(PermissionCode.AI_FORECASTS_READ_OWN)}
        forecast_assigned = {
            ACCESS_EXTENSION: access(PermissionCode.AI_FORECASTS_READ_ASSIGNED)
        }

        add(
            f"{OWN_PREFIX}/metrics",
            get_own_metrics,
            methods=["GET"],
            operation_id="get_own_metrics",
            summary="Mis métricas glucémicas",
            description=(
                "TIR, TBR, TAR, media, GMI, CV y episodios de hipoglucemia de la "
                "ventana, con las metas del perfil del paciente. Con datos "
                "insuficientes `is_sufficient` es `false` y no hay porcentajes."
            ),
            responses=OWN_ERRORS,
            openapi_extra=metrics_read,
        )
        add(
            f"{OWN_PREFIX}/forecast",
            get_own_forecast,
            methods=["GET"],
            operation_id="get_own_forecast",
            summary="Mi pronóstico de glucosa",
            description=(
                "Tendencia y banda p10 a p90 por horizonte. Si la IA no responde o "
                "faltan datos, responde el respaldo con `is_fallback: true`. Nunca "
                "contiene una dosis de insulina."
            ),
            responses=OWN_ERRORS,
            openapi_extra=forecast_own,
        )
        add(
            f"{ASSIGNED_PREFIX}/metrics",
            get_patient_metrics,
            methods=["GET"],
            operation_id="get_patient_metrics",
            summary="Métricas glucémicas de un paciente asignado",
            description=(
                "Las mismas métricas de `GET /patients/own/metrics` para un paciente "
                "asignado. Queda registrada en la auditoría. Un paciente no asignado "
                "o de otra clínica responde `404`."
            ),
            responses=METRICS_ERRORS,
            openapi_extra=metrics_assigned,
        )
        add(
            f"{ASSIGNED_PREFIX}/metrics/agp",
            get_patient_agp,
            methods=["GET"],
            operation_id="get_patient_agp",
            summary="Perfil glucémico de los días (AGP)",
            description=(
                "Percentiles p5 a p95 por franja del día local, con el rango objetivo "
                "del perfil. Con datos insuficientes `bins` va vacío y `is_sufficient` "
                "es `false`."
            ),
            responses=METRICS_ERRORS,
            openapi_extra=metrics_assigned,
        )
        add(
            f"{ASSIGNED_PREFIX}/forecast",
            get_patient_forecast,
            methods=["GET"],
            operation_id="get_patient_forecast",
            summary="Pronóstico de glucosa de un paciente asignado",
            description=(
                "Pronóstico corto o nocturno del paciente asignado. La IA solo apoya "
                "al médico: si no responde, el respaldo por reglas va con su motivo "
                "en `fallback_reason` y nunca es un error."
            ),
            responses=METRICS_ERRORS,
            openapi_extra=forecast_assigned,
        )
