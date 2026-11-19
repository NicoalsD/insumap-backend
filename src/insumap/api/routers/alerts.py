"""Alert endpoints (API.md 8.9): rules, alerts, their summary and the two decisions."""

from datetime import datetime
from http import HTTPStatus
from typing import Annotated, Any, Final, Self, final
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
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
from insumap.application.alerts.commands import (
    AcknowledgeAlertCommand,
    CreateAlertRuleCommand,
    CreateAlertRuleVersionCommand,
    ResolveAlertCommand,
)
from insumap.application.alerts.queries import (
    AlertView,
    GetAlertRuleUseCase,
    GetAlertSummaryUseCase,
    GetAlertUseCase,
    ListAlertRulesUseCase,
    ListAlertsUseCase,
)
from insumap.application.commands.base import CommandBus
from insumap.application.common.actor import Actor
from insumap.domain.alerts.alert import (
    Alert,
    AlertPriority,
    AlertRuleVersion,
    AlertType,
)
from insumap.domain.alerts.escalation import EscalationStep
from insumap.domain.alerts.state import AlertStatus
from insumap.domain.identity.permissions import PermissionCode
from insumap.shared.field_limits import FieldLimits

ALERTS_PREFIX: Final = f"{API_V1_PREFIX}"
ALERT_RULE_PATH: Final = "/alert-rules"
ALERT_PATH: Final = "/alerts"

NAME_FIELD: Final = Field(
    min_length=1,
    max_length=FieldLimits.ALERT_NAME_MAX_LENGTH,
    description="Nombre de la regla, visible para el personal.",
)
CHANGE_REASON_FIELD: Final = Field(
    min_length=FieldLimits.REASON_MIN_LENGTH,
    max_length=FieldLimits.REASON_MAX_LENGTH,
    description="Motivo de la versión nueva (queda en la auditoría).",
)
NOTE_FIELD: Final = Field(
    default=None,
    max_length=FieldLimits.REASON_MAX_LENGTH,
    description="Nota opcional del reconocimiento.",
)
LEVEL_FIELD: Final = Field(
    default=None,
    ge=FieldLimits.ALERT_LEVEL_MIN,
    le=FieldLimits.ALERT_LEVEL_MAX,
    description="Nivel de hipoglucemia (1, 2 o 3); nulo en otros tipos.",
)
ESCALATION_FIELD: Final[list[dict[str, Any]]] = Field(
    default_factory=list,
    max_length=FieldLimits.ALERT_LEVEL_MAX,
    description="Cadena de escalamiento, un paso por nivel desde el 1.",
)

RULE_ERRORS: Final = error_responses(
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
    HTTPStatus.UNPROCESSABLE_ENTITY,
    HTTPStatus.NOT_FOUND,
)
ALERT_ERRORS: Final = error_responses(
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
    HTTPStatus.UNPROCESSABLE_ENTITY,
    HTTPStatus.NOT_FOUND,
    HTTPStatus.CONFLICT,
)


class AlertRuleFields(StrictRequest):
    """The fields a rule version carries; thresholds are data, never code."""

    name: str = NAME_FIELD
    alert_type: AlertType
    priority: AlertPriority
    level: int | None = LEVEL_FIELD
    condition: dict[str, Any] = Field(
        description=(
            "Árbol de condiciones: nodos THRESHOLD, DURATION y RATE_OF_CHANGE "
            "combinados con ALL_OF y ANY_OF. Los umbrales son datos de la regla."
        )
    )
    escalation: list[dict[str, Any]] = ESCALATION_FIELD


class CreateAlertRuleRequest(AlertRuleFields):
    """A new rule of the clinic, active from version 1."""


class CreateAlertRuleVersionRequest(AlertRuleFields):
    """The next version of a rule; the active one is retired."""

    change_reason: str = CHANGE_REASON_FIELD


class AcknowledgeAlertRequest(StrictRequest):
    note: str | None = NOTE_FIELD


class ResolveAlertRequest(StrictRequest):
    note: str = Field(
        min_length=FieldLimits.REASON_MIN_LENGTH,
        max_length=FieldLimits.REASON_MAX_LENGTH,
        description="Nota de cierre, obligatoria.",
    )


def _escalation_out(steps: tuple[EscalationStep, ...]) -> list[dict[str, Any]]:
    return [step.to_definition() for step in steps]


class AlertRuleResponse(BaseModel):
    """One rule version of the clinic."""

    id: UUID
    version: int
    status: str
    name: str
    alert_type: AlertType
    priority: AlertPriority
    level: int | None
    condition: dict[str, Any]
    escalation: list[dict[str, Any]]

    @classmethod
    def of(cls, rule: AlertRuleVersion) -> Self:
        return cls(
            id=rule.rule_id,
            version=rule.version,
            status=rule.status.value,
            name=rule.name,
            alert_type=rule.alert_type,
            priority=rule.priority,
            level=rule.level,
            condition=dict(rule.condition),
            escalation=_escalation_out(rule.escalation),
        )


class AlertRuleDetailResponse(AlertRuleResponse):
    """A rule with the history of its versions."""

    versions: list[AlertRuleResponse]


class AlertResponse(BaseModel):
    """An alert in a listing: its state and the references, never the evidence."""

    id: UUID
    patient_id: UUID
    type: AlertType
    level: int | None
    priority: AlertPriority
    status: AlertStatus
    opened_at: datetime
    rule_id: UUID
    is_fallback: bool
    escalation_level: int
    simulated: bool

    @classmethod
    def of(cls, alert: Alert, *, simulated: bool) -> Self:
        return cls(
            id=alert.alert_id,
            patient_id=alert.patient_id,
            type=alert.alert_type,
            level=alert.level,
            priority=alert.priority,
            status=alert.status,
            opened_at=alert.opened_at,
            rule_id=alert.rule_id,
            is_fallback=alert.is_fallback,
            escalation_level=alert.escalation_level,
            simulated=simulated,
        )


class AlertHistoryItem(BaseModel):
    """One change of status: who, when and the note."""

    from_status: AlertStatus | None
    to_status: AlertStatus
    actor_type: str
    actor_id: UUID | None
    occurred_at: datetime
    note: str | None


class AlertDetailResponse(AlertResponse):
    """An alert with its history (append only)."""

    acknowledged_by: UUID | None
    acknowledged_at: datetime | None
    resolved_by: UUID | None
    resolved_at: datetime | None
    resolution_note: str | None
    history: list[AlertHistoryItem]

    @classmethod
    def from_view(cls, view: AlertView, *, simulated: bool) -> Self:
        alert = view.alert
        return cls(
            **AlertResponse.of(alert, simulated=simulated).model_dump(),
            acknowledged_by=alert.acknowledged_by,
            acknowledged_at=alert.acknowledged_at,
            resolved_by=alert.resolved_by,
            resolved_at=alert.resolved_at,
            resolution_note=alert.resolution_note,
            history=[
                AlertHistoryItem(
                    from_status=change.from_status,
                    to_status=change.to_status,
                    actor_type=change.actor_type.value,
                    actor_id=change.actor_user_id,
                    occurred_at=change.occurred_at,
                    note=change.note,
                )
                for change in view.history
            ],
        )


class AlertSummaryCareTeam(BaseModel):
    doctor_id: UUID
    unattended_count: int


class AlertSummaryResponse(BaseModel):
    """Counts only; small counts are grouped by the database function."""

    open_count: int
    escalated_count: int
    by_care_team: list[AlertSummaryCareTeam]


@final
class AlertRouter:
    """Builds the rules and alerts endpoints over the use cases and the bus (P13).

    Reads go to their use case, which applies the scope (P11) and the audit (P09).
    Decisions go through the command bus, so they run in their transaction.
    """

    def __init__(
        self,
        *,
        commands: CommandBus,
        list_rules: ListAlertRulesUseCase,
        get_rule: GetAlertRuleUseCase,
        list_alerts: ListAlertsUseCase,
        get_summary: GetAlertSummaryUseCase,
        get_alert: GetAlertUseCase,
        session_actor: Any,
    ) -> None:
        self._commands = commands
        self._list_rules = list_rules
        self._get_rule = get_rule
        self._list_alerts = list_alerts
        self._get_summary = get_summary
        self._get_alert = get_alert
        self._session_actor = session_actor
        self.router = APIRouter(prefix=ALERTS_PREFIX, tags=[ApiTag.ALERTS])
        self._add_routes()

    def _add_routes(self) -> None:
        add = self.router.add_api_route
        session = Depends(self._session_actor)

        def create_rule(
            body: CreateAlertRuleRequest,
            response: Response,
            actor: Annotated[Actor, session],
        ) -> AlertRuleResponse:
            rule = self._commands.dispatch(
                CreateAlertRuleCommand(
                    actor=actor,
                    name=body.name,
                    alert_type=body.alert_type,
                    priority=body.priority,
                    level=body.level,
                    condition=body.condition,
                    escalation=body.escalation,
                )
            )
            response.headers["Location"] = f"{ALERT_RULE_PATH}/{rule.rule_id}"
            return AlertRuleResponse.of(rule)

        def list_rules(
            actor: Annotated[Actor, session],
            alert_type: Annotated[AlertType | None, Query()] = None,
            limit: LimitQuery = FieldLimits.PAGE_SIZE_DEFAULT,
            cursor: CursorQuery = None,
        ) -> PageResponse[AlertRuleResponse]:
            page = self._list_rules.execute(
                actor, alert_type=alert_type, page=page_request(limit, cursor)
            )
            return PageResponse(
                items=[AlertRuleResponse.of(rule) for rule in page.items],
                next_cursor=page.next_cursor,
            )

        def get_rule(
            rule_id: UUID, actor: Annotated[Actor, session]
        ) -> AlertRuleDetailResponse:
            view = self._get_rule.execute(actor, rule_id)
            current = AlertRuleResponse.of(view.rule)
            return AlertRuleDetailResponse(
                **current.model_dump(),
                versions=[AlertRuleResponse.of(v) for v in view.versions],
            )

        def create_rule_version(
            rule_id: UUID,
            body: CreateAlertRuleVersionRequest,
            response: Response,
            actor: Annotated[Actor, session],
        ) -> AlertRuleResponse:
            rule = self._commands.dispatch(
                CreateAlertRuleVersionCommand(
                    actor=actor,
                    rule_id=rule_id,
                    name=body.name,
                    alert_type=body.alert_type,
                    priority=body.priority,
                    level=body.level,
                    condition=body.condition,
                    escalation=body.escalation,
                    change_reason=body.change_reason,
                )
            )
            response.headers["Location"] = f"{ALERT_RULE_PATH}/{rule.rule_id}"
            return AlertRuleResponse.of(rule)

        def list_alerts(
            actor: Annotated[Actor, session],
            status: Annotated[AlertStatus | None, Query()] = None,
            type: Annotated[AlertType | None, Query()] = None,
            from_: Annotated[datetime | None, Query(alias="from")] = None,
            to: Annotated[datetime | None, Query()] = None,
            patient_id: Annotated[UUID | None, Query()] = None,
            limit: LimitQuery = FieldLimits.PAGE_SIZE_DEFAULT,
            cursor: CursorQuery = None,
        ) -> PageResponse[AlertResponse]:
            page = self._list_alerts.execute(
                actor,
                status=status,
                alert_type=type,
                opened_from=from_,
                opened_to=to,
                patient_id=patient_id,
                page=page_request(limit, cursor),
            )
            return PageResponse(
                items=[
                    AlertResponse.of(alert, simulated=actor.clinic_is_demo)
                    for alert in page.items
                ],
                next_cursor=page.next_cursor,
            )

        def alert_summary(
            actor: Annotated[Actor, session],
        ) -> AlertSummaryResponse:
            summary = self._get_summary.execute(actor)
            return AlertSummaryResponse(
                open_count=summary.open_count,
                escalated_count=summary.escalated_count,
                by_care_team=[
                    AlertSummaryCareTeam(
                        doctor_id=row.doctor_id,
                        unattended_count=row.unattended_count,
                    )
                    for row in summary.by_care_team
                ],
            )

        def get_alert(
            alert_id: UUID, actor: Annotated[Actor, session]
        ) -> AlertDetailResponse:
            view = self._get_alert.execute(actor, alert_id)
            return AlertDetailResponse.from_view(view, simulated=actor.clinic_is_demo)

        def acknowledge_alert(
            alert_id: UUID,
            body: AcknowledgeAlertRequest,
            actor: Annotated[Actor, session],
        ) -> AlertDetailResponse:
            alert = self._commands.dispatch(
                AcknowledgeAlertCommand(actor=actor, alert_id=alert_id, note=body.note)
            )
            return AlertDetailResponse.from_view(
                self._get_alert.execute(actor, alert.alert_id),
                simulated=actor.clinic_is_demo,
            )

        def resolve_alert(
            alert_id: UUID,
            body: ResolveAlertRequest,
            actor: Annotated[Actor, session],
        ) -> AlertDetailResponse:
            alert = self._commands.dispatch(
                ResolveAlertCommand(actor=actor, alert_id=alert_id, note=body.note)
            )
            return AlertDetailResponse.from_view(
                self._get_alert.execute(actor, alert.alert_id),
                simulated=actor.clinic_is_demo,
            )

        rules_read = {ACCESS_EXTENSION: access(PermissionCode.ALERT_RULES_READ)}
        rules_write = {ACCESS_EXTENSION: access(PermissionCode.ALERT_RULES_MANAGE)}
        alerts_read = {ACCESS_EXTENSION: access(PermissionCode.ALERTS_READ_ASSIGNED)}
        summary_read = {ACCESS_EXTENSION: access(PermissionCode.ALERTS_READ_SUMMARY)}
        ack = {ACCESS_EXTENSION: access(PermissionCode.ALERTS_ACKNOWLEDGE)}
        resolve = {ACCESS_EXTENSION: access(PermissionCode.ALERTS_RESOLVE)}

        add(
            ALERT_RULE_PATH,
            create_rule,
            methods=["POST"],
            status_code=HTTPStatus.CREATED,
            operation_id="create_alert_rule",
            summary="Crear una regla de alerta",
            description=(
                "Crea la versión 1 de una regla de la clínica, activa de inmediato. "
                "Los umbrales, las duraciones y la cadena de escalamiento son datos "
                "de la regla."
            ),
            responses=RULE_ERRORS,
            openapi_extra=rules_write,
        )
        add(
            ALERT_RULE_PATH,
            list_rules,
            methods=["GET"],
            operation_id="list_alert_rules",
            summary="Listar las reglas de alerta vigentes",
            description="Reglas activas de la clínica y las semillas globales.",
            responses=RULE_ERRORS,
            openapi_extra=rules_read,
        )
        add(
            f"{ALERT_RULE_PATH}/{{rule_id}}",
            get_rule,
            methods=["GET"],
            operation_id="get_alert_rule",
            summary="Consultar una regla de alerta",
            description="La regla con el historial de sus versiones.",
            responses=RULE_ERRORS,
            openapi_extra=rules_read,
        )
        add(
            f"{ALERT_RULE_PATH}/{{rule_id}}/versions",
            create_rule_version,
            methods=["POST"],
            status_code=HTTPStatus.CREATED,
            operation_id="create_alert_rule_version",
            summary="Publicar una versión nueva de una regla",
            description=(
                "La versión activa pasa a retirada y la nueva queda activa. Una "
                "regla activa no se edita. Una semilla global responde `404`."
            ),
            responses=RULE_ERRORS,
            openapi_extra=rules_write,
        )
        add(
            ALERT_PATH,
            list_alerts,
            methods=["GET"],
            operation_id="list_alerts",
            summary="Listar alertas",
            description=(
                "El médico ve las alertas de sus pacientes asignados; el paciente, "
                "las propias. Cada paciente del listado queda auditado."
            ),
            responses=ALERT_ERRORS,
            openapi_extra=alerts_read,
        )
        add(
            f"{ALERT_PATH}/summary",
            alert_summary,
            methods=["GET"],
            operation_id="get_alert_summary",
            summary="Resumen de alertas de la clínica",
            description=(
                "Conteos agregados para el administrador. Nunca glucosa ni datos del "
                "paciente; los conteos pequeños se agrupan."
            ),
            responses=error_responses(HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN),
            openapi_extra=summary_read,
        )
        add(
            f"{ALERT_PATH}/{{alert_id}}",
            get_alert,
            methods=["GET"],
            operation_id="get_alert",
            summary="Consultar una alerta",
            description="La alerta con su historial de estados (solo se agrega).",
            responses=ALERT_ERRORS,
            openapi_extra=alerts_read,
        )
        add(
            f"{ALERT_PATH}/{{alert_id}}/acknowledge",
            acknowledge_alert,
            methods=["POST"],
            operation_id="acknowledge_alert",
            summary="Reconocer una alerta",
            description=(
                "Detiene el escalamiento. Solo una alerta abierta o escalada se "
                "reconoce; una resuelta responde `409`."
            ),
            responses=ALERT_ERRORS,
            openapi_extra=ack,
        )
        add(
            f"{ALERT_PATH}/{{alert_id}}/resolve",
            resolve_alert,
            methods=["POST"],
            operation_id="resolve_alert",
            summary="Resolver una alerta",
            description="Solo una alerta reconocida se resuelve, con una nota.",
            responses=ALERT_ERRORS,
            openapi_extra=resolve,
        )
