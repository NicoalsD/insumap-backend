"""Patient endpoints (API.md 8.4 and the own profile of 8.6).

The administrator reads the roster and changes the account status of the
patients of its clinic. The patient reads its own profile, which is never
addressed by an id in the path (V3).
"""

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
from insumap.application.commands.base import CommandBus
from insumap.application.common.actor import Actor
from insumap.application.monitoring.profile import (
    GetOwnPatientProfileUseCase,
    OwnPatientProfile,
)
from insumap.application.patients.commands import (
    DeactivatePatientCommand,
    ReactivatePatientCommand,
    SuspendPatientCommand,
)
from insumap.application.patients.ports import (
    PatientAdministrativeView,
    PatientRosterFilter,
)
from insumap.application.patients.queries import (
    GetPatientInput,
    GetPatientUseCase,
    ListPatientsInput,
    ListPatientsUseCase,
)
from insumap.domain.identity.account_state import AccountStatus
from insumap.domain.identity.invitation import InvitationStatus
from insumap.domain.identity.permissions import PermissionCode
from insumap.shared.field_limits import FieldLimits

PATIENTS_PREFIX: Final = f"{API_V1_PREFIX}/patients"

REASON_FIELD: Final = Field(
    min_length=FieldLimits.REASON_MIN_LENGTH,
    max_length=FieldLimits.REASON_MAX_LENGTH,
    description="Motivo de la decisión (queda en la auditoría).",
)


class PatientStatusRequest(StrictRequest):
    """Why the account changes status (suspension and deactivation)."""

    reason: str = REASON_FIELD


class ReactivatePatientRequest(StrictRequest):
    """Optional note for the reactivation; it is kept in the audit log."""

    reason: str | None = Field(
        default=None,
        min_length=FieldLimits.REASON_MIN_LENGTH,
        max_length=FieldLimits.REASON_MAX_LENGTH,
        description="Motivo opcional (queda en la auditoría).",
    )


class PatientAdministrativeResponse(BaseModel):
    """A patient as the clinic administrator sees it: no clinical data."""

    id: UUID
    full_name: str
    mrn: str
    document_last4: str = Field(description="Últimos cuatro caracteres del documento.")
    account_status: AccountStatus
    primary_doctor_id: UUID | None
    assigned_doctor_count: int
    invitation_status: InvitationStatus | None = Field(
        description="Estado de la invitación más reciente, si la hay."
    )
    simulated: bool

    @classmethod
    def of(cls, view: PatientAdministrativeView) -> Self:
        return cls(
            id=view.patient_id,
            full_name=view.full_name,
            mrn=view.mrn,
            document_last4=view.document_last4,
            account_status=view.account_status,
            primary_doctor_id=view.primary_doctor_id,
            assigned_doctor_count=view.assigned_doctor_count,
            invitation_status=view.invitation_status,
            simulated=view.simulated,
        )


class OwnClinicResponse(BaseModel):
    """The clinic the patient belongs to, for the app's header."""

    name: str
    simulated: bool


class TargetProfileReference(BaseModel):
    """The glycemic target profile in force, with the version that applies."""

    id: UUID
    code: str
    version: int


class OwnPatientProfileResponse(BaseModel):
    """The patient's own profile: who it is for the app, without clinical data."""

    id: UUID
    account_status: AccountStatus
    clinic: OwnClinicResponse
    target_profile: TargetProfileReference | None
    simulated: bool

    @classmethod
    def of(cls, profile: OwnPatientProfile) -> Self:
        target = profile.target_profile
        return cls(
            id=profile.patient_id,
            account_status=profile.account_status,
            clinic=OwnClinicResponse(
                name=profile.clinic_name, simulated=profile.simulated
            ),
            target_profile=None
            if target is None
            else TargetProfileReference(
                id=target.id, code=target.code, version=target.version
            ),
            simulated=profile.simulated,
        )


type AccountStatusQuery = Annotated[
    AccountStatus | None,
    Query(description="Filtra por estado de la cuenta."),
]
type WithoutDoctorQuery = Annotated[
    bool,
    Query(description="Solo pacientes sin médico vigente."),
]
type ImportBatchQuery = Annotated[
    UUID | None,
    Query(description="Solo los pacientes creados por ese lote de importación."),
]

ROSTER_ERRORS: Final = error_responses(
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
    HTTPStatus.UNPROCESSABLE_ENTITY,
)
PATIENT_ERRORS: Final = error_responses(
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
    HTTPStatus.NOT_FOUND,
    HTTPStatus.UNPROCESSABLE_ENTITY,
)
STATUS_ERRORS: Final = error_responses(
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
    HTTPStatus.NOT_FOUND,
    HTTPStatus.CONFLICT,
    HTTPStatus.UNPROCESSABLE_ENTITY,
)
OWN_ERRORS: Final = error_responses(
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
)


@final
class PatientRouter:
    """Builds ``/api/v1/patients`` over the read use cases and the status commands.

    Status changes go through the command bus, so each one runs in its transaction
    and leaves its audit row (P09). Permissions and the clinic scope are checked in
    the use cases; row level security repeats the clinic scope.
    """

    def __init__(
        self,
        *,
        commands: CommandBus,
        list_patients: ListPatientsUseCase,
        get_patient: GetPatientUseCase,
        own_profile: GetOwnPatientProfileUseCase,
        session_actor: Any,
    ) -> None:
        self._commands = commands
        self._list = list_patients
        self._get = get_patient
        self._own = own_profile
        self._session_actor = session_actor
        self.router = APIRouter(prefix=PATIENTS_PREFIX, tags=[ApiTag.PATIENTS])
        self._add_routes()

    def _add_routes(self) -> None:
        add = self.router.add_api_route
        session = Depends(self._session_actor)

        def list_patients(
            actor: Annotated[Actor, session],
            account_status: AccountStatusQuery = None,
            without_doctor: WithoutDoctorQuery = False,
            import_batch_id: ImportBatchQuery = None,
            limit: LimitQuery = FieldLimits.PAGE_SIZE_DEFAULT,
            cursor: CursorQuery = None,
        ) -> PageResponse[PatientAdministrativeResponse]:
            page = self._list.execute(
                ListPatientsInput(
                    actor=actor,
                    filters=PatientRosterFilter(
                        account_status=account_status,
                        without_doctor=without_doctor,
                        import_batch_id=import_batch_id,
                    ),
                    page=page_request(limit, cursor),
                )
            )
            return PageResponse(
                items=[PatientAdministrativeResponse.of(v) for v in page.items],
                next_cursor=page.next_cursor,
            )

        def get_own_patient_profile(
            actor: Annotated[Actor, session],
        ) -> OwnPatientProfileResponse:
            return OwnPatientProfileResponse.of(self._own.execute(actor))

        def get_patient_administrative_view(
            patient_id: UUID, actor: Annotated[Actor, session]
        ) -> PatientAdministrativeResponse:
            return PatientAdministrativeResponse.of(
                self._get.execute(GetPatientInput(actor=actor, patient_id=patient_id))
            )

        def suspend_patient(
            patient_id: UUID,
            body: PatientStatusRequest,
            actor: Annotated[Actor, session],
        ) -> PatientAdministrativeResponse:
            return PatientAdministrativeResponse.of(
                self._commands.dispatch(
                    SuspendPatientCommand(
                        actor=actor, patient_id=patient_id, reason=body.reason
                    )
                )
            )

        def reactivate_patient(
            patient_id: UUID,
            actor: Annotated[Actor, session],
            body: ReactivatePatientRequest | None = None,
        ) -> PatientAdministrativeResponse:
            return PatientAdministrativeResponse.of(
                self._commands.dispatch(
                    ReactivatePatientCommand(
                        actor=actor,
                        patient_id=patient_id,
                        reason=None if body is None else body.reason,
                    )
                )
            )

        def deactivate_patient(
            patient_id: UUID,
            body: PatientStatusRequest,
            actor: Annotated[Actor, session],
        ) -> PatientAdministrativeResponse:
            return PatientAdministrativeResponse.of(
                self._commands.dispatch(
                    DeactivatePatientCommand(
                        actor=actor, patient_id=patient_id, reason=body.reason
                    )
                )
            )

        read_roster = {ACCESS_EXTENSION: access(PermissionCode.PATIENTS_READ_ROSTER)}
        manage_status = {
            ACCESS_EXTENSION: access(PermissionCode.PATIENTS_MANAGE_STATUS)
        }
        read_own = {ACCESS_EXTENSION: access(PermissionCode.PATIENTS_READ_OWN)}
        # Declared before "/{patient_id}" so that "own" is never read as an id.
        add(
            "",
            list_patients,
            methods=["GET"],
            operation_id="list_patients",
            summary="Listar los pacientes de la clínica",
            description=(
                "Vista administrativa del personal de la clínica: identificación, "
                "MRN, últimos dígitos del documento, estado de la cuenta, médico "
                "principal y estado de la invitación. Nunca incluye datos clínicos "
                "ni el documento completo. Cada consulta queda en la auditoría de "
                "lecturas."
            ),
            responses=ROSTER_ERRORS,
            openapi_extra=read_roster,
        )
        add(
            "/own",
            get_own_patient_profile,
            methods=["GET"],
            operation_id="get_own_patient_profile",
            summary="Consultar el propio perfil de paciente",
            description=(
                "Identidad del paciente para la aplicación: estado de la cuenta, "
                "clínica (con su marca de datos simulados) y perfil de metas vigente. "
                "No incluye datos clínicos. Exige el consentimiento vigente."
            ),
            responses=OWN_ERRORS,
            openapi_extra=read_own,
        )
        add(
            "/{patient_id}",
            get_patient_administrative_view,
            methods=["GET"],
            operation_id="get_patient_administrative_view",
            summary="Consultar un paciente de la clínica",
            description=(
                "Vista administrativa de un paciente de la clínica. Un paciente de "
                "otra clínica o inexistente responde `404`. El médico no usa esta "
                "ruta: su detalle clínico está en el expediente."
            ),
            responses=PATIENT_ERRORS,
            openapi_extra=read_roster,
        )
        add(
            "/{patient_id}/suspend",
            suspend_patient,
            methods=["POST"],
            operation_id="suspend_patient",
            summary="Suspender la cuenta de un paciente",
            description=(
                "Pasa la cuenta de `ACTIVE` a `SUSPENDED` con motivo obligatorio y "
                "cierra sus sesiones abiertas. Cualquier otro estado responde `409`."
            ),
            responses=STATUS_ERRORS,
            openapi_extra=manage_status,
        )
        add(
            "/{patient_id}/reactivate",
            reactivate_patient,
            methods=["POST"],
            operation_id="reactivate_patient",
            summary="Reactivar la cuenta de un paciente",
            description=(
                "Pasa la cuenta de `SUSPENDED` a `ACTIVE`. El motivo es opcional. "
                "Una cuenta desactivada es terminal y responde `409`."
            ),
            responses=STATUS_ERRORS,
            openapi_extra=manage_status,
        )
        add(
            "/{patient_id}/deactivate",
            deactivate_patient,
            methods=["POST"],
            operation_id="deactivate_patient",
            summary="Dar de baja la cuenta de un paciente",
            description=(
                "Cierra la cuenta para siempre con motivo obligatorio desde "
                "`IMPORTED`, `INVITED`, `ACTIVE` o `SUSPENDED`. Cierra sus sesiones y "
                "revoca la invitación pendiente. Es terminal."
            ),
            responses=STATUS_ERRORS,
            openapi_extra=manage_status,
        )
