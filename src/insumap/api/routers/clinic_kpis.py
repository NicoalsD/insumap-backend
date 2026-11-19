"""``GET /api/v1/clinic-kpis``: clinic aggregates for its administrator (8.11)."""

from http import HTTPStatus
from typing import Annotated, Any, Final, final

from fastapi import APIRouter, Depends

from insumap.api.paths import API_V1_PREFIX
from insumap.api.routers.common import ACCESS_EXTENSION, access, error_responses
from insumap.api.routers.dashboard_schemas import ClinicKpisResponse
from insumap.api.tags import ApiTag
from insumap.application.clinic_kpis.queries import GetClinicKpisUseCase
from insumap.application.common.actor import Actor
from insumap.domain.identity.permissions import PermissionCode

KPIS_ERRORS: Final = error_responses(
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
    HTTPStatus.UNPROCESSABLE_ENTITY,
)


@final
class ClinicKpiRouter:
    """Builds ``GET /api/v1/clinic-kpis``: counts only, never clinical detail."""

    def __init__(self, *, kpis: GetClinicKpisUseCase, staff_actor: Any) -> None:
        self._kpis = kpis
        self._staff_actor = staff_actor
        self.router = APIRouter(prefix=API_V1_PREFIX, tags=[ApiTag.DASHBOARD])
        self._add_routes()

    def _add_routes(self) -> None:
        staff = Depends(self._staff_actor)

        def get_clinic_kpis(
            actor: Annotated[Actor, staff],
        ) -> ClinicKpisResponse:
            return ClinicKpisResponse.of(self._kpis.execute(actor))

        self.router.add_api_route(
            "/clinic-kpis",
            get_clinic_kpis,
            methods=["GET"],
            operation_id="get_clinic_kpis",
            summary="Ver los indicadores de la clínica",
            description=(
                "Pacientes por estado de cuenta, tasa de activación y alertas "
                "abiertas de la clínica, sin glucosa ni dosis. Los conteos menores "
                "que el tamaño mínimo de celda aparecen como `null`."
            ),
            responses=KPIS_ERRORS,
            openapi_extra={ACCESS_EXTENSION: access(PermissionCode.CLINIC_KPIS_READ)},
        )
