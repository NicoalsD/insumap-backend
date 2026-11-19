"""``/api/v1/dashboard``: the doctor's triage list and its reviews (8.11)."""

from http import HTTPStatus
from typing import Annotated, Any, Final, final
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from insumap.api.paths import API_V1_PREFIX
from insumap.api.routers.common import (
    ACCESS_EXTENSION,
    CursorQuery,
    LimitQuery,
    PageResponse,
    access,
    error_responses,
    page_request,
)
from insumap.api.routers.dashboard_schemas import (
    ReviewedPatientResponse,
    TriagePatientResponse,
    triage_patient,
)
from insumap.api.tags import ApiTag
from insumap.application.commands.base import CommandBus
from insumap.application.common.actor import Actor
from insumap.application.dashboard.commands import (
    ROLLING_DAY_WINDOW_DAYS,
    MarkPatientReviewedCommand,
)
from insumap.application.dashboard.triage_facade import (
    DoctorDashboardFacade,
    TriageInput,
)
from insumap.application.metrics.metrics import MetricWindow
from insumap.domain.dashboard.triage import TriageFlag
from insumap.domain.identity.permissions import PermissionCode
from insumap.shared.field_limits import FieldLimits
from insumap.shared.i18n.message_catalog import MessageCatalog

DASHBOARD_PREFIX: Final = f"{API_V1_PREFIX}/dashboard"
WINDOW_DESCRIPTION: Final = "Ventana de las métricas: `24h`, `7d`, `14d` o `30d`."
ERRORS: Final = error_responses(
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
    HTTPStatus.UNPROCESSABLE_ENTITY,
)
REVIEW_ERRORS: Final = error_responses(
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
    HTTPStatus.NOT_FOUND,
    HTTPStatus.UNPROCESSABLE_ENTITY,
)


@final
class DashboardRouter:
    """Builds ``/api/v1/dashboard`` over the triage facade and the review command.

    The list is the facade's (P10, one audit batch); the review is a command
    through the bus, so it runs inside its transaction and leaves its audit row.
    """

    def __init__(
        self,
        *,
        commands: CommandBus,
        triage: DoctorDashboardFacade,
        messages: MessageCatalog,
        staff_actor: Any,
    ) -> None:
        self._commands = commands
        self._triage = triage
        self._reasons: dict[TriageFlag, str] = {
            flag: messages.render(f"triage.flag.{flag.value.lower()}")
            for flag in TriageFlag
        }
        self._staff_actor = staff_actor
        self.router = APIRouter(prefix=DASHBOARD_PREFIX, tags=[ApiTag.DASHBOARD])
        self._add_routes()

    def _add_routes(self) -> None:
        add = self.router.add_api_route
        staff = Depends(self._staff_actor)
        read = {ACCESS_EXTENSION: access(PermissionCode.DASHBOARD_READ_ASSIGNED)}

        def get_triage_dashboard(
            actor: Annotated[Actor, staff],
            window: Annotated[
                MetricWindow,
                Query(description=WINDOW_DESCRIPTION),
            ] = MetricWindow.LAST_14_DAYS,
            reviewed: Annotated[
                bool | None,
                Query(description="Solo revisados (`true`) o pendientes (`false`)."),
            ] = None,
            limit: LimitQuery = FieldLimits.PAGE_SIZE_DEFAULT,
            cursor: CursorQuery = None,
        ) -> PageResponse[TriagePatientResponse]:
            page = self._triage.triage(
                TriageInput(
                    actor=actor,
                    window=window,
                    reviewed=reviewed,
                    page=page_request(limit, cursor),
                )
            )
            return PageResponse(
                items=[
                    triage_patient(
                        item,
                        reasons=self._reasons,
                        simulated=actor.clinic_is_demo,
                    )
                    for item in page.items
                ],
                next_cursor=page.next_cursor,
            )

        def mark_patient_reviewed(
            patient_id: UUID,
            actor: Annotated[Actor, staff],
            window: Annotated[
                MetricWindow,
                Query(description=WINDOW_DESCRIPTION),
            ] = MetricWindow.LAST_14_DAYS,
        ) -> ReviewedPatientResponse:
            review = self._commands.dispatch(
                MarkPatientReviewedCommand(
                    actor=actor,
                    patient_id=patient_id,
                    window_days=window.days or ROLLING_DAY_WINDOW_DAYS,
                )
            )
            return ReviewedPatientResponse(
                patient_id=review.patient_id,
                reviewed_at=review.reviewed_at,
                window=window,
            )

        add(
            "/triage",
            get_triage_dashboard,
            methods=["GET"],
            operation_id="get_triage_dashboard",
            summary="Ver la lista de triage de mis pacientes",
            description=(
                "Pacientes asignados al médico, del más urgente al menos urgente. "
                "Por paciente: banderas con su motivo, alertas abiertas, tiempo en "
                "rango de la ventana, la última lectura y si ya fue revisado. El "
                "orden usa reglas (`is_fallback`), no la IA. Cada paciente listado "
                "queda en la auditoría."
            ),
            responses=ERRORS,
            openapi_extra=read,
        )
        add(
            "/patients/{patient_id}/review",
            mark_patient_reviewed,
            methods=["POST"],
            operation_id="mark_patient_reviewed",
            summary="Marcar un paciente como revisado",
            description=(
                "Registra que el médico revisó al paciente asignado. El paciente "
                "baja de prioridad hasta que llegue una lectura nueva. Un paciente "
                "no asignado responde `404`."
            ),
            responses=REVIEW_ERRORS,
            openapi_extra=read,
        )
