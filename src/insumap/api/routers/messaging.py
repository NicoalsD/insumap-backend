"""Messaging and follow-up endpoints (API.md 8.12): the thread and the controls.

The patient's own routes take no patient id (V3); a doctor names an assigned
patient and gets ``404`` for anyone else. The administrator has no permission
on these routes and gets ``403``.
"""

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
from insumap.api.routers.messaging_schemas import (
    CloseFollowUpRequest,
    CreateFollowUpRequest,
    FollowUpResponse,
    MessageListResponse,
    MessageResponse,
    SendMessageRequest,
)
from insumap.api.tags import ApiTag
from insumap.application.commands.base import CommandBus
from insumap.application.common.actor import Actor
from insumap.application.follow_ups.commands import (
    CloseFollowUpCommand,
    CreateFollowUpCommand,
)
from insumap.application.follow_ups.queries import (
    ListFollowUpsInput,
    ListFollowUpsUseCase,
)
from insumap.application.messaging.list_messages import (
    ListMessagesInput,
    ListMessagesUseCase,
)
from insumap.application.messaging.send_message import (
    SendMessageInput,
    SendMessageUseCase,
)
from insumap.domain.follow_ups.follow_up import FollowUpStatus
from insumap.domain.identity.permissions import PermissionCode
from insumap.shared.field_limits import FieldLimits

MESSAGE_ERRORS: Final = error_responses(
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
    HTTPStatus.NOT_FOUND,
    HTTPStatus.UNPROCESSABLE_ENTITY,
)
FOLLOW_UP_WRITE_ERRORS: Final = error_responses(
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
    HTTPStatus.NOT_FOUND,
    HTTPStatus.CONFLICT,
    HTTPStatus.UNPROCESSABLE_ENTITY,
)


@final
class MessagingRouter:
    """Builds the thread and control routes over the use cases and the command bus.

    Writes go through the command bus (P13, audited P09) for the controls and
    through the send use case (transaction, P07 notification) for messages.
    Scope and permissions are checked in the use cases; row level security
    repeats the scope.
    """

    def __init__(
        self,
        *,
        commands: CommandBus,
        list_messages: ListMessagesUseCase,
        send_message: SendMessageUseCase,
        list_follow_ups: ListFollowUpsUseCase,
        session_actor: Any,
    ) -> None:
        self._commands = commands
        self._list_messages = list_messages
        self._send_message = send_message
        self._list_follow_ups = list_follow_ups
        self._actor_guard = session_actor
        self.router = APIRouter(prefix=API_V1_PREFIX, tags=[ApiTag.MESSAGING])
        self._add_routes()

    def _add_routes(self) -> None:
        add = self.router.add_api_route
        guard = Depends(self._actor_guard)
        # The label names the patient's permission; the doctor's is in the description.
        own = {ACCESS_EXTENSION: access(PermissionCode.MESSAGES_USE_OWN)}
        follow_own = {ACCESS_EXTENSION: access(PermissionCode.FOLLOW_UPS_READ_OWN)}
        manage = {ACCESS_EXTENSION: access(PermissionCode.FOLLOW_UPS_MANAGE)}

        def list_messages(
            actor: Annotated[Actor, guard],
            patient_id: Annotated[UUID | None, Query()] = None,
            limit: LimitQuery = FieldLimits.PAGE_SIZE_DEFAULT,
            cursor: CursorQuery = None,
        ) -> MessageListResponse:
            listing = self._list_messages.execute(
                ListMessagesInput(
                    actor=actor,
                    patient_id=patient_id,
                    page=page_request(limit, cursor),
                )
            )
            return MessageListResponse(
                items=[
                    MessageResponse.of(message, simulated=actor.clinic_is_demo)
                    for message in listing.page.items
                ],
                next_cursor=listing.page.next_cursor,
                emergency_notice=listing.emergency_notice,
            )

        def send_message(
            body: SendMessageRequest, actor: Annotated[Actor, guard]
        ) -> MessageResponse:
            message = self._send_message.execute(
                SendMessageInput(
                    actor=actor, patient_id=body.patient_id, body=body.body
                )
            )
            return MessageResponse.of(message, simulated=actor.clinic_is_demo)

        def list_follow_ups(
            actor: Annotated[Actor, guard],
            patient_id: Annotated[UUID | None, Query()] = None,
            status: Annotated[FollowUpStatus | None, Query()] = None,
            limit: LimitQuery = FieldLimits.PAGE_SIZE_DEFAULT,
            cursor: CursorQuery = None,
        ) -> PageResponse[FollowUpResponse]:
            page = self._list_follow_ups.execute(
                ListFollowUpsInput(
                    actor=actor,
                    patient_id=patient_id,
                    status=status,
                    page=page_request(limit, cursor),
                )
            )
            return PageResponse(
                items=[
                    FollowUpResponse.of(item, simulated=actor.clinic_is_demo)
                    for item in page.items
                ],
                next_cursor=page.next_cursor,
            )

        def create_follow_up(
            body: CreateFollowUpRequest, actor: Annotated[Actor, guard]
        ) -> FollowUpResponse:
            follow_up = self._commands.dispatch(
                CreateFollowUpCommand(
                    actor=actor,
                    patient_id=body.patient_id,
                    scheduled_for=body.scheduled_at,
                )
            )
            return FollowUpResponse.of(follow_up, simulated=actor.clinic_is_demo)

        def close_follow_up(
            follow_up_id: UUID,
            body: CloseFollowUpRequest,
            actor: Annotated[Actor, guard],
        ) -> FollowUpResponse:
            follow_up = self._commands.dispatch(
                CloseFollowUpCommand(
                    actor=actor,
                    follow_up_id=follow_up_id,
                    outcome=body.outcome,
                    result_note=body.result_note,
                )
            )
            return FollowUpResponse.of(follow_up, simulated=actor.clinic_is_demo)

        add(
            "/messages",
            list_messages,
            methods=["GET"],
            operation_id="list_messages",
            summary="Listar los mensajes del hilo de un paciente",
            description=(
                "El paciente lee su propio hilo (`messages.use_own`). El médico "
                "(`messages.use_assigned`) lee el de un paciente asignado con "
                "`patient_id`; la lectura queda auditada. Devuelve del más reciente "
                "al más antiguo, con el aviso de que no es un canal de emergencias."
            ),
            responses=MESSAGE_ERRORS,
            openapi_extra=own,
        )
        add(
            "/messages",
            send_message,
            methods=["POST"],
            status_code=HTTPStatus.CREATED,
            operation_id="send_message",
            summary="Enviar un mensaje al equipo de atención",
            description=(
                "Agrega un mensaje de texto plano al hilo. El remitente es la sesión "
                "y su rol; el paciente no envía `patient_id`. Avisa al otro lado "
                "dentro de la app, sin el texto. No es un canal de emergencias."
            ),
            responses=MESSAGE_ERRORS,
            openapi_extra=own,
        )
        add(
            "/follow-ups",
            list_follow_ups,
            methods=["GET"],
            operation_id="list_follow_ups",
            summary="Listar los controles de seguimiento",
            description=(
                "El paciente ve sus controles (`follow_ups.read_own`). El médico "
                "(`follow_ups.manage`) ve los de un paciente asignado; `patient_id` "
                "es obligatorio para él. Filtra por `status`."
            ),
            responses=MESSAGE_ERRORS,
            openapi_extra=follow_own,
        )
        add(
            "/follow-ups",
            create_follow_up,
            methods=["POST"],
            status_code=HTTPStatus.CREATED,
            operation_id="create_follow_up",
            summary="Programar un control de seguimiento",
            description=(
                "El médico programa un control de un paciente asignado en una fecha "
                "futura. Un paciente no asignado responde `404`; una fecha pasada, "
                "`422`."
            ),
            responses=FOLLOW_UP_WRITE_ERRORS,
            openapi_extra=manage,
        )
        add(
            "/follow-ups/{follow_up_id}/close",
            close_follow_up,
            methods=["POST"],
            operation_id="close_follow_up",
            summary="Cerrar un control con su resultado",
            description=(
                "Registra si el control se atendió (`DONE`) o no (`MISSED`), con el "
                "resultado en texto. Un control ya cerrado responde `409`."
            ),
            responses=FOLLOW_UP_WRITE_ERRORS,
            openapi_extra=manage,
        )
