"""Care team endpoints (API.md 8.5): assign, designate, reassign and withdraw."""

from datetime import datetime
from enum import StrEnum
from http import HTTPStatus
from typing import Annotated, Any, Final, Self, final
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from insumap.api.paths import API_V1_PREFIX
from insumap.api.routers.common import (
    ACCESS_EXTENSION,
    CursorQuery,
    LimitQuery,
    PageResponse,
    StrictRequest,
    access,
    error_responses,
    page_request,
)
from insumap.api.tags import ApiTag
from insumap.application.care_team.commands import (
    AssignDoctorCommand,
    EndAssignmentCommand,
    ReassignDoctorCommand,
    SetPrimaryDoctorCommand,
)
from insumap.application.care_team.list_assignments import (
    ListCareTeamAssignmentsInput,
    ListCareTeamAssignmentsUseCase,
)
from insumap.application.commands.base import CommandBus
from insumap.application.common.actor import Actor
from insumap.domain.care_team.assignment import CareAssignment
from insumap.domain.identity.permissions import PermissionCode
from insumap.shared.field_limits import FieldLimits

CARE_TEAM_PREFIX: Final = f"{API_V1_PREFIX}/care-team"

REASON_FIELD: Final = Field(
    min_length=FieldLimits.REASON_MIN_LENGTH,
    max_length=FieldLimits.REASON_MAX_LENGTH,
    description="Motivo de la decisión (queda en la auditoría).",
)


class AssignmentStatus(StrEnum):
    """Filter of the listing: open assignments or the ended history."""

    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class AssignDoctorRequest(StrictRequest):
    """A doctor of the clinic for a patient of the clinic."""

    patient_id: UUID
    doctor_id: UUID = Field(description="Médico activo de la misma clínica.")
    is_primary: bool = Field(
        default=False,
        description="El primer médico asignado queda como principal siempre.",
    )


class ReassignDoctorRequest(StrictRequest):
    """The doctor who takes over the assignment and why."""

    new_doctor_id: UUID
    reason: str = REASON_FIELD


class EndAssignmentRequest(StrictRequest):
    """Why the doctor leaves and, if it was the primary, who replaces him."""

    reason: str = REASON_FIELD
    new_primary_assignment_id: UUID | None = Field(
        default=None,
        description="Obligatorio al retirar al médico principal.",
    )


class CareAssignmentResponse(BaseModel):
    """One doctor assigned to one patient."""

    id: UUID
    patient_id: UUID
    doctor_id: UUID
    is_primary: bool
    started_at: datetime
    ended_at: datetime | None
    end_reason: str | None

    @classmethod
    def of(cls, assignment: CareAssignment) -> Self:
        return cls(
            id=assignment.assignment_id,
            patient_id=assignment.patient_id,
            doctor_id=assignment.doctor_user_id,
            is_primary=assignment.is_primary,
            started_at=assignment.assigned_at,
            ended_at=assignment.ended_at,
            end_reason=assignment.end_reason,
        )


ASSIGN_ERRORS: Final = error_responses(
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
    HTTPStatus.NOT_FOUND,
    HTTPStatus.CONFLICT,
    HTTPStatus.UNPROCESSABLE_ENTITY,
)


@final
class CareTeamRouter:
    """Builds ``/api/v1/care-team`` over the care team commands (P13) and listing.

    Every decision goes through the command bus, so it runs inside its
    transaction and leaves its audit row (P09). Scope and permissions are
    checked in the handlers; row level security repeats the clinic scope.
    """

    def __init__(
        self,
        *,
        commands: CommandBus,
        list_assignments: ListCareTeamAssignmentsUseCase,
        staff_actor: Any,
    ) -> None:
        self._commands = commands
        self._list = list_assignments
        self._staff_actor = staff_actor
        self.router = APIRouter(prefix=CARE_TEAM_PREFIX, tags=[ApiTag.CARE_TEAM])
        self._add_routes()

    def _add_routes(self) -> None:
        add = self.router.add_api_route
        staff = Depends(self._staff_actor)

        def list_care_team_assignments(
            actor: Annotated[Actor, staff],
            patient_id: Annotated[UUID | None, Query()] = None,
            doctor_id: Annotated[UUID | None, Query()] = None,
            status: Annotated[AssignmentStatus | None, Query()] = None,
            limit: LimitQuery = FieldLimits.PAGE_SIZE_DEFAULT,
            cursor: CursorQuery = None,
        ) -> PageResponse[CareAssignmentResponse]:
            page = self._list.execute(
                ListCareTeamAssignmentsInput(
                    actor=actor,
                    patient_id=patient_id,
                    doctor_id=doctor_id,
                    ended=None if status is None else status is AssignmentStatus.ENDED,
                    page=page_request(limit, cursor),
                )
            )
            return PageResponse(
                items=[CareAssignmentResponse.of(a) for a in page.items],
                next_cursor=page.next_cursor,
            )

        def assign_doctor(
            body: AssignDoctorRequest, actor: Annotated[Actor, staff]
        ) -> CareAssignmentResponse:
            return CareAssignmentResponse.of(
                self._commands.dispatch(
                    AssignDoctorCommand(
                        actor=actor,
                        patient_id=body.patient_id,
                        doctor_user_id=body.doctor_id,
                        is_primary=body.is_primary,
                    )
                )
            )

        def set_primary_doctor(
            assignment_id: UUID, actor: Annotated[Actor, staff]
        ) -> CareAssignmentResponse:
            return CareAssignmentResponse.of(
                self._commands.dispatch(
                    SetPrimaryDoctorCommand(actor=actor, assignment_id=assignment_id)
                )
            )

        def reassign_doctor(
            assignment_id: UUID,
            body: ReassignDoctorRequest,
            actor: Annotated[Actor, staff],
        ) -> CareAssignmentResponse:
            return CareAssignmentResponse.of(
                self._commands.dispatch(
                    ReassignDoctorCommand(
                        actor=actor,
                        assignment_id=assignment_id,
                        new_doctor_user_id=body.new_doctor_id,
                        reason=body.reason,
                    )
                )
            )

        def end_assignment(
            assignment_id: UUID,
            body: EndAssignmentRequest,
            actor: Annotated[Actor, staff],
        ) -> CareAssignmentResponse:
            return CareAssignmentResponse.of(
                self._commands.dispatch(
                    EndAssignmentCommand(
                        actor=actor,
                        assignment_id=assignment_id,
                        reason=body.reason,
                        new_primary_assignment_id=body.new_primary_assignment_id,
                    )
                )
            )

        read = {ACCESS_EXTENSION: access(PermissionCode.CARE_TEAM_READ)}
        write = {ACCESS_EXTENSION: access(PermissionCode.CARE_TEAM_ASSIGN)}
        add(
            "/assignments",
            list_care_team_assignments,
            methods=["GET"],
            operation_id="list_care_team_assignments",
            summary="Listar las asignaciones del equipo de atención",
            description=(
                "El administrador de la clínica ve las asignaciones de su clínica; "
                "el médico, solo las propias. Con `status=ENDED` devuelve el "
                "historial con fechas y motivo."
            ),
            responses=error_responses(
                HTTPStatus.UNAUTHORIZED,
                HTTPStatus.FORBIDDEN,
                HTTPStatus.UNPROCESSABLE_ENTITY,
            ),
            openapi_extra=read,
        )
        add(
            "/assignments",
            assign_doctor,
            methods=["POST"],
            status_code=HTTPStatus.CREATED,
            operation_id="assign_doctor",
            summary="Asignar un médico a un paciente",
            description=(
                "Agrega un médico activo de la clínica al equipo del paciente. Un "
                "paciente con equipo tiene exactamente un médico principal; el "
                "primero asignado queda como principal. Un médico o un paciente de "
                "otra clínica responde `404`."
            ),
            responses=ASSIGN_ERRORS,
            openapi_extra=write,
        )
        add(
            "/assignments/{assignment_id}/make-primary",
            set_primary_doctor,
            methods=["POST"],
            operation_id="set_primary_doctor",
            summary="Designar al médico principal",
            description=(
                "El médico de la asignación pasa a ser el principal y el anterior "
                "deja de serlo en la misma operación."
            ),
            responses=ASSIGN_ERRORS,
            openapi_extra=write,
        )
        add(
            "/assignments/{assignment_id}/reassign",
            reassign_doctor,
            methods=["POST"],
            status_code=HTTPStatus.CREATED,
            operation_id="reassign_doctor",
            summary="Reasignar el paciente a otro médico",
            description=(
                "Termina la asignación con motivo y crea la del médico nuevo, que "
                "hereda si era principal."
            ),
            responses=ASSIGN_ERRORS,
            openapi_extra=write,
        )
        add(
            "/assignments/{assignment_id}/end",
            end_assignment,
            methods=["POST"],
            operation_id="end_assignment",
            summary="Retirar a un médico del equipo",
            description=(
                "Termina la asignación con motivo. Si es el médico principal, exige "
                "`new_primary_assignment_id`. El médico retirado deja de ver al "
                "paciente; sus decisiones previas siguen en la auditoría."
            ),
            responses=ASSIGN_ERRORS,
            openapi_extra=write,
        )
