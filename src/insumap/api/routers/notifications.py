"""Notification endpoints (API.md 8.9): the caller's own inbox, settings and Web Push.

Every route belongs to the caller. A patient needs the current consent (C3);
staff need the second factor, which the session actor checks (C2).
"""

from datetime import datetime, time
from http import HTTPStatus
from typing import Annotated, Any, Final, Self, final
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_serializer

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
from insumap.application.common.actor import Actor
from insumap.application.notifications.list_notifications import (
    ListNotificationsInput,
    ListNotificationsUseCase,
    NotificationItem,
)
from insumap.application.notifications.mark_read import MarkNotificationReadUseCase
from insumap.application.notifications.preferences import (
    GetNotificationPreferencesUseCase,
    UpdateNotificationPreferencesInput,
    UpdateNotificationPreferencesUseCase,
)
from insumap.application.notifications.web_push import (
    RegisterWebPushInput,
    RegisterWebPushSubscriptionUseCase,
    RemoveWebPushSubscriptionUseCase,
)
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.notifications.preferences import (
    Channel,
    NotificationPreferences,
)
from insumap.shared.field_limits import FieldLimits

NOTIFICATIONS_PATH: Final = "/notifications"
PREFERENCES_PATH: Final = "/notification-preferences"
WEB_PUSH_PATH: Final = f"{PREFERENCES_PATH}/web-push-subscription"
TIME_FORMAT: Final = "%H:%M"


class ChannelSettingsRequest(StrictRequest):
    """Whether each channel may reach the person."""

    EMAIL: bool = Field(description="Correo electrónico.")
    WEB_PUSH: bool = Field(description="Notificación push del navegador.")
    IN_APP: bool = Field(description="Aviso dentro de la aplicación.")


class ChannelSettingsResponse(BaseModel):
    """The channels as saved."""

    EMAIL: bool
    WEB_PUSH: bool
    IN_APP: bool


class QuietHoursRequest(StrictRequest):
    """A daily silence in the local time of the clinic; it may cross midnight."""

    start: time = Field(description="Inicio del silencio, `HH:MM` (hora local).")
    end: time = Field(description="Fin del silencio, `HH:MM` (hora local).")


class QuietHoursResponse(BaseModel):
    """The silence window as saved."""

    start: time
    end: time

    @field_serializer("start", "end")
    def hour_and_minute(self, value: time) -> str:
        return value.strftime(TIME_FORMAT)


class UpdatePreferencesRequest(StrictRequest):
    """The full preferences: a channel left out is disabled.

    `quiet_hours` set to `null` clears the silence.
    """

    channels: ChannelSettingsRequest
    quiet_hours: QuietHoursRequest | None = Field(
        description="Horario de silencio, o `null` para no tener."
    )


class PreferencesResponse(BaseModel):
    """The preferences of the caller."""

    channels: ChannelSettingsResponse
    quiet_hours: QuietHoursResponse | None

    @classmethod
    def of(cls, preferences: NotificationPreferences) -> Self:
        quiet = preferences.quiet_hours
        return cls(
            channels=ChannelSettingsResponse(
                EMAIL=preferences.is_enabled(Channel.EMAIL),
                WEB_PUSH=preferences.is_enabled(Channel.WEB_PUSH),
                IN_APP=preferences.is_enabled(Channel.IN_APP),
            ),
            quiet_hours=None
            if quiet is None
            else QuietHoursResponse(start=quiet.start, end=quiet.end),
        )


class PushKeysRequest(StrictRequest):
    """The public key and the auth secret of the browser subscription."""

    p256dh: str = Field(
        min_length=1,
        max_length=FieldLimits.PUSH_KEY_MAX_LENGTH,
        pattern=FieldLimits.PUSH_KEY_PATTERN,
        description="Clave pública del navegador (base64url).",
    )
    auth: str = Field(
        min_length=1,
        max_length=FieldLimits.PUSH_AUTH_SECRET_MAX_LENGTH,
        pattern=FieldLimits.PUSH_KEY_PATTERN,
        description="Secreto de autenticación del navegador (base64url).",
    )


class WebPushSubscriptionRequest(StrictRequest):
    """The subscription the browser created; the endpoint must be https."""

    endpoint: str = Field(
        max_length=FieldLimits.PUSH_ENDPOINT_MAX_LENGTH,
        pattern=FieldLimits.PUSH_ENDPOINT_PATTERN,
        description=(
            "URL https del servicio push. Un servicio no permitido responde `422`."
        ),
    )
    keys: PushKeysRequest


class NotificationResponse(BaseModel):
    """One in-app notification, with its text in the language of the API."""

    id: UUID
    type: str = Field(description="Tipo de notificación, por ejemplo `ALERT`.")
    title: str
    body: str
    entity_type: str | None = Field(description="Tipo del recurso referido.")
    entity_id: UUID | None = Field(description="Identificador del recurso referido.")
    created_at: datetime
    read_at: datetime | None
    simulated: bool = Field(description="Igual que `is_demo`: datos simulados.")

    @classmethod
    def of(cls, item: NotificationItem, *, simulated: bool) -> Self:
        return cls(
            id=item.notification_id,
            type=item.notification_type,
            title=item.title,
            body=item.body,
            entity_type=item.entity_type,
            entity_id=item.entity_id,
            created_at=item.created_at,
            read_at=item.read_at,
            simulated=simulated,
        )


READ_ERRORS: Final = error_responses(
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
    HTTPStatus.UNPROCESSABLE_ENTITY,
)
ITEM_ERRORS: Final = error_responses(
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
    HTTPStatus.NOT_FOUND,
    HTTPStatus.UNPROCESSABLE_ENTITY,
)
SUBSCRIPTION_ERRORS: Final = error_responses(
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
    HTTPStatus.UNPROCESSABLE_ENTITY,
    HTTPStatus.CONFLICT,
)


@final
class NotificationRouter:
    """Builds the notification routes over their use cases; no repository here.

    Permissions and scope are checked in the use cases; the account comes from
    the token, never from the path or the body.
    """

    def __init__(
        self,
        *,
        list_notifications: ListNotificationsUseCase,
        mark_read: MarkNotificationReadUseCase,
        get_preferences: GetNotificationPreferencesUseCase,
        update_preferences: UpdateNotificationPreferencesUseCase,
        register_push: RegisterWebPushSubscriptionUseCase,
        remove_push: RemoveWebPushSubscriptionUseCase,
        session_actor: Any,
    ) -> None:
        self._list = list_notifications
        self._mark_read = mark_read
        self._get_preferences = get_preferences
        self._update_preferences = update_preferences
        self._register_push = register_push
        self._remove_push = remove_push
        self._session_actor = session_actor
        self.router = APIRouter(prefix=API_V1_PREFIX, tags=[ApiTag.NOTIFICATIONS])
        self._add_routes()

    def _add_routes(self) -> None:
        add = self.router.add_api_route
        session = Depends(self._session_actor)

        def list_notifications(
            actor: Annotated[Actor, session],
            unread_only: Annotated[bool, Query()] = False,
            limit: LimitQuery = FieldLimits.PAGE_SIZE_DEFAULT,
            cursor: CursorQuery = None,
        ) -> PageResponse[NotificationResponse]:
            page = self._list.execute(
                ListNotificationsInput(
                    actor=actor,
                    unread_only=unread_only,
                    page=page_request(limit, cursor),
                )
            )
            simulated = actor.clinic_is_demo
            return PageResponse(
                items=[
                    NotificationResponse.of(item, simulated=simulated)
                    for item in page.items
                ],
                next_cursor=page.next_cursor,
            )

        def mark_notification_read(
            notification_id: UUID, actor: Annotated[Actor, session]
        ) -> None:
            self._mark_read.execute(actor, notification_id)

        def get_notification_preferences(
            actor: Annotated[Actor, session],
        ) -> PreferencesResponse:
            return PreferencesResponse.of(self._get_preferences.execute(actor))

        def update_notification_preferences(
            body: UpdatePreferencesRequest, actor: Annotated[Actor, session]
        ) -> PreferencesResponse:
            quiet = body.quiet_hours
            return PreferencesResponse.of(
                self._update_preferences.execute(
                    UpdateNotificationPreferencesInput(
                        actor=actor,
                        channels={
                            Channel.EMAIL: body.channels.EMAIL,
                            Channel.WEB_PUSH: body.channels.WEB_PUSH,
                            Channel.IN_APP: body.channels.IN_APP,
                        },
                        quiet_start=None if quiet is None else quiet.start,
                        quiet_end=None if quiet is None else quiet.end,
                    )
                )
            )

        def register_web_push_subscription(
            body: WebPushSubscriptionRequest, actor: Annotated[Actor, session]
        ) -> None:
            self._register_push.execute(
                RegisterWebPushInput(
                    actor=actor,
                    endpoint=body.endpoint,
                    p256dh=body.keys.p256dh,
                    auth=body.keys.auth,
                )
            )

        def remove_web_push_subscription(actor: Annotated[Actor, session]) -> None:
            self._remove_push.execute(actor)

        read = {ACCESS_EXTENSION: access(PermissionCode.NOTIFICATIONS_READ_OWN)}
        prefs = {
            ACCESS_EXTENSION: access(PermissionCode.NOTIFICATION_PREFERENCES_MANAGE_OWN)
        }
        add(
            NOTIFICATIONS_PATH,
            list_notifications,
            methods=["GET"],
            operation_id="list_notifications",
            summary="Listar mis notificaciones",
            description=(
                "Notificaciones dentro de la aplicación del usuario que llama, con "
                "título y texto ya redactados. Con `unread_only=true` solo las no "
                "leídas. No incluye valores clínicos."
            ),
            responses=READ_ERRORS,
            openapi_extra=read,
        )
        add(
            f"{NOTIFICATIONS_PATH}/{{notification_id}}/read",
            mark_notification_read,
            methods=["POST"],
            status_code=HTTPStatus.NO_CONTENT,
            operation_id="mark_notification_read",
            summary="Marcar una notificación como leída",
            description=(
                "Registra la hora de lectura la primera vez. Repetirla no cambia "
                "la hora. Una notificación de otra persona responde `404`."
            ),
            responses=ITEM_ERRORS,
            openapi_extra=read,
        )
        add(
            PREFERENCES_PATH,
            get_notification_preferences,
            methods=["GET"],
            operation_id="get_notification_preferences",
            summary="Consultar mis preferencias de notificación",
            description=(
                "Canales habilitados (`EMAIL`, `WEB_PUSH` e `IN_APP`) y horario de "
                "silencio. Sin preferencias guardadas, todos los canales están "
                "habilitados y no hay silencio."
            ),
            responses=READ_ERRORS,
            openapi_extra=prefs,
        )
        add(
            PREFERENCES_PATH,
            update_notification_preferences,
            methods=["PUT"],
            operation_id="update_notification_preferences",
            summary="Cambiar mis preferencias de notificación",
            description=(
                "Reemplaza los canales y el horario de silencio. Las alertas críticas "
                "(hipoglucemia de nivel 2 y 3) no se silencian."
            ),
            responses=READ_ERRORS,
            openapi_extra=prefs,
        )
        add(
            WEB_PUSH_PATH,
            register_web_push_subscription,
            methods=["PUT"],
            status_code=HTTPStatus.NO_CONTENT,
            operation_id="register_web_push_subscription",
            summary="Registrar mi suscripción Web Push",
            description=(
                "Guarda la suscripción del navegador y reemplaza la anterior del "
                "usuario. El endpoint debe ser https y de un servicio permitido; si "
                "no lo es, responde `422` y queda registrado. Si el endpoint ya "
                "pertenece a otra cuenta responde `409`."
            ),
            responses=SUBSCRIPTION_ERRORS,
            openapi_extra=prefs,
        )
        add(
            WEB_PUSH_PATH,
            remove_web_push_subscription,
            methods=["DELETE"],
            status_code=HTTPStatus.NO_CONTENT,
            operation_id="remove_web_push_subscription",
            summary="Quitar mi suscripción Web Push",
            description=(
                "Elimina las suscripciones Web Push del usuario que llama. No es un "
                "registro clínico."
            ),
            responses=READ_ERRORS,
            openapi_extra=prefs,
        )
