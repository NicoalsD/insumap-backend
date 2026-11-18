# Arquitectura operativa del backend (para agentes)

> Versión operativa de [Arquitectura](../docs/Arquitectura.md). Responde una sola pregunta: dónde va cada cosa y cómo se llama. Si esta guía y la documentación canónica no coinciden, gana la documentación canónica y se corrige esta guía.

## 1. Paquetes y dónde va cada cosa

Paquete base: `insumap`, en `src/insumap/`. Las capas dependen así: `api → application → domain`, e `infrastructure` implementa los puertos de `application`. `shared` es transversal y no depende de nadie. Solo `main.py`, `container.py` y `scheduler.py` conocen todas las capas. `<módulo>` es uno de los subpaquetes de la sección 1.3 de [Arquitectura](../docs/Arquitectura.md#13-módulos-y-dónde-viven) (`identity`, `clinic`, `onboarding`, `care_team`, `access`, `monitoring`, `treatment`, `metrics`, `triage`, `alerts`, `notifications`, `ai`, `dashboard`, `reports`, `messaging`, `audit`).

| Quiero agregar... | Dónde | Nombre | Notas |
|---|---|---|---|
| Un endpoint REST | `insumap/api/<módulo>/router.py` | Clase `*Router` con `build() -> APIRouter` | Recibe sus casos de uso por el constructor. Endpoints `def` (síncronos). Solo valida forma, llama un caso de uso, una fachada o el `CommandBus`, y mapea. Swagger según [`api-documentation.md`](api-documentation.md). |
| Un modelo de entrada HTTP | `insumap/api/<módulo>/schemas.py` | `*Request` | Hereda de `ApiModel` (`api/common`), que fija `extra="forbid"` y tipos estrictos. Límites con `FieldLimits`, nunca literales. |
| Un modelo de salida HTTP | `insumap/api/<módulo>/schemas.py` | `*Response` | Nunca expone un `*Orm` ni una entidad. Glucosa en mg/dL. Si la clínica es demo, incluye `data_source = "SIMULATED"`. |
| Un mapeo HTTP a caso de uso | `insumap/api/<módulo>/mappers.py` | Funciones `to_<nombre>_input()` y `to_<nombre>_response()` | Funciones puras. `*Request` + `Actor` → `*Input`; `*Result` → `*Response`. |
| El actor autenticado | `insumap/api/security/` | `CurrentActor` (`Annotated[Actor, Depends(...)]`) | Único uso de `Depends` junto con la paginación. |
| Un código de estado HTTP para un error | `insumap/api/errors/http_status.py` | Entrada en `ERROR_HTTP_STATUS` | El único lugar que traduce `ErrorCode` a HTTP. |
| Un caso de uso | `insumap/application/<módulo>/<verbo_sustantivo>.py` | `*UseCase` con `execute(input) -> *Result` | Un método público. Colaboradores por constructor (puertos, `UnitOfWorkFactory`, `Clock`, `IdGenerator`). Abre la unidad de trabajo; nunca una sesión. |
| La entrada de un caso de uso | El mismo archivo del caso de uso | `*Input` | `@dataclass(frozen=True, slots=True, kw_only=True)`. Datos ya validados en forma; identificadores como `UUID`. |
| La salida de un caso de uso | El mismo archivo | `*Result` | Dataclass congelada. Lo que la API necesita, sin entidades. |
| Un puerto de salida | `insumap/application/<módulo>/ports.py` | `*Port` (`abc.ABC` con `@abstractmethod`) | Habla en tipos del dominio. Nunca recibe ni devuelve un `*Orm`, un `dict` de cable o un modelo Pydantic. |
| Un comando de decisión | `insumap/application/<módulo>/commands.py` | `*Command` (hereda de `Command`) y `*CommandHandler` | Solo decisiones clínicas o administrativas (P13). El contenedor envuelve cada handler con `AuditingCommandHandler` (P09). |
| Un suscriptor de evento | `insumap/application/<módulo>/subscribers.py` | `<Acción>On<Evento>`, por ejemplo `EvaluateAlertsOnReadingRecorded` | Implementa `EventSubscriber`. Abre su propia unidad de trabajo. Se registra en `container.py`. |
| Un trabajo programado | `insumap/application/jobs/` | `*Job` con `name` y `run(now)` | Idempotente. Una unidad de trabajo por clínica, con el usuario de sistema. |
| Una fachada de lectura | `insumap/application/dashboard/` | `*Facade` | Compone puertos de lectura. Nunca llama a la IA ni escribe, salvo la auditoría de acceso. |
| Una entidad | `insumap/domain/<módulo>/` | Nombre del concepto (`GlucoseReading`, `TreatmentPlan`) | `@dataclass(frozen=True, slots=True, kw_only=True)`, validación en `__post_init__`. Un cambio de estado devuelve una instancia nueva (`dataclasses.replace`) con el evento en `pending_events`. |
| Un value object | `insumap/domain/<módulo>/` | Nombre del concepto (`GlucoseValue`, `InsulinUnits`) | Dataclass congelada con validación en `__post_init__` y constructores con nombre (`GlucoseValue.from_input(value, unit)`). |
| Un evento de dominio | `insumap/domain/<módulo>/events.py` | Concepto en pasado (`GlucoseReadingRecorded`) | Dataclass congelada que hereda de `DomainEvent`, con `event_id` y `occurred_at`. |
| Un error de negocio | `insumap/domain/<módulo>/errors.py` | `*Error` (hereda de `DomainError`) | Lleva un `ErrorCode` y parámetros para el mensaje. Nunca un texto en español. |
| Un código de error | `insumap/shared/errors/error_code.py` | Miembro de `ErrorCode` (`StrEnum`) en `UPPER_SNAKE` | Va con su clave en `messages_es.json` y su estado en `ERROR_HTTP_STATUS`. |
| Una regla o un patrón del dominio | `insumap/domain/<módulo>/` | Nombre del concepto o del rol (`AlertRule`, `TreatmentPlanBuilder`) | Python puro, con la etiqueta `Pattern: Pnn <Name>` y su prueba. Esqueletos en [`design-patterns.md`](design-patterns.md). |
| Un repositorio | `insumap/infrastructure/persistence/repositories/<módulo>.py` | `*Repository` (implementa un `*Port`) | SQLAlchemy 2 con `select()`, `insert()` y parámetros enlazados. Convierte `*Orm` ↔ entidad. Entrega los `pending_events` a la unidad de trabajo. |
| Un modelo ORM | `insumap/infrastructure/persistence/orm/<esquema>.py` | `*Orm` | Mapea una tabla que ya existe en `insumap-database` (`__table_args__ = {"schema": "monitoring"}`). Nunca sale de `infrastructure.persistence`. |
| Un adaptador de un servicio o formato externo | `insumap/infrastructure/<servicio>/` | `*Adapter` | Único lugar que conoce el formato (FHIR, CSV de CGM, JSON de la IA, SMTP, Web Push). Valida al convertir. |
| Un proxy | `insumap/infrastructure/<área>/` | `*Proxy` | Implementa el mismo `*Port` que el sujeto real (`PatientRecordAccessProxy`, `RemoteAiServiceProxy`). |
| Un decorador de un puerto | `insumap/infrastructure/<área>/` | `*Decorator` | Implementa el mismo `*Port` (`PhiAccessAuditDecorator`). El de comandos vive en `application/commands` (`AuditingCommandHandler`). |
| Un respaldo determinista de la IA | `insumap/infrastructure/ai/` | `RuleBasedAiFallbackAdapter` | Implementa `AiServicePort` con reglas del dominio. |
| Un límite técnico | `insumap/shared/field_limits.py` | Atributo `Final[int]` de `FieldLimits` | Única fuente de longitudes, patrones, tamaños de cuerpo y de página. Con su prueba de deriva. |
| Un parámetro clínico o de negocio | Base de datos | Columna en `care.target_profiles`, `alerts.alert_rules`, `care.protocol_templates`, `care.reminder_schedules` o la configuración de la clínica | Nunca una constante. Se lee por un puerto. Lo configura el `CLINIC_ADMIN`. |
| Una variable de entorno | `insumap/shared/config.py` | Campo de `Settings` (pydantic-settings) | Secretos como `SecretStr` sin valor por defecto. Se documenta en `.env.example` y en [`configuration.md`](configuration.md). Solo la leen `container.py`, `api` e `infrastructure`. |
| Un texto para el usuario | `insumap/shared/i18n/messages_es.json` | Clave en inglés con puntos, derivada del código (`GLUCOSE_OUT_OF_RANGE` → `glucose.out_of_range`) | Interpolación con nombres (`{value}`). Nunca datos personales. |
| Una constante física o de unidad | `insumap/shared/units.py` | `MG_DL_PER_MMOL_L` | Única excepción a "sin números en el código". |
| Un permiso | Semilla en `insumap-database` y miembro de `PermissionCode` | `recurso.acción` en minúsculas (`glucose.write_own`) | La asignación rol → permiso vive solo en la BD. Lista en [Actores y permisos](../docs/Actores-y-permisos.md). |
| Una tabla, columna, índice o política RLS | Repositorio `insumap-database` | Migración de Alembic con SQL escrito a mano | Nunca aquí. Después se sube `db-schema.lock`. |
| El armado de dependencias | `insumap/container.py` | `build_container(settings)` | Composition root único. |
| Una prueba de patrón | `tests/unit/patterns/` | `test_<clase>.py` | Sin FastAPI ni BD. Ver [`testing-plan.md`](testing-plan.md). |
| Una prueba unitaria de dominio o de caso de uso | `tests/unit/` | `test_<módulo o clase>.py` | Con dobles de los puertos, `FixedClock` y `SequentialIdGenerator`. |
| Una prueba de API | `tests/api/` | `test_<recurso>_api.py` | `TestClient` con dobles de los casos de uso. |
| Una prueba de integración | `tests/integration/` | `test_<repositorio>.py`, marcador `integration` | Testcontainers con el esquema de la etiqueta de `db-schema.lock`. |

## 2. Convenciones de nombres

| Tipo | Patrón | Ejemplo |
|---|---|---|
| Módulo y paquete | `snake_case` en inglés | `record_glucose_reading.py`, `care_team` |
| Router | `*Router` | `GlucoseReadingRouter` |
| Entrada HTTP | `*Request` | `RecordGlucoseReadingRequest` |
| Salida HTTP | `*Response` | `GlucoseReadingResponse` |
| Mapper | `to_<nombre>_input`, `to_<nombre>_response` | `to_record_glucose_reading_input` |
| Caso de uso | `*UseCase` con `execute()` | `RecordGlucoseReadingUseCase` |
| Entrada y salida de caso de uso | `*Input`, `*Result` | `RecordGlucoseReadingInput`, `RecordGlucoseReadingResult` |
| Puerto | `*Port` | `GlucoseReadingPort`, `AiServicePort` |
| Repositorio | `*Repository` | `GlucoseReadingRepository` |
| Modelo ORM | `*Orm` | `GlucoseReadingOrm` |
| Adaptador | `*Adapter` | `AiServiceClientAdapter`, `FhirPatientAdapter` |
| Proxy | `*Proxy` | `PatientRecordAccessProxy` |
| Decorador | `*Decorator` (o `Auditing*` para handlers) | `PhiAccessAuditDecorator`, `AuditingCommandHandler` |
| Fachada | `*Facade` | `DoctorDashboardFacade` |
| Comando y handler | `*Command`, `*CommandHandler` | `ApproveRecommendationCommand`, `ApproveRecommendationCommandHandler` |
| Evento de dominio | Concepto en pasado | `HypoglycemiaDetected` |
| Suscriptor | `<Acción>On<Evento>` | `StartAlertEscalationOnAlertOpened` |
| Trabajo programado | `*Job` | `ExpireRecommendationsJob` |
| Error de negocio | `*Error` con `ErrorCode` | `RecommendationStateError` |
| Código de error | `UPPER_SNAKE` en inglés | `GLUCOSE_OUT_OF_RANGE` |
| Estado persistido | `*Status` (`StrEnum`) | `RecommendationStatus.APPROVED_WITH_CHANGES` |
| Clase de estado (P18) | `<Estado>State` | `ProposedState`, `HalfOpenState` |
| Rol de patrón | Sufijo del rol GoF | `TreatmentPlanBuilder`, `ClinicIntegrationFactory`, `ReportGeneratorCreator`, `RiskScoringStrategy`, `ClinicalEventVisitor`, `GlucoseWindowIterator`, `TreatmentPlanMemento` |
| Permiso | `recurso.acción` | `patients.read_assigned` |
| Prueba | `test_*.py` con funciones `test_<comportamiento>` en inglés | `test_rejects_duplicate_reading` |

Reglas de idioma: código, identificadores, docstrings, logs y nombres de prueba en inglés. Textos para el usuario en `messages_es.json`. Documentación en español.

## 3. Reglas que siempre aplican

1. **El dominio es Python puro.** `insumap.domain` no importa `fastapi`, `starlette`, `pydantic`, `pydantic_settings`, `sqlalchemy`, `psycopg`, `httpx` ni `apscheduler` (`ARCH-01`), ni otras capas (`ARCH-02`). `uv run lint-imports` lo verifica.
2. **Un router no llama a un repositorio ni a un adaptador.** Solo a un caso de uso, una fachada o el `CommandBus`. Nunca importa `insumap.container` (`ARCH-05`).
3. **Un caso de uso no abre transacciones ni sesiones.** Usa la `UnitOfWork`. Toda escritura y toda lectura de datos clínicos pasan por una.
4. **El contexto de la RLS se fija dentro de la transacción** con `SELECT set_config('app.clinic_id', :clinic_id, true), set_config('app.user_id', :user_id, true)`. Nunca a nivel de conexión. Solo `SqlAlchemyUnitOfWork` lo hace.
5. **La hora solo llega por el `Clock` inyectado.** `datetime.now()`, `datetime.utcnow()`, `datetime.today()`, `date.today()` y `time.time()` están prohibidos fuera de `shared/time/system_clock.py` (`ARCH-09`, `tests/architecture/test_no_wall_clock.py`). Las pruebas usan `FixedClock`.
6. **El dominio no genera identificadores.** Nada de `uuid.uuid4()` en `domain` (`ARCH-12`): llegan por `IdGenerator`.
7. **Nada de SQL armado con texto.** Se usa `select()`, `insert()` y parámetros enlazados. `text()` solo con una cadena literal y `:parámetros`; nunca con f-strings, `%`, `.format()` ni concatenación (`ARCH-11`, ruff `S608`).
8. **Ningún parámetro de negocio como constante.** Metas, umbrales, duraciones, tiempos de escalamiento, vencimientos y plantillas vienen de la BD. Ruff `PLR2004` vigila los números mágicos; suprimirlo exige un motivo escrito.
9. **Nada de `utils.py`, `helpers.py` ni `common.py` con lógica de negocio.** La lógica va en un concepto con nombre (`GlucoseValue`, `PatientAccessPolicy`).
10. **Los eventos se publican después del commit**, nunca dentro de la transacción. La unidad de trabajo es la única que los entrega.
11. **Nunca se borran ni se editan registros clínicos, decisiones ni auditoría.** Una corrección es una fila nueva con `supersedes_id`. Un plan cambia creando una versión nueva (P05), nunca editando una `ACTIVE`.
12. **Los datos clínicos se leen solo por `PatientRecordPort`**, que el contenedor arma como `PhiAccessAuditDecorator(PatientRecordAccessProxy(PatientRecordRepository))`. Una fachada nunca usa el repositorio directamente.
13. **Los errores de negocio son `*Error` con `ErrorCode`.** `HTTPException` solo existe en `api`. Ningún texto en español dentro del código: el mensaje sale de `messages_es.json`.
14. **Tipos estrictos.** `mypy --strict` sin `Any` en puertos, casos de uso ni dominio. `@override` en cada método sobrescrito y `@final` en métodos plantilla y clases que no se extienden.
15. **Las dataclasses congeladas no se mutan.** Nada de `object.__setattr__` para "arreglar" un valor: la normalización va en un constructor con nombre.
16. **`Settings` solo se lee en el arranque, `api` e `infrastructure`.** Nada de `os.getenv` en otro lugar. El dominio y la aplicación reciben valores tipados.
17. **Ningún dato personal ni de salud en los logs.** Solo identificadores (UUID). Nunca cuerpos de petición, glucosas, notas, mensajes, nombres, documentos ni tokens.
18. **Cada patrón es explícito**, con su clase, la etiqueta `Pattern: Pnn <Name>` en el docstring y su prueba en `tests/unit/patterns/`.

## 4. Forma de un caso de uso y de un router

Referencia mínima. Los nombres de los puertos son ilustrativos.

```python
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import final
from uuid import UUID

from insumap.application.common.actor import Actor
from insumap.application.common.ids import IdGenerator
from insumap.application.common.unit_of_work import UnitOfWorkFactory
from insumap.application.monitoring.ports import GlucoseReadingPort, ValidationSettingsPort
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.monitoring.glucose import GlucoseReading, GlucoseValue
from insumap.shared.time import Clock


@dataclass(frozen=True, slots=True, kw_only=True)
class RecordGlucoseReadingInput:
    actor: Actor
    client_reading_id: UUID
    value: Decimal
    unit: str
    measured_at: datetime
    source: str
    context: str


@dataclass(frozen=True, slots=True, kw_only=True)
class RecordGlucoseReadingResult:
    reading_id: UUID
    value_mg_dl: Decimal
    status: str
    issue_codes: tuple[str, ...]
    is_replay: bool


@final
class RecordGlucoseReadingUseCase:
    """Records a glucose reading of the authenticated patient."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        readings: GlucoseReadingPort,
        settings: ValidationSettingsPort,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._uow_factory = uow_factory
        self._readings = readings
        self._settings = settings
        self._ids = ids
        self._clock = clock

    def execute(self, input: RecordGlucoseReadingInput) -> RecordGlucoseReadingResult:
        with self._uow_factory.begin(input.actor) as uow:      # sets app.clinic_id and app.user_id
            input.actor.require(PermissionCode.GLUCOSE_WRITE_OWN)  # permissions come from iam.role_permissions
            patient_id = input.actor.own_patient_id()           # never from the path or the body
            value = GlucoseValue.from_input(input.value, input.unit)
            existing = self._readings.find_by_client_id(patient_id, input.client_reading_id)
            if existing is not None:
                existing.ensure_same_content(value=value, measured_at=input.measured_at)  # else CONFLICT
                return _to_result(existing, is_replay=True)
            reading = GlucoseReading.record(
                reading_id=self._ids.new_id(),
                patient_id=patient_id,
                value=value,
                measured_at=input.measured_at,
                recorded_at=self._clock.now(),
                validation=self._settings.for_patient(patient_id),  # chain of P12 runs inside
            )
            self._readings.add(reading)                         # hands pending_events to the uow
            uow.commit()                                        # events are published after this
        return _to_result(reading, is_replay=False)


def _to_result(reading: GlucoseReading, *, is_replay: bool) -> RecordGlucoseReadingResult:
    return RecordGlucoseReadingResult(
        reading_id=reading.id,
        value_mg_dl=reading.value.mg_dl,
        status=reading.status.value,
        issue_codes=tuple(issue.value for issue in reading.issues),
        is_replay=is_replay,
    )
```

```python
from typing import final

from fastapi import APIRouter, Response, status

from insumap.api.errors.schemas import ErrorResponse
from insumap.api.monitoring.mappers import to_glucose_reading_response, to_record_glucose_reading_input
from insumap.api.monitoring.schemas import GlucoseReadingResponse, RecordGlucoseReadingRequest
from insumap.api.security import CurrentActor
from insumap.application.monitoring.record_glucose_reading import RecordGlucoseReadingUseCase


@final
class GlucoseReadingRouter:
    """Builds the glucose reading endpoints. Use cases arrive from container.py."""

    def __init__(self, record_reading: RecordGlucoseReadingUseCase) -> None:
        self._record_reading = record_reading

    def build(self) -> APIRouter:
        router = APIRouter(tags=["Registros del paciente"])
        record_reading = self._record_reading

        @router.post(
            "/readings",
            status_code=status.HTTP_201_CREATED,
            response_model=GlucoseReadingResponse,
            operation_id="record_glucose_reading",
            summary="Registrar una lectura de glucosa",
            description="Registra una lectura del paciente autenticado. Idempotente por client_reading_id.",
            responses={
                401: {"model": ErrorResponse, "description": "Token ausente, inválido o vencido."},
                403: {"model": ErrorResponse, "description": "El rol no puede registrar lecturas."},
                409: {"model": ErrorResponse, "description": "El identificador ya existe con otro contenido."},
                422: {"model": ErrorResponse, "description": "Valor fuera de rango o campo inválido."},
            },
        )
        def record_glucose_reading(
            body: RecordGlucoseReadingRequest,
            actor: CurrentActor,
            response: Response,
        ) -> GlucoseReadingResponse:
            result = record_reading.execute(to_record_glucose_reading_input(body, actor))
            if result.is_replay:
                response.status_code = status.HTTP_200_OK
            return to_glucose_reading_response(result)

        return router
```

Las descripciones de Swagger en español de este ejemplo son metadatos de la API, que la regla de idioma permite en español. El resto de textos visibles va en `messages_es.json`.

## 5. Checklist para agregar un endpoint

Usar esta lista en orden. Cada punto es un commit lógico (ver [`workflow.md`](workflow.md)); entre paréntesis, un ejemplo de mensaje.

1. **Contrato.** Confirmar método, ruta, permiso y errores en [API](../docs/API.md) y el requisito en [Requerimientos](../docs/Requerimientos.md). Si no existe, preguntar antes de inventarlo.
2. **Permiso.** Verificar que el permiso existe en las semillas de `insumap-database` (`iam.permissions` y `iam.role_permissions`) y en `PermissionCode`. Si falta, va primero allá; aquí solo se agrega el miembro del enum (`feat: agrega el permiso glucose.write_own al catálogo`).
3. **Esquema.** Si hace falta una tabla o columna nueva: PR en `insumap-database`, merge y etiqueta. Luego subir `db-schema.lock` (`build: fija el esquema db-v0.3.0`).
4. **Límites.** Agregar los límites nuevos a `FieldLimits` y cubrirlos en `tests/integration/test_field_limits_drift.py` (`feat: agrega los límites de la nota de glucosa`).
5. **Dominio.** Entidad, value object, regla o patrón en `insumap.domain.<módulo>`, con pruebas unitarias sin FastAPI ni BD. Si es un patrón, con la etiqueta y su prueba en `tests/unit/patterns/` (`feat: agrega la cadena de validación de lecturas de glucosa`).
6. **Errores.** Miembro de `ErrorCode`, clave en `messages_es.json` y estado en `ERROR_HTTP_STATUS`, con la prueba del catálogo (`feat: agrega el error GLUCOSE_OUT_OF_RANGE`).
7. **Puerto.** Declarar en `application.<módulo>.ports` lo que el caso de uso necesita, si no existe.
8. **Caso de uso.** `*UseCase` con su `*Input` y `*Result`, probado con dobles de los puertos y `FixedClock` (`feat: registra lecturas de glucosa con RecordGlucoseReadingUseCase`).
9. **Persistencia.** `*Repository` y `*Orm`, con prueba de integración en Testcontainers que cubra la RLS entre dos clínicas y, si lee datos clínicos, el médico no asignado (`feat: persiste lecturas de glucosa con GlucoseReadingRepository`).
10. **Request, response y mappers.** `*Request` sobre `ApiModel`, `*Response` y funciones de `mappers.py`.
11. **Router y contenedor.** `*Router` con la documentación de Swagger de [`api-documentation.md`](api-documentation.md) y su registro en `container.py` (`feat: expone POST /api/v1/readings`).
12. **Pruebas de API.** `422` de validación, `401`, `403`, `404` de otra clínica o de un paciente no asignado, conflicto si aplica, caso feliz y formato canónico del error (`test: cubre la API de lecturas de glucosa`).
13. **Auditoría y eventos.** Si la acción lee datos clínicos, va por `PatientRecordPort` (P09 y P11). Si es una decisión, va por el `CommandBus` (P13 con P09). Si dispara efectos, el evento (P17) y su suscriptor, con la prueba de que se publica después del commit.
14. **Arquitectura.** `uv run lint-imports` y `uv run pytest tests/architecture`.
15. **Documentación.** Actualizar [API](../docs/API.md), el [Diccionario de datos](../docs/Diccionario-de-datos.md) si cambió el esquema, `.env.example` si hay variables nuevas, la copia de OpenAPI que exige [`testing-plan.md`](testing-plan.md) y los diagramas afectados (`docs: documenta POST /api/v1/readings`).
16. **Cobertura.** Dominio ≥ 90 % y global ≥ 80 %.

## 6. Qué no hacer

- No llamar a `datetime.now()`, `date.today()` ni `time.time()` fuera de `SystemClock`.
- No usar `Depends` para resolver casos de uso, repositorios ni adaptadores; llegan por el constructor del `*Router` desde `container.py`.
- No escribir endpoints `async def` ni puertos `async` (ADR-02 de [Arquitectura](../docs/Arquitectura.md#18-decisiones-de-arquitectura)).
- No devolver un `*Orm`, una entidad ni un `dict` desde un router.
- No lanzar `HTTPException` fuera de `api` ni crear excepciones sin `ErrorCode`.
- No poner textos en español en el código, ni en los mensajes de las excepciones.
- No usar `SELECT *`, concatenar SQL ni pasar f-strings a `text()`.
- No crear tablas, columnas ni índices desde aquí: nada de `metadata.create_all` ni migraciones locales.
- No borrar ni editar lecturas, dosis, decisiones ni auditoría. Usar una corrección (`supersedes_id`) o una versión nueva.
- No leer datos clínicos con un repositorio "directo" saltándose el proxy y la auditoría.
- No fijar `app.clinic_id` con `SET` a nivel de sesión ni usar un rol con `BYPASSRLS`.
- No publicar eventos dentro de la transacción ni usar los eventos de sesión de SQLAlchemy para efectos de negocio.
- No enviar a la IA nombres, documentos, número de historia ni contacto: solo `AiSubject` con `subject_ref`.
- No crear `utils.py` ni `helpers.py` con lógica de negocio.
- No usar `copy.deepcopy` para versionar planes ni `functools.lru_cache` como sustituto de un patrón del catálogo.
- No escribir números clínicos (`70`, `180`, `54`, `250`) en el código, las pruebas de dominio ni los enums: vienen del perfil de metas.

Relacionados: [Arquitectura](../docs/Arquitectura.md), [Patrones de diseño](../docs/Patrones-de-diseno.md), [Patrones para agentes](design-patterns.md), [Configuración](configuration.md), [Plan de pruebas](testing-plan.md), [Documentación de API](api-documentation.md)
