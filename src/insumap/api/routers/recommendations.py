"""Recommendation endpoints (API.md 8.10): list, detail and three decisions."""

from collections.abc import Mapping
from datetime import datetime
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
from insumap.application.ai.commands import (
    ApproveRecommendationCommand,
    ModifyRecommendationCommand,
    RecommendationDecision,
    RejectRecommendationCommand,
)
from insumap.application.ai.queries import (
    GetRecommendationUseCase,
    ListRecommendationsUseCase,
    RecommendationView,
)
from insumap.application.commands.base import CommandBus
from insumap.application.common.actor import Actor
from insumap.domain.ai.recommendation import DecisionRecord, Recommendation
from insumap.domain.ai.recommendation_state import RecommendationStatus
from insumap.domain.identity.permissions import PermissionCode
from insumap.shared.field_limits import FieldLimits

RECOMMENDATIONS_PATH: Final = "/recommendations"
REASON_FIELD: Final = Field(
    min_length=FieldLimits.REASON_MIN_LENGTH,
    max_length=FieldLimits.REASON_MAX_LENGTH,
    description="Motivo, obligatorio (queda en la auditoría y en el historial).",
)
DOSE_FIELD: Final = Field(
    ge=0,
    le=FieldLimits.INSULIN_UNITS_MAX,
    description="Dosis basal propuesta por el médico, en unidades.",
)
ERRORS: Final = error_responses(
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
    HTTPStatus.UNPROCESSABLE_ENTITY,
    HTTPStatus.NOT_FOUND,
    HTTPStatus.CONFLICT,
)
READ_ERRORS: Final = error_responses(
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
    HTTPStatus.UNPROCESSABLE_ENTITY,
    HTTPStatus.NOT_FOUND,
)


class ModifiedProposalRequest(StrictRequest):
    """The doctor's version of the proposal: the dose and the change it implies."""

    action: str = Field(pattern="^(INCREASE|DECREASE)$")
    current_dose_units: float = DOSE_FIELD
    proposed_dose_units: float = DOSE_FIELD
    delta_units: float = Field(
        ge=-FieldLimits.INSULIN_UNITS_MAX,
        le=FieldLimits.INSULIN_UNITS_MAX,
        description="Cambio respecto de la dosis vigente, en unidades.",
    )


class ModifyRecommendationRequest(StrictRequest):
    modified_proposal: ModifiedProposalRequest
    reason: str = REASON_FIELD


class RejectRecommendationRequest(StrictRequest):
    reason: str = REASON_FIELD


class ProposalResponse(BaseModel):
    action: str
    current_dose_units: float | None
    proposed_dose_units: float | None
    delta_units: float | None
    requires_doctor_approval: bool


class ExplanationResponse(BaseModel):
    summary: str
    factors: list[dict[str, Any]]
    data_refs: list[dict[str, Any]]


class RecommendationResponse(BaseModel):
    """A recommendation as the doctor sees it: the proposal and its explanation."""

    id: UUID
    patient_id: UUID
    status: RecommendationStatus
    proposal: ProposalResponse
    explanation: ExplanationResponse
    model_version: str
    is_fallback: bool
    fallback_reason: str | None
    expires_at: datetime
    created_at: datetime
    simulated: bool
    draft_plan_id: UUID | None = None

    @classmethod
    def of(
        cls,
        recommendation: Recommendation,
        *,
        simulated: bool,
        draft_plan_id: UUID | None = None,
    ) -> Self:
        suggestion = recommendation.suggestion
        explanation = recommendation.explanation
        return cls(
            id=recommendation.recommendation_id,
            patient_id=recommendation.patient_id,
            status=recommendation.status,
            proposal=ProposalResponse(
                action=recommendation.action.value,
                current_dose_units=_number(suggestion.get("current_dose_units")),
                proposed_dose_units=_number(suggestion.get("proposed_dose_units")),
                delta_units=_number(suggestion.get("delta_units")),
                requires_doctor_approval=True,
            ),
            explanation=ExplanationResponse(
                summary=str(explanation.get("summary", "")),
                factors=list(explanation.get("factors", [])),
                data_refs=list(explanation.get("data_refs", [])),
            ),
            model_version=recommendation.model_version,
            is_fallback=recommendation.is_fallback,
            fallback_reason=recommendation.fallback_reason,
            expires_at=recommendation.expires_at,
            created_at=recommendation.proposed_at,
            simulated=simulated,
            draft_plan_id=draft_plan_id,
        )


class DecisionEntry(BaseModel):
    """One decision of the history: who, when, why and what changed."""

    decision: RecommendationStatus
    actor_id: UUID | None
    decided_at: datetime
    reason: str | None
    original_suggestion: dict[str, Any] | None
    modified_suggestion: dict[str, Any] | None

    @classmethod
    def of(cls, record: DecisionRecord) -> Self:
        return cls(
            decision=record.decision,
            actor_id=record.decided_by,
            decided_at=record.decided_at,
            reason=record.reason,
            original_suggestion=_plain(record.original_suggestion),
            modified_suggestion=_plain(record.modified_suggestion),
        )


class RecommendationDetailResponse(RecommendationResponse):
    decisions: list[DecisionEntry]


def _number(value: object) -> float | None:
    return None if value is None else float(str(value))


def _plain(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
    return None if value is None else dict(value)


@final
class RecommendationRouter:
    """Builds the recommendation endpoints over the use cases and the bus (P13).

    Reads go to their use case, which applies the assigned scope (P11) and the
    audit (P09). Decisions go through the command bus, so they run in their
    transaction and are audited with it.
    """

    def __init__(
        self,
        *,
        commands: CommandBus,
        list_recommendations: ListRecommendationsUseCase,
        get_recommendation: GetRecommendationUseCase,
        session_actor: Any,
    ) -> None:
        self._commands = commands
        self._list = list_recommendations
        self._get = get_recommendation
        self._session_actor = session_actor
        self.router = APIRouter(prefix=API_V1_PREFIX, tags=[ApiTag.AI])
        self._add_routes()

    def _add_routes(self) -> None:
        add = self.router.add_api_route
        session = Depends(self._session_actor)

        def to_detail(
            view: RecommendationView, actor: Actor
        ) -> RecommendationDetailResponse:
            base = RecommendationResponse.of(
                view.recommendation, simulated=actor.clinic_is_demo
            )
            return RecommendationDetailResponse(
                **base.model_dump(),
                decisions=[DecisionEntry.of(record) for record in view.decisions],
            )

        def decided(
            decision: RecommendationDecision, actor: Actor
        ) -> RecommendationResponse:
            return RecommendationResponse.of(
                decision.recommendation,
                simulated=actor.clinic_is_demo,
                draft_plan_id=decision.draft_plan_id,
            )

        def list_recommendations(
            actor: Annotated[Actor, session],
            patient_id: Annotated[UUID | None, Query()] = None,
            status: Annotated[RecommendationStatus | None, Query()] = None,
            limit: LimitQuery = FieldLimits.PAGE_SIZE_DEFAULT,
            cursor: CursorQuery = None,
        ) -> PageResponse[RecommendationResponse]:
            page = self._list.execute(
                actor,
                patient_id=patient_id,
                status=status,
                page=page_request(limit, cursor),
            )
            return PageResponse(
                items=[
                    RecommendationResponse.of(item, simulated=actor.clinic_is_demo)
                    for item in page.items
                ],
                next_cursor=page.next_cursor,
            )

        def get_recommendation(
            recommendation_id: UUID, actor: Annotated[Actor, session]
        ) -> RecommendationDetailResponse:
            return to_detail(self._get.execute(actor, recommendation_id), actor)

        def approve(
            recommendation_id: UUID, actor: Annotated[Actor, session]
        ) -> RecommendationResponse:
            result = self._commands.dispatch(
                ApproveRecommendationCommand(
                    actor=actor, recommendation_id=recommendation_id
                )
            )
            return decided(result, actor)

        def modify(
            recommendation_id: UUID,
            body: ModifyRecommendationRequest,
            actor: Annotated[Actor, session],
        ) -> RecommendationResponse:
            result = self._commands.dispatch(
                ModifyRecommendationCommand(
                    actor=actor,
                    recommendation_id=recommendation_id,
                    modified_proposal=body.modified_proposal.model_dump(),
                    reason=body.reason,
                )
            )
            return decided(result, actor)

        def reject(
            recommendation_id: UUID,
            body: RejectRecommendationRequest,
            actor: Annotated[Actor, session],
        ) -> RecommendationResponse:
            result = self._commands.dispatch(
                RejectRecommendationCommand(
                    actor=actor, recommendation_id=recommendation_id, reason=body.reason
                )
            )
            return decided(result, actor)

        read = {ACCESS_EXTENSION: access(PermissionCode.RECOMMENDATIONS_READ_ASSIGNED)}
        decide = {ACCESS_EXTENSION: access(PermissionCode.RECOMMENDATIONS_DECIDE)}

        add(
            RECOMMENDATIONS_PATH,
            list_recommendations,
            methods=["GET"],
            operation_id="list_recommendations",
            summary="Listar recomendaciones de la IA de pacientes asignados",
            description=(
                "Propuestas de ajuste de la IA. Nacen en `PROPOSED`, nunca dan una "
                "dosis al paciente y solo las ve el médico asignado."
            ),
            responses=READ_ERRORS,
            openapi_extra=read,
        )
        add(
            f"{RECOMMENDATIONS_PATH}/{{recommendation_id}}",
            get_recommendation,
            methods=["GET"],
            operation_id="get_recommendation",
            summary="Consultar una recomendación",
            description="La recomendación con el historial de sus decisiones.",
            responses=READ_ERRORS,
            openapi_extra=read,
        )
        add(
            f"{RECOMMENDATIONS_PATH}/{{recommendation_id}}/approve",
            approve,
            methods=["POST"],
            operation_id="approve_recommendation",
            summary="Aprobar una recomendación",
            description=(
                "El médico acepta la propuesta tal como está. Abre un borrador del "
                "plan para que lo active; el paciente no ve nada hasta que lo haga."
            ),
            responses=ERRORS,
            openapi_extra=decide,
        )
        add(
            f"{RECOMMENDATIONS_PATH}/{{recommendation_id}}/modify",
            modify,
            methods=["POST"],
            operation_id="modify_recommendation",
            summary="Aprobar una recomendación con cambios",
            description=(
                "El médico cambia la propuesta y la aprueba. Se guardan la propuesta "
                "original, la modificada y el motivo, que es obligatorio."
            ),
            responses=ERRORS,
            openapi_extra=decide,
        )
        add(
            f"{RECOMMENDATIONS_PATH}/{{recommendation_id}}/reject",
            reject,
            methods=["POST"],
            operation_id="reject_recommendation",
            summary="Rechazar una recomendación",
            description="El médico rechaza la propuesta con un motivo obligatorio.",
            responses=ERRORS,
            openapi_extra=decide,
        )
