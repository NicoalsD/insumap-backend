"""Clinic endpoints (API.md 8.3): create, read, update, suspend and reactivate.

The first ``CLINIC_ADMIN`` of a clinic is created here too (``/admins``). The
access reset of a clinic administrator is still pending: its database function
does not return the e-mail of the holder, so the code cannot be sent.
"""

from collections.abc import Callable
from datetime import datetime
from http import HTTPStatus
from typing import Annotated, Final, Self, final
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field, field_validator

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
from insumap.application.clinic_admins.commands import (
    CreateClinicAdminCommand,
    CreatedClinicAdmin,
)
from insumap.application.clinics.commands import (
    CreateClinicCommand,
    ReactivateClinicCommand,
    SuspendClinicCommand,
    UpdateClinicCommand,
)
from insumap.application.clinics.queries import (
    GetClinicInput,
    GetClinicUseCase,
    GetCurrentClinicInput,
    GetCurrentClinicUseCase,
    ListClinicsInput,
    ListClinicsUseCase,
)
from insumap.application.commands.base import CommandBus
from insumap.application.common.actor import Actor
from insumap.domain.clinic.clinic import DEFAULT_TIMEZONE, Clinic, ClinicStatus
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role
from insumap.shared.field_limits import FieldLimits

CLINICS_PREFIX: Final = f"{API_V1_PREFIX}/clinics"
LOCATION_HEADER: Final = "Location"
USERS_LOCATION: Final = f"{API_V1_PREFIX}/users"
"""The created administrator is a staff member: ``Location`` points at ``/users``."""

CLINIC_ERRORS: Final = error_responses(
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
    HTTPStatus.NOT_FOUND,
    HTTPStatus.UNPROCESSABLE_ENTITY,
)
CLINIC_CHANGE_ERRORS: Final = error_responses(
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
    HTTPStatus.NOT_FOUND,
    HTTPStatus.CONFLICT,
    HTTPStatus.UNPROCESSABLE_ENTITY,
)
STATE_CHANGE_ERRORS: Final = error_responses(
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
    HTTPStatus.NOT_FOUND,
    HTTPStatus.CONFLICT,
    HTTPStatus.UNPROCESSABLE_ENTITY,
)


class CreateClinicRequest(StrictRequest):
    """A new clinic: it starts ``ACTIVE``."""

    name: str = Field(
        max_length=FieldLimits.CLINIC_NAME_MAX_LENGTH,
        description=(
            "Nombre de la clínica. No puede repetirse, sin distinguir mayúsculas."
        ),
    )
    tax_id: str = Field(
        max_length=FieldLimits.TAX_ID_MAX_LENGTH,
        description="Identificación fiscal de la clínica.",
    )
    is_demo: bool = Field(
        default=False,
        description="Marca la clínica de datos simulados.",
    )
    timezone: str = Field(
        default=DEFAULT_TIMEZONE,
        max_length=FieldLimits.TIMEZONE_MAX_LENGTH,
        description="Zona horaria IANA, por ejemplo `America/Bogota`.",
    )


class UpdateClinicRequest(StrictRequest):
    """Only the fields sent change; the others keep their value."""

    name: str | None = Field(
        default=None, max_length=FieldLimits.CLINIC_NAME_MAX_LENGTH
    )
    tax_id: str | None = Field(default=None, max_length=FieldLimits.TAX_ID_MAX_LENGTH)
    is_demo: bool | None = None
    timezone: str | None = Field(
        default=None, max_length=FieldLimits.TIMEZONE_MAX_LENGTH
    )


class CreateClinicAdminRequest(StrictRequest):
    """The first administrator of a clinic; its activation code goes by email only."""

    email: str = Field(
        max_length=FieldLimits.EMAIL_MAX_LENGTH,
        pattern=FieldLimits.EMAIL_PATTERN,
        description="Correo de la cuenta. Se normaliza (NFKC, recorte y minúsculas).",
    )
    full_name: str = Field(
        min_length=1,
        max_length=FieldLimits.STAFF_FULL_NAME_MAX_LENGTH,
        description="Nombre completo del administrador.",
    )

    @field_validator("full_name")
    @classmethod
    def name_is_not_blank(cls, value: str) -> str:
        """Trimmed, and never blank (a blank name is a ``422``)."""
        stripped = value.strip()
        if not stripped:
            raise ValueError("el nombre completo no puede estar vacío")
        return stripped


class SuspendClinicRequest(StrictRequest):
    """Why the clinic is blocked: 10 to 500 characters, kept in the audit."""

    reason: str | None = Field(
        default=None,
        description="Motivo de la suspensión, de 10 a 500 caracteres.",
    )


class ClinicResponse(BaseModel):
    """A clinic as the platform lists and creates it."""

    id: UUID
    name: str
    tax_id: str
    status: ClinicStatus
    is_demo: bool
    simulated: bool = Field(description="Igual que `is_demo`: datos simulados.")
    timezone: str
    created_at: datetime

    @classmethod
    def of(cls, clinic: Clinic) -> Self:
        return cls(
            id=clinic.clinic_id,
            name=clinic.name,
            tax_id=clinic.tax_id,
            status=clinic.status,
            is_demo=clinic.is_demo,
            simulated=clinic.is_demo,
            timezone=clinic.timezone,
            created_at=clinic.created_at,
        )


class ClinicDetailResponse(ClinicResponse):
    """A clinic with its suspension, when it has one."""

    suspended_at: datetime | None
    suspended_reason: str | None

    @classmethod
    def of(cls, clinic: Clinic) -> Self:
        return cls(
            id=clinic.clinic_id,
            name=clinic.name,
            tax_id=clinic.tax_id,
            status=clinic.status,
            is_demo=clinic.is_demo,
            simulated=clinic.is_demo,
            timezone=clinic.timezone,
            created_at=clinic.created_at,
            suspended_at=clinic.suspended_at,
            suspended_reason=clinic.suspended_reason,
        )


class CurrentClinicResponse(BaseModel):
    """The clinic of the caller, without its tax identifier."""

    id: UUID
    name: str
    status: ClinicStatus
    is_demo: bool
    simulated: bool = Field(description="Igual que `is_demo`: datos simulados.")
    timezone: str

    @classmethod
    def of(cls, clinic: Clinic) -> Self:
        return cls(
            id=clinic.clinic_id,
            name=clinic.name,
            status=clinic.status,
            is_demo=clinic.is_demo,
            simulated=clinic.is_demo,
            timezone=clinic.timezone,
        )


class CreatedClinicAdminResponse(BaseModel):
    """The new administrator; the activation code is never shown here."""

    user_id: UUID
    email: str
    role: Role
    invitation_expires_at: datetime

    @classmethod
    def of(cls, created: CreatedClinicAdmin) -> Self:
        return cls(
            user_id=created.user_id,
            email=created.email,
            role=created.role,
            invitation_expires_at=created.invitation_expires_at,
        )


@final
class ClinicRouter:
    """Builds ``/api/v1/clinics`` over the clinic commands (P13) and reads.

    Every change goes through the command bus, so it runs inside its transaction
    and leaves its audit row (P09). Permissions are checked in the use cases and
    row level security limits what a clinic sees.
    """

    def __init__(
        self,
        *,
        commands: CommandBus,
        list_clinics: ListClinicsUseCase,
        get_clinic: GetClinicUseCase,
        get_current_clinic: GetCurrentClinicUseCase,
        staff_actor: Callable[..., Actor],
    ) -> None:
        self._commands = commands
        self._list = list_clinics
        self._get = get_clinic
        self._get_current = get_current_clinic
        self._staff_actor = staff_actor
        self.router = APIRouter(prefix=CLINICS_PREFIX, tags=[ApiTag.CLINICS])
        self._add_routes()

    def _add_routes(self) -> None:
        add = self.router.add_api_route
        staff = Depends(self._staff_actor)

        def create_clinic(
            body: CreateClinicRequest, actor: Annotated[Actor, staff]
        ) -> ClinicResponse:
            return ClinicResponse.of(
                self._commands.dispatch(
                    CreateClinicCommand(
                        actor=actor,
                        name=body.name,
                        tax_id=body.tax_id,
                        timezone=body.timezone,
                        is_demo=body.is_demo,
                    )
                )
            )

        def list_clinics(
            actor: Annotated[Actor, staff],
            status: Annotated[ClinicStatus | None, Query()] = None,
            is_demo: Annotated[bool | None, Query()] = None,
            limit: LimitQuery = FieldLimits.PAGE_SIZE_DEFAULT,
            cursor: CursorQuery = None,
        ) -> PageResponse[ClinicResponse]:
            page = self._list.execute(
                ListClinicsInput(
                    actor=actor,
                    status=status,
                    is_demo=is_demo,
                    page=page_request(limit, cursor),
                )
            )
            return PageResponse(
                items=[ClinicResponse.of(clinic) for clinic in page.items],
                next_cursor=page.next_cursor,
            )

        def get_current_clinic(actor: Annotated[Actor, staff]) -> CurrentClinicResponse:
            return CurrentClinicResponse.of(
                self._get_current.execute(GetCurrentClinicInput(actor=actor))
            )

        def get_clinic(
            clinic_id: UUID, actor: Annotated[Actor, staff]
        ) -> ClinicDetailResponse:
            return ClinicDetailResponse.of(
                self._get.execute(GetClinicInput(actor=actor, clinic_id=clinic_id))
            )

        def update_clinic(
            clinic_id: UUID, body: UpdateClinicRequest, actor: Annotated[Actor, staff]
        ) -> ClinicDetailResponse:
            return ClinicDetailResponse.of(
                self._commands.dispatch(
                    UpdateClinicCommand(
                        actor=actor,
                        clinic_id=clinic_id,
                        name=body.name,
                        tax_id=body.tax_id,
                        timezone=body.timezone,
                        is_demo=body.is_demo,
                    )
                )
            )

        def suspend_clinic(
            clinic_id: UUID, body: SuspendClinicRequest, actor: Annotated[Actor, staff]
        ) -> ClinicDetailResponse:
            return ClinicDetailResponse.of(
                self._commands.dispatch(
                    SuspendClinicCommand(
                        actor=actor, clinic_id=clinic_id, reason=body.reason
                    )
                )
            )

        def reactivate_clinic(
            clinic_id: UUID, actor: Annotated[Actor, staff]
        ) -> ClinicDetailResponse:
            return ClinicDetailResponse.of(
                self._commands.dispatch(
                    ReactivateClinicCommand(actor=actor, clinic_id=clinic_id)
                )
            )

        def create_clinic_admin(
            clinic_id: UUID,
            body: CreateClinicAdminRequest,
            actor: Annotated[Actor, staff],
            response: Response,
        ) -> CreatedClinicAdminResponse:
            created = self._commands.dispatch(
                CreateClinicAdminCommand(
                    actor=actor,
                    clinic_id=clinic_id,
                    email=body.email,
                    full_name=body.full_name,
                )
            )
            response.headers[LOCATION_HEADER] = f"{USERS_LOCATION}/{created.user_id}"
            return CreatedClinicAdminResponse.of(created)

        manage = {ACCESS_EXTENSION: access(PermissionCode.CLINICS_MANAGE)}
        manage_admins = {ACCESS_EXTENSION: access(PermissionCode.CLINIC_ADMINS_MANAGE)}
        read_own = {ACCESS_EXTENSION: access(PermissionCode.CLINICS_READ)}
        add(
            "",
            create_clinic,
            methods=["POST"],
            status_code=HTTPStatus.CREATED,
            operation_id="create_clinic",
            summary="Crear una clínica",
            description=(
                "Registra una clínica nueva, activa y aislada como tenant. Solo el "
                "administrador de la plataforma. Un nombre repetido responde `409`."
            ),
            responses=CLINIC_CHANGE_ERRORS,
            openapi_extra=manage,
        )
        add(
            "",
            list_clinics,
            methods=["GET"],
            operation_id="list_clinics",
            summary="Listar las clínicas",
            description=(
                "Lista las clínicas con su estado. Filtra por `status` y `is_demo`. "
                "Nunca muestra datos de pacientes."
            ),
            responses=CLINIC_ERRORS,
            openapi_extra=manage,
        )
        # Declared before `/{clinic_id}` so that "current" is not read as an id.
        add(
            "/current",
            get_current_clinic,
            methods=["GET"],
            operation_id="get_current_clinic",
            summary="Ver la clínica propia",
            description=(
                "Devuelve la clínica del token de quien consulta, para cualquier "
                "miembro del personal de esa clínica. No recibe identificador."
            ),
            responses=error_responses(HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN),
            openapi_extra=read_own,
        )
        add(
            "/{clinic_id}",
            get_clinic,
            methods=["GET"],
            operation_id="get_clinic",
            summary="Ver una clínica",
            description=(
                "Devuelve los datos de la clínica, con la fecha y el motivo de su "
                "suspensión si la tiene. Una clínica inexistente responde `404`."
            ),
            responses=CLINIC_ERRORS,
            openapi_extra=manage,
        )
        add(
            "/{clinic_id}",
            update_clinic,
            methods=["PATCH"],
            operation_id="update_clinic",
            summary="Editar una clínica",
            description=(
                "Cambia el nombre, la identificación fiscal, la zona horaria o la "
                "marca de demo. Solo cambian los campos enviados."
            ),
            responses=CLINIC_CHANGE_ERRORS,
            openapi_extra=manage,
        )
        add(
            "/{clinic_id}/suspend",
            suspend_clinic,
            methods=["POST"],
            operation_id="suspend_clinic",
            summary="Suspender una clínica",
            description=(
                "Bloquea la clínica: su personal y sus pacientes no pueden iniciar "
                "sesión y sus sesiones abiertas se revocan. Exige un motivo de 10 a "
                "500 caracteres. Una clínica ya suspendida responde `409`."
            ),
            responses=STATE_CHANGE_ERRORS,
            openapi_extra=manage,
        )
        add(
            "/{clinic_id}/reactivate",
            reactivate_clinic,
            methods=["POST"],
            operation_id="reactivate_clinic",
            summary="Reactivar una clínica",
            description=(
                "Levanta la suspensión y restablece el acceso de su personal y sus "
                "pacientes. Una clínica activa responde `409`."
            ),
            responses=STATE_CHANGE_ERRORS,
            openapi_extra=manage,
        )
        add(
            "/{clinic_id}/admins",
            create_clinic_admin,
            methods=["POST"],
            status_code=HTTPStatus.CREATED,
            operation_id="create_clinic_admin",
            summary="Crear el primer administrador de una clínica",
            description=(
                "Crea el primer `CLINIC_ADMIN` de la clínica. Solo el administrador "
                "de la plataforma. La cuenta nace `INVITED` y su código de activación "
                "de un solo uso viaja solo por correo: la respuesta no lo muestra. El "
                "administrador debe activar la cuenta y enrolar MFA en su primer "
                "ingreso. Un correo ya registrado responde `409`, igual que una "
                "clínica suspendida."
            ),
            responses=CLINIC_CHANGE_ERRORS,
            openapi_extra=manage_admins,
        )
