"""AI assessment endpoints (API.md 8.10): risk, findings, summaries, dropout and
evaluations.

The router maps HTTP to a use case and the result back. It never calls a
repository or an adapter, and every route declares its permission (P11 gates and
the RLS do the rest).
"""

from http import HTTPStatus
from typing import Annotated, Any, Final, final
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from insumap.api.paths import API_V1_PREFIX
from insumap.api.routers.ai_assessments_schemas import (
    RISK_LABEL_KEY,
    AiEvaluationResponse,
    ClinicalSummaryResponse,
    CreateClinicalSummaryRequest,
    DropoutRiskResponse,
    PatternFindingResponse,
    RiskResponse,
    summary_label,
)
from insumap.api.routers.common import (
    ACCESS_EXTENSION,
    CursorQuery,
    LimitQuery,
    PageResponse,
    access,
    error_responses,
    page_request,
)
from insumap.api.tags import ApiTag
from insumap.application.ai.assessment_reads import (
    ListAiEvaluationsUseCase,
    ListDropoutRisksUseCase,
    ListPatternFindingsUseCase,
)
from insumap.application.ai.records import AiEvaluationFilter
from insumap.application.ai.risk import GetPatientRiskUseCase
from insumap.application.ai.summaries import (
    CreateClinicalSummaryUseCase,
    GetClinicalSummaryUseCase,
)
from insumap.application.common.actor import Actor
from insumap.domain.ai.risk import RiskTier
from insumap.domain.identity.permissions import PermissionCode
from insumap.shared.field_limits import FieldLimits
from insumap.shared.i18n.message_catalog import MessageCatalog

PATIENT_PATH: Final = "/patients/{patient_id}"
WINDOW_DAYS_QUERY: Final = Query(
    ge=FieldLimits.AI_WINDOW_DAYS_MIN,
    le=FieldLimits.AI_WINDOW_DAYS_MAX,
    description="Días completos de la ventana, que terminan hoy (por defecto 14).",
)
READ_ERRORS: Final = error_responses(
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
    HTTPStatus.UNPROCESSABLE_ENTITY,
    HTTPStatus.NOT_FOUND,
)
SUMMARY_ERRORS: Final = error_responses(
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
    HTTPStatus.UNPROCESSABLE_ENTITY,
    HTTPStatus.NOT_FOUND,
)
ROLE_ERRORS: Final = error_responses(
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
    HTTPStatus.UNPROCESSABLE_ENTITY,
)
type TierQuery = Annotated[
    RiskTier | None,
    Query(
        description="Filtra por nivel de riesgo: `LOW`, `MEDIUM`, `HIGH` o `CRITICAL`."
    ),
]
type UseCaseQuery = Annotated[
    str | None,
    Query(
        pattern="^IA[1-7]$",
        description="Caso de uso: `IA1` a `IA7`.",
    ),
]
type ModelVersionQuery = Annotated[
    str | None,
    Query(
        max_length=FieldLimits.AI_MODEL_VERSION_MAX_LENGTH,
        description="Versión del modelo evaluado.",
    ),
]


@final
class AiAssessmentRouter:
    """Builds the AI assessment routes over their use cases.

    Pattern: none of its own; the gates (P11) and the audit (P09) are in the use cases.
    """

    def __init__(
        self,
        *,
        risk: GetPatientRiskUseCase,
        findings: ListPatternFindingsUseCase,
        create_summary: CreateClinicalSummaryUseCase,
        get_summary: GetClinicalSummaryUseCase,
        dropout: ListDropoutRisksUseCase,
        evaluations: ListAiEvaluationsUseCase,
        messages: MessageCatalog,
        session_actor: Any,
    ) -> None:
        self._risk = risk
        self._findings = findings
        self._create_summary = create_summary
        self._get_summary = get_summary
        self._dropout = dropout
        self._evaluations = evaluations
        self._messages = messages
        self._session_actor = session_actor
        self.router = APIRouter(prefix=API_V1_PREFIX, tags=[ApiTag.AI])
        self._add_routes()

    def _label(self, key: str) -> str:
        return self._messages.render(key)

    def _add_routes(self) -> None:
        add = self.router.add_api_route
        session = Depends(self._session_actor)

        def get_patient_risk(
            patient_id: UUID,
            actor: Annotated[Actor, session],
            window_days: Annotated[
                int, WINDOW_DAYS_QUERY
            ] = FieldLimits.AI_WINDOW_DAYS_DEFAULT,
        ) -> RiskResponse:
            result = self._risk.execute(actor, patient_id, window_days)
            return RiskResponse.of(
                result,
                label=self._label(RISK_LABEL_KEY),
                simulated=actor.clinic_is_demo,
            )

        def list_pattern_findings(
            patient_id: UUID,
            actor: Annotated[Actor, session],
            limit: LimitQuery = FieldLimits.PAGE_SIZE_DEFAULT,
            cursor: CursorQuery = None,
        ) -> PageResponse[PatternFindingResponse]:
            page = self._findings.execute(
                actor, patient_id, page_request(limit, cursor)
            )
            return PageResponse(
                items=[
                    PatternFindingResponse.of(
                        item,
                        label=self._label(RISK_LABEL_KEY),
                        simulated=actor.clinic_is_demo,
                    )
                    for item in page.items
                ],
                next_cursor=page.next_cursor,
            )

        def create_clinical_summary(
            patient_id: UUID,
            actor: Annotated[Actor, session],
            response: Response,
            body: CreateClinicalSummaryRequest | None = None,
        ) -> ClinicalSummaryResponse:
            days = (
                FieldLimits.AI_WINDOW_DAYS_DEFAULT if body is None else body.period_days
            )
            result = self._create_summary.execute(actor, patient_id, days)
            response.headers["Location"] = (
                f"{API_V1_PREFIX}/patients/{patient_id}/clinical-summaries/"
                f"{result.summary_id}"
            )
            return ClinicalSummaryResponse.of_result(
                result,
                patient_id=patient_id,
                label=self._label(summary_label(result)),
                simulated=actor.clinic_is_demo,
            )

        def get_clinical_summary(
            patient_id: UUID,
            summary_id: UUID,
            actor: Annotated[Actor, session],
        ) -> ClinicalSummaryResponse:
            view = self._get_summary.execute(actor, patient_id, summary_id)
            return ClinicalSummaryResponse.of_view(
                view,
                label=self._label(summary_label(view)),
                simulated=actor.clinic_is_demo,
            )

        def list_dropout_risks(
            actor: Annotated[Actor, session],
            risk_tier: TierQuery = None,
            limit: LimitQuery = FieldLimits.PAGE_SIZE_DEFAULT,
            cursor: CursorQuery = None,
        ) -> PageResponse[DropoutRiskResponse]:
            page = self._dropout.execute(
                actor, tier=risk_tier, page=page_request(limit, cursor)
            )
            return PageResponse(
                items=[
                    DropoutRiskResponse.of(
                        item,
                        label=self._label(RISK_LABEL_KEY),
                        simulated=actor.clinic_is_demo,
                    )
                    for item in page.items
                ],
                next_cursor=page.next_cursor,
            )

        def list_ai_evaluations(
            actor: Annotated[Actor, session],
            use_case: UseCaseQuery = None,
            model_version: ModelVersionQuery = None,
            limit: LimitQuery = FieldLimits.PAGE_SIZE_DEFAULT,
            cursor: CursorQuery = None,
        ) -> PageResponse[AiEvaluationResponse]:
            page = self._evaluations.execute(
                actor,
                filters=AiEvaluationFilter(
                    use_case=use_case, model_version=model_version
                ),
                page=page_request(limit, cursor),
            )
            return PageResponse(
                items=[AiEvaluationResponse.of(item) for item in page.items],
                next_cursor=page.next_cursor,
            )

        read = PermissionCode.AI_RISK_READ_ASSIGNED
        summaries = PermissionCode.CLINICAL_SUMMARIES_GENERATE
        add(
            f"{PATIENT_PATH}/risk",
            get_patient_risk,
            methods=["GET"],
            operation_id="get_patient_risk",
            summary="Consultar el riesgo de deterioro de un paciente asignado",
            description=(
                "Sugerencia de la IA (o de las reglas tipo TIDE si la IA no responde) "
                "sobre el riesgo de deterioro glucémico. El médico decide; la "
                "respuesta trae `is_fallback` y `fallback_reason` cuando calculan las "
                "reglas."
            ),
            responses=READ_ERRORS,
            openapi_extra={ACCESS_EXTENSION: access(read)},
        )
        add(
            f"{PATIENT_PATH}/pattern-findings",
            list_pattern_findings,
            methods=["GET"],
            operation_id="list_pattern_findings",
            summary="Listar los hallazgos de patrones de un paciente asignado",
            description=(
                "Hallazgos de IA3 (hipoglucemia nocturna, fenómeno del alba, picos "
                "posprandiales, dosis y adherencia), más recientes primero."
            ),
            responses=READ_ERRORS,
            openapi_extra={ACCESS_EXTENSION: access(read)},
        )
        add(
            f"{PATIENT_PATH}/clinical-summaries",
            create_clinical_summary,
            methods=["POST"],
            operation_id="create_clinical_summary",
            status_code=HTTPStatus.CREATED,
            summary="Generar el resumen previo a la consulta",
            description=(
                "Resumen de IA5 con sus cifras. Generado con IA como apoyo; verifica "
                "con los datos. Sin el LLM o sin datos simulados permitidos, responde "
                "la plantilla fija."
            ),
            responses=SUMMARY_ERRORS,
            openapi_extra={ACCESS_EXTENSION: access(summaries)},
        )
        add(
            f"{PATIENT_PATH}/clinical-summaries/{{summary_id}}",
            get_clinical_summary,
            methods=["GET"],
            operation_id="get_clinical_summary",
            summary="Consultar un resumen clínico generado",
            description="El resumen ya guardado; no vuelve a llamar a la IA.",
            responses=SUMMARY_ERRORS,
            openapi_extra={ACCESS_EXTENSION: access(summaries)},
        )
        add(
            "/dropout-risks",
            list_dropout_risks,
            methods=["GET"],
            operation_id="list_dropout_risks",
            summary="Listar el riesgo de abandono de mis pacientes asignados",
            description=(
                "Riesgo de abandono (IA7) del último cálculo por paciente asignado, "
                "sin valores clínicos. La lista de la clínica para el administrador "
                "todavía no está disponible."
            ),
            responses=ROLE_ERRORS,
            openapi_extra={
                ACCESS_EXTENSION: access(PermissionCode.AI_DROPOUT_RISK_READ)
            },
        )
        add(
            "/ai-evaluations",
            list_ai_evaluations,
            methods=["GET"],
            operation_id="list_ai_evaluations",
            summary="Listar la evaluación de la IA frente al respaldo",
            description=(
                "Métricas agregadas de cada caso de uso frente a su respaldo, sobre "
                "cohortes simuladas. Nunca series de pacientes."
            ),
            responses=ROLE_ERRORS,
            openapi_extra={
                ACCESS_EXTENSION: access(PermissionCode.AI_EVALUATIONS_READ)
            },
        )
