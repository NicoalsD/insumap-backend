"""Staff endpoints (API.md 8.3, ``/api/v1/users``): create, read, update and close.

The router maps HTTP to commands and queries and back. Scope and permissions
are checked in the use cases; the clinic always comes from the token.
"""

from datetime import datetime
from enum import StrEnum
from http import HTTPStatus
from typing import Annotated, Any, Final, Self, final
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field, field_validator, model_validator

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
from insumap.application.users.commands import (
    CreatedStaff,
    CreateStaffUserCommand,
    DeactivatedStaff,
    DeactivateStaffUserCommand,
    ResetStaffMfaCommand,
    UnlockStaffUserCommand,
    UpdateStaffUserCommand,
)
from insumap.application.users.ports import StaffFilter, StaffMember
from insumap.application.users.queries import (
    GetStaffInput,
    GetStaffUseCase,
    ListStaffInput,
    ListStaffUseCase,
)
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role
from insumap.shared.field_limits import FieldLimits

USERS_PREFIX: Final = f"{API_V1_PREFIX}/users"
LOCATION_HEADER: Final = "Location"
PROFILE_FIELDS: Final = ("full_name", "professional_license", "specialty")

REASON_FIELD: Final = Field(
    min_length=FieldLimits.REASON_MIN_LENGTH,
    max_length=FieldLimits.REASON_MAX_LENGTH,
    description="Motivo de la decisión (queda en la auditoría).",
)


class StaffRoleCode(StrEnum):
    """Roles a staff account can hold; patients and platform admins are not staff."""

    DOCTOR = "DOCTOR"
    CLINIC_ADMIN = "CLINIC_ADMIN"


def _not_blank(value: str | None) -> str | None:
    """Trim a text field; a blank one is a validation error (``422``)."""
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        raise ValueError("el campo no puede estar vacío")
    return stripped


class CreateUserRequest(StrictRequest):
    """A staff member of the caller's clinic; the invitation goes by email."""

    email: str = Field(
        max_length=FieldLimits.EMAIL_MAX_LENGTH,
        pattern=FieldLimits.EMAIL_PATTERN,
        description="Correo de la cuenta. Se normaliza (NFKC, recorte y minúsculas).",
    )
    full_name: str = Field(
        min_length=1,
        max_length=FieldLimits.STAFF_FULL_NAME_MAX_LENGTH,
        description="Nombre completo del personal.",
    )
    role: StaffRoleCode = Field(description="`DOCTOR` o `CLINIC_ADMIN`.")
    professional_license: str | None = Field(
        default=None,
        max_length=FieldLimits.PROFESSIONAL_LICENSE_MAX_LENGTH,
        description="Registro profesional. Obligatorio para `DOCTOR`.",
    )
    specialty: str | None = Field(
        default=None,
        max_length=FieldLimits.SPECIALTY_MAX_LENGTH,
        description="Especialidad médica.",
    )

    @field_validator("full_name", "professional_license", "specialty")
    @classmethod
    def clean_text(cls, value: str | None) -> str | None:
        """Trimmed, and never blank."""
        return _not_blank(value)


class UpdateUserRequest(StrictRequest):
    """Profile fields to change; the fields left out stay as they are."""

    full_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=FieldLimits.STAFF_FULL_NAME_MAX_LENGTH,
        description="Nombre completo. No admite `null`.",
    )
    professional_license: str | None = Field(
        default=None,
        max_length=FieldLimits.PROFESSIONAL_LICENSE_MAX_LENGTH,
        description="Registro profesional. Un médico debe conservarlo.",
    )
    specialty: str | None = Field(
        default=None,
        max_length=FieldLimits.SPECIALTY_MAX_LENGTH,
        description="Especialidad médica; `null` la quita.",
    )

    @field_validator(*PROFILE_FIELDS)
    @classmethod
    def clean_text(cls, value: str | None) -> str | None:
        """Trimmed, and never blank (a blank value is a ``422``)."""
        return _not_blank(value)

    @model_validator(mode="after")
    def name_is_never_null(self) -> Self:
        """The name is required: sending it as ``null`` is refused."""
        if "full_name" in self.model_fields_set and self.full_name is None:
            raise ValueError("el nombre completo no admite null")
        return self


class DeactivateUserRequest(StrictRequest):
    """Why the account is closed."""

    reason: str = REASON_FIELD


class ResetMfaRequest(StrictRequest):
    """Why the second factor is reset."""

    reason: str = REASON_FIELD


class StaffSummaryResponse(BaseModel):
    """A staff member in a listing."""

    id: UUID
    email: str | None
    full_name: str
    role: StaffRoleCode
    is_active: bool
    specialty: str | None

    @classmethod
    def of(cls, member: StaffMember) -> Self:
        return cls(
            id=member.user_id,
            email=member.email,
            full_name=member.full_name,
            role=StaffRoleCode(member.role.value),
            is_active=member.is_active,
            specialty=member.specialty,
        )


class StaffResponse(StaffSummaryResponse):
    """A staff member with its professional profile and MFA state."""

    professional_license: str | None
    mfa_enabled: bool

    @classmethod
    def of(cls, member: StaffMember) -> Self:
        return cls(
            id=member.user_id,
            email=member.email,
            full_name=member.full_name,
            role=StaffRoleCode(member.role.value),
            is_active=member.is_active,
            specialty=member.specialty,
            professional_license=member.professional_license,
            mfa_enabled=member.mfa_enabled,
        )


class CreatedStaffResponse(BaseModel):
    """The new account; the activation code is never shown here."""

    id: UUID
    email: str
    role: StaffRoleCode
    is_active: bool
    invitation_expires_at: datetime

    @classmethod
    def of(cls, created: CreatedStaff) -> Self:
        return cls(
            id=created.user_id,
            email=created.email,
            role=StaffRoleCode(created.role.value),
            is_active=False,
            invitation_expires_at=created.invitation_expires_at,
        )


class DeactivatedStaffResponse(StaffResponse):
    """The closed account and how many patients need a new doctor."""

    patients_pending_reassignment: int

    @classmethod
    def of_result(cls, closed: DeactivatedStaff) -> Self:
        base = StaffResponse.of(closed.member)
        return cls(
            patients_pending_reassignment=closed.patients_pending_reassignment,
            **dict(base),
        )


CREATE_ERRORS: Final = error_responses(
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
    HTTPStatus.CONFLICT,
    HTTPStatus.UNPROCESSABLE_ENTITY,
)
ID_ERRORS: Final = error_responses(
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
    HTTPStatus.NOT_FOUND,
    HTTPStatus.UNPROCESSABLE_ENTITY,
)
WRITE_ERRORS: Final = error_responses(
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
    HTTPStatus.NOT_FOUND,
    HTTPStatus.CONFLICT,
    HTTPStatus.UNPROCESSABLE_ENTITY,
)


@final
class UserRouter:
    """Builds ``/api/v1/users`` over the staff queries and commands (P13).

    Every write goes through the command bus, so it runs inside its transaction
    and leaves its audit row (P09). A user of another clinic, or a patient, is
    ``404`` with the same body as a missing one.
    """

    def __init__(
        self,
        *,
        commands: CommandBus,
        list_staff: ListStaffUseCase,
        get_staff: GetStaffUseCase,
        staff_actor: Any,
    ) -> None:
        self._commands = commands
        self._list = list_staff
        self._get = get_staff
        self._staff_actor = staff_actor
        self.router = APIRouter(prefix=USERS_PREFIX, tags=[ApiTag.USERS])
        self._add_routes()

    def _add_routes(self) -> None:
        add = self.router.add_api_route
        staff = Depends(self._staff_actor)

        def list_users(
            actor: Annotated[Actor, staff],
            role: Annotated[StaffRoleCode | None, Query()] = None,
            is_active: Annotated[bool | None, Query()] = None,
            limit: LimitQuery = FieldLimits.PAGE_SIZE_DEFAULT,
            cursor: CursorQuery = None,
        ) -> PageResponse[StaffSummaryResponse]:
            page = self._list.execute(
                ListStaffInput(
                    actor=actor,
                    filters=StaffFilter(
                        role=None if role is None else Role(role.value),
                        is_active=is_active,
                    ),
                    page=page_request(limit, cursor),
                )
            )
            return PageResponse(
                items=[StaffSummaryResponse.of(m) for m in page.items],
                next_cursor=page.next_cursor,
            )

        def create_user(
            body: CreateUserRequest, actor: Annotated[Actor, staff], response: Response
        ) -> CreatedStaffResponse:
            created = self._commands.dispatch(
                CreateStaffUserCommand(
                    actor=actor,
                    email=body.email,
                    full_name=body.full_name,
                    role=Role(body.role.value),
                    professional_license=body.professional_license,
                    specialty=body.specialty,
                )
            )
            response.headers[LOCATION_HEADER] = f"{USERS_PREFIX}/{created.user_id}"
            return CreatedStaffResponse.of(created)

        def get_user(user_id: UUID, actor: Annotated[Actor, staff]) -> StaffResponse:
            return StaffResponse.of(
                self._get.execute(GetStaffInput(actor=actor, user_id=user_id))
            )

        def update_user(
            user_id: UUID, body: UpdateUserRequest, actor: Annotated[Actor, staff]
        ) -> StaffResponse:
            return StaffResponse.of(
                self._commands.dispatch(
                    UpdateStaffUserCommand(
                        actor=actor,
                        user_id=user_id,
                        full_name=body.full_name,
                        professional_license=body.professional_license,
                        specialty=body.specialty,
                        provided=frozenset(body.model_fields_set),
                    )
                )
            )

        def deactivate_user(
            user_id: UUID, body: DeactivateUserRequest, actor: Annotated[Actor, staff]
        ) -> DeactivatedStaffResponse:
            return DeactivatedStaffResponse.of_result(
                self._commands.dispatch(
                    DeactivateStaffUserCommand(
                        actor=actor, user_id=user_id, reason=body.reason
                    )
                )
            )

        def unlock_user(user_id: UUID, actor: Annotated[Actor, staff]) -> None:
            self._commands.dispatch(
                UnlockStaffUserCommand(actor=actor, user_id=user_id)
            )

        def reset_user_mfa(
            user_id: UUID, body: ResetMfaRequest, actor: Annotated[Actor, staff]
        ) -> None:
            self._commands.dispatch(
                ResetStaffMfaCommand(actor=actor, user_id=user_id, reason=body.reason)
            )

        read = {ACCESS_EXTENSION: access(PermissionCode.USERS_READ)}
        write = {ACCESS_EXTENSION: access(PermissionCode.USERS_MANAGE)}
        add(
            "",
            list_users,
            methods=["GET"],
            operation_id="list_users",
            summary="Listar el personal de la clínica",
            description=(
                "Devuelve el personal de la clínica del token (médicos y "
                "administradores), con filtros por rol y estado. Nunca datos "
                "clínicos."
            ),
            responses=error_responses(
                HTTPStatus.UNAUTHORIZED,
                HTTPStatus.FORBIDDEN,
                HTTPStatus.UNPROCESSABLE_ENTITY,
            ),
            openapi_extra=read,
        )
        add(
            "",
            create_user,
            methods=["POST"],
            status_code=HTTPStatus.CREATED,
            operation_id="create_user",
            summary="Dar de alta a un médico o un administrador",
            description=(
                "Crea la cuenta en la clínica del token, inactiva hasta la activación. "
                "Envía por correo un código de activación de un solo uso (7 días), "
                "que no se devuelve en la respuesta. El personal debe activar MFA en "
                "su primer ingreso."
            ),
            responses=CREATE_ERRORS,
            openapi_extra=write,
        )
        add(
            "/{user_id}",
            get_user,
            methods=["GET"],
            operation_id="get_user",
            summary="Consultar un miembro del personal",
            description=(
                "Devuelve el perfil profesional y si el segundo factor está activo. "
                "Un usuario de otra clínica o un paciente responde `404`."
            ),
            responses=ID_ERRORS,
            openapi_extra=read,
        )
        add(
            "/{user_id}",
            update_user,
            methods=["PATCH"],
            operation_id="update_user",
            summary="Actualizar el perfil profesional",
            description=(
                "Cambia el nombre, el registro profesional o la especialidad. Los "
                "campos que no se envían no cambian. Un médico conserva su registro "
                "profesional."
            ),
            responses=WRITE_ERRORS,
            openapi_extra=write,
        )
        add(
            "/{user_id}/deactivate",
            deactivate_user,
            methods=["POST"],
            operation_id="deactivate_user",
            summary="Desactivar a un miembro del personal",
            description=(
                "Cierra la cuenta de forma definitiva con su motivo, revoca todas sus "
                "sesiones y termina su membresía. Sus asignaciones de pacientes siguen "
                "abiertas y se cuentan en `patients_pending_reassignment`. Nadie se "
                "desactiva a sí mismo."
            ),
            responses=WRITE_ERRORS,
            openapi_extra=write,
        )
        add(
            "/{user_id}/unlock",
            unlock_user,
            methods=["POST"],
            status_code=HTTPStatus.NO_CONTENT,
            operation_id="unlock_user",
            summary="Quitar el bloqueo de inicio de sesión",
            description=(
                "Quita el bloqueo global del correo de la cuenta (por fallos desde "
                "varias IP). Queda en la auditoría."
            ),
            responses=ID_ERRORS,
            openapi_extra=write,
        )
        add(
            "/{user_id}/mfa-reset",
            reset_user_mfa,
            methods=["POST"],
            status_code=HTTPStatus.NO_CONTENT,
            operation_id="reset_user_mfa",
            summary="Restablecer el segundo factor del personal",
            description=(
                "Elimina el TOTP y los códigos de respaldo, revoca las sesiones y "
                "avisa al titular. En su siguiente ingreso debe enrolar MFA de nuevo. "
                "Nadie restablece su propio MFA."
            ),
            responses=WRITE_ERRORS,
            openapi_extra=write,
        )
