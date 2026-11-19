"""Report endpoints: patient, own and clinic reports (API.md 8.11)."""

from enum import StrEnum
from http import HTTPStatus
from typing import Annotated, Any, Final, final
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field

from insumap.api.paths import API_V1_PREFIX
from insumap.api.routers.common import ACCESS_EXTENSION, access
from insumap.api.routers.records_errors import records_error_responses
from insumap.api.tags import ApiTag
from insumap.application.common.actor import Actor
from insumap.application.metrics.metrics import MetricWindow
from insumap.application.reports.generate import (
    ClinicReportInput,
    GenerateClinicReportUseCase,
    GenerateOwnReportUseCase,
    GeneratePatientReportUseCase,
    PatientReportInput,
)
from insumap.application.reports.model import ReportFormat
from insumap.domain.identity.permissions import PermissionCode

PDF_MEDIA_TYPE: Final = "application/pdf"
HTML_MEDIA_TYPE: Final = "text/html; charset=utf-8"
NO_STORE: Final = {"Cache-Control": "no-store"}
FILE_NAMES: Final = {ReportFormat.PDF: "reporte.pdf", ReportFormat.HTML: "reporte.html"}


class ReportOutputFormat(StrEnum):
    """The ``format`` of a report request: a PDF or an HTML document."""

    PDF = "pdf"
    HTML = "html"


OUTPUT_FORMATS: Final[dict[ReportOutputFormat, ReportFormat]] = {
    ReportOutputFormat.PDF: ReportFormat.PDF,
    ReportOutputFormat.HTML: ReportFormat.HTML,
}


class StrictReportRequest(BaseModel):
    """Base of the report bodies: unknown fields answer ``422``."""

    model_config = ConfigDict(extra="forbid")


class PatientReportRequest(StrictReportRequest):
    """The assigned patient, the window of the report and its format."""

    patient_id: UUID = Field(description="Paciente asignado al médico que lo solicita.")
    window: MetricWindow = Field(
        default=MetricWindow.LAST_14_DAYS,
        description="Ventana del periodo: `24h`, `7d`, `14d` o `30d`.",
    )
    format: ReportOutputFormat = Field(description="`pdf` o `html`.")


class OwnReportRequest(StrictReportRequest):
    """The window of the patient's own report and its format."""

    window: MetricWindow = Field(
        default=MetricWindow.LAST_14_DAYS,
        description="Ventana del periodo: `24h`, `7d`, `14d` o `30d`.",
    )
    format: ReportOutputFormat = Field(description="`pdf` o `html`.")


class ClinicReportRequest(StrictReportRequest):
    """The format of the clinic indicators."""

    format: ReportOutputFormat = Field(description="`pdf` o `html`.")


REPORT_ERRORS: Final = records_error_responses(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
PATIENT_REPORT_ERRORS: Final = records_error_responses(
    HTTPStatus.REQUEST_ENTITY_TOO_LARGE, HTTPStatus.NOT_FOUND
)
DOCUMENT_RESPONSES: Final[dict[int | str, Any]] = {
    200: {
        "description": "El documento del reporte (PDF o HTML).",
        "content": {PDF_MEDIA_TYPE: {}, HTML_MEDIA_TYPE: {}},
    }
}


@final
class ReportRouter:
    """Builds the report routes over their use cases.

    The router only maps the body to an input and the document to a response;
    the permission, the rate limit, the audit and the rendering live in the
    use cases.
    """

    def __init__(
        self,
        *,
        patient: GeneratePatientReportUseCase,
        own: GenerateOwnReportUseCase,
        clinic: GenerateClinicReportUseCase,
        session_actor: Any,
    ) -> None:
        self._patient = patient
        self._own = own
        self._clinic = clinic
        self._session_actor = session_actor
        self.router = APIRouter(prefix=API_V1_PREFIX, tags=[ApiTag.REPORTS])
        self._add_routes()

    def _add_routes(self) -> None:
        add = self.router.add_api_route
        guard = Depends(self._session_actor)

        def create_patient_report(
            body: PatientReportRequest,
            actor: Annotated[Actor, guard],
        ) -> Response:
            rendered = self._patient.execute(
                PatientReportInput(
                    actor=actor,
                    window=body.window,
                    output=OUTPUT_FORMATS[body.format],
                    patient_id=body.patient_id,
                )
            )
            return _document(rendered.content, rendered.media_type, body.format)

        def create_own_report(
            body: OwnReportRequest,
            actor: Annotated[Actor, guard],
        ) -> Response:
            rendered = self._own.execute(
                PatientReportInput(
                    actor=actor,
                    window=body.window,
                    output=OUTPUT_FORMATS[body.format],
                )
            )
            return _document(rendered.content, rendered.media_type, body.format)

        def create_clinic_report(
            body: ClinicReportRequest,
            actor: Annotated[Actor, guard],
        ) -> Response:
            rendered = self._clinic.execute(
                ClinicReportInput(actor=actor, output=OUTPUT_FORMATS[body.format])
            )
            return _document(rendered.content, rendered.media_type, body.format)

        add(
            "/reports/patient",
            create_patient_report,
            methods=["POST"],
            operation_id="create_patient_report",
            summary="Reporte de un paciente asignado",
            description=(
                "PDF o HTML con AGP, métricas, eventos y plan del paciente asignado, "
                "con la fecha y el periodo. Ambos formatos muestran la misma "
                "información. Un paciente de la clínica demo lleva la marca "
                "«Datos simulados». Queda registrado en la auditoría como exportación. "
                "Un paciente no asignado o de otra clínica responde `404`."
            ),
            responses={**PATIENT_REPORT_ERRORS, **DOCUMENT_RESPONSES},
            status_code=HTTPStatus.OK,
            openapi_extra={
                ACCESS_EXTENSION: access(PermissionCode.REPORTS_GENERATE_ASSIGNED)
            },
        )
        add(
            "/reports/own",
            create_own_report,
            methods=["POST"],
            operation_id="create_own_report",
            summary="Mi reporte para compartir con mi equipo",
            description=(
                "PDF o HTML con mis datos, para compartir con mi equipo de atención. "
                "Solo contiene datos del paciente autenticado y queda registrado en "
                "la auditoría como exportación."
            ),
            responses={**REPORT_ERRORS, **DOCUMENT_RESPONSES},
            status_code=HTTPStatus.OK,
            openapi_extra={
                ACCESS_EXTENSION: access(PermissionCode.REPORTS_GENERATE_OWN)
            },
        )
        add(
            "/reports/clinic",
            create_clinic_report,
            methods=["POST"],
            operation_id="create_clinic_report",
            summary="Indicadores agregados de la clínica",
            description=(
                "PDF o HTML con pacientes por estado, activación y alertas de la "
                "clínica. No contiene datos clínicos individuales: los conteos "
                "pequeños no se muestran. Queda registrado en la auditoría como "
                "exportación."
            ),
            responses={**REPORT_ERRORS, **DOCUMENT_RESPONSES},
            status_code=HTTPStatus.OK,
            openapi_extra={
                ACCESS_EXTENSION: access(PermissionCode.REPORTS_GENERATE_CLINIC)
            },
        )


def _document(content: bytes, media_type: str, output: ReportOutputFormat) -> Response:
    """The document with ``no-store`` (no cache) and a download file name."""
    name = FILE_NAMES[OUTPUT_FORMATS[output]]
    return Response(
        content=content,
        media_type=media_type,
        headers={**NO_STORE, "Content-Disposition": f'attachment; filename="{name}"'},
    )
