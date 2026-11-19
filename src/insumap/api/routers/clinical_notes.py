"""Clinical notes of an assigned patient: append only (API.md 8.11)."""

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
from insumap.api.routers.dashboard_schemas import (
    ClinicalNoteRequest,
    ClinicalNoteResponse,
)
from insumap.api.tags import ApiTag
from insumap.application.commands.base import CommandBus
from insumap.application.common.actor import Actor
from insumap.application.dashboard.clinical_notes_queries import (
    ListClinicalNotesInput,
    ListClinicalNotesUseCase,
)
from insumap.application.dashboard.commands import CreateClinicalNoteCommand
from insumap.domain.identity.permissions import PermissionCode
from insumap.shared.field_limits import FieldLimits

CLINICAL_NOTES_PATH: Final = "/patients/{patient_id}/clinical-notes"
NOTE_ERRORS: Final = error_responses(
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
    HTTPStatus.NOT_FOUND,
    HTTPStatus.UNPROCESSABLE_ENTITY,
)


@final
class ClinicalNotesRouter:
    """``/api/v1/patients/{patient_id}/clinical-notes``.

    The write goes through the bus (P13, audited); the list through the use case
    (P11 and the granted read audit, P09). Only the assigned doctor reaches them.
    """

    def __init__(
        self,
        *,
        commands: CommandBus,
        list_notes: ListClinicalNotesUseCase,
        staff_actor: Any,
    ) -> None:
        self._commands = commands
        self._list = list_notes
        self._staff_actor = staff_actor
        self.router = APIRouter(prefix=API_V1_PREFIX, tags=[ApiTag.DASHBOARD])
        self._add_routes()

    def _add_routes(self) -> None:
        add = self.router.add_api_route
        staff = Depends(self._staff_actor)
        label = {ACCESS_EXTENSION: access(PermissionCode.CLINICAL_NOTES_MANAGE)}

        def create_clinical_note(
            patient_id: UUID,
            body: ClinicalNoteRequest,
            actor: Annotated[Actor, staff],
        ) -> ClinicalNoteResponse:
            note = self._commands.dispatch(
                CreateClinicalNoteCommand(
                    actor=actor,
                    patient_id=patient_id,
                    text=body.text,
                    corrects_note_id=body.corrects_note_id,
                )
            )
            return ClinicalNoteResponse.of(note, simulated=actor.clinic_is_demo)

        def list_clinical_notes(
            patient_id: UUID,
            actor: Annotated[Actor, staff],
            limit: LimitQuery = FieldLimits.PAGE_SIZE_DEFAULT,
            cursor: CursorQuery = None,
        ) -> PageResponse[ClinicalNoteResponse]:
            page = self._list.execute(
                ListClinicalNotesInput(
                    actor=actor,
                    patient_id=patient_id,
                    page=page_request(limit, cursor),
                )
            )
            return PageResponse(
                items=[
                    ClinicalNoteResponse.of(note, simulated=actor.clinic_is_demo)
                    for note in page.items
                ],
                next_cursor=page.next_cursor,
            )

        add(
            CLINICAL_NOTES_PATH,
            create_clinical_note,
            methods=["POST"],
            status_code=HTTPStatus.CREATED,
            operation_id="create_clinical_note",
            summary="Agregar una nota clínica",
            description=(
                "Agrega una nota del médico asignado. Las notas no se editan ni se "
                "borran: para corregir una, se crea otra con `corrects_note_id`. "
                "El administrador recibe `403`; un paciente no asignado, `404`."
            ),
            responses=NOTE_ERRORS,
            openapi_extra=label,
        )
        add(
            CLINICAL_NOTES_PATH,
            list_clinical_notes,
            methods=["GET"],
            operation_id="list_clinical_notes",
            summary="Listar las notas clínicas de un paciente",
            description=(
                "Notas del paciente asignado, de la más antigua a la más reciente. "
                "Cada lectura queda en la auditoría. El administrador recibe `403`."
            ),
            responses=NOTE_ERRORS,
            openapi_extra=label,
        )
