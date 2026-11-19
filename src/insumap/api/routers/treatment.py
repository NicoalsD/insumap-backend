"""Treatment plan and protocol template endpoints (API.md 8.7).

Decisions go through the command bus (P13, behind P09 and the transaction);
reads go through their use case. Plan content is never read from the request
without ``extra="forbid"`` and the limits of ``FieldLimits``.
"""

from datetime import datetime, time
from decimal import Decimal
from enum import StrEnum
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
from insumap.application.treatment.inputs import PlanContentInput
from insumap.application.treatment.plan_commands import (
    ActivateTreatmentPlanCommand,
    CreateTreatmentPlanCommand,
    CreateTreatmentPlanVersionCommand,
    RestoreTreatmentPlanCommand,
    UpdateTreatmentPlanCommand,
)
from insumap.application.treatment.ports import StoredSnapshot
from insumap.application.treatment.queries import (
    GetOwnTreatmentPlanUseCase,
    GetProtocolTemplateUseCase,
    GetTreatmentPlanUseCase,
    ListProtocolTemplatesUseCase,
    ListTreatmentPlanSnapshotsUseCase,
    ListTreatmentPlansUseCase,
)
from insumap.application.treatment.template_commands import (
    CreateProtocolTemplateCommand,
    CreateProtocolTemplateVersionCommand,
    RetireProtocolTemplateCommand,
)
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.treatment.content import (
    InsulinKind,
    ItemSpec,
    ItemType,
    PlanItem,
    ProtocolLimits,
    TemplateContent,
    TitrationRules,
)
from insumap.domain.treatment.plan import PlanStatus, TreatmentPlan
from insumap.domain.treatment.template import ProtocolTemplate, TemplateStatus
from insumap.shared.field_limits import FieldLimits

TREATMENT_PREFIX: Final = API_V1_PREFIX
MAX_WEEKDAY: Final = 7
MIN_WEEKDAY: Final = 1
MAX_DOSE_DIGITS: Final = 6
MAX_DOSE_DECIMALS: Final = 2
MAX_STEP_UNITS: Final = FieldLimits.INSULIN_UNITS_INPUT_MAX

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
ID_FIELD: Final = Field(description="Identificador del recurso.")


class TemplateStatusFilter(StrEnum):
    """Filter of the template listing."""

    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class PlanStatusFilter(StrEnum):
    """Filter of the plan listing."""

    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class ItemRequest(StrictRequest):
    """One insulin, medication or measurement of a plan."""

    item_type: ItemType
    name: str = Field(
        min_length=1,
        max_length=FieldLimits.PLAN_ITEM_NAME_MAX_LENGTH,
        description="Producto, medicamento o medición.",
    )
    insulin_kind: InsulinKind | None = Field(
        default=None, description="Obligatorio solo en insulinas."
    )
    dose_units: Decimal | None = Field(
        default=None,
        gt=0,
        le=MAX_STEP_UNITS,
        max_digits=MAX_DOSE_DIGITS,
        decimal_places=MAX_DOSE_DECIMALS,
        description="Dosis en unidades. Los límites clínicos los fija el protocolo.",
    )
    time_of_day: time | None = Field(default=None, description="Hora local.")
    days_of_week: list[Annotated[int, Field(ge=MIN_WEEKDAY, le=MAX_WEEKDAY)]] | None = (
        Field(default=None, description="1 lunes a 7 domingo; nulo es todos los días.")
    )
    instructions: str | None = Field(
        default=None, max_length=FieldLimits.INSTRUCTIONS_MAX_LENGTH
    )

    def to_spec(self) -> ItemSpec:
        return ItemSpec(
            item_type=self.item_type,
            name=self.name,
            insulin_kind=self.insulin_kind,
            dose_units=self.dose_units,
            time_of_day=self.time_of_day,
            days_of_week=None
            if self.days_of_week is None
            else tuple(self.days_of_week),
            instructions=self.instructions,
        )


class TitrationRulesRequest(StrictRequest):
    """How a dose may be adjusted; the values come from the protocol."""

    step_units: Decimal = Field(gt=0, le=MAX_STEP_UNITS, max_digits=MAX_DOSE_DIGITS)
    max_change_units: Decimal = Field(
        gt=0, le=MAX_STEP_UNITS, max_digits=MAX_DOSE_DIGITS
    )
    min_days_between_adjustments: int = Field(ge=0)

    def to_rules(self) -> TitrationRules:
        return TitrationRules(
            step_units=self.step_units,
            max_change_units=self.max_change_units,
            min_days_between_adjustments=self.min_days_between_adjustments,
        )


class ProtocolLimitsRequest(StrictRequest):
    """Ceilings a plan built from the template must respect."""

    max_dose_units: Decimal | None = Field(
        default=None, gt=0, le=MAX_STEP_UNITS, max_digits=MAX_DOSE_DIGITS
    )
    min_gap_minutes: int | None = Field(default=None, ge=0)

    def to_limits(self) -> ProtocolLimits:
        return ProtocolLimits(
            max_dose_units=self.max_dose_units, min_gap_minutes=self.min_gap_minutes
        )


class TemplateContentRequest(StrictRequest):
    """The structure of a protocol template."""

    items: list[ItemRequest] = Field(max_length=FieldLimits.PLAN_ITEMS_MAX_ITEMS)
    titration_rules: TitrationRulesRequest | None = None
    limits: ProtocolLimitsRequest | None = None

    def to_content(self) -> TemplateContent:
        return TemplateContent(
            items=tuple(item.to_spec() for item in self.items),
            titration_rules=None
            if self.titration_rules is None
            else self.titration_rules.to_rules(),
            limits=None if self.limits is None else self.limits.to_limits(),
        )


class TemplateCreateRequest(StrictRequest):
    """A new protocol template; its code is derived from the name."""

    name: str = Field(
        min_length=1,
        max_length=FieldLimits.TEMPLATE_NAME_MAX_LENGTH,
        description="Nombre visible, por ejemplo «Basal-bolo adulto DM1».",
    )
    content: TemplateContentRequest


class TemplateVersionRequest(StrictRequest):
    """The content of the next version of a template."""

    content: TemplateContentRequest


class PlanContentRequest(StrictRequest):
    """The content of a plan draft."""

    items: list[ItemRequest] = Field(max_length=FieldLimits.PLAN_ITEMS_MAX_ITEMS)
    titration_rules: TitrationRulesRequest | None = None
    notes: str | None = Field(
        default=None, max_length=FieldLimits.PLAN_NOTES_MAX_LENGTH
    )

    def to_input(self) -> PlanContentInput:
        return PlanContentInput(
            items=tuple(item.to_spec() for item in self.items),
            titration_rules=None
            if self.titration_rules is None
            else self.titration_rules.to_rules(),
            notes=self.notes,
        )


class PlanCreateRequest(StrictRequest):
    """A plan for an assigned patient, from a template or written from scratch."""

    patient_id: UUID
    template_id: UUID | None = Field(
        default=None, description="Plantilla que se clona en profundidad."
    )
    content: PlanContentRequest | None = None


class PlanUpdateRequest(StrictRequest):
    """The new content of a draft plan."""

    content: PlanContentRequest


class RestoreRequest(StrictRequest):
    """The photo to bring back as a new draft."""

    snapshot_id: UUID


class ItemResponse(BaseModel):
    """An item of a plan (with its id) or of a template (without one)."""

    id: UUID | None
    item_type: ItemType
    name: str
    insulin_kind: InsulinKind | None
    dose_units: Decimal | None
    time_of_day: time | None
    days_of_week: list[int] | None
    instructions: str | None

    @classmethod
    def of(cls, item: ItemSpec) -> Self:
        return cls(
            id=item.item_id if isinstance(item, PlanItem) else None,
            item_type=item.item_type,
            name=item.name,
            insulin_kind=item.insulin_kind,
            dose_units=item.dose_units,
            time_of_day=item.time_of_day,
            days_of_week=None if item.days_of_week is None else list(item.days_of_week),
            instructions=item.instructions,
        )


class TitrationRulesResponse(BaseModel):
    step_units: Decimal
    max_change_units: Decimal
    min_days_between_adjustments: int


class PlanResponse(BaseModel):
    """A treatment plan version."""

    id: UUID
    patient_id: UUID
    version: int
    status: PlanStatus
    template_id: UUID | None
    previous_plan_id: UUID | None
    notes: str | None
    titration_rules: TitrationRulesResponse | None
    items: list[ItemResponse]
    created_at: datetime
    updated_at: datetime
    activated_at: datetime | None
    simulated: bool = Field(description="Datos simulados de una clínica demo.")

    @classmethod
    def of(cls, plan: TreatmentPlan, *, simulated: bool) -> Self:
        rules = plan.titration_rules
        return cls(
            id=plan.plan_id,
            patient_id=plan.patient_id,
            version=plan.version,
            status=plan.status,
            template_id=plan.template_id,
            previous_plan_id=plan.previous_plan_id,
            notes=plan.notes,
            titration_rules=None
            if rules is None
            else TitrationRulesResponse(
                step_units=rules.step_units,
                max_change_units=rules.max_change_units,
                min_days_between_adjustments=rules.min_days_between_adjustments,
            ),
            items=[ItemResponse.of(item) for item in plan.items],
            created_at=plan.created_at,
            updated_at=plan.updated_at,
            activated_at=plan.activated_at,
            simulated=simulated,
        )


class TemplateResponse(BaseModel):
    """A protocol template version."""

    id: UUID
    code: str
    name: str
    version: int
    status: TemplateStatus
    items: list[ItemResponse]
    titration_rules: TitrationRulesResponse | None
    simulated: bool = Field(description="Datos simulados de una clínica demo.")

    @classmethod
    def of(cls, template: ProtocolTemplate, *, simulated: bool) -> Self:
        rules = template.content.titration_rules
        return cls(
            id=template.template_id,
            code=template.code,
            name=template.name,
            version=template.version,
            status=template.status,
            items=[
                ItemResponse.of(PlanItem.of(UUID(int=0), spec))
                for spec in template.content.items
            ],
            titration_rules=None
            if rules is None
            else TitrationRulesResponse(
                step_units=rules.step_units,
                max_change_units=rules.max_change_units,
                min_days_between_adjustments=rules.min_days_between_adjustments,
            ),
            simulated=simulated,
        )


class TemplateVersionResponse(BaseModel):
    id: UUID
    version: int
    status: TemplateStatus


class TemplateDetailResponse(TemplateResponse):
    """A template and the versions of its family."""

    versions: list[TemplateVersionResponse]


class SnapshotResponse(BaseModel):
    """A photo of a plan, to choose which one to restore."""

    id: UUID
    version: int = Field(description="Versión del plan en la foto.")
    created_at: datetime
    created_by: UUID

    @classmethod
    def of(cls, stored: StoredSnapshot) -> Self:
        return cls(
            id=stored.snapshot_id,
            version=int(stored.memento.data["version"]),
            created_at=stored.memento.taken_at,
            created_by=stored.taken_by,
        )


def _of_template(template: ProtocolTemplate, actor: Actor) -> TemplateResponse:
    return TemplateResponse.of(template, simulated=actor.clinic_is_demo)


def _of_plan(plan: TreatmentPlan, actor: Actor) -> PlanResponse:
    return PlanResponse.of(plan, simulated=actor.clinic_is_demo)


@final
class TreatmentRouter:
    """Builds the treatment endpoints over the command bus and the read use cases.

    Permissions are checked in the handlers and the use cases; the patient's own
    plan is read through ``OwnPatientGate`` (C3) and never shows a draft.
    """

    def __init__(
        self,
        *,
        commands: CommandBus,
        list_templates: ListProtocolTemplatesUseCase,
        get_template: GetProtocolTemplateUseCase,
        list_plans: ListTreatmentPlansUseCase,
        get_plan: GetTreatmentPlanUseCase,
        list_snapshots: ListTreatmentPlanSnapshotsUseCase,
        get_own_plan: GetOwnTreatmentPlanUseCase,
        staff_actor: Any,
    ) -> None:
        self._commands = commands
        self._list_templates = list_templates
        self._get_template = get_template
        self._list_plans = list_plans
        self._get_plan = get_plan
        self._list_snapshots = list_snapshots
        self._get_own_plan = get_own_plan
        self._staff_actor = staff_actor
        self.router = APIRouter(prefix=TREATMENT_PREFIX, tags=[ApiTag.TREATMENT])
        self._add_routes()

    def _add_routes(self) -> None:
        add = self.router.add_api_route
        staff = Depends(self._staff_actor)
        manage_templates = {
            ACCESS_EXTENSION: access(PermissionCode.PROTOCOL_TEMPLATES_MANAGE)
        }
        read_templates = {
            ACCESS_EXTENSION: access(PermissionCode.PROTOCOL_TEMPLATES_READ)
        }
        manage_plans = {ACCESS_EXTENSION: access(PermissionCode.TREATMENT_PLANS_MANAGE)}
        read_own = {ACCESS_EXTENSION: access(PermissionCode.TREATMENT_PLANS_READ_OWN)}
        commands = self._commands

        def create_protocol_template(
            body: TemplateCreateRequest, actor: Annotated[Actor, staff]
        ) -> TemplateResponse:
            template = commands.dispatch(
                CreateProtocolTemplateCommand(
                    actor=actor, name=body.name, content=body.content.to_content()
                )
            )
            return _of_template(template, actor)

        def list_protocol_templates(
            actor: Annotated[Actor, staff],
            status: Annotated[TemplateStatusFilter | None, Query()] = None,
            limit: LimitQuery = FieldLimits.PAGE_SIZE_DEFAULT,
            cursor: CursorQuery = None,
        ) -> PageResponse[TemplateResponse]:
            page = self._list_templates.execute(
                actor,
                None if status is None else TemplateStatus(status.value),
                page_request(limit, cursor),
            )
            return PageResponse(
                items=[_of_template(row, actor) for row in page.items],
                next_cursor=page.next_cursor,
            )

        def get_protocol_template(
            template_id: UUID, actor: Annotated[Actor, staff]
        ) -> TemplateDetailResponse:
            view = self._get_template.execute(actor, template_id)
            base = _of_template(view.template, actor)
            return TemplateDetailResponse(
                **base.model_dump(),
                versions=[
                    TemplateVersionResponse(
                        id=v.template_id, version=v.version, status=v.status
                    )
                    for v in view.versions
                ],
            )

        def create_protocol_template_version(
            template_id: UUID,
            body: TemplateVersionRequest,
            actor: Annotated[Actor, staff],
        ) -> TemplateResponse:
            template = commands.dispatch(
                CreateProtocolTemplateVersionCommand(
                    actor=actor,
                    template_id=template_id,
                    content=body.content.to_content(),
                )
            )
            return _of_template(template, actor)

        def retire_protocol_template(
            template_id: UUID, actor: Annotated[Actor, staff]
        ) -> TemplateResponse:
            template = commands.dispatch(
                RetireProtocolTemplateCommand(actor=actor, template_id=template_id)
            )
            return _of_template(template, actor)

        def create_treatment_plan(
            body: PlanCreateRequest, actor: Annotated[Actor, staff]
        ) -> PlanResponse:
            plan = commands.dispatch(
                CreateTreatmentPlanCommand(
                    actor=actor,
                    patient_id=body.patient_id,
                    template_id=body.template_id,
                    content=None if body.content is None else body.content.to_input(),
                )
            )
            return _of_plan(plan, actor)

        def list_treatment_plans(
            actor: Annotated[Actor, staff],
            patient_id: Annotated[UUID, Query()],
            status: Annotated[PlanStatusFilter | None, Query()] = None,
            limit: LimitQuery = FieldLimits.PAGE_SIZE_DEFAULT,
            cursor: CursorQuery = None,
        ) -> PageResponse[PlanResponse]:
            page = self._list_plans.execute(
                actor,
                patient_id,
                None if status is None else PlanStatus(status.value),
                page_request(limit, cursor),
            )
            return PageResponse(
                items=[_of_plan(row, actor) for row in page.items],
                next_cursor=page.next_cursor,
            )

        def get_treatment_plan(
            plan_id: UUID, actor: Annotated[Actor, staff]
        ) -> PlanResponse:
            return _of_plan(self._get_plan.execute(actor, plan_id), actor)

        def update_treatment_plan(
            plan_id: UUID, body: PlanUpdateRequest, actor: Annotated[Actor, staff]
        ) -> PlanResponse:
            plan = commands.dispatch(
                UpdateTreatmentPlanCommand(
                    actor=actor, plan_id=plan_id, content=body.content.to_input()
                )
            )
            return _of_plan(plan, actor)

        def activate_treatment_plan(
            plan_id: UUID, actor: Annotated[Actor, staff]
        ) -> PlanResponse:
            plan = commands.dispatch(
                ActivateTreatmentPlanCommand(actor=actor, plan_id=plan_id)
            )
            return _of_plan(plan, actor)

        def create_treatment_plan_version(
            plan_id: UUID, actor: Annotated[Actor, staff]
        ) -> PlanResponse:
            plan = commands.dispatch(
                CreateTreatmentPlanVersionCommand(actor=actor, plan_id=plan_id)
            )
            return _of_plan(plan, actor)

        def list_treatment_plan_snapshots(
            plan_id: UUID,
            actor: Annotated[Actor, staff],
            limit: LimitQuery = FieldLimits.PAGE_SIZE_DEFAULT,
            cursor: CursorQuery = None,
        ) -> PageResponse[SnapshotResponse]:
            page = self._list_snapshots.execute(
                actor, plan_id, page_request(limit, cursor)
            )
            return PageResponse(
                items=[SnapshotResponse.of(row) for row in page.items],
                next_cursor=page.next_cursor,
            )

        def restore_treatment_plan(
            plan_id: UUID, body: RestoreRequest, actor: Annotated[Actor, staff]
        ) -> PlanResponse:
            plan = commands.dispatch(
                RestoreTreatmentPlanCommand(
                    actor=actor, plan_id=plan_id, snapshot_id=body.snapshot_id
                )
            )
            return _of_plan(plan, actor)

        def get_own_treatment_plan(actor: Annotated[Actor, staff]) -> PlanResponse:
            return _of_plan(self._get_own_plan.execute(actor), actor)

        add(
            "/protocol-templates",
            create_protocol_template,
            methods=["POST"],
            status_code=HTTPStatus.CREATED,
            operation_id="create_protocol_template",
            summary="Crear una plantilla de protocolo",
            description=(
                "Guarda la versión 1 de una plantilla de la clínica. El código sale "
                "del nombre y debe ser único en la clínica."
            ),
            responses=WRITE_ERRORS,
            openapi_extra=manage_templates,
        )
        add(
            "/protocol-templates",
            list_protocol_templates,
            methods=["GET"],
            operation_id="list_protocol_templates",
            summary="Listar las plantillas de protocolo",
            description=(
                "La última versión de cada plantilla de la clínica y las semillas."
            ),
            responses=READ_ERRORS,
            openapi_extra=read_templates,
        )
        add(
            "/protocol-templates/{template_id}",
            get_protocol_template,
            methods=["GET"],
            operation_id="get_protocol_template",
            summary="Consultar una plantilla de protocolo",
            description="La versión pedida, con su contenido y las de su familia.",
            responses=READ_ERRORS,
            openapi_extra=read_templates,
        )
        add(
            "/protocol-templates/{template_id}/versions",
            create_protocol_template_version,
            methods=["POST"],
            status_code=HTTPStatus.CREATED,
            operation_id="create_protocol_template_version",
            summary="Publicar una nueva versión de la plantilla",
            description=(
                "Crea la versión siguiente. Las versiones anteriores y los planes ya "
                "creados no cambian."
            ),
            responses=WRITE_ERRORS,
            openapi_extra=manage_templates,
        )
        add(
            "/protocol-templates/{template_id}/retire",
            retire_protocol_template,
            methods=["POST"],
            operation_id="retire_protocol_template",
            summary="Retirar una plantilla de protocolo",
            description=(
                "Una plantilla retirada no se puede clonar. Los planes que ya la usan "
                "no cambian."
            ),
            responses=WRITE_ERRORS,
            openapi_extra=manage_templates,
        )
        add(
            "/treatment-plans",
            create_treatment_plan,
            methods=["POST"],
            status_code=HTTPStatus.CREATED,
            operation_id="create_treatment_plan",
            summary="Crear un plan de tratamiento",
            description=(
                "Crea un borrador para un paciente asignado, clonando una plantilla o "
                "desde cero. El borrador no se valida hasta activarlo."
            ),
            responses=WRITE_ERRORS,
            openapi_extra=manage_plans,
        )
        add(
            "/treatment-plans",
            list_treatment_plans,
            methods=["GET"],
            operation_id="list_treatment_plans",
            summary="Listar los planes de un paciente asignado",
            description="Los planes del paciente, del más reciente al más antiguo.",
            responses=READ_ERRORS,
            openapi_extra=manage_plans,
        )
        add(
            "/treatment-plans/{plan_id}",
            get_treatment_plan,
            methods=["GET"],
            operation_id="get_treatment_plan",
            summary="Consultar un plan de tratamiento",
            description="El plan con su contenido.",
            responses=READ_ERRORS,
            openapi_extra=manage_plans,
        )
        add(
            "/treatment-plans/{plan_id}",
            update_treatment_plan,
            methods=["PATCH"],
            operation_id="update_treatment_plan",
            summary="Editar el borrador de un plan",
            description=(
                "Solo un borrador se edita. Antes del cambio se guarda una foto."
            ),
            responses=WRITE_ERRORS,
            openapi_extra=manage_plans,
        )
        add(
            "/treatment-plans/{plan_id}/activate",
            activate_treatment_plan,
            methods=["POST"],
            operation_id="activate_treatment_plan",
            summary="Activar un plan de tratamiento",
            description=(
                "Valida las invariantes del borrador y lo activa. El plan activo "
                "anterior pasa a superado."
            ),
            responses=WRITE_ERRORS,
            openapi_extra=manage_plans,
        )
        add(
            "/treatment-plans/{plan_id}/versions",
            create_treatment_plan_version,
            methods=["POST"],
            status_code=HTTPStatus.CREATED,
            operation_id="create_treatment_plan_version",
            summary="Abrir una nueva versión de un plan activo",
            description=(
                "Copia el plan activo en un borrador nuevo. El plan activo no cambia "
                "hasta activar la versión."
            ),
            responses=WRITE_ERRORS,
            openapi_extra=manage_plans,
        )
        add(
            "/treatment-plans/{plan_id}/snapshots",
            list_treatment_plan_snapshots,
            methods=["GET"],
            operation_id="list_treatment_plan_snapshots",
            summary="Listar las fotos de un plan",
            description=(
                "Las fotos guardadas antes de cada cambio, para elegir una a restaurar."
            ),
            responses=READ_ERRORS,
            openapi_extra=manage_plans,
        )
        add(
            "/treatment-plans/{plan_id}/restore",
            restore_treatment_plan,
            methods=["POST"],
            status_code=HTTPStatus.CREATED,
            operation_id="restore_treatment_plan",
            summary="Restaurar una foto de un plan",
            description=(
                "Crea un borrador nuevo con el contenido de la foto. El historial "
                "no se pierde."
            ),
            responses=WRITE_ERRORS,
            openapi_extra=manage_plans,
        )
        add(
            "/patients/own/treatment-plan",
            get_own_treatment_plan,
            methods=["GET"],
            operation_id="get_own_treatment_plan",
            summary="Consultar mi plan de tratamiento activo",
            description=(
                "El plan activo en lenguaje claro. No muestra borradores ni opciones "
                "de edición."
            ),
            responses=READ_ERRORS,
            openapi_extra=read_own,
        )
