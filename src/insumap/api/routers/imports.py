"""Patient import endpoints (API.md 8.4): preview, confirm and the reads of a batch."""

from datetime import datetime
from http import HTTPStatus
from typing import Annotated, Any, Final, Self, final
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from insumap.api.paths import API_V1_PREFIX
from insumap.api.routers.common import (
    ACCESS_EXTENSION,
    CursorQuery,
    LimitQuery,
    PageResponse,
    access,
    page_request,
)
from insumap.api.routers.records_errors import records_error_responses
from insumap.api.tags import ApiTag
from insumap.application.commands.base import CommandBus
from insumap.application.common.actor import Actor
from insumap.application.onboarding.commands import (
    ConfirmImportCommand,
    PreviewImportCommand,
)
from insumap.application.onboarding.ports import ImportRowRecord
from insumap.application.onboarding.queries import (
    DownloadCsvTemplateUseCase,
    ExportImportErrorsUseCase,
    GetImportBatchUseCase,
    ListImportBatchesInput,
    ListImportBatchesUseCase,
    ListImportRowsInput,
    ListImportRowsUseCase,
)
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.onboarding.batch import ImportBatch, ImportTotals
from insumap.domain.onboarding.vocabulary import (
    RowStatus,
    SourceFormat,
)
from insumap.shared.errors import ErrorCode, InsumapError
from insumap.shared.field_limits import FieldLimits

IMPORTS_PREFIX: Final = f"{API_V1_PREFIX}/imports"
FHIR_MEDIA_TYPE: Final = "application/fhir+json"
CSV_MEDIA_TYPE: Final = "text/csv"
CSV_HEADERS: Final = {"Cache-Control": "no-store"}


class ImportTotalsResponse(BaseModel):
    """Counters of a batch: what the preview found and what the confirmation made."""

    total: int
    valid: int = Field(description="Filas válidas que pueden convertirse en pacientes.")
    warning: int = Field(description="Filas válidas con un dato omitido.")
    error: int = Field(description="Filas rechazadas.")
    skipped: int = Field(
        description="Filas omitidas por duplicado (`SKIPPED_DUPLICATE`)."
    )
    created: int = Field(description="Pacientes creados por la confirmación.")

    @classmethod
    def of(cls, totals: ImportTotals) -> Self:
        return cls(
            total=totals.total,
            valid=totals.valid,
            warning=totals.warning,
            error=totals.error,
            skipped=totals.skipped,
            created=totals.created,
        )


class ImportBatchResponse(BaseModel):
    """One import batch. The file itself is never returned."""

    batch_id: UUID
    source: SourceFormat
    status: str
    created_by: UUID
    created_at: datetime
    finished_at: datetime | None
    simulated: bool = Field(description="Verdadero solo para datos de la clínica demo.")
    totals: ImportTotalsResponse

    @classmethod
    def of(cls, batch: ImportBatch) -> Self:
        return cls(
            batch_id=batch.batch_id,
            source=batch.source_format,
            status=batch.status.value,
            created_by=batch.created_by,
            created_at=batch.created_at,
            finished_at=batch.finished_at,
            simulated=batch.simulated,
            totals=ImportTotalsResponse.of(batch.totals),
        )


class ImportRowResponse(BaseModel):
    """What happened to one row. The row content is not returned."""

    row_number: int
    resource_type: str | None
    status: RowStatus
    issue_codes: list[str]
    patient_id: UUID | None

    @classmethod
    def of(cls, record: ImportRowRecord) -> Self:
        return cls(
            row_number=record.row_number,
            resource_type=record.resource_type,
            status=record.status,
            issue_codes=[issue.value for issue in record.issues],
            patient_id=record.patient_id,
        )


PREVIEW_ERRORS: Final = records_error_responses(
    HTTPStatus.NOT_FOUND,
    HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
    HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
)
READ_ERRORS: Final = records_error_responses(HTTPStatus.NOT_FOUND)
CONFIRM_ERRORS: Final = records_error_responses(
    HTTPStatus.NOT_FOUND, HTTPStatus.CONFLICT
)


def _media_type(request: Request) -> str:
    return request.headers.get("content-type", "").split(";")[0].strip().lower()


@final
class ImportRouter:
    """Builds ``/api/v1/imports`` over the import commands (P13) and its reads.

    The preview and the confirmation run through the command bus, so they run
    in their transaction and leave their audit row (P09). Bodies are read raw
    and their size is limited per route in ``main.py``.

    Pattern: P20 Template Method is behind the commands, not in this router.
    """

    def __init__(
        self,
        *,
        commands: CommandBus,
        list_batches: ListImportBatchesUseCase,
        get_batch: GetImportBatchUseCase,
        list_rows: ListImportRowsUseCase,
        export_errors: ExportImportErrorsUseCase,
        csv_template: DownloadCsvTemplateUseCase,
        staff_actor: Any,
    ) -> None:
        self._commands = commands
        self._list_batches = list_batches
        self._get_batch = get_batch
        self._list_rows = list_rows
        self._export_errors = export_errors
        self._csv_template = csv_template
        self._staff_actor = staff_actor
        self.router = APIRouter(prefix=IMPORTS_PREFIX, tags=[ApiTag.IMPORTS])
        self._add_routes()

    def _add_routes(self) -> None:
        add = self.router.add_api_route
        staff = Depends(self._staff_actor)
        write = {ACCESS_EXTENSION: access(PermissionCode.PATIENTS_IMPORT)}
        read = {ACCESS_EXTENSION: access(PermissionCode.IMPORT_BATCHES_READ)}

        # Declared first: "csv-template" must not be read as a batch id.
        def download_template(actor: Annotated[Actor, staff]) -> PlainTextResponse:
            text = self._csv_template.execute(actor)
            return PlainTextResponse(
                text, media_type=CSV_MEDIA_TYPE, headers=CSV_HEADERS
            )

        async def preview_fhir(
            request: Request, response: Response, actor: Annotated[Actor, staff]
        ) -> ImportBatchResponse:
            return await self._preview_request(
                SourceFormat.FHIR, FHIR_MEDIA_TYPE, request, response, actor
            )

        async def preview_csv(
            request: Request, response: Response, actor: Annotated[Actor, staff]
        ) -> ImportBatchResponse:
            return await self._preview_request(
                SourceFormat.CSV, CSV_MEDIA_TYPE, request, response, actor
            )

        def list_imports(
            actor: Annotated[Actor, staff],
            source: SourceFormat | None = None,
            limit: LimitQuery = FieldLimits.PAGE_SIZE_DEFAULT,
            cursor: CursorQuery = None,
        ) -> PageResponse[ImportBatchResponse]:
            page = self._list_batches.execute(
                ListImportBatchesInput(
                    actor=actor, source=source, page=page_request(limit, cursor)
                )
            )
            return PageResponse(
                items=[ImportBatchResponse.of(batch) for batch in page.items],
                next_cursor=page.next_cursor,
            )

        def get_import(
            batch_id: UUID, actor: Annotated[Actor, staff]
        ) -> ImportBatchResponse:
            return ImportBatchResponse.of(self._get_batch.execute(actor, batch_id))

        def list_import_rows(
            batch_id: UUID,
            actor: Annotated[Actor, staff],
            status: RowStatus | None = None,
            limit: LimitQuery = FieldLimits.PAGE_SIZE_DEFAULT,
            cursor: CursorQuery = None,
        ) -> PageResponse[ImportRowResponse]:
            page = self._list_rows.execute(
                ListImportRowsInput(
                    actor=actor,
                    batch_id=batch_id,
                    status=status,
                    page=page_request(limit, cursor),
                )
            )
            return PageResponse(
                items=[ImportRowResponse.of(record) for record in page.items],
                next_cursor=page.next_cursor,
            )

        def download_errors(
            batch_id: UUID, actor: Annotated[Actor, staff]
        ) -> PlainTextResponse:
            text = self._export_errors.execute(actor, batch_id)
            return PlainTextResponse(
                text, media_type=CSV_MEDIA_TYPE, headers=CSV_HEADERS
            )

        async def confirm(
            batch_id: UUID, actor: Annotated[Actor, staff]
        ) -> ImportBatchResponse:
            batch = await run_in_threadpool(
                self._commands.dispatch,
                ConfirmImportCommand(actor=actor, batch_id=batch_id),
            )
            return ImportBatchResponse.of(batch)

        add(
            "/csv-template",
            download_template,
            methods=["GET"],
            operation_id="download_csv_import_template",
            summary="Descargar la plantilla CSV de pacientes",
            description=(
                "Devuelve el encabezado del CSV de pacientes. `mrn`, `birth_date`, "
                "`full_name`, `document_type` y `document_number` son obligatorias."
            ),
            responses=records_error_responses(),
            openapi_extra=write,
        )
        add(
            "/fhir",
            preview_fhir,
            methods=["POST"],
            status_code=HTTPStatus.CREATED,
            operation_id="create_fhir_import_preview",
            summary="Previsualizar la importación FHIR",
            description=(
                "Recibe un Bundle FHIR R4 (`application/fhir+json`) y valida cada "
                "paciente. No crea cuentas: la confirmación las crea. Una fila "
                "inválida "
                "no impide ver las demás."
            ),
            responses=PREVIEW_ERRORS,
            openapi_extra=write,
        )
        add(
            "/csv",
            preview_csv,
            methods=["POST"],
            status_code=HTTPStatus.CREATED,
            operation_id="create_csv_import_preview",
            summary="Previsualizar la importación CSV",
            description=(
                "Recibe un CSV UTF-8 sin BOM (`text/csv`), separado por coma o punto y "
                "coma. No crea cuentas: la confirmación las crea."
            ),
            responses=PREVIEW_ERRORS,
            openapi_extra=write,
        )
        add(
            "",
            list_imports,
            methods=["GET"],
            operation_id="list_import_batches",
            summary="Listar los lotes de importación",
            description="Lotes de la clínica, del más reciente al más antiguo.",
            responses=records_error_responses(),
            openapi_extra=read,
        )
        add(
            "/{batch_id}",
            get_import,
            methods=["GET"],
            operation_id="get_import_batch",
            summary="Consultar un lote de importación",
            description=(
                "Totales, autor, origen y fecha. Sirve para seguir la confirmación."
            ),
            responses=READ_ERRORS,
            openapi_extra=read,
        )
        add(
            "/{batch_id}/rows",
            list_import_rows,
            methods=["GET"],
            operation_id="list_import_rows",
            summary="Listar el resultado por fila de un lote",
            description=(
                "Estado, códigos de incidencia y paciente creado de cada fila. No "
                "devuelve el contenido de la fila."
            ),
            responses=READ_ERRORS,
            openapi_extra=read,
        )
        add(
            "/{batch_id}/errors",
            download_errors,
            methods=["GET"],
            operation_id="download_import_errors",
            summary="Descargar el reporte de errores de un lote",
            description=(
                "CSV con fila, columna y causa de cada fila rechazada, sin datos "
                "personales. Las celdas que parecen fórmulas llevan un apóstrofo."
            ),
            responses=READ_ERRORS,
            openapi_extra=read,
        )
        add(
            "/{batch_id}/confirm",
            confirm,
            methods=["POST"],
            status_code=HTTPStatus.ACCEPTED,
            operation_id="confirm_import",
            summary="Confirmar un lote de importación",
            description=(
                "Crea los pacientes válidos como `IMPORTED`, sin contraseña ni acceso, "
                "y omite los duplicados por número de historia o documento."
            ),
            responses=CONFIRM_ERRORS,
            openapi_extra=write,
        )

    async def _preview_request(
        self,
        source: SourceFormat,
        media_type: str,
        request: Request,
        response: Response,
        actor: Actor,
    ) -> ImportBatchResponse:
        if _media_type(request) != media_type:
            raise InsumapError(ErrorCode.UNSUPPORTED_MEDIA_TYPE)
        content = await request.body()
        batch = await run_in_threadpool(
            self._commands.dispatch,
            PreviewImportCommand(actor=actor, source_format=source, content=content),
        )
        response.headers["Location"] = f"{IMPORTS_PREFIX}/{batch.batch_id}"
        return ImportBatchResponse.of(batch)
