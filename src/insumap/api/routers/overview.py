"""Patient overview: the start page of an assigned or own patient (API.md 8.6)."""

from http import HTTPStatus
from typing import Annotated, Any, Final, final
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from insumap.api.paths import API_V1_PREFIX
from insumap.api.routers.common import ACCESS_EXTENSION, access, error_responses
from insumap.api.routers.dashboard_schemas import PatientOverviewResponse
from insumap.api.tags import ApiTag
from insumap.application.common.actor import Actor
from insumap.application.metrics.metrics import MetricWindow
from insumap.application.overview.patient_overview_facade import PatientOverviewFacade
from insumap.domain.identity.permissions import PermissionCode

PATIENTS_PREFIX: Final = f"{API_V1_PREFIX}/patients"
WINDOW_DESCRIPTION: Final = "Ventana de las métricas: `24h`, `7d`, `14d` o `30d`."
OWN_ERRORS: Final = error_responses(
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
    HTTPStatus.UNPROCESSABLE_ENTITY,
)
ASSIGNED_ERRORS: Final = error_responses(
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
    HTTPStatus.NOT_FOUND,
    HTTPStatus.UNPROCESSABLE_ENTITY,
)


@final
class PatientOverviewRouter:
    """Builds the two overviews over the facade (P10).

    ``/patients/own/overview`` is declared before ``/patients/{patient_id}/overview``
    so that ``own`` is not read as a patient id.
    """

    def __init__(self, *, overview: PatientOverviewFacade, session_actor: Any) -> None:
        self._overview = overview
        self._session_actor = session_actor
        self.router = APIRouter(prefix=PATIENTS_PREFIX, tags=[ApiTag.PATIENTS])
        self._add_routes()

    def _add_routes(self) -> None:
        add = self.router.add_api_route
        session = Depends(self._session_actor)

        def get_own_overview(
            actor: Annotated[Actor, session],
            window: Annotated[
                MetricWindow, Query(description=WINDOW_DESCRIPTION)
            ] = MetricWindow.LAST_14_DAYS,
        ) -> PatientOverviewResponse:
            return PatientOverviewResponse.of(self._overview.for_own(actor, window))

        def get_patient_overview(
            patient_id: UUID,
            actor: Annotated[Actor, session],
            window: Annotated[
                MetricWindow, Query(description=WINDOW_DESCRIPTION)
            ] = MetricWindow.LAST_14_DAYS,
        ) -> PatientOverviewResponse:
            return PatientOverviewResponse.of(
                self._overview.for_assigned(actor, patient_id, window)
            )

        add(
            "/own/overview",
            get_own_overview,
            methods=["GET"],
            operation_id="get_own_overview",
            summary="Ver mi inicio",
            description=(
                "Mi inicio: lecturas recientes con su rango objetivo, métricas de la "
                "ventana, plan activo, alertas abiertas y recordatorios activos. No "
                "llama a la IA."
            ),
            responses=OWN_ERRORS,
            openapi_extra={ACCESS_EXTENSION: access(PermissionCode.PATIENTS_READ_OWN)},
        )
        add(
            "/{patient_id}/overview",
            get_patient_overview,
            methods=["GET"],
            operation_id="get_patient_overview",
            summary="Ver el inicio de un paciente asignado",
            description=(
                "Inicio del paciente asignado al médico: lecturas recientes, métricas "
                "de la ventana, plan activo, alertas abiertas y recordatorios. Leerlo "
                "queda en la auditoría. Un paciente no asignado responde `404`."
            ),
            responses=ASSIGNED_ERRORS,
            openapi_extra={
                ACCESS_EXTENSION: access(PermissionCode.PATIENTS_READ_ASSIGNED)
            },
        )
