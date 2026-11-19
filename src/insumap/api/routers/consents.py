"""Consent and privacy endpoints (API.md 8.13)."""

from http import HTTPStatus
from typing import Annotated, Any, Final, final
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from insumap.api.paths import API_V1_PREFIX
from insumap.api.routers.common import (
    ACCESS_EXTENSION,
    PUBLIC,
    CursorQuery,
    LimitQuery,
    PageResponse,
    access,
    error_responses,
    page_request,
)
from insumap.api.routers.consents_schemas import (
    AcceptConsentRequest,
    OwnConsentResponse,
    PatientConsentStatusResponse,
    PrivacyNoticeResponse,
    PrivacyRequestCreateRequest,
    PrivacyRequestResponse,
    ResolvePrivacyRequestRequest,
    WithdrawConsentRequest,
)
from insumap.api.tags import ApiTag
from insumap.application.commands.base import CommandBus
from insumap.application.common.actor import Actor
from insumap.application.consents.commands import (
    AcceptConsentCommand,
    WithdrawConsentCommand,
)
from insumap.application.consents.privacy_requests import (
    CreatePrivacyRequestCommand,
    ExportPrivacyRequestUseCase,
    ListPrivacyRequestsUseCase,
    ResolvePrivacyRequestCommand,
)
from insumap.application.consents.queries import (
    GetOwnConsentUseCase,
    GetPrivacyNoticeUseCase,
    ListConsentStatusesInput,
    ListConsentStatusesUseCase,
)
from insumap.domain.identity.permissions import PermissionCode
from insumap.shared.field_limits import FieldLimits

CONSENTS_PREFIX: Final = f"{API_V1_PREFIX}/consents"
PRIVACY_PREFIX: Final = f"{API_V1_PREFIX}/privacy-requests"
PUBLIC_NOTICE_PREFIX: Final = f"{API_V1_PREFIX}/public/privacy-notices"
REQUEST_PATH: Final = "/{request_id}"

OWN_ERRORS: Final = error_responses(
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
    HTTPStatus.UNPROCESSABLE_ENTITY,
)
WRITE_ERRORS: Final = error_responses(
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
    HTTPStatus.UNPROCESSABLE_ENTITY,
    HTTPStatus.CONFLICT,
)
NOT_FOUND_ERRORS: Final = error_responses(
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
    HTTPStatus.NOT_FOUND,
    HTTPStatus.UNPROCESSABLE_ENTITY,
    HTTPStatus.CONFLICT,
)
PUBLIC_ERRORS: Final = error_responses(
    HTTPStatus.NOT_FOUND, HTTPStatus.UNPROCESSABLE_ENTITY
)


@final
class ConsentRouter:
    """Builds the consent and privacy routes over use cases and the command bus.

    Writes go through the bus (transaction and audit, P09 and P13). The consent
    routes of the patient are exempt from C3 so that a pending version can be
    accepted (API.md 2.4, point 6).
    """

    def __init__(
        self,
        *,
        commands: CommandBus,
        notice: GetPrivacyNoticeUseCase,
        own_consent: GetOwnConsentUseCase,
        list_statuses: ListConsentStatusesUseCase,
        list_requests: ListPrivacyRequestsUseCase,
        export_request: ExportPrivacyRequestUseCase,
        session_actor: Any,
    ) -> None:
        self._commands = commands
        self._notice = notice
        self._own = own_consent
        self._statuses = list_statuses
        self._requests = list_requests
        self._export = export_request
        self._session_actor = session_actor
        self.router = APIRouter()
        self._add_routes()

    def _add_routes(self) -> None:
        add = self.router.add_api_route
        session = Depends(self._session_actor)

        def get_privacy_notice(
            privacy_notice_version_id: UUID,
        ) -> PrivacyNoticeResponse:
            return PrivacyNoticeResponse.of(
                self._notice.execute(privacy_notice_version_id)
            )

        def get_own_consent(actor: Annotated[Actor, session]) -> OwnConsentResponse:
            return OwnConsentResponse.of(self._own.execute(actor))

        def accept_consent(
            body: AcceptConsentRequest, actor: Annotated[Actor, session]
        ) -> OwnConsentResponse:
            return OwnConsentResponse.of(
                self._commands.dispatch(
                    AcceptConsentCommand(
                        actor=actor,
                        privacy_notice_version_id=body.privacy_notice_version_id,
                        ai_external_processing=body.ai_external_processing,
                    )
                )
            )

        def withdraw_consent(
            body: WithdrawConsentRequest, actor: Annotated[Actor, session]
        ) -> OwnConsentResponse:
            return OwnConsentResponse.of(
                self._commands.dispatch(
                    WithdrawConsentCommand(actor=actor, scope=body.scope)
                )
            )

        def list_consent_statuses(
            actor: Annotated[Actor, session],
            limit: LimitQuery = FieldLimits.PAGE_SIZE_DEFAULT,
            cursor: CursorQuery = None,
        ) -> PageResponse[PatientConsentStatusResponse]:
            page = self._statuses.execute(
                ListConsentStatusesInput(actor=actor, page=page_request(limit, cursor))
            )
            return PageResponse(
                items=[PatientConsentStatusResponse.of(s) for s in page.items],
                next_cursor=page.next_cursor,
            )

        def create_privacy_request(
            body: PrivacyRequestCreateRequest, actor: Annotated[Actor, session]
        ) -> PrivacyRequestResponse:
            return PrivacyRequestResponse.of(
                self._commands.dispatch(
                    CreatePrivacyRequestCommand(
                        actor=actor,
                        request_type=body.request_type,
                        description=body.description,
                    )
                )
            )

        def list_privacy_requests(
            actor: Annotated[Actor, session],
            limit: LimitQuery = FieldLimits.PAGE_SIZE_DEFAULT,
            cursor: CursorQuery = None,
        ) -> PageResponse[PrivacyRequestResponse]:
            page = self._requests.execute(actor, page_request(limit, cursor))
            return PageResponse(
                items=[PrivacyRequestResponse.of(r) for r in page.items],
                next_cursor=page.next_cursor,
            )

        def resolve_privacy_request(
            request_id: UUID,
            body: ResolvePrivacyRequestRequest,
            actor: Annotated[Actor, session],
        ) -> PrivacyRequestResponse:
            return PrivacyRequestResponse.of(
                self._commands.dispatch(
                    ResolvePrivacyRequestCommand(
                        actor=actor,
                        request_id=request_id,
                        decision=body.decision,
                        note=body.note,
                    )
                )
            )

        def export_privacy_request(
            request_id: UUID, actor: Annotated[Actor, session]
        ) -> JSONResponse:
            exported = self._export.execute(actor, request_id)
            return JSONResponse(
                content={
                    "request_id": str(exported.request_id),
                    "patient_id": str(exported.patient_id),
                    "generated_at": exported.generated_at.isoformat(),
                    "events": exported.events,
                    "consents": exported.consents,
                },
            )

        public = {ACCESS_EXTENSION: PUBLIC}
        own = {ACCESS_EXTENSION: access(PermissionCode.CONSENTS_MANAGE_OWN)}
        read_status = {ACCESS_EXTENSION: access(PermissionCode.CONSENTS_READ_STATUS)}
        create_own = {
            ACCESS_EXTENSION: access(PermissionCode.PRIVACY_REQUESTS_CREATE_OWN)
        }
        manage = {ACCESS_EXTENSION: access(PermissionCode.PRIVACY_REQUESTS_MANAGE)}

        add(
            f"{PUBLIC_NOTICE_PREFIX}/{{privacy_notice_version_id}}",
            get_privacy_notice,
            methods=["GET"],
            operation_id="get_privacy_notice",
            summary="Leer el aviso de privacidad vigente",
            description=(
                "Texto del aviso de privacidad de una versión, sin sesión. Lo usa la "
                "activación antes del inicio de sesión."
            ),
            tags=[ApiTag.PUBLIC],
            responses=PUBLIC_ERRORS,
            openapi_extra=public,
        )
        add(
            f"{CONSENTS_PREFIX}/own",
            get_own_consent,
            methods=["GET"],
            operation_id="get_own_consent",
            summary="Consultar el consentimiento propio",
            description=(
                "Versión aceptada, fecha y alcances. No exige un consentimiento "
                "vigente, "
                "para poder aceptar una versión nueva."
            ),
            tags=[ApiTag.CONSENT],
            responses=OWN_ERRORS,
            openapi_extra=own,
        )
        add(
            f"{CONSENTS_PREFIX}/own/acceptances",
            accept_consent,
            methods=["POST"],
            status_code=HTTPStatus.CREATED,
            operation_id="accept_consent",
            summary="Aceptar el aviso de privacidad vigente",
            description=(
                "Guarda la aceptación con la versión, la fecha y el alcance. Una "
                "versión que ya no es la vigente responde `409`."
            ),
            tags=[ApiTag.CONSENT],
            responses=WRITE_ERRORS,
            openapi_extra=own,
        )
        add(
            f"{CONSENTS_PREFIX}/own/withdrawals",
            withdraw_consent,
            methods=["POST"],
            operation_id="withdraw_consent",
            summary="Retirar un alcance del consentimiento",
            description=(
                "Agrega una fila de retiro; no borra lo anterior. Retirar el "
                "tratamiento "
                "de datos sensibles detiene los registros nuevos y avisa a la clínica."
            ),
            tags=[ApiTag.CONSENT],
            responses=WRITE_ERRORS,
            openapi_extra=own,
        )
        add(
            CONSENTS_PREFIX,
            list_consent_statuses,
            methods=["GET"],
            operation_id="list_consent_statuses",
            summary="Listar el estado del consentimiento por paciente",
            description=(
                "Estado del consentimiento y versión aceptada de cada paciente de la "
                "clínica. No incluye contenido clínico. Queda en la auditoría."
            ),
            tags=[ApiTag.CONSENT],
            responses=error_responses(
                HTTPStatus.UNAUTHORIZED,
                HTTPStatus.FORBIDDEN,
                HTTPStatus.UNPROCESSABLE_ENTITY,
            ),
            openapi_extra=read_status,
        )
        add(
            PRIVACY_PREFIX,
            create_privacy_request,
            methods=["POST"],
            status_code=HTTPStatus.CREATED,
            operation_id="create_privacy_request",
            summary="Crear una solicitud de privacidad",
            description=(
                "El paciente pide acceso, rectificación, supresión o retiro. La "
                "respuesta trae el estado y el plazo."
            ),
            tags=[ApiTag.CONSENT],
            responses=OWN_ERRORS,
            openapi_extra=create_own,
        )
        add(
            PRIVACY_PREFIX,
            list_privacy_requests,
            methods=["GET"],
            operation_id="list_privacy_requests",
            summary="Listar las solicitudes de privacidad",
            description=(
                "El paciente ve las propias; el administrador de la clínica, las de su "
                "clínica. Sin contenido clínico."
            ),
            tags=[ApiTag.CONSENT],
            responses=OWN_ERRORS,
            openapi_extra=create_own,
        )
        add(
            f"{PRIVACY_PREFIX}{REQUEST_PATH}/resolve",
            resolve_privacy_request,
            methods=["POST"],
            operation_id="resolve_privacy_request",
            summary="Aprobar o rechazar una solicitud de privacidad",
            description=(
                "La clínica decide con un motivo. Una solicitud ya resuelta "
                "responde `409`."
            ),
            tags=[ApiTag.CONSENT],
            responses=NOT_FOUND_ERRORS,
            openapi_extra=manage,
        )
        add(
            f"{PRIVACY_PREFIX}{REQUEST_PATH}/export",
            export_privacy_request,
            methods=["GET"],
            operation_id="export_privacy_request_data",
            summary="Exportar los datos propios de una solicitud aprobada",
            description=(
                "Datos del paciente en JSON, solo para una solicitud aprobada. Queda "
                "registrada como exportación en la auditoría. El formato FHIR aún no "
                "está disponible."
            ),
            tags=[ApiTag.CONSENT],
            responses=NOT_FOUND_ERRORS,
            openapi_extra=create_own,
        )
