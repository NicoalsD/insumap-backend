"""Site endpoints (API.md 8.3, RF-15 Post-MVP): clinic sites and staff sites."""

from http import HTTPStatus
from typing import Annotated, Any, Final, Self, final
from uuid import UUID

from fastapi import APIRouter, Depends
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
from insumap.application.commands.base import CommandBus
from insumap.application.common.actor import Actor
from insumap.application.sites.commands import (
    CreateSiteCommand,
    SetUserSitesCommand,
    UpdateSiteCommand,
)
from insumap.application.sites.list_sites import ListSitesInput, ListSitesUseCase
from insumap.domain.clinic.site import Site, StaffSites
from insumap.domain.identity.permissions import PermissionCode
from insumap.shared.field_limits import FieldLimits

NAME_DESCRIPTION: Final = (
    "Nombre de la sede. Es único en la clínica, sin distinguir mayúsculas."
)
SITE_NAME_FIELD: Final = Field(
    max_length=FieldLimits.SITE_NAME_MAX_LENGTH, description=NAME_DESCRIPTION
)


class CreateSiteRequest(StrictRequest):
    """A site of the clinic of the administrator."""

    name: str = SITE_NAME_FIELD


class UpdateSiteRequest(StrictRequest):
    """The new name of a site."""

    name: str = SITE_NAME_FIELD


class SetUserSitesRequest(StrictRequest):
    """The complete list of sites where a staff member works (replaces the old one)."""

    site_ids: list[UUID] = Field(
        max_length=FieldLimits.STAFF_SITES_MAX_ITEMS,
        description=(
            "Sedes de la clínica donde trabaja el personal. Una lista vacía quita "
            "todas. Los identificadores repetidos cuentan una sola vez."
        ),
    )


class SiteResponse(BaseModel):
    """A site of the clinic."""

    id: UUID
    name: str
    simulated: bool = Field(
        description="`true` si la clínica es la de datos simulados."
    )

    @classmethod
    def of(cls, site: Site) -> Self:
        return cls(id=site.site_id, name=site.name, simulated=site.clinic_is_demo)


class StaffSitesResponse(BaseModel):
    """A staff member with the sites where it works."""

    user_id: UUID
    site_ids: list[UUID]
    simulated: bool = Field(
        description="`true` si la clínica es la de datos simulados."
    )

    @classmethod
    def of(cls, staff: StaffSites) -> Self:
        return cls(
            user_id=staff.user_id,
            site_ids=sorted(staff.site_ids),
            simulated=staff.clinic_is_demo,
        )


WRITE_ERRORS: Final = error_responses(
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
    HTTPStatus.UNPROCESSABLE_ENTITY,
    HTTPStatus.CONFLICT,
)
WRITE_ERRORS_WITH_TARGET: Final = error_responses(
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
    HTTPStatus.NOT_FOUND,
    HTTPStatus.UNPROCESSABLE_ENTITY,
    HTTPStatus.CONFLICT,
)
STAFF_SITES_ERRORS: Final = error_responses(
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
    HTTPStatus.NOT_FOUND,
    HTTPStatus.UNPROCESSABLE_ENTITY,
)


@final
class SiteRouter:
    """Builds the site endpoints over the command bus (P13) and the listing.

    Every write goes through the command bus, so it runs in its transaction and
    leaves its audit row (P09). The permission and the clinic scope are checked in
    the handlers; row level security repeats the clinic scope.
    """

    def __init__(
        self,
        *,
        commands: CommandBus,
        list_sites: ListSitesUseCase,
        staff_actor: Any,
    ) -> None:
        self._commands = commands
        self._list = list_sites
        self._staff_actor = staff_actor
        self.router = APIRouter(prefix=API_V1_PREFIX, tags=[ApiTag.CLINICS])
        self._add_routes()

    def _add_routes(self) -> None:
        add = self.router.add_api_route
        staff = Depends(self._staff_actor)
        manage = {ACCESS_EXTENSION: access(PermissionCode.SITES_MANAGE)}

        def create_site(
            body: CreateSiteRequest, actor: Annotated[Actor, staff]
        ) -> SiteResponse:
            return SiteResponse.of(
                self._commands.dispatch(CreateSiteCommand(actor=actor, name=body.name))
            )

        def list_sites(
            actor: Annotated[Actor, staff],
            limit: LimitQuery = FieldLimits.PAGE_SIZE_DEFAULT,
            cursor: CursorQuery = None,
        ) -> PageResponse[SiteResponse]:
            page = self._list.execute(
                ListSitesInput(actor=actor, page=page_request(limit, cursor))
            )
            return PageResponse(
                items=[SiteResponse.of(site) for site in page.items],
                next_cursor=page.next_cursor,
            )

        def update_site(
            site_id: UUID, body: UpdateSiteRequest, actor: Annotated[Actor, staff]
        ) -> SiteResponse:
            return SiteResponse.of(
                self._commands.dispatch(
                    UpdateSiteCommand(actor=actor, site_id=site_id, name=body.name)
                )
            )

        def set_user_sites(
            user_id: UUID,
            body: SetUserSitesRequest,
            actor: Annotated[Actor, staff],
        ) -> StaffSitesResponse:
            return StaffSitesResponse.of(
                self._commands.dispatch(
                    SetUserSitesCommand(
                        actor=actor,
                        user_id=user_id,
                        site_ids=frozenset(body.site_ids),
                    )
                )
            )

        add(
            "/sites",
            create_site,
            methods=["POST"],
            status_code=HTTPStatus.CREATED,
            operation_id="create_site",
            summary="Crear una sede",
            description=(
                "Agrega una sede a la clínica del administrador. El nombre no puede "
                "repetirse en la clínica, sin distinguir mayúsculas."
            ),
            responses=WRITE_ERRORS,
            openapi_extra=manage,
        )
        add(
            "/sites",
            list_sites,
            methods=["GET"],
            operation_id="list_sites",
            summary="Listar las sedes de la clínica",
            description=(
                "Devuelve las sedes de la clínica del administrador, por página."
            ),
            responses=error_responses(
                HTTPStatus.UNAUTHORIZED,
                HTTPStatus.FORBIDDEN,
                HTTPStatus.UNPROCESSABLE_ENTITY,
            ),
            openapi_extra=manage,
        )
        add(
            "/sites/{site_id}",
            update_site,
            methods=["PATCH"],
            operation_id="update_site",
            summary="Cambiar el nombre de una sede",
            description=(
                "Cambia el nombre de una sede de la clínica. Una sede de otra clínica "
                "responde `404`."
            ),
            responses=WRITE_ERRORS_WITH_TARGET,
            openapi_extra=manage,
        )
        add(
            "/users/{user_id}/sites",
            set_user_sites,
            methods=["PUT"],
            operation_id="set_user_sites",
            summary="Reemplazar las sedes de un integrante del personal",
            description=(
                "Reemplaza la lista completa de sedes donde trabaja el personal. Cada "
                "sede debe ser de la clínica; un personal u una sede de otra clínica "
                "responde `404`."
            ),
            responses=STAFF_SITES_ERRORS,
            openapi_extra=manage,
        )
