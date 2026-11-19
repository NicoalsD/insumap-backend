"""Patient record endpoints: readings, doses, meals, activities, symptoms, labs."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from http import HTTPStatus
from typing import Annotated, Any, Final, Literal, final
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import AwareDatetime, ValidationError

from insumap.api.paths import API_V1_PREFIX
from insumap.api.routers.auth import ACCESS_EXTENSION
from insumap.api.routers.records_errors import records_error_responses
from insumap.api.routers.records_schemas import (
    ActivityFields,
    ActivityListResponse,
    ActivityResponse,
    AnnulRecordRequest,
    BatchItemResponse,
    BatchResponse,
    CgmImportResponse,
    CorrectRecordRequest,
    GlucoseFields,
    GlucoseReadingListResponse,
    GlucoseReadingResponse,
    InsulinDoseListResponse,
    InsulinDoseResponse,
    InsulinFields,
    LabResultListResponse,
    LabResultResponse,
    MealFields,
    MealListResponse,
    MealResponse,
    RecordActivityRequest,
    RecordFields,
    RecordGlucoseReadingRequest,
    RecordGlucoseReadingsBatchRequest,
    RecordInsulinDoseRequest,
    RecordLabResultRequest,
    RecordMealRequest,
    RecordResponse,
    RecordSymptomRequest,
    SymptomFields,
    SymptomListResponse,
    SymptomResponse,
    TimelineItemResponse,
    TimelineResponse,
)
from insumap.api.tags import ApiTag
from insumap.application.common.actor import Actor
from insumap.application.monitoring.corrections import (
    AnnulRecordInput,
    AnnulRecordUseCase,
    CorrectRecordInput,
    CorrectRecordUseCase,
)
from insumap.application.monitoring.data import RecordData
from insumap.application.monitoring.glucose import (
    BatchItem,
    ImportCgmReadingsInput,
    ImportCgmReadingsUseCase,
    RecordGlucoseReadingInput,
    RecordGlucoseReadingsBatchInput,
    RecordGlucoseReadingsBatchUseCase,
    RecordGlucoseReadingUseCase,
    RecordOutcome,
)
from insumap.application.monitoring.ports import ReadingFilters
from insumap.application.monitoring.queries import (
    ExportFormat,
    ExportTimelineInput,
    ExportTimelineUseCase,
    GetTimelineUseCase,
    ListableKind,
    ListRecordsInput,
    ListRecordsUseCase,
    ListRequest,
    TimelineInput,
)
from insumap.application.monitoring.records import (
    AssignedLabInput,
    RecordActivityUseCase,
    RecordedRecord,
    RecordInput,
    RecordInsulinDoseUseCase,
    RecordMealUseCase,
    RecordOwnLabResultUseCase,
    RecordPatientLabResultUseCase,
    RecordSymptomUseCase,
)
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.monitoring.errors import UnsupportedMediaTypeError
from insumap.domain.monitoring.glucose import GlucoseReading, ReadingSource
from insumap.domain.monitoring.record import ClinicalRecord, RecordType
from insumap.domain.monitoring.records import (
    InsulinDose,
    LabOrigin,
    LabResult,
    Meal,
    PhysicalActivity,
    Symptom,
)
from insumap.domain.monitoring.timeline import TimelineEventType
from insumap.shared.errors import ErrorCode, InsumapError
from insumap.shared.field_limits import FieldLimits

READINGS_PATH: Final = f"{API_V1_PREFIX}/readings"
CSV_MEDIA_TYPE: Final = "text/csv"
PATIENT_PATH: Final = "/patients/{patient_id}"
CONTENT_DISPOSITION: Final = "Content-Disposition"
type ReadingStatusFilter = Literal["ACCEPTED", "FLAGGED", "CORRECTED"]


def permission(code: PermissionCode) -> dict[str, Any]:
    """The ``x-access`` extension of an operation: the permission it requires."""
    return {ACCESS_EXTENSION: f"permission:{code.value}"}


def list_params(
    start: Annotated[
        AwareDatetime | None,
        Query(alias="from", description="Inicio del rango (ISO 8601 con zona)."),
    ] = None,
    end: Annotated[
        AwareDatetime | None,
        Query(alias="to", description="Fin del rango, exclusivo (ISO 8601 con zona)."),
    ] = None,
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=FieldLimits.PAGE_SIZE_MAX,
            description="Elementos por página.",
        ),
    ] = FieldLimits.PAGE_SIZE_DEFAULT,
    cursor: Annotated[
        str | None,
        Query(
            max_length=FieldLimits.CURSOR_MAX_LENGTH,
            description="Cursor opaco de la página anterior (`next_cursor`).",
        ),
    ] = None,
) -> ListRequest:
    """Rango de fechas y paginación por cursor de un listado."""
    return ListRequest(start=start, end=end, limit=limit, cursor=cursor)


Paging = Annotated[ListRequest, Depends(list_params)]


def _validation_error(error: ValidationError) -> InsumapError:
    return InsumapError(
        ErrorCode.VALIDATION_ERROR,
        detail={
            "errors": [
                {
                    "field": ".".join(["body", "correction", *map(str, item["loc"])]),
                    "type": str(item["type"]),
                }
                for item in error.errors()
            ]
        },
    )


CORRECTION_MODELS: Final[dict[RecordType, type[RecordFields]]] = {
    RecordType.READINGS: GlucoseFields,
    RecordType.INSULIN_DOSES: InsulinFields,
    RecordType.MEALS: MealFields,
    RecordType.ACTIVITIES: ActivityFields,
    RecordType.SYMPTOMS: SymptomFields,
}


def parse_correction(record_type: RecordType, raw: dict[str, Any]) -> RecordData:
    """The ``correction`` of the body as the typed values of its record type."""
    try:
        parsed = CORRECTION_MODELS[record_type].model_validate(raw)
    except ValidationError as error:
        raise _validation_error(error) from error
    return parsed.to_data()


@final
class RecordsRouter:
    """Builds the patient record endpoints from their use cases."""

    def __init__(  # noqa: PLR0913 - one use case per endpoint
        self,
        *,
        record_reading: RecordGlucoseReadingUseCase,
        record_batch: RecordGlucoseReadingsBatchUseCase,
        import_cgm: ImportCgmReadingsUseCase,
        record_dose: RecordInsulinDoseUseCase,
        record_meal: RecordMealUseCase,
        record_activity: RecordActivityUseCase,
        record_symptom: RecordSymptomUseCase,
        record_own_lab: RecordOwnLabResultUseCase,
        record_patient_lab: RecordPatientLabResultUseCase,
        correct: CorrectRecordUseCase,
        annul: AnnulRecordUseCase,
        list_records: ListRecordsUseCase,
        timeline: GetTimelineUseCase,
        export_timeline: ExportTimelineUseCase,
        session_actor: Any,
    ) -> None:
        self._record_reading = record_reading
        self._record_batch = record_batch
        self._import_cgm = import_cgm
        self._record_dose = record_dose
        self._record_meal = record_meal
        self._record_activity = record_activity
        self._record_symptom = record_symptom
        self._record_own_lab = record_own_lab
        self._record_patient_lab = record_patient_lab
        self._correct = correct
        self._annul = annul
        self._list = list_records
        self._timeline = timeline
        self._export = export_timeline
        self._actor_guard = session_actor
        self.router = APIRouter(prefix=API_V1_PREFIX, tags=[ApiTag.RECORDS])
        self._add_write_routes()
        self._add_read_routes()
        self._add_correction_routes()
        self._add_timeline_routes()

    # -- helpers ---------------------------------------------------------

    def _created(
        self, response: Response, created: bool, location: str | None = None
    ) -> None:
        response.status_code = HTTPStatus.CREATED if created else HTTPStatus.OK
        if created and location is not None:
            response.headers["Location"] = location

    def _page[R: ClinicalRecord, T](
        self,
        actor: Actor,
        kind: ListableKind,
        request: ListRequest,
        convert: Callable[[R, bool], T],
        *,
        patient_id: UUID | None = None,
        filters: ReadingFilters | None = None,
    ) -> dict[str, Any]:
        page = self._list.execute(
            ListRecordsInput(
                actor=actor,
                kind=kind,
                request=request,
                patient_id=patient_id,
                filters=filters or ReadingFilters(),
            )
        )
        items: Sequence[Any] = page.items
        return {
            "items": [convert(item, actor.clinic_is_demo) for item in items],
            "next_cursor": page.next_cursor,
        }

    # -- writes ----------------------------------------------------------

    def _add_write_routes(self) -> None:
        add = self.router.add_api_route
        guard = Depends(self._actor_guard)

        def post_reading(
            body: RecordGlucoseReadingRequest,
            response: Response,
            actor: Annotated[Actor, guard],
        ) -> GlucoseReadingResponse:
            recorded = self._record_reading.execute(
                RecordGlucoseReadingInput(
                    actor=actor,
                    client_reading_id=body.client_reading_id,
                    data=body.to_data(),
                )
            )
            created = recorded.outcome is RecordOutcome.CREATED
            self._created(
                response, created, f"{READINGS_PATH}/{quote(str(recorded.reading.id))}"
            )
            return GlucoseReadingResponse.of(
                recorded.reading, simulated=actor.clinic_is_demo
            )

        def post_batch(
            body: RecordGlucoseReadingsBatchRequest,
            actor: Annotated[Actor, guard],
        ) -> BatchResponse:
            results = self._record_batch.execute(
                RecordGlucoseReadingsBatchInput(
                    actor=actor,
                    items=[
                        BatchItem(
                            client_reading_id=item.client_reading_id,
                            data=item.to_data(),
                        )
                        for item in body.items
                    ],
                )
            )
            return BatchResponse(items=[BatchItemResponse.of(r) for r in results])

        async def post_cgm_import(
            request: Request, actor: Annotated[Actor, guard]
        ) -> CgmImportResponse:
            media_type = request.headers.get("content-type", "").split(";")[0].strip()
            if media_type.lower() != CSV_MEDIA_TYPE:
                raise UnsupportedMediaTypeError
            content = await request.body()
            result = await run_in_threadpool(
                self._import_cgm.execute,
                ImportCgmReadingsInput(actor=actor, content=content),
            )
            return CgmImportResponse.of(result)

        def post_dose(
            body: RecordInsulinDoseRequest,
            response: Response,
            actor: Annotated[Actor, guard],
        ) -> InsulinDoseResponse:
            recorded = self._record_dose.execute(
                RecordInput(
                    actor=actor,
                    data=body.to_data(),
                    client_record_id=body.client_record_id,
                )
            )
            self._created(response, recorded.created)
            return InsulinDoseResponse.of(
                recorded.record, simulated=actor.clinic_is_demo
            )

        def post_meal(
            body: RecordMealRequest,
            response: Response,
            actor: Annotated[Actor, guard],
        ) -> MealResponse:
            recorded = self._record_meal.execute(
                RecordInput(
                    actor=actor,
                    data=body.to_data(),
                    client_record_id=body.client_record_id,
                )
            )
            self._created(response, recorded.created)
            return MealResponse.of(recorded.record, simulated=actor.clinic_is_demo)

        def post_activity(
            body: RecordActivityRequest,
            response: Response,
            actor: Annotated[Actor, guard],
        ) -> ActivityResponse:
            recorded = self._record_activity.execute(
                RecordInput(
                    actor=actor,
                    data=body.to_data(),
                    client_record_id=body.client_record_id,
                )
            )
            self._created(response, recorded.created)
            return ActivityResponse.of(recorded.record, simulated=actor.clinic_is_demo)

        def post_symptom(
            body: RecordSymptomRequest,
            response: Response,
            actor: Annotated[Actor, guard],
        ) -> SymptomResponse:
            recorded = self._record_symptom.execute(
                RecordInput(
                    actor=actor,
                    data=body.to_data(),
                    client_record_id=body.client_record_id,
                )
            )
            self._created(response, recorded.created)
            return SymptomResponse.of(recorded.record, simulated=actor.clinic_is_demo)

        def post_own_lab(
            body: RecordLabResultRequest,
            response: Response,
            actor: Annotated[Actor, guard],
        ) -> LabResultResponse:
            recorded = self._record_own_lab.execute(
                RecordInput(
                    actor=actor,
                    data=body.to_data(LabOrigin.PATIENT_REPORTED),
                    client_record_id=body.client_record_id,
                )
            )
            self._created(response, recorded.created)
            return LabResultResponse.of(recorded.record, simulated=actor.clinic_is_demo)

        def post_patient_lab(
            patient_id: UUID,
            body: RecordLabResultRequest,
            response: Response,
            actor: Annotated[Actor, guard],
        ) -> LabResultResponse:
            recorded: RecordedRecord[LabResult] = self._record_patient_lab.execute(
                AssignedLabInput(
                    actor=actor,
                    patient_id=patient_id,
                    data=body.to_data(LabOrigin.LAB),
                    client_record_id=body.client_record_id,
                )
            )
            self._created(response, recorded.created)
            return LabResultResponse.of(recorded.record, simulated=actor.clinic_is_demo)

        patient = PermissionCode.PATIENTS_READ_ASSIGNED
        del patient
        add(
            "/readings",
            post_reading,
            methods=["POST"],
            response_model=GlucoseReadingResponse,
            status_code=HTTPStatus.CREATED,
            operation_id="record_glucose_reading",
            summary="Registrar una lectura de glucosa",
            description=(
                "Registra una lectura propia. El valor se guarda siempre en mg/dL. "
                "La cadena de validación bloquea lo imposible (fuera del rango "
                "medible, fecha futura o demasiado vieja) y marca `FLAGGED` lo "
                "sospechoso (duplicado, cambio imposible, posible confusión de "
                "unidad) sin ocultarlo. Repetir el mismo contenido con el mismo "
                "`client_reading_id` responde `200` con la original; con otro "
                "contenido, `409 CONFLICT`. Con `201` trae `Location`. Las alertas "
                "corren después del commit y la respuesta no las espera."
            ),
            responses=records_error_responses(HTTPStatus.CONFLICT),
            openapi_extra=permission(PermissionCode.GLUCOSE_WRITE_OWN),
        )
        add(
            "/readings/batch",
            post_batch,
            methods=["POST"],
            response_model=BatchResponse,
            operation_id="record_glucose_readings_batch",
            summary="Enviar la cola sin conexión de lecturas",
            description=(
                "Hasta 500 lecturas y 512 KiB. Las válidas se guardan aunque otra se "
                "rechace. Cada elemento responde `CREATED`, `DUPLICATE` o `REJECTED` "
                "con el código de la causa, en el mismo orden. Reenviar el lote no "
                "duplica nada. El lote queda en `monitoring.sync_batches`."
            ),
            responses=records_error_responses(HTTPStatus.REQUEST_ENTITY_TOO_LARGE),
            openapi_extra=permission(PermissionCode.GLUCOSE_WRITE_OWN),
        )
        add(
            "/readings/cgm-import",
            post_cgm_import,
            methods=["POST"],
            response_model=CgmImportResponse,
            operation_id="import_cgm_readings",
            summary="Importar la exportación CSV de un sensor",
            description=(
                "Cuerpo crudo `text/csv` (hasta 10 MiB y 100.000 filas), leído por "
                "`CgmCsvAdapter`. Cada fila pasa por la validación en cadena y se "
                "guarda con fuente `CGM`; reimportar el archivo cuenta las filas como "
                "`duplicates`. Un formato desconocido responde `422` con los "
                "formatos admitidos en `detail.supported_formats`."
            ),
            responses=records_error_responses(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE, HTTPStatus.UNSUPPORTED_MEDIA_TYPE
            ),
            openapi_extra=permission(PermissionCode.GLUCOSE_WRITE_OWN),
        )
        for path, handler, model, op, summary, text in (
            (
                "/insulin-doses",
                post_dose,
                InsulinDoseResponse,
                "record_insulin_dose",
                "Registrar una dosis de insulina",
                "Guarda solo lo que el paciente indica: nunca calcula ni sugiere una "
                "dosis. Trae el plan activo, si existe.",
            ),
            (
                "/meals",
                post_meal,
                MealResponse,
                "record_meal",
                "Registrar una comida",
                "Comida con carbohidratos estimados dentro del límite técnico.",
            ),
            (
                "/activities",
                post_activity,
                ActivityResponse,
                "record_activity",
                "Registrar una actividad física",
                "Se usa como contexto en los patrones.",
            ),
            (
                "/symptoms",
                post_symptom,
                SymptomResponse,
                "record_symptoms",
                "Registrar un síntoma",
                "Un síntoma del catálogo de la clínica por registro. Si es de alarma, "
                '`alarm_detected` es `true` y la app muestra "contacta a tu equipo '
                'o a urgencias".',
            ),
            (
                "/lab-results",
                post_own_lab,
                LabResultResponse,
                "record_own_lab_result",
                "Registrar un resultado de laboratorio propio",
                "HbA1c en `%` o `mmol/mol` (se convierte con IFCC-NGSP). El origen "
                "queda `PATIENT_REPORTED`.",
            ),
        ):
            add(
                path,
                handler,
                methods=["POST"],
                response_model=model,
                status_code=HTTPStatus.CREATED,
                operation_id=op,
                summary=summary,
                description=(
                    f"{text} El `client_record_id` es opcional; si se repite con el "
                    "mismo contenido responde `200` con el original."
                ),
                responses=records_error_responses(HTTPStatus.CONFLICT),
                openapi_extra=permission(
                    PermissionCode.LABS_WRITE_OWN
                    if path == "/lab-results"
                    else PermissionCode.RECORDS_WRITE_OWN
                ),
            )
        add(
            f"{PATIENT_PATH}/lab-results",
            post_patient_lab,
            methods=["POST"],
            response_model=LabResultResponse,
            status_code=HTTPStatus.CREATED,
            operation_id="record_patient_lab_result",
            summary="Registrar un resultado de laboratorio de un paciente asignado",
            description=(
                "El médico asignado confirma una HbA1c. El origen queda `LAB` y "
                "reemplaza al autorreporte en las gráficas de tendencia. Un paciente "
                "no asignado o de otra clínica responde `404`."
            ),
            responses=records_error_responses(
                HTTPStatus.NOT_FOUND, HTTPStatus.CONFLICT
            ),
            openapi_extra=permission(PermissionCode.LABS_WRITE_ASSIGNED),
        )

    # -- reads -----------------------------------------------------------

    def _add_read_routes(self) -> None:
        add = self.router.add_api_route
        guard = Depends(self._actor_guard)

        def get_readings(
            paging: Paging,
            actor: Annotated[Actor, guard],
            source: Annotated[ReadingSource | None, Query()] = None,
            status: Annotated[ReadingStatusFilter | None, Query()] = None,
        ) -> GlucoseReadingListResponse:
            return self._readings_page(actor, paging, source, status, None)

        def get_patient_readings(
            patient_id: UUID,
            paging: Paging,
            actor: Annotated[Actor, guard],
            source: Annotated[ReadingSource | None, Query()] = None,
            status: Annotated[ReadingStatusFilter | None, Query()] = None,
        ) -> GlucoseReadingListResponse:
            return self._readings_page(actor, paging, source, status, patient_id)

        def make_list(
            kind: ListableKind, convert: Callable[[Any, bool], Any]
        ) -> Callable[..., dict[str, Any]]:
            def handler(
                paging: Paging, actor: Annotated[Actor, guard]
            ) -> dict[str, Any]:
                return self._page(actor, kind, paging, convert)

            return handler

        def get_patient_labs(
            patient_id: UUID, paging: Paging, actor: Annotated[Actor, guard]
        ) -> LabResultListResponse:
            return LabResultListResponse(
                **self._page(
                    actor,
                    ListableKind.LAB_RESULTS,
                    paging,
                    _lab_item,
                    patient_id=patient_id,
                )
            )

        add(
            "/readings",
            get_readings,
            methods=["GET"],
            response_model=GlucoseReadingListResponse,
            operation_id="list_glucose_readings",
            summary="Listar las lecturas de glucosa propias",
            description=(
                "Más recientes primero, con `from`, `to`, `source`, `status`, `limit` "
                "y `cursor`. Una lectura corregida sigue visible con `status` "
                "`CORRECTED` y la corrección trae `supersedes_id`."
            ),
            responses=records_error_responses(),
            openapi_extra=permission(PermissionCode.GLUCOSE_READ_OWN),
        )
        for path, kind, model, op, noun, convert in (
            (
                "/insulin-doses",
                ListableKind.INSULIN_DOSES,
                InsulinDoseListResponse,
                "list_insulin_doses",
                "las dosis de insulina propias",
                _dose_item,
            ),
            (
                "/meals",
                ListableKind.MEALS,
                MealListResponse,
                "list_meals",
                "las comidas propias",
                _meal_item,
            ),
            (
                "/activities",
                ListableKind.ACTIVITIES,
                ActivityListResponse,
                "list_activities",
                "las actividades propias",
                _activity_item,
            ),
            (
                "/symptoms",
                ListableKind.SYMPTOMS,
                SymptomListResponse,
                "list_symptoms",
                "los síntomas propios",
                _symptom_item,
            ),
            (
                "/lab-results",
                ListableKind.LAB_RESULTS,
                LabResultListResponse,
                "list_lab_results",
                "los resultados de laboratorio propios con su origen",
                _lab_item,
            ),
        ):
            add(
                path,
                make_list(kind, convert),
                methods=["GET"],
                response_model=model,
                operation_id=op,
                summary=f"Listar {noun}",
                description=(
                    "Más recientes primero, con `from`, `to`, `limit` y `cursor`. "
                    "Una fila reemplazada sigue visible como `CORRECTED` o `VOIDED`."
                ),
                responses=records_error_responses(),
                openapi_extra=permission(PermissionCode.RECORDS_READ_OWN),
            )
        add(
            f"{PATIENT_PATH}/readings",
            get_patient_readings,
            methods=["GET"],
            response_model=GlucoseReadingListResponse,
            operation_id="list_patient_glucose_readings",
            summary="Listar las lecturas de un paciente asignado",
            description=(
                "Las mismas lecturas del paciente, para su médico asignado. Cada "
                "petición se audita antes de responder. Un paciente no asignado o "
                "de otra clínica responde `404`."
            ),
            responses=records_error_responses(HTTPStatus.NOT_FOUND),
            openapi_extra=permission(PermissionCode.PATIENTS_READ_ASSIGNED),
        )
        add(
            f"{PATIENT_PATH}/lab-results",
            get_patient_labs,
            methods=["GET"],
            response_model=LabResultListResponse,
            operation_id="list_patient_lab_results",
            summary="Listar los resultados de laboratorio de un paciente asignado",
            description=(
                "Resultados con su origen, para el médico asignado. Se audita. Un "
                "paciente no asignado o de otra clínica responde `404`."
            ),
            responses=records_error_responses(HTTPStatus.NOT_FOUND),
            openapi_extra=permission(PermissionCode.PATIENTS_READ_ASSIGNED),
        )

    def _readings_page(
        self,
        actor: Actor,
        paging: ListRequest,
        source: ReadingSource | None,
        status: str | None,
        patient_id: UUID | None,
    ) -> GlucoseReadingListResponse:
        return GlucoseReadingListResponse(
            **self._page(
                actor,
                ListableKind.READINGS,
                paging,
                _reading_item,
                patient_id=patient_id,
                filters=ReadingFilters(source=source, status=status),
            )
        )

    # -- corrections -----------------------------------------------------

    def _add_correction_routes(self) -> None:
        add = self.router.add_api_route
        guard = Depends(self._actor_guard)

        def post_correction(
            record_type: RecordType,
            record_id: UUID,
            body: CorrectRecordRequest,
            actor: Annotated[Actor, guard],
        ) -> dict[str, Any]:
            record = self._correct.execute(
                CorrectRecordInput(
                    actor=actor,
                    record_type=record_type,
                    record_id=record_id,
                    reason=body.reason,
                    data=parse_correction(record_type, body.correction),
                )
            )
            return _record_body(record, actor.clinic_is_demo)

        def post_annulment(
            record_type: RecordType,
            record_id: UUID,
            body: AnnulRecordRequest,
            actor: Annotated[Actor, guard],
        ) -> dict[str, Any]:
            record = self._annul.execute(
                AnnulRecordInput(
                    actor=actor,
                    record_type=record_type,
                    record_id=record_id,
                    reason=body.reason,
                )
            )
            return _record_body(record, actor.clinic_is_demo)

        add(
            "/records/{record_type}/{record_id}/corrections",
            post_correction,
            methods=["POST"],
            response_model=RecordResponse,
            response_model_exclude_unset=True,
            status_code=HTTPStatus.CREATED,
            operation_id="correct_record",
            summary="Corregir un registro propio",
            description=(
                "`record_type` es `readings`, `insulin-doses`, `meals`, `activities` "
                "o `symptoms`. Crea una fila nueva que apunta al original "
                "(`supersedes_id`); el original queda visible como `CORRECTED`. Una "
                "lectura pasa de nuevo por la validación en cadena. El motivo "
                "lleva de 10 a 500 caracteres. Un registro ajeno responde `404`."
            ),
            responses=records_error_responses(
                HTTPStatus.NOT_FOUND, HTTPStatus.CONFLICT
            ),
            openapi_extra=permission(PermissionCode.RECORDS_CORRECT_OWN),
        )
        add(
            "/records/{record_type}/{record_id}/annulments",
            post_annulment,
            methods=["POST"],
            response_model=RecordResponse,
            response_model_exclude_unset=True,
            status_code=HTTPStatus.CREATED,
            operation_id="annul_record",
            summary="Anular un registro propio",
            description=(
                "Anula sin borrar: agrega una fila de anulación que apunta al "
                "original, que queda visible como `VOIDED`."
            ),
            responses=records_error_responses(
                HTTPStatus.NOT_FOUND, HTTPStatus.CONFLICT
            ),
            openapi_extra=permission(PermissionCode.RECORDS_CORRECT_OWN),
        )

    # -- timeline --------------------------------------------------------

    def _add_timeline_routes(self) -> None:
        add = self.router.add_api_route
        guard = Depends(self._actor_guard)
        types_query = Query(
            max_length=FieldLimits.TIMELINE_EVENT_TYPES_MAX,
            description="Tipos de evento a incluir; sin valor, todos.",
        )

        def timeline_page(
            actor: Actor,
            paging: ListRequest,
            event_types: list[TimelineEventType] | None,
            patient_id: UUID | None,
        ) -> TimelineResponse:
            page = self._timeline.execute(
                TimelineInput(
                    actor=actor,
                    request=paging,
                    patient_id=patient_id,
                    event_types=(
                        frozenset(event_types)
                        if event_types
                        else frozenset(TimelineEventType)
                    ),
                )
            )
            return TimelineResponse(
                items=[TimelineItemResponse.of(item) for item in page.items],
                next_cursor=page.next_cursor,
                simulated=actor.clinic_is_demo,
            )

        def get_timeline(
            paging: Paging,
            actor: Annotated[Actor, guard],
            event_types: Annotated[list[TimelineEventType] | None, types_query] = None,
        ) -> TimelineResponse:
            return timeline_page(actor, paging, event_types, None)

        def get_patient_timeline(
            patient_id: UUID,
            paging: Paging,
            actor: Annotated[Actor, guard],
            event_types: Annotated[list[TimelineEventType] | None, types_query] = None,
        ) -> TimelineResponse:
            return timeline_page(actor, paging, event_types, patient_id)

        def export(
            actor: Actor,
            fmt: ExportFormat,
            start: datetime | None,
            end: datetime | None,
            patient_id: UUID | None,
        ) -> Response:
            exported = self._export.execute(
                ExportTimelineInput(
                    actor=actor,
                    format=fmt,
                    start=start,
                    end=end,
                    patient_id=patient_id,
                )
            )
            return Response(
                content=exported.content,
                media_type=exported.media_type,
                headers={
                    CONTENT_DISPOSITION: f'attachment; filename="{exported.filename}"'
                },
            )

        def get_export(
            actor: Annotated[Actor, guard],
            fmt: Annotated[ExportFormat, Query(alias="format")],
            start: Annotated[AwareDatetime | None, Query(alias="from")] = None,
            end: Annotated[AwareDatetime | None, Query(alias="to")] = None,
        ) -> Response:
            return export(actor, fmt, start, end, None)

        def get_patient_export(
            patient_id: UUID,
            actor: Annotated[Actor, guard],
            fmt: Annotated[ExportFormat, Query(alias="format")],
            start: Annotated[AwareDatetime | None, Query(alias="from")] = None,
            end: Annotated[AwareDatetime | None, Query(alias="to")] = None,
        ) -> Response:
            return export(actor, fmt, start, end, patient_id)

        timeline_text = (
            "Eventos de glucosa, dosis, comidas, actividad y síntomas ordenados por "
            "hora (más recientes primero), con su tipo, estado y los datos propios "
            "de cada uno. Las filas de anulación no se muestran."
        )
        export_text = (
            "Archivo `text/csv` (las celdas que empiezan con `=`, `+`, `-` o `@` "
            "llevan el prefijo `'`) o Bundle FHIR R4 `application/fhir+json`, con "
            "los eventos vigentes del rango. No incluye nombres ni notas. Cuenta "
            "para el límite de exportaciones."
        )
        add(
            "/timeline",
            get_timeline,
            methods=["GET"],
            response_model=TimelineResponse,
            operation_id="get_own_timeline",
            summary="Ver la línea de tiempo propia",
            description=timeline_text,
            responses=records_error_responses(),
            openapi_extra=permission(PermissionCode.RECORDS_READ_OWN),
        )
        add(
            "/timeline/export",
            get_export,
            methods=["GET"],
            response_class=Response,
            operation_id="export_own_timeline",
            summary="Exportar la línea de tiempo propia",
            description=export_text,
            responses=records_error_responses(),
            openapi_extra=permission(PermissionCode.RECORDS_READ_OWN),
        )
        add(
            f"{PATIENT_PATH}/timeline",
            get_patient_timeline,
            methods=["GET"],
            response_model=TimelineResponse,
            operation_id="get_patient_timeline",
            summary="Ver la línea de tiempo de un paciente asignado",
            description=f"{timeline_text} Se audita como `PATIENT_TIMELINE`. Un "
            "paciente no asignado o de otra clínica responde `404`.",
            responses=records_error_responses(HTTPStatus.NOT_FOUND),
            openapi_extra=permission(PermissionCode.PATIENTS_READ_ASSIGNED),
        )
        add(
            f"{PATIENT_PATH}/timeline/export",
            get_patient_export,
            methods=["GET"],
            response_class=Response,
            operation_id="export_patient_timeline",
            summary="Exportar la línea de tiempo de un paciente asignado",
            description=f"{export_text} Se audita con `action = EXPORT`.",
            responses=records_error_responses(HTTPStatus.NOT_FOUND),
            openapi_extra=permission(PermissionCode.PATIENTS_READ_ASSIGNED),
        )


def _reading_item(record: GlucoseReading, simulated: bool) -> GlucoseReadingResponse:
    return GlucoseReadingResponse.of(record, simulated=simulated)


def _dose_item(record: InsulinDose, simulated: bool) -> InsulinDoseResponse:
    return InsulinDoseResponse.of(record, simulated=simulated)


def _meal_item(record: Meal, simulated: bool) -> MealResponse:
    return MealResponse.of(record, simulated=simulated)


def _activity_item(record: PhysicalActivity, simulated: bool) -> ActivityResponse:
    return ActivityResponse.of(record, simulated=simulated)


def _symptom_item(record: Symptom, simulated: bool) -> SymptomResponse:
    return SymptomResponse.of(record, simulated=simulated)


def _lab_item(record: LabResult, simulated: bool) -> LabResultResponse:
    return LabResultResponse.of(record, simulated=simulated)


def _record_body(record: ClinicalRecord, simulated: bool) -> dict[str, Any]:
    """The response of a correction or annulment, by the type of the new row."""
    if isinstance(record, GlucoseReading):
        return GlucoseReadingResponse.of(record, simulated=simulated).model_dump()
    if isinstance(record, InsulinDose):
        return InsulinDoseResponse.of(record, simulated=simulated).model_dump()
    if isinstance(record, Meal):
        return MealResponse.of(record, simulated=simulated).model_dump()
    if isinstance(record, PhysicalActivity):
        return ActivityResponse.of(record, simulated=simulated).model_dump()
    if isinstance(record, Symptom):
        return SymptomResponse.of(record, simulated=simulated).model_dump()
    raise InsumapError(ErrorCode.INTERNAL_ERROR)
