"""Target profile endpoints (API.md 8.7): catalog, versions and assignment."""

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
from insumap.api.routers.targets_schemas import (
    PatientTargetAssignmentResponse,
    ProfilePopulation,
    TargetProfileAssignRequest,
    TargetProfileCreateRequest,
    TargetProfileDetailResponse,
    TargetProfileResponse,
    TargetProfileVersionRequest,
    TargetProfileVersionSummary,
)
from insumap.api.tags import ApiTag
from insumap.application.commands.base import CommandBus
from insumap.application.common.actor import Actor
from insumap.application.targets.commands import (
    AssignTargetProfileCommand,
    CreateTargetProfileCommand,
    CreateTargetProfileVersionCommand,
)
from insumap.application.targets.queries import (
    GetTargetProfileInput,
    GetTargetProfileUseCase,
    ListTargetProfilesInput,
    ListTargetProfilesUseCase,
)
from insumap.domain.identity.permissions import PermissionCode
from insumap.shared.field_limits import FieldLimits

WRITE_ERRORS: Final = error_responses(
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
    HTTPStatus.NOT_FOUND,
    HTTPStatus.CONFLICT,
    HTTPStatus.UNPROCESSABLE_ENTITY,
)
READ_ERRORS: Final = error_responses(
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
    HTTPStatus.NOT_FOUND,
    HTTPStatus.UNPROCESSABLE_ENTITY,
)
ASSIGN_ERRORS: Final = error_responses(
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
    HTTPStatus.NOT_FOUND,
    HTTPStatus.CONFLICT,
    HTTPStatus.UNPROCESSABLE_ENTITY,
)


@final
class TargetProfileRouter:
    """Builds the goals routes over the catalog use cases and the commands (P13).

    Writes go through the command bus, so each one runs in its transaction and
    leaves its audit row (P09). The permission and the scope are checked in the
    use cases and the handlers; row level security repeats the clinic scope.
    """

    def __init__(
        self,
        *,
        commands: CommandBus,
        list_profiles: ListTargetProfilesUseCase,
        get_profile: GetTargetProfileUseCase,
        session_actor: Any,
    ) -> None:
        self._commands = commands
        self._list = list_profiles
        self._get = get_profile
        self._actor_guard = session_actor
        self.router = APIRouter(prefix=API_V1_PREFIX, tags=[ApiTag.TREATMENT])
        self._add_routes()

    def _add_routes(self) -> None:
        add = self.router.add_api_route
        guard = Depends(self._actor_guard)
        manage = {ACCESS_EXTENSION: access(PermissionCode.TARGET_PROFILES_MANAGE)}
        assign = {ACCESS_EXTENSION: access(PermissionCode.TARGET_PROFILES_ASSIGN)}

        def create_target_profile(
            body: TargetProfileCreateRequest, actor: Annotated[Actor, guard]
        ) -> TargetProfileResponse:
            return TargetProfileResponse.of(
                self._commands.dispatch(
                    CreateTargetProfileCommand(
                        actor=actor, code=body.code, values=body.to_values()
                    )
                )
            )

        def list_target_profiles(
            actor: Annotated[Actor, guard],
            population: Annotated[ProfilePopulation | None, Query()] = None,
            limit: LimitQuery = FieldLimits.PAGE_SIZE_DEFAULT,
            cursor: CursorQuery = None,
        ) -> PageResponse[TargetProfileResponse]:
            page = self._list.execute(
                ListTargetProfilesInput(
                    actor=actor,
                    population=None if population is None else population.value,
                    page=page_request(limit, cursor),
                )
            )
            return PageResponse(
                items=[TargetProfileResponse.of(v) for v in page.items],
                next_cursor=page.next_cursor,
            )

        def get_target_profile(
            profile_id: UUID, actor: Annotated[Actor, guard]
        ) -> TargetProfileDetailResponse:
            detail = self._get.execute(
                GetTargetProfileInput(actor=actor, profile_id=profile_id)
            )
            current = TargetProfileResponse.of(detail.profile)
            return TargetProfileDetailResponse(
                **current.model_dump(),
                versions=[TargetProfileVersionSummary.of(v) for v in detail.versions],
            )

        def create_target_profile_version(
            profile_id: UUID,
            body: TargetProfileVersionRequest,
            actor: Annotated[Actor, guard],
        ) -> TargetProfileResponse:
            return TargetProfileResponse.of(
                self._commands.dispatch(
                    CreateTargetProfileVersionCommand(
                        actor=actor,
                        profile_id=profile_id,
                        changes=body.changes(),
                        change_reason=body.change_reason,
                    )
                )
            )

        def assign_target_profile(
            patient_id: UUID,
            body: TargetProfileAssignRequest,
            actor: Annotated[Actor, guard],
        ) -> PatientTargetAssignmentResponse:
            return PatientTargetAssignmentResponse.of(
                self._commands.dispatch(
                    AssignTargetProfileCommand(
                        actor=actor,
                        patient_id=patient_id,
                        target_profile_id=body.target_profile_id,
                    )
                )
            )

        add(
            "/target-profiles",
            create_target_profile,
            methods=["POST"],
            status_code=HTTPStatus.CREATED,
            operation_id="create_target_profile",
            summary="Crear un perfil de metas de la clínica",
            description=(
                "Crea un perfil con su código y sus valores; la versión 1 queda "
                "vigente. Los valores se validan como conjunto: rangos ordenados y "
                "porcentajes entre 0 y 100. Un código repetido responde `409`."
            ),
            responses=WRITE_ERRORS,
            openapi_extra=manage,
        )
        add(
            "/target-profiles",
            list_target_profiles,
            methods=["GET"],
            operation_id="list_target_profiles",
            summary="Listar los perfiles de metas vigentes",
            description=(
                "Perfiles vigentes de la clínica y los perfiles semilla. Permiso: "
                "`target_profiles.manage` o `target_profiles.assign`."
            ),
            responses=READ_ERRORS,
            openapi_extra=manage,
        )
        add(
            "/target-profiles/{profile_id}",
            get_target_profile,
            methods=["GET"],
            operation_id="get_target_profile",
            summary="Consultar un perfil de metas y su historial",
            description=(
                "Devuelve el perfil con todos sus valores y el historial de versiones "
                "de su código. Permiso: `target_profiles.manage` o "
                "`target_profiles.assign`."
            ),
            responses=READ_ERRORS,
            openapi_extra=manage,
        )
        add(
            "/target-profiles/{profile_id}/versions",
            create_target_profile_version,
            methods=["POST"],
            status_code=HTTPStatus.CREATED,
            operation_id="create_target_profile_version",
            summary="Crear una versión nueva de un perfil de la clínica",
            description=(
                "Copia la versión vigente, aplica los cambios y la hace vigente; la "
                "anterior pasa a `RETIRED`. Las métricas pasadas conservan la versión "
                "con la que se calcularon. Los perfiles semilla no se versionan."
            ),
            responses=WRITE_ERRORS,
            openapi_extra=manage,
        )
        add(
            "/patients/{patient_id}/target-profile",
            assign_target_profile,
            methods=["PUT"],
            operation_id="assign_target_profile",
            summary="Asignar un perfil de metas a un paciente",
            description=(
                "Cierra la asignación vigente y abre la del perfil indicado. Las "
                "métricas del paciente se comparan desde entonces con ese perfil. Un "
                "paciente no asignado al médico responde `404`; un perfil retirado, "
                "`409`."
            ),
            responses=ASSIGN_ERRORS,
            openapi_extra=assign,
        )
