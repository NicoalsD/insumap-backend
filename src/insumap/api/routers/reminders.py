"""Reminder endpoints (API.md 8.7): the doctor schedules, the patient adjusts."""

from http import HTTPStatus
from typing import Annotated, Any, Final, final
from uuid import UUID

from fastapi import APIRouter, Depends

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
from insumap.api.routers.targets_schemas import (
    ReminderCreateRequest,
    ReminderResponse,
    ReminderUpdateRequest,
)
from insumap.api.tags import ApiTag
from insumap.application.commands.base import CommandBus
from insumap.application.common.actor import Actor
from insumap.application.reminders.commands import (
    CreateReminderCommand,
    UpdateOwnReminderCommand,
    UpdatePatientReminderCommand,
)
from insumap.application.reminders.queries import (
    ListOwnRemindersInput,
    ListOwnRemindersUseCase,
    ListPatientRemindersInput,
    ListPatientRemindersUseCase,
)
from insumap.domain.identity.permissions import PermissionCode
from insumap.shared.field_limits import FieldLimits

STAFF_WRITE_ERRORS: Final = error_responses(
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
    HTTPStatus.NOT_FOUND,
    HTTPStatus.UNPROCESSABLE_ENTITY,
)
STAFF_READ_ERRORS: Final = error_responses(
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
    HTTPStatus.NOT_FOUND,
    HTTPStatus.UNPROCESSABLE_ENTITY,
)
OWN_ERRORS: Final = error_responses(
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
    HTTPStatus.NOT_FOUND,
    HTTPStatus.UNPROCESSABLE_ENTITY,
)


@final
class ReminderRouter:
    """Builds the reminder routes: the doctor's for his patients, the patient's own.

    The patient's own routes are declared on ``/reminders``; the doctor's sit under
    ``/patients/{patient_id}`` and answer ``404`` for a patient he does not care for.
    """

    def __init__(
        self,
        *,
        commands: CommandBus,
        list_patient: ListPatientRemindersUseCase,
        list_own: ListOwnRemindersUseCase,
        session_actor: Any,
    ) -> None:
        self._commands = commands
        self._list_patient = list_patient
        self._list_own = list_own
        self._actor_guard = session_actor
        self.router = APIRouter(prefix=API_V1_PREFIX, tags=[ApiTag.TREATMENT])
        self._add_routes()

    def _add_routes(self) -> None:
        add = self.router.add_api_route
        guard = Depends(self._actor_guard)
        assigned = {ACCESS_EXTENSION: access(PermissionCode.REMINDERS_MANAGE_ASSIGNED)}
        own = {ACCESS_EXTENSION: access(PermissionCode.REMINDERS_MANAGE_OWN)}

        def create_patient_reminder(
            patient_id: UUID,
            body: ReminderCreateRequest,
            actor: Annotated[Actor, guard],
        ) -> ReminderResponse:
            return ReminderResponse.of(
                self._commands.dispatch(
                    CreateReminderCommand(
                        actor=actor,
                        patient_id=patient_id,
                        reminder_type=body.reminder_type,
                        schedule=body.schedule.to_schedule(),
                        is_active=body.is_active,
                    )
                )
            )

        def list_patient_reminders(
            patient_id: UUID,
            actor: Annotated[Actor, guard],
            limit: LimitQuery = FieldLimits.PAGE_SIZE_DEFAULT,
            cursor: CursorQuery = None,
        ) -> PageResponse[ReminderResponse]:
            page = self._list_patient.execute(
                ListPatientRemindersInput(
                    actor=actor,
                    patient_id=patient_id,
                    page=page_request(limit, cursor),
                )
            )
            return PageResponse(
                items=[ReminderResponse.of(r) for r in page.items],
                next_cursor=page.next_cursor,
            )

        def update_patient_reminder(
            patient_id: UUID,
            reminder_id: UUID,
            body: ReminderUpdateRequest,
            actor: Annotated[Actor, guard],
        ) -> ReminderResponse:
            return ReminderResponse.of(
                self._commands.dispatch(
                    UpdatePatientReminderCommand(
                        actor=actor,
                        patient_id=patient_id,
                        reminder_id=reminder_id,
                        schedule=None
                        if body.schedule is None
                        else body.schedule.to_schedule(),
                        is_active=body.is_active,
                    )
                )
            )

        def list_own_reminders(
            actor: Annotated[Actor, guard],
            limit: LimitQuery = FieldLimits.PAGE_SIZE_DEFAULT,
            cursor: CursorQuery = None,
        ) -> PageResponse[ReminderResponse]:
            page = self._list_own.execute(
                ListOwnRemindersInput(actor=actor, page=page_request(limit, cursor))
            )
            return PageResponse(
                items=[ReminderResponse.of(r) for r in page.items],
                next_cursor=page.next_cursor,
            )

        def update_own_reminder(
            reminder_id: UUID,
            body: ReminderUpdateRequest,
            actor: Annotated[Actor, guard],
        ) -> ReminderResponse:
            return ReminderResponse.of(
                self._commands.dispatch(
                    UpdateOwnReminderCommand(
                        actor=actor,
                        reminder_id=reminder_id,
                        schedule=None
                        if body.schedule is None
                        else body.schedule.to_schedule(),
                        is_active=body.is_active,
                    )
                )
            )

        add(
            "/patients/{patient_id}/reminders",
            create_patient_reminder,
            methods=["POST"],
            status_code=HTTPStatus.CREATED,
            operation_id="create_reminder",
            summary="Programar un recordatorio a un paciente asignado",
            description=(
                "El médico programa un recordatorio con su hora local y sus días. "
                "El texto sale de su tipo y no lleva datos clínicos. Un paciente no "
                "asignado responde `404`."
            ),
            responses=STAFF_WRITE_ERRORS,
            openapi_extra=assigned,
        )
        add(
            "/patients/{patient_id}/reminders",
            list_patient_reminders,
            methods=["GET"],
            operation_id="list_patient_reminders",
            summary="Listar los recordatorios de un paciente asignado",
            description="Recordatorios del paciente, del más antiguo al más nuevo.",
            responses=STAFF_READ_ERRORS,
            openapi_extra=assigned,
        )
        add(
            "/patients/{patient_id}/reminders/{reminder_id}",
            update_patient_reminder,
            methods=["PATCH"],
            operation_id="update_patient_reminder",
            summary="Cambiar el horario o activar un recordatorio de un paciente",
            description=(
                "Cambia la hora, los días o la bandera de activo. Un recordatorio de "
                "otro paciente responde `404`."
            ),
            responses=STAFF_WRITE_ERRORS,
            openapi_extra=assigned,
        )
        add(
            "/reminders",
            list_own_reminders,
            methods=["GET"],
            operation_id="list_own_reminders",
            summary="Listar mis recordatorios",
            description="Recordatorios propios del paciente que consulta.",
            responses=OWN_ERRORS,
            openapi_extra=own,
        )
        add(
            "/reminders/{reminder_id}",
            update_own_reminder,
            methods=["PATCH"],
            operation_id="update_own_reminder",
            summary="Ajustar un recordatorio propio",
            description=(
                "El paciente cambia la hora, los días o la bandera de activo de un "
                "recordatorio propio. Un recordatorio ajeno responde `404`. Quedan "
                "pendientes los límites que fije el plan de tratamiento."
            ),
            responses=OWN_ERRORS,
            openapi_extra=own,
        )
