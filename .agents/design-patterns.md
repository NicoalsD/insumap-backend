# Patrones de diseño del backend (esqueletos en Python 3.13)

> Guía operativa de [Patrones de diseño](../docs/Patrones-de-diseno.md). Responde: cómo se escribe cada patrón P01 a P23 en este repositorio, dónde vive, cómo se prueba y qué no hacer. Si esta guía y el catálogo no coinciden, gana el catálogo y se corrige esta guía. Los paquetes y nombres siguen [`architecture.md`](architecture.md).

## 1. Reglas comunes

1. **Implementación explícita (sección 1.1 del catálogo).** Cada patrón tiene su clase o interfaz aunque Python, FastAPI o SQLAlchemy ofrezcan algo parecido (`lru_cache`, `Depends`, `@decorator`, generadores, `copy.deepcopy`, `singledispatch`, eventos de sesión). Usar el mecanismo del lenguaje **dentro** de la clase del patrón está permitido; reemplazar la clase por el mecanismo, no.
2. **Etiqueta.** La clase principal lleva en su docstring, en inglés, `Pattern: Pnn <Name>` (`grep -rn "Pattern: P11" src`).
3. **Prueba propia.** `tests/unit/patterns/test_<clase_en_snake_case>.py`, sin FastAPI, sin BD y con `FixedClock`. Un patrón sin prueba no se integra.
4. **Tipos.** `mypy --strict`: sin `Any` en puertos, casos de uso ni dominio. `@final` en clases hoja y en los métodos plantilla; `@override` en cada método sobrescrito (`typing.override`, Python 3.12 o superior).
5. **Interfaces.** `abc.ABC` con `@abstractmethod` para los `*Port` y los participantes de un patrón. `typing.Protocol` solo para interfaces mínimas como `Clock`.
6. **Dominio puro.** Las entidades y los patrones de `insumap.domain` son `@dataclass(frozen=True, slots=True, kw_only=True)`, sin `pydantic`, `sqlalchemy`, `httpx` ni `fastapi` (`ARCH-01`). Un cambio devuelve una instancia nueva con `dataclasses.replace`.
7. **Hora e identificadores por argumento.** Nada de `datetime.now()` ni `uuid.uuid4()` en el dominio (`ARCH-09`, `ARCH-12`): llegan por `Clock` e `IdGenerator`.
8. **Errores.** Un `*Error` que hereda de `InsumapError` (`insumap.shared.errors`) con un `ErrorCode`. El texto en español vive en `messages_es.json`, nunca en el código. Los códigos que usan los esqueletos y todavía no existen están en la sección 2.3.
9. **Nada de valores clínicos ni de negocio** en el código: los umbrales, las duraciones y los límites de dosis llegan como parámetros leídos de la BD por un puerto.
10. **Un patrón se ensambla solo en `container.py`.** Los esqueletos de la sección 4 muestran el armado.

Orden de lectura: la sección 2 define los tipos de apoyo que los esqueletos usan sin repetirlos; la sección 3 recorre P01 a P23; la sección 4 muestra el armado en `container.py`; la sección 5 es la lista de verificación.

## 2. Tipos de apoyo compartidos

Los esqueletos dan por existentes estos tipos. Los que figuran como "existe" ya están en `src/insumap/`; los demás los crea la fase que los necesita, con estas formas. En todos los archivos reales se usa `from __future__ import annotations` (como en el código existente); aquí se omite en cada bloque para no repetirlo.

### 2.1 Tipos transversales

```python
# insumap/domain/common/events.py (propuesto, architecture.md sección 1)
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True, kw_only=True)
class DomainEvent:
    event_id: UUID
    occurred_at: datetime
```

```python
# insumap/application/common/ids.py (propuesto)
from abc import ABC, abstractmethod
from uuid import UUID


class IdGenerator(ABC):
    """Port that creates identifiers. Production uses UUIDv7 (infrastructure.ids)."""

    @abstractmethod
    def new_id(self) -> UUID: ...
```

```python
# insumap/domain/identity/permissions.py (propuesto; un miembro por permiso de Actores-y-permisos.md)
from enum import StrEnum


class PermissionCode(StrEnum):
    PATIENTS_READ_ASSIGNED = "patients.read_assigned"
    PATIENTS_READ_ROSTER = "patients.read_roster"
    RECOMMENDATIONS_DECIDE = "recommendations.decide"
    CREDENTIALS_ISSUE = "credentials.issue"
    # ... el resto del catálogo
```

```python
# insumap/application/common/actor.py (propuesto; la forma completa está en security.md sección 10)
from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID

from insumap.domain.identity.permissions import PermissionCode
from insumap.shared.errors import ErrorCode, InsumapError


class Role(StrEnum):
    PLATFORM_ADMIN = "PLATFORM_ADMIN"
    CLINIC_ADMIN = "CLINIC_ADMIN"
    DOCTOR = "DOCTOR"
    PATIENT = "PATIENT"


@dataclass(frozen=True, slots=True, kw_only=True)
class Actor:
    user_id: UUID
    clinic_id: UUID | None
    role: Role
    patient_id: UUID | None = None
    permissions: frozenset[PermissionCode] = field(default=frozenset())

    def require(self, permission: PermissionCode) -> None:
        """Deny by default: the permission must have been granted."""
        if permission not in self.permissions:
            raise InsumapError(ErrorCode.FORBIDDEN)
```

```python
# tests/factories/ids.py (propuesto; FixedClock ya existe en tests/support/fixed_clock.py)
from uuid import UUID

from insumap.application.common.ids import IdGenerator


class SequentialIdGenerator(IdGenerator):
    """Deterministic ids for tests: 00000000-...-000000000001, then 2, 3..."""

    def __init__(self) -> None:
        self._last = 0

    def new_id(self) -> UUID:
        self._last += 1
        return UUID(int=self._last)
```

### 2.2 Plan de tratamiento (lo comparten P04, P05 y P16)

`TreatmentPlan` es una sola clase: P05 le da `copy_for_new_version()` y P16 le da `create_memento()` y `from_memento()`. P04 la construye. Los límites del protocolo (`ProtocolLimits`) vienen de la BD, nunca del código.

```python
# insumap/domain/treatment/plan.py (propuesto)
import json
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Self
from uuid import UUID

from insumap.domain.common.events import DomainEvent


class PlanStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


@dataclass(frozen=True, slots=True, kw_only=True)
class PlanItem:
    item_id: UUID
    insulin_code: str
    units: Decimal
    at_minute_of_day: int


@dataclass(frozen=True, slots=True, kw_only=True)
class ProtocolLimits:
    """Read from the protocol in the database, never written in code."""

    max_units_per_dose: Decimal
    min_gap_minutes: int


@dataclass(frozen=True, slots=True, kw_only=True)
class TreatmentPlanMemento:
    """Pattern: P16 Memento. Primitive snapshot, JSON text ready for jsonb."""

    schema_version: int
    taken_at: datetime
    payload: str


@dataclass(frozen=True, slots=True, kw_only=True)
class TreatmentPlan:
    plan_id: UUID
    patient_id: UUID
    version: int
    status: PlanStatus
    target_profile_id: UUID
    items: tuple[PlanItem, ...]
    created_at: datetime
    template_id: UUID | None = None
    based_on_plan_id: UUID | None = None
    pending_events: tuple[DomainEvent, ...] = field(default=())

    def copy_for_new_version(
        self, *, new_plan_id: UUID, item_ids: tuple[UUID, ...], created_at: datetime
    ) -> Self:
        """P05: deep copy as DRAFT, next version, new ids, no pending events."""
        if len(item_ids) != len(self.items):
            raise ValueError("one new id per item is required")
        copied = tuple(
            replace(item, item_id=new_id)
            for item, new_id in zip(self.items, item_ids, strict=True)
        )
        return replace(
            self,
            plan_id=new_plan_id,
            version=self.version + 1,
            status=PlanStatus.DRAFT,
            items=copied,
            created_at=created_at,
            based_on_plan_id=self.plan_id,
            pending_events=(),
        )

    def create_memento(self, taken_at: datetime) -> TreatmentPlanMemento:
        """P16: snapshot with primitive data only."""
        data = {
            "plan_id": str(self.plan_id),
            "patient_id": str(self.patient_id),
            "version": self.version,
            "status": self.status.value,
            "target_profile_id": str(self.target_profile_id),
            "created_at": self.created_at.isoformat(),
            "template_id": str(self.template_id) if self.template_id else None,
            "based_on_plan_id": (
                str(self.based_on_plan_id) if self.based_on_plan_id else None
            ),
            "items": [
                [str(i.item_id), i.insulin_code, str(i.units), i.at_minute_of_day]
                for i in self.items
            ],
        }
        return TreatmentPlanMemento(
            schema_version=1, taken_at=taken_at, payload=json.dumps(data, sort_keys=True)
        )

    @classmethod
    def from_memento(cls, memento: TreatmentPlanMemento) -> Self:
        data = json.loads(memento.payload)
        return cls(
            plan_id=UUID(data["plan_id"]),
            patient_id=UUID(data["patient_id"]),
            version=int(data["version"]),
            status=PlanStatus(data["status"]),
            target_profile_id=UUID(data["target_profile_id"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            template_id=UUID(data["template_id"]) if data["template_id"] else None,
            based_on_plan_id=(
                UUID(data["based_on_plan_id"]) if data["based_on_plan_id"] else None
            ),
            items=tuple(
                PlanItem(
                    item_id=UUID(i[0]),
                    insulin_code=i[1],
                    units=Decimal(i[2]),
                    at_minute_of_day=int(i[3]),
                )
                for i in data["items"]
            ),
        )
```

### 2.3 Códigos de error que suponen los esqueletos

Hoy `ErrorCode` tiene `VALIDATION_ERROR`, `NOT_FOUND`, `UNAUTHENTICATED`, `FORBIDDEN`, `CONFLICT`, `RATE_LIMITED`, `PAYLOAD_TOO_LARGE` e `INTERNAL_ERROR`. Los esqueletos suponen estos miembros nuevos; cada uno se agrega con su clave en `messages_es.json`, su estado en `STATUS_BY_CODE` y su prueba de catálogo (`architecture.md`, sección 5, punto 6):

| Código | HTTP | Lo usa |
|---|---|---|
| `TREATMENT_PLAN_INVALID` | 422 | P04 |
| `GLUCOSE_OUT_OF_RANGE`, `READING_IN_FUTURE` | 422 | P12 |
| `INVALID_STATE_TRANSITION` | 409 | P18 |
| `REASON_REQUIRED` | 422 | P13 |
| `COMMAND_NOT_HANDLED` | 500 | P13 (error de armado) |
| `ALERT_RULE_SYNTAX_ERROR` | 422 | P22 |
| `UNKNOWN_INSULIN_PRODUCT` | 500 | P23 |
| `AI_SERVICE_TIMEOUT`, `AI_SERVICE_UNAVAILABLE` | 503 | P06, P11 (se traducen a respaldo y no llegan al cliente) |

### 2.4 Ventana de glucosa (la comparten P08 y P14)

```python
# insumap/domain/metrics/window.py (propuesto)
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True, kw_only=True)
class GlucosePoint:
    at: datetime
    mg_dl: Decimal


@dataclass(frozen=True, slots=True, kw_only=True)
class GlucoseWindow:
    start: datetime
    end: datetime
    points: tuple[GlucosePoint, ...]
    has_enough_data: bool
```

## 3. Catálogo de esqueletos

### P01. Singleton: `SystemClock`

- **Dónde vive:** `insumap/shared/time.py` (ya existe). El puerto es `Clock` (`typing.Protocol`); en pruebas, `FixedClock` de `tests/support/fixed_clock.py`.
- **Cómo se usa:** `container.py` llama una sola vez a `SystemClock.instance()` y lo inyecta como `Clock`. Nadie más construye ni importa `SystemClock`.

```python
# insumap/shared/time.py (código real, resumido)
import threading
from datetime import UTC, datetime
from typing import ClassVar, Protocol, final, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime: ...


@final
class SystemClock:
    """The only place in the backend that reads the system clock. Always UTC.

    Pattern: P01 Singleton
    """

    _instance: ClassVar[SystemClock | None] = None
    _lock: ClassVar[threading.Lock] = threading.Lock()
    _construction_token: ClassVar[object] = object()

    def __init__(self, construction_token: object = None) -> None:
        if construction_token is not SystemClock._construction_token:
            raise TypeError("SystemClock is a singleton: use SystemClock.instance()")

    @classmethod
    def instance(cls) -> SystemClock:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(cls._construction_token)
        return cls._instance

    def now(self) -> datetime:
        return datetime.now(UTC)
```

**Prueba** (`tests/unit/patterns/test_system_clock.py`; hoy el archivo está en `tests/unit/shared/test_system_clock.py`, ver sección 6): misma instancia, `datetime` con zona UTC, construcción directa rechazada, `isinstance(..., Clock)`, `FixedClock` rechaza instantes sin zona. Una prueba con hilos (`ThreadPoolExecutor`) comprueba que 16 llamadas simultáneas a `instance()` devuelven el mismo objeto.

**Antipatrones**
- Un global de módulo (`clock = SystemClock()`) o `datetime.now(UTC)` dentro de un caso de uso: lo vigila `tests/architecture/test_no_wall_clock.py`.
- `@functools.cache` sobre una función que devuelve el reloj.
- Importar `SystemClock` desde `domain` o `application`: ahí solo existe `Clock`.

### P02. Factory Method: `ReportGeneratorCreator`

- **Dónde vive:** `insumap/infrastructure/reports/creators.py`. El producto es `ReportGenerator` (P20) y la fábrica de piezas es `ReportDocumentFactory` (P03). El caso de uso llega por `ReportRenderingPort`, implementado por `ReportRenderingAdapter`.
- **Idea:** el método fábrica `create_generator()` es abstracto y protegido; la operación pública `generator_for()` es la que usa el adaptador. Cada creador concreto decide la clase.

```python
from abc import ABC, abstractmethod
from typing import final, override

from insumap.infrastructure.reports.generators import (
    ClinicReport,
    PatientReport,
    PreVisitSummary,
    ReportDocumentFactory,
    ReportGenerator,
)


class ReportGeneratorCreator(ABC):
    """Creator of report generators.

    Pattern: P02 Factory Method
    """

    @final
    def generator_for(self, documents: ReportDocumentFactory) -> ReportGenerator:
        return self.create_generator(documents)

    @abstractmethod
    def create_generator(self, documents: ReportDocumentFactory) -> ReportGenerator:
        """Factory method: each creator returns its own generator class."""


@final
class PatientReportCreator(ReportGeneratorCreator):
    @override
    def create_generator(self, documents: ReportDocumentFactory) -> ReportGenerator:
        return PatientReport(documents)


@final
class ClinicReportCreator(ReportGeneratorCreator):
    @override
    def create_generator(self, documents: ReportDocumentFactory) -> ReportGenerator:
        return ClinicReport(documents)


@final
class PreVisitSummaryCreator(ReportGeneratorCreator):
    @override
    def create_generator(self, documents: ReportDocumentFactory) -> ReportGenerator:
        return PreVisitSummary(documents)
```

**Prueba** (`test_report_generator_creator.py`): cada creador devuelve la clase esperada (`isinstance`) y `generator_for()` delega en `create_generator()` una sola vez (subclase de prueba que cuenta llamadas). Agregar un tipo de reporte agrega un creador, sin tocar el adaptador.

**Antipatrones**
- Un `dict[str, Callable[..., ReportGenerator]]` o un `if report_type == ...` dentro de `ReportRenderingAdapter`.
- Que el creador conozca el formato PDF o HTML: eso lo decide la fábrica abstracta (P03).
- Que `generator_for()` sea sobrescribible: lleva `@final`.

### P03. Abstract Factory: `ClinicIntegrationFactory` y `ReportDocumentFactory`

- **Dónde vive:** la interfaz `ClinicIntegrationFactory` y los productos abstractos en `insumap/application/onboarding/integration.py`; las familias en `insumap/infrastructure/integration/fhir/` y `.../csv/`. `ReportDocumentFactory` y sus familias, en `insumap/infrastructure/reports/documents.py`.
- **Regla:** una corrida de importación pide su familia **una sola vez** y usa las tres piezas de esa familia. Mezclar piezas de familias distintas debe ser imposible: cada producto declara su `source_format` y la prueba verifica que coincidan.

```python
# insumap/application/onboarding/integration.py
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum


class SourceFormat(StrEnum):
    FHIR = "FHIR"
    CSV = "CSV"


type SourceRow = Mapping[str, object]


@dataclass(frozen=True, slots=True, kw_only=True)
class PatientImportCandidate:
    mrn: str
    birth_date: str
    given_name: str
    family_name: str


class PatientSourceParser(ABC):
    source_format: SourceFormat

    @abstractmethod
    def parse(self, raw: bytes) -> Sequence[SourceRow]: ...


class PatientRecordMapper(ABC):
    source_format: SourceFormat

    @abstractmethod
    def to_candidate(self, row: SourceRow) -> PatientImportCandidate: ...


class ImportValidator(ABC):
    source_format: SourceFormat

    @abstractmethod
    def validate(self, candidate: PatientImportCandidate) -> tuple[str, ...]:
        """Return issue codes; an empty tuple means the row is valid."""


class ClinicIntegrationFactory(ABC):
    """Abstract factory of one import family.

    Pattern: P03 Abstract Factory
    """

    @property
    @abstractmethod
    def source_format(self) -> SourceFormat: ...

    @abstractmethod
    def create_parser(self) -> PatientSourceParser: ...

    @abstractmethod
    def create_mapper(self) -> PatientRecordMapper: ...

    @abstractmethod
    def create_validator(self) -> ImportValidator: ...
```

```python
# insumap/infrastructure/integration/fhir/factory.py (la familia CSV es análoga)
import json
from collections.abc import Sequence
from typing import final, override

from insumap.application.onboarding.integration import (
    ClinicIntegrationFactory,
    ImportValidator,
    PatientImportCandidate,
    PatientRecordMapper,
    PatientSourceParser,
    SourceFormat,
    SourceRow,
)
from insumap.infrastructure.integration.fhir.adapter import FhirPatientAdapter  # P06


@final
class FhirBundleParser(PatientSourceParser):
    source_format = SourceFormat.FHIR

    @override
    def parse(self, raw: bytes) -> Sequence[SourceRow]:
        bundle = json.loads(raw)
        return [entry["resource"] for entry in bundle.get("entry", [])]


@final
class FhirImportValidator(ImportValidator):
    source_format = SourceFormat.FHIR

    @override
    def validate(self, candidate: PatientImportCandidate) -> tuple[str, ...]:
        return () if candidate.mrn else ("MRN_MISSING",)


@final
class FhirIntegrationFactory(ClinicIntegrationFactory):
    @property
    @override
    def source_format(self) -> SourceFormat:
        return SourceFormat.FHIR

    @override
    def create_parser(self) -> PatientSourceParser:
        return FhirBundleParser()

    @override
    def create_mapper(self) -> PatientRecordMapper:
        return FhirPatientAdapter()

    @override
    def create_validator(self) -> ImportValidator:
        return FhirImportValidator()
```

`ReportDocumentFactory` sigue la misma forma: una interfaz con `create_header()` y `create_footer()` (más `output_format`), y las familias `PdfReportDocumentFactory` y `HtmlReportDocumentFactory`. El pie siempre recibe `is_demo` para la marca "Datos simulados" y el aviso de que no es un dispositivo médico; la familia HTML escapa todo el contenido (`html.escape`).

```python
# insumap/infrastructure/reports/documents.py
import html
from abc import ABC, abstractmethod
from typing import final, override


class ReportPiece(ABC):
    @abstractmethod
    def render(self) -> str: ...


class ReportDocumentFactory(ABC):
    """Abstract factory of report pieces (PDF or HTML family).

    Pattern: P03 Abstract Factory
    """

    @property
    @abstractmethod
    def output_format(self) -> str: ...

    @abstractmethod
    def create_header(self, title: str) -> ReportPiece: ...

    @abstractmethod
    def create_footer(self, *, is_demo: bool, disclaimer: str, demo_mark: str) -> ReportPiece: ...


@final
class HtmlPiece(ReportPiece):
    def __init__(self, tag: str, text: str) -> None:
        self._tag = tag
        self._text = text

    @override
    def render(self) -> str:
        return f"<{self._tag}>{html.escape(self._text)}</{self._tag}>"


@final
class HtmlReportDocumentFactory(ReportDocumentFactory):
    @property
    @override
    def output_format(self) -> str:
        return "HTML"

    @override
    def create_header(self, title: str) -> ReportPiece:
        return HtmlPiece("h1", title)

    @override
    def create_footer(self, *, is_demo: bool, disclaimer: str, demo_mark: str) -> ReportPiece:
        return HtmlPiece("footer", f"{demo_mark} {disclaimer}" if is_demo else disclaimer)
```

**Prueba** (`test_clinic_integration_factory.py` y `test_report_document_factory.py`): cada familia produce piezas con el mismo `source_format`; un Bundle FHIR de `tests/fixtures/` pasa por las tres piezas FHIR; el HTML escapa `<script>`; el pie lleva la marca solo si `is_demo`. Los textos "Datos simulados" y el aviso llegan de `messages_es.json`, no del esqueleto.

**Antipatrones**
- Registrar `parser`, `mapper` y `validator` como dependencias sueltas en `container.py` o elegir cada pieza con `if source_format == ...`.
- Una fábrica que devuelve piezas de otra familia "por comodidad".
- Instanciar un producto concreto (`FhirBundleParser()`) fuera de su fábrica.

### P04. Builder: `TreatmentPlanBuilder`

- **Dónde vive:** `insumap/domain/treatment/builder.py`. La entidad `TreatmentPlan` está en la sección 2.2.
- **Regla:** `build()` valida **todas** las invariantes y devuelve la lista completa de las incumplidas; un plan inválido no existe como objeto. Los límites (`ProtocolLimits`) llegan de la BD, ya resueltos por el caso de uso (Director).

```python
from datetime import datetime
from decimal import Decimal
from itertools import pairwise
from typing import Self, final
from uuid import UUID

from insumap.application.common.ids import IdGenerator
from insumap.domain.treatment.plan import (
    PlanItem,
    PlanStatus,
    ProtocolLimits,
    TreatmentPlan,
)
from insumap.shared.errors import ErrorCode, InsumapError
from insumap.shared.time import Clock


@final
class TreatmentPlanInvariantError(InsumapError):
    def __init__(self, violations: tuple[str, ...]) -> None:
        super().__init__(
            ErrorCode.TREATMENT_PLAN_INVALID, detail={"violations": list(violations)}
        )
        self.violations = violations


@final
class TreatmentPlanBuilder:
    """Builds a valid DRAFT plan; ``build()`` checks every invariant.

    Pattern: P04 Builder
    """

    def __init__(self, *, limits: ProtocolLimits, ids: IdGenerator, clock: Clock) -> None:
        self._limits = limits
        self._ids = ids
        self._clock = clock
        self._patient_id: UUID | None = None
        self._profile_id: UUID | None = None
        self._items: list[tuple[str, Decimal, int]] = []

    def for_patient(self, patient_id: UUID) -> Self:
        self._patient_id = patient_id
        return self

    def with_target_profile(self, profile_id: UUID) -> Self:
        self._profile_id = profile_id
        return self

    def add_item(self, *, insulin_code: str, units: Decimal, at_minute_of_day: int) -> Self:
        self._items.append((insulin_code, units, at_minute_of_day))
        return self

    def build(self) -> TreatmentPlan:
        violations = self._violations()
        if violations or self._patient_id is None or self._profile_id is None:
            raise TreatmentPlanInvariantError(violations)
        now: datetime = self._clock.now()
        return TreatmentPlan(
            plan_id=self._ids.new_id(),
            patient_id=self._patient_id,
            version=1,
            status=PlanStatus.DRAFT,
            target_profile_id=self._profile_id,
            items=tuple(
                PlanItem(
                    item_id=self._ids.new_id(),
                    insulin_code=code,
                    units=units,
                    at_minute_of_day=minute,
                )
                for code, units, minute in self._items
            ),
            created_at=now,
        )

    def _violations(self) -> tuple[str, ...]:
        found: list[str] = []
        if self._patient_id is None:
            found.append("PATIENT_REQUIRED")
        if self._profile_id is None:
            found.append("TARGET_PROFILE_REQUIRED")
        if any(units > self._limits.max_units_per_dose for _, units, _ in self._items):
            found.append("DOSE_ABOVE_PROTOCOL_LIMIT")
        minutes = sorted(minute for _, _, minute in self._items)
        if any(b - a < self._limits.min_gap_minutes for a, b in pairwise(minutes)):
            found.append("SCHEDULE_OVERLAP")
        return tuple(found)
```

**Prueba** (`test_treatment_plan_builder.py`): rechaza dosis sobre el límite, horarios solapados y campos obligatorios ausentes; devuelve **todas** las invariantes juntas; el plan nace en `DRAFT`, versión 1, con ids de `SequentialIdGenerator`. Los límites de la prueba son los de un `ProtocolLimits` de prueba, no los del protocolo real.

**Antipatrones**
- Un constructor con muchos opcionales, o un modelo Pydantic con validadores dentro del dominio (`ARCH-01`).
- Validar en `add_item()` y detener en el primer error: el médico quiere ver todas las invariantes.
- Escribir el límite de dosis como constante.
- Que `build()` lea la hora con `datetime.now()`.

### P05. Prototype: `ProtocolTemplate.clone_for_patient()` y `TreatmentPlan.copy_for_new_version()`

- **Dónde vive:** `insumap/domain/treatment/`. `copy_for_new_version()` está en `TreatmentPlan` (sección 2.2); `ProtocolTemplate` va en `template.py`.
- **Regla:** la copia **no** es `copy.deepcopy` ni `copy.replace`: nace en `DRAFT`, con versión siguiente, ids nuevos para el plan y para cada ítem (que llegan por argumento), referencia al origen y sin eventos pendientes. El origen no cambia.

```python
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from insumap.domain.treatment.plan import (
    PlanItem,
    PlanStatus,
    TreatmentPlan,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ProtocolTemplate:
    """Prototype of the content of a plan.

    Pattern: P05 Prototype
    """

    template_id: UUID
    target_profile_id: UUID
    items: tuple[PlanItem, ...]

    def clone_for_patient(
        self,
        *,
        patient_id: UUID,
        new_plan_id: UUID,
        item_ids: tuple[UUID, ...],
        created_at: datetime,
    ) -> TreatmentPlan:
        if len(item_ids) != len(self.items):
            raise ValueError("one new id per item is required")
        return TreatmentPlan(
            plan_id=new_plan_id,
            patient_id=patient_id,
            version=1,
            status=PlanStatus.DRAFT,
            target_profile_id=self.target_profile_id,
            items=tuple(
                PlanItem(
                    item_id=new_id,
                    insulin_code=item.insulin_code,
                    units=item.units,
                    at_minute_of_day=item.at_minute_of_day,
                )
                for item, new_id in zip(self.items, item_ids, strict=True)
            ),
            created_at=created_at,
            template_id=self.template_id,
        )
```

**Prueba** (`test_protocol_template.py` y `test_treatment_plan_prototype.py`): el plan nace en `DRAFT` con `template_id`; la plantilla queda igual; los ítems no comparten `item_id` con los de la plantilla; la nueva versión de un plan `ACTIVE` tiene `version + 1`, `based_on_plan_id` correcto, `pending_events == ()` y el original sigue `ACTIVE`.

**Antipatrones**
- `copy.deepcopy(plan)`, `copy.replace(plan, ...)` o `__deepcopy__` que esconde las reglas.
- Generar los ids dentro del método (`uuid4()`): llegan por argumento.
- Editar una versión `ACTIVE` en lugar de copiarla.

### P06. Adapter: `FhirPatientAdapter`, `CgmCsvAdapter`, `AiServiceClientAdapter`

- **Dónde vive:** `insumap/infrastructure/integration/fhir/`, `insumap/infrastructure/integration/cgm/` e `insumap/infrastructure/ai/`. Cada adaptador es el único lugar que conoce su formato y valida al convertir.

```python
# insumap/infrastructure/integration/fhir/adapter.py
from typing import final, override

from insumap.application.onboarding.integration import (
    PatientImportCandidate,
    PatientRecordMapper,
    SourceFormat,
    SourceRow,
)
from insumap.shared.errors import ErrorCode, InsumapError


@final
class FhirPatientAdapter(PatientRecordMapper):
    """Adapts a FHIR R4 ``Patient`` to the import candidate.

    Pattern: P06 Adapter
    """

    source_format = SourceFormat.FHIR

    @override
    def to_candidate(self, row: SourceRow) -> PatientImportCandidate:
        if row.get("resourceType") != "Patient":
            raise _row_error("UNSUPPORTED_RESOURCE")
        mrn = _mrn(row)
        birth_date = row.get("birthDate")
        if not isinstance(birth_date, str):
            raise _row_error("BIRTH_DATE_MISSING")
        names = row.get("name")
        first = names[0] if isinstance(names, list) and names else {}
        given = first.get("given", [""]) if isinstance(first, dict) else [""]
        family = first.get("family", "") if isinstance(first, dict) else ""
        return PatientImportCandidate(
            mrn=mrn,
            birth_date=birth_date,
            given_name=str(given[0]),
            family_name=str(family),
        )


def _mrn(resource: SourceRow) -> str:
    identifiers = resource.get("identifier")
    if isinstance(identifiers, list):
        for identifier in identifiers:
            if isinstance(identifier, dict) and identifier.get("value"):
                return str(identifier["value"])
    raise _row_error("MRN_MISSING")


def _row_error(issue: str) -> InsumapError:
    return InsumapError(ErrorCode.VALIDATION_ERROR, detail={"issue": issue})
```

```python
# insumap/infrastructure/integration/cgm/adapter.py
import csv
import io
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import final, override

from insumap.shared.errors import ErrorCode, InsumapError
from insumap.shared.units import MG_DL_PER_MMOL_L


@dataclass(frozen=True, slots=True, kw_only=True)
class GlucoseCandidate:
    measured_at: str
    value_mg_dl: Decimal


class CgmReadingSource(ABC):
    @abstractmethod
    def read(self, raw: str) -> Sequence[GlucoseCandidate]: ...


@final
class CgmCsvAdapter(CgmReadingSource):
    """Adapts a vendor CSV (mg/dL or mmol/L) to glucose candidates in mg/dL.

    Pattern: P06 Adapter
    """

    @override
    def read(self, raw: str) -> Sequence[GlucoseCandidate]:
        reader = csv.DictReader(io.StringIO(raw))
        required = {"timestamp", "value", "unit"}
        if reader.fieldnames is None or not required <= set(reader.fieldnames):
            raise InsumapError(ErrorCode.VALIDATION_ERROR, detail={"issue": "COLUMN_MISSING"})
        out: list[GlucoseCandidate] = []
        for row in reader:
            value = Decimal(row["value"])
            if row["unit"] == "mmol/L":
                value = (value * MG_DL_PER_MMOL_L).quantize(Decimal(1))
            out.append(GlucoseCandidate(measured_at=row["timestamp"], value_mg_dl=value))
        return out
```

```python
# insumap/domain/ai/risk.py y insumap/application/ai/ports.py (se muestran juntos; el puerto completo
# tiene una operación por caso IA1 a IA7, ver Arquitectura sección 7.1)
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class RiskAssessment:
    score: float
    model_version: str
    is_fallback: bool
    fallback_reason: str | None


class AiServicePort(ABC):
    @abstractmethod
    def score_risk(self, subject_ref: str, features: dict[str, float]) -> RiskAssessment: ...
```

```python
# insumap/infrastructure/ai/client_adapter.py (cuerpo mínimo; el contrato completo está en docs/Contrato-IA.md)
import math
from http import HTTPStatus
from typing import final, override

import httpx
from pydantic import SecretStr

from insumap.application.ai.ports import AiServicePort
from insumap.domain.ai.risk import RiskAssessment
from insumap.shared.errors import ErrorCode, InsumapError


@final
class AiServiceClientAdapter(AiServicePort):
    """The only class that knows the JSON of ``insumap-ai``.

    Pattern: P06 Adapter
    """

    def __init__(self, client: httpx.Client, token: SecretStr, timeout_seconds: float) -> None:
        self._client = client
        self._token = token
        self._timeout = timeout_seconds

    @override
    def score_risk(self, subject_ref: str, features: dict[str, float]) -> RiskAssessment:
        try:
            response = self._client.post(
                "/v1/risk-assessments",
                json={"subject_ref": subject_ref, "features": features},
                headers={"Authorization": f"Bearer {self._token.get_secret_value()}"},
                timeout=self._timeout,
            )
        except httpx.TimeoutException as error:
            raise InsumapError(ErrorCode.AI_SERVICE_TIMEOUT) from error
        if response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR or response.status_code == HTTPStatus.UNAUTHORIZED:
            raise InsumapError(ErrorCode.AI_SERVICE_UNAVAILABLE)
        body = response.json()
        score = body.get("score")
        if not isinstance(score, float) or not math.isfinite(score) or not body.get("model_version"):
            raise InsumapError(ErrorCode.AI_SERVICE_UNAVAILABLE)
        return RiskAssessment(
            score=score,
            model_version=str(body["model_version"]),
            is_fallback=bool(body.get("is_fallback", False)),
            fallback_reason=body.get("fallback_reason"),
        )
```

`MG_DL_PER_MMOL_L` vive en `insumap/shared/units.py` (aún no existe; `configuration.md` lo muestra como `float`, aquí se usa `Decimal("18.016")` para no arrastrar error de redondeo; ver sección 6).

**Prueba:** `test_fhir_patient_adapter.py` (Bundle válido; `Patient` sin identificador de historia; recurso que no es `Patient`), `test_cgm_csv_adapter.py` (mmol/L convertido a mg/dL; columna faltante) y `tests/contract/test_ai_service_client_adapter.py` con `httpx.MockTransport` (`200`, `401`, `422`, `503`, timeout, `score` no finito). Ningún adaptador se prueba con la red real.

**Antipatrones**
- Mapear diccionarios externos dentro de un caso de uso o usar un modelo Pydantic del formato externo en el dominio.
- Un adaptador que deja pasar un valor sin validar (cuantiles desordenados, unidad desconocida).
- Devolver al caso de uso un `httpx.Response` o un `dict` de cable: se devuelven tipos del dominio.
- Que el `Authorization` o el cuerpo salgan en un log o en el mensaje de la excepción.

### P07. Bridge: `Notification` × `NotificationChannel`

- **Dónde vive:** la abstracción y la interfaz del implementador en `insumap/application/notifications/`; los canales (`EmailChannel`, `WebPushChannel`, `InAppChannel`) en `insumap/infrastructure/notifications/`.
- **Regla:** los canales **solo entregan**. La abstracción decide el contenido: un canal externo (correo, push) nunca lleva datos clínicos, solo el texto fijo "Tienes una alerta nueva en Insumap"; la clínica demo lleva la marca "Datos simulados". Los textos salen de `messages_es.json`.

```python
from abc import ABC, abstractmethod
from typing import final, override
from uuid import UUID

from insumap.shared.i18n import MessageCatalog


class NotificationChannel(ABC):
    """Implementor of the bridge."""

    @property
    @abstractmethod
    def is_external(self) -> bool:
        """True for channels that leave the app (email, push)."""

    @abstractmethod
    def deliver(self, *, recipient_id: UUID, subject: str, body: str) -> None: ...


class Notification(ABC):
    """Abstraction of the bridge: it owns the content rules, not the delivery.

    Pattern: P07 Bridge
    """

    def __init__(self, channel: NotificationChannel, messages: MessageCatalog) -> None:
        self._channel = channel
        self._messages = messages

    @final
    def send(self, recipient_id: UUID, *, is_demo: bool) -> None:
        if self._channel.is_external:
            subject, body = self.compose_external()
        else:
            subject, body = self.compose_in_app()
        if is_demo:
            body = f"{self._messages.render('demo.mark')} {body}"
        self._channel.deliver(recipient_id=recipient_id, subject=subject, body=body)

    @abstractmethod
    def compose_in_app(self) -> tuple[str, str]: ...

    @abstractmethod
    def compose_external(self) -> tuple[str, str]:
        """Text for email and push: no values, names or diagnoses."""


@final
class HypoglycemiaAlertNotification(Notification):
    def __init__(
        self, channel: NotificationChannel, messages: MessageCatalog, *, alert_id: UUID
    ) -> None:
        super().__init__(channel, messages)
        self._alert_id = alert_id

    @override
    def compose_in_app(self) -> tuple[str, str]:
        return (
            self._messages.render("notification.alert.subject"),
            self._messages.render("notification.alert.in_app", alert_id=self._alert_id),
        )

    @override
    def compose_external(self) -> tuple[str, str]:
        text = self._messages.render("notification.alert.external")
        return text, text
```

**Prueba** (`test_notification.py`): cada aviso por cada canal (matriz `parametrize`) con un canal de prueba que guarda lo entregado; el mensaje externo no contiene el identificador, un valor de glucosa, un nombre ni el diagnóstico (se verifica con valores centinela); la marca aparece solo con `is_demo`; el código de activación solo viaja en `CredentialInvitationNotification`.

**Antipatrones**
- Una clase por combinación aviso × canal, o `if channel == "email"` dentro del aviso.
- Que un canal arme texto o decida qué datos incluir.
- Que la abstracción llame a `smtplib` o a `pywebpush`: eso es del canal.

### P08. Composite: `AlertRule`

- **Dónde vive:** `insumap/domain/alerts/rules.py`. Los umbrales, las duraciones y las tasas llegan **de `alerts.alert_rules`** (BD) al construir el árbol; el dominio no los conoce. La ventana es `GlucoseWindow` (sección 2.4).

```python
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import final, override

from insumap.domain.metrics.window import GlucoseWindow
from insumap.shared.errors import ErrorCode, InsumapError

SECONDS_PER_MINUTE = 60
MIN_POINTS_FOR_RATE = 2


@dataclass(frozen=True, slots=True, kw_only=True)
class RuleMatch:
    rule: str
    matched_at: datetime


class AlertRule(ABC):
    """Component of the composite.

    Pattern: P08 Composite
    """

    @abstractmethod
    def evaluate(self, window: GlucoseWindow, now: datetime) -> RuleMatch | None: ...


@final
class ThresholdRule(AlertRule):
    def __init__(self, *, below_mg_dl: Decimal) -> None:
        self._below = below_mg_dl

    @override
    def evaluate(self, window: GlucoseWindow, now: datetime) -> RuleMatch | None:
        if window.points and window.points[-1].mg_dl < self._below:
            return RuleMatch(rule="threshold", matched_at=window.points[-1].at)
        return None


@final
class DurationRule(AlertRule):
    """Every point of the last ``lasting`` is below the threshold."""

    def __init__(self, *, below_mg_dl: Decimal, lasting: timedelta) -> None:
        self._below = below_mg_dl
        self._lasting = lasting

    @override
    def evaluate(self, window: GlucoseWindow, now: datetime) -> RuleMatch | None:
        recent = [p for p in window.points if p.at >= now - self._lasting]
        if recent and recent[0].at - (now - self._lasting) <= self._lasting and all(
            p.mg_dl < self._below for p in recent
        ):
            return RuleMatch(rule="duration", matched_at=recent[-1].at)
        return None


@final
class RateOfChangeRule(AlertRule):
    def __init__(self, *, drop_per_minute_mg_dl: Decimal) -> None:
        self._drop = drop_per_minute_mg_dl

    @override
    def evaluate(self, window: GlucoseWindow, now: datetime) -> RuleMatch | None:
        if len(window.points) < MIN_POINTS_FOR_RATE:
            return None
        first, last = window.points[-2], window.points[-1]
        minutes = Decimal((last.at - first.at).total_seconds()) / SECONDS_PER_MINUTE
        if minutes > 0 and (first.mg_dl - last.mg_dl) / minutes > self._drop:
            return RuleMatch(rule="rate_of_change", matched_at=last.at)
        return None


class _CompositeRule(AlertRule):
    def __init__(self, children: Sequence[AlertRule]) -> None:
        if not children:
            raise InsumapError(ErrorCode.VALIDATION_ERROR, detail={"issue": "EMPTY_RULE_TREE"})
        self._children = tuple(children)


@final
class AllOfRule(_CompositeRule):
    @override
    def evaluate(self, window: GlucoseWindow, now: datetime) -> RuleMatch | None:
        matches = [child.evaluate(window, now) for child in self._children]
        if all(match is not None for match in matches):
            return RuleMatch(rule="all_of", matched_at=max(m.matched_at for m in matches if m))
        return None


@final
class AnyOfRule(_CompositeRule):
    @override
    def evaluate(self, window: GlucoseWindow, now: datetime) -> RuleMatch | None:
        for child in self._children:
            match = child.evaluate(window, now)
            if match is not None:
                return match
        return None
```

`SECONDS_PER_MINUTE` y `MIN_POINTS_FOR_RATE` son constantes con nombre (permitida por `configuration.md`, sección 8); cualquier umbral clínico no.

**Prueba** (`test_alert_rule.py`): `AllOfRule` exige todas, `AnyOfRule` basta con una, anidación de tres niveles, árbol vacío rechazado. Los umbrales de la prueba son valores de prueba declarados en la prueba, no los de producción.

**Antipatrones**
- Una tabla plana de condiciones con un campo "operador lógico" (no anida).
- Un `70` o un `15` escritos en el código de una regla: vienen de la BD.
- Que el evaluador haga `isinstance` para distinguir hojas de compuestos.

### P09. Decorator: `PhiAccessAuditDecorator` y `AuditingCommandHandler`

- **Dónde vive:** `PhiAccessAuditDecorator` en `insumap/infrastructure/access/`; `AuditingCommandHandler` en `insumap/application/commands/`. Los dos implementan **la misma interfaz** que lo que envuelven y se componen en `container.py` (sección 4).
- **Regla de la lectura:** el orden es `PhiAccessAuditDecorator(PatientRecordAccessProxy(PatientRecordRepository))`: la auditoría va por fuera para registrar también los accesos denegados. El acceso concedido se escribe en la **misma transacción** de la lectura y, si la escritura falla, la lectura falla (fallo cerrado, V5). El denegado se escribe en una transacción corta e independiente, porque la de la petición se revierte al propagarse el error.

```python
# insumap/application/access/ports.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from insumap.application.common.actor import Actor


class AccessPurpose(StrEnum):
    CARE = "CARE"
    SELF = "SELF"
    ADMINISTRATION = "ADMINISTRATION"
    AI_PROCESSING = "AI_PROCESSING"


@dataclass(frozen=True, slots=True, kw_only=True)
class PatientRecord:
    patient_id: UUID
    glucose_mg_dl: tuple[Decimal, ...]


class PatientRecordPort(ABC):
    @abstractmethod
    def read_record(
        self, actor: Actor, patient_id: UUID, purpose: AccessPurpose
    ) -> PatientRecord: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class DataAccessRecord:
    occurred_at: datetime
    actor_user_id: UUID
    actor_role: str
    clinic_id: UUID | None
    patient_id: UUID
    resource_type: str
    purpose: AccessPurpose
    outcome: str
    request_id: str | None


class DataAccessLogPort(ABC):
    @abstractmethod
    def record_granted(self, record: DataAccessRecord) -> None:
        """Same transaction as the read. If it fails, the read fails."""

    @abstractmethod
    def record_denied(self, record: DataAccessRecord) -> None:
        """Short independent transaction: it is committed even if the request rolls back."""
```

```python
# insumap/infrastructure/access/audit_decorator.py
from typing import final, override
from uuid import UUID

from insumap.application.access.ports import (
    AccessPurpose,
    DataAccessLogPort,
    DataAccessRecord,
    PatientRecord,
    PatientRecordPort,
)
from insumap.application.common.actor import Actor
from insumap.shared.errors import ErrorCode, InsumapError
from insumap.shared.request_context import current_request_id
from insumap.shared.time import Clock

DENIAL_CODES = frozenset({ErrorCode.NOT_FOUND, ErrorCode.FORBIDDEN})


@final
class PhiAccessAuditDecorator(PatientRecordPort):
    """Audits every read of clinical data, granted or denied.

    Pattern: P09 Decorator
    """

    def __init__(self, inner: PatientRecordPort, log: DataAccessLogPort, clock: Clock) -> None:
        self._inner = inner
        self._log = log
        self._clock = clock

    @override
    def read_record(
        self, actor: Actor, patient_id: UUID, purpose: AccessPurpose
    ) -> PatientRecord:
        try:
            record = self._inner.read_record(actor, patient_id, purpose)
        except InsumapError as error:
            if error.code in DENIAL_CODES:
                self._log.record_denied(self._entry(actor, patient_id, purpose, "DENIED"))
            raise
        self._log.record_granted(self._entry(actor, patient_id, purpose, "GRANTED"))
        return record

    def _entry(
        self, actor: Actor, patient_id: UUID, purpose: AccessPurpose, outcome: str
    ) -> DataAccessRecord:
        return DataAccessRecord(
            occurred_at=self._clock.now(),
            actor_user_id=actor.user_id,
            actor_role=actor.role.value,
            clinic_id=actor.clinic_id,
            patient_id=patient_id,
            resource_type="PATIENT_RECORD",
            purpose=purpose,
            outcome=outcome,
            request_id=current_request_id(),
        )
```

```python
# insumap/application/commands/auditing.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import final, override
from uuid import UUID

from insumap.application.commands.base import Command, CommandHandler  # P13
from insumap.shared.time import Clock


@dataclass(frozen=True, slots=True, kw_only=True)
class AuditEntry:
    occurred_at: datetime
    actor_user_id: UUID
    action: str
    outcome: str
    reason: str | None


class AuditLogPort(ABC):
    @abstractmethod
    def record(self, entry: AuditEntry) -> None:
        """Success: same transaction as the action."""

    @abstractmethod
    def record_failure(self, entry: AuditEntry) -> None:
        """Failure: independent transaction. See guide section 6 (open point)."""


@final
class AuditingCommandHandler[C: Command[object], R](CommandHandler[C, R]):
    """Records every command, with its outcome, and re-raises the error.

    Pattern: P09 Decorator
    """

    def __init__(self, inner: CommandHandler[C, R], log: AuditLogPort, clock: Clock) -> None:
        self._inner = inner
        self._log = log
        self._clock = clock

    @override
    def handle(self, command: C) -> R:
        action = type(command).__name__
        try:
            result = self._inner.handle(command)
        except Exception:
            self._log.record_failure(self._entry(command, action, "FAILED"))
            raise
        self._log.record(self._entry(command, action, "SUCCEEDED"))
        return result

    def _entry(self, command: C, action: str, outcome: str) -> AuditEntry:
        return AuditEntry(
            occurred_at=self._clock.now(),
            actor_user_id=command.actor.user_id,
            action=action,
            outcome=outcome,
            reason=None,
        )
```

**Prueba** (`test_phi_access_audit_decorator.py` y `test_auditing_command_handler.py`): un acceso concedido deja una fila `GRANTED` y llama al componente una sola vez; uno denegado deja una fila `DENIED` por `record_denied` y relanza el mismo error; si `record_granted` lanza, `read_record` lanza (fallo cerrado); un error que no es de acceso (por ejemplo `INTERNAL_ERROR`) no deja fila `DENIED`. Para el handler: éxito deja `SUCCEEDED`, el error se relanza y deja `FAILED`. El log de prueba es un fake en memoria.

**Antipatrones**
- Un `@decorator` de función, un middleware HTTP (no ve al paciente ni el propósito) o un trigger de lectura en la BD (PostgreSQL no tiene triggers de `SELECT`).
- Poner la auditoría **dentro** del proxy: los accesos denegados quedarían sin fila.
- Registrar valores clínicos, nombres o el cuerpo de la petición en la fila: solo ids, tipo de recurso, propósito y resultado.
- Tragarse el error de la auditoría (`except Exception: pass`): rompe el fallo cerrado.

### P10. Facade: `DoctorDashboardFacade` y `PatientOverviewFacade`

- **Dónde vive:** `insumap/application/dashboard/`. El router llama a la fachada, no a los puertos.
- **Regla:** la fachada lee datos clínicos **solo por `PatientRecordPort`** (proxy y auditoría) y **nunca llama a la IA**: lee lo guardado. Si la clínica es demo, marca la respuesta.

```python
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import final
from uuid import UUID

from insumap.application.access.ports import AccessPurpose, PatientRecordPort
from insumap.application.common.actor import Actor
from insumap.domain.identity.permissions import PermissionCode


class AssignedPatientsPort(ABC):
    @abstractmethod
    def list_assigned(self, actor: Actor) -> Sequence[UUID]: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class DashboardRow:
    patient_id: UUID
    readings_count: int


@dataclass(frozen=True, slots=True, kw_only=True)
class DoctorDashboard:
    rows: tuple[DashboardRow, ...]
    is_demo: bool


@final
class DoctorDashboardFacade:
    """One answer per screen; the router knows no queries.

    Pattern: P10 Facade
    """

    def __init__(
        self, assigned: AssignedPatientsPort, records: PatientRecordPort, *, is_demo: bool
    ) -> None:
        self._assigned = assigned
        self._records = records
        self._is_demo = is_demo

    def triage(self, actor: Actor) -> DoctorDashboard:
        actor.require(PermissionCode.PATIENTS_READ_ASSIGNED)
        rows = tuple(
            DashboardRow(
                patient_id=patient_id,
                readings_count=len(
                    self._records.read_record(actor, patient_id, AccessPurpose.CARE).glucose_mg_dl
                ),
            )
            for patient_id in self._assigned.list_assigned(actor)
        )
        return DoctorDashboard(rows=rows, is_demo=self._is_demo)
```

**Prueba** (`test_doctor_dashboard_facade.py` y `test_patient_overview_facade.py`): solo aparecen los pacientes asignados; un paciente sin lecturas aparece con cero; la marca demo se propaga; sin el permiso responde `FORBIDDEN` antes de leer; la fachada no tiene ningún puerto de IA en su constructor (la prueba lo verifica con `inspect.signature`).

**Antipatrones**
- Que el router llame a varios casos de uso para armar una pantalla, o que el frontend haga cinco llamadas y combine.
- Leer con el repositorio directamente: se salta el proxy y la auditoría.
- Que la fachada contenga reglas de negocio: orquesta, no decide.

### P11. Proxy: `PatientRecordAccessProxy` y `RemoteAiServiceProxy`

- **Dónde vive:** `insumap/infrastructure/access/` e `insumap/infrastructure/ai/`. La política es de dominio (`insumap/domain/access/policy.py`) y se prueba sin proxy.
- **Regla:** el proxy tiene la **misma interfaz** que el sujeto real y el contenedor entrega solo el proxy; así ningún caso de uso puede saltarse el control. Un médico no asignado o un paciente ajeno recibe `404` (`NOT_FOUND`); el `CLINIC_ADMIN` o el `PLATFORM_ADMIN` que piden datos clínicos, `403`; un paciente de otra clínica no existe para la RLS (`404`).

```python
# insumap/domain/access/policy.py
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import final
from uuid import UUID

from insumap.application.common.actor import Actor, Role


class AccessDecision(StrEnum):
    GRANTED = "GRANTED"
    NOT_FOUND = "NOT_FOUND"
    FORBIDDEN = "FORBIDDEN"


@dataclass(frozen=True, slots=True, kw_only=True)
class PatientRef:
    patient_id: UUID
    user_id: UUID | None


@dataclass(frozen=True, slots=True, kw_only=True)
class CareTeamAssignment:
    doctor_user_id: UUID
    patient_id: UUID
    ended_at: datetime | None

    def is_active(self, at: datetime) -> bool:
        return self.ended_at is None or self.ended_at > at


@final
class PatientAccessPolicy:
    """Who may read the clinical record of a patient (Seguridad 6.3)."""

    def decide(
        self,
        actor: Actor,
        patient: PatientRef,
        assignments: Sequence[CareTeamAssignment],
        at: datetime,
    ) -> AccessDecision:
        match actor.role:
            case Role.PATIENT:
                own = patient.user_id is not None and patient.user_id == actor.user_id
                return AccessDecision.GRANTED if own else AccessDecision.NOT_FOUND
            case Role.DOCTOR:
                assigned = any(
                    a.doctor_user_id == actor.user_id
                    and a.patient_id == patient.patient_id
                    and a.is_active(at)
                    for a in assignments
                )
                return AccessDecision.GRANTED if assigned else AccessDecision.NOT_FOUND
            case Role.CLINIC_ADMIN | Role.PLATFORM_ADMIN:
                return AccessDecision.FORBIDDEN
```

```python
# insumap/infrastructure/access/access_proxy.py
from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import final, override
from uuid import UUID

from insumap.application.access.ports import AccessPurpose, PatientRecord, PatientRecordPort
from insumap.application.common.actor import Actor
from insumap.domain.access.policy import (
    AccessDecision,
    CareTeamAssignment,
    PatientAccessPolicy,
    PatientRef,
)
from insumap.shared.errors import ErrorCode, InsumapError
from insumap.shared.time import Clock


class PatientDirectoryPort(ABC):
    @abstractmethod
    def find(self, patient_id: UUID) -> PatientRef | None:
        """Runs under RLS: a patient of another clinic is simply not found."""


class CareTeamAssignmentPort(ABC):
    @abstractmethod
    def for_patient(self, patient_id: UUID) -> Sequence[CareTeamAssignment]: ...


@final
class PatientRecordAccessProxy(PatientRecordPort):
    """Protection proxy: only the assigned care team, the patient or a limited admin.

    Pattern: P11 Proxy
    """

    def __init__(
        self,
        subject: PatientRecordPort,
        patients: PatientDirectoryPort,
        assignments: CareTeamAssignmentPort,
        policy: PatientAccessPolicy,
        clock: Clock,
    ) -> None:
        self._subject = subject
        self._patients = patients
        self._assignments = assignments
        self._policy = policy
        self._clock = clock

    @override
    def read_record(
        self, actor: Actor, patient_id: UUID, purpose: AccessPurpose
    ) -> PatientRecord:
        patient = self._patients.find(patient_id)
        if patient is None:
            raise InsumapError(ErrorCode.NOT_FOUND)
        decision = self._policy.decide(
            actor, patient, self._assignments.for_patient(patient_id), self._clock.now()
        )
        if decision is AccessDecision.FORBIDDEN:
            raise InsumapError(ErrorCode.FORBIDDEN)
        if decision is AccessDecision.NOT_FOUND:
            raise InsumapError(ErrorCode.NOT_FOUND)
        return self._subject.read_record(actor, patient_id, purpose)
```

El segundo proxy marca cada resultado con `is_fallback` y `fallback_reason`, y se apoya en `CircuitBreaker` (P18) y en `RuleBasedAiFallbackAdapter`:

```python
# insumap/infrastructure/ai/remote_proxy.py
from enum import StrEnum
from typing import final, override

from insumap.application.ai.ports import AiServicePort
from insumap.domain.ai.risk import RiskAssessment
from insumap.shared.errors import ErrorCode, InsumapError
from dataclasses import replace


class FallbackReason(StrEnum):
    AI_TIMEOUT = "AI_TIMEOUT"
    CIRCUIT_OPEN = "CIRCUIT_OPEN"
    AI_ERROR = "AI_ERROR"


@final
class RemoteAiServiceProxy(AiServicePort):
    """Remote proxy with circuit breaker and deterministic fallback.

    Pattern: P11 Proxy
    """

    def __init__(
        self,
        remote: AiServicePort,
        fallback: AiServicePort,
        breaker: CircuitBreaker,
        *,
        enabled: bool,
    ) -> None:
        self._remote = remote
        self._fallback = fallback
        self._breaker = breaker
        self._enabled = enabled

    @override
    def score_risk(self, subject_ref: str, features: dict[str, float]) -> RiskAssessment:
        if not self._enabled or not self._breaker.allow_request():
            return self._fallback_result(subject_ref, features, FallbackReason.CIRCUIT_OPEN)
        try:
            result = self._remote.score_risk(subject_ref, features)
        except InsumapError as error:
            self._breaker.record_failure()
            reason = (
                FallbackReason.AI_TIMEOUT
                if error.code is ErrorCode.AI_SERVICE_TIMEOUT
                else FallbackReason.AI_ERROR
            )
            return self._fallback_result(subject_ref, features, reason)
        self._breaker.record_success()
        return result

    def _fallback_result(
        self, subject_ref: str, features: dict[str, float], reason: FallbackReason
    ) -> RiskAssessment:
        result = self._fallback.score_risk(subject_ref, features)
        return replace(result, is_fallback=True, fallback_reason=reason.value)
```

**Prueba** (`test_patient_record_access_proxy.py` y `test_remote_ai_service_proxy.py`): médico asignado lee; no asignado recibe `NOT_FOUND`; una asignación terminada retira el acceso (se avanza el `FixedClock`); admin recibe `FORBIDDEN`; el sujeto real **no** se llama cuando se deniega. IA: timeout produce `AI_TIMEOUT`; circuito abierto no llama al adaptador y produce `CIRCUIT_OPEN`; con `enabled=False` siempre usa el respaldo. La política (`PatientAccessPolicy`) tiene su propia prueba sin proxy.

Ejemplo de prueba (`tests/unit/patterns/test_patient_record_access_proxy.py`), con fakes en memoria:

```python
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from tests.support.fixed_clock import FixedClock

PATIENT_ID = UUID(int=100)
DOCTOR_ID = UUID(int=1)
NOW = datetime(2026, 3, 2, 12, 0, tzinfo=UTC)


class RecordingSubject(PatientRecordPort):
    def __init__(self) -> None:
        self.calls = 0

    def read_record(self, actor: Actor, patient_id: UUID, purpose: AccessPurpose) -> PatientRecord:
        self.calls += 1
        return PatientRecord(patient_id=patient_id, glucose_mg_dl=())


class FakeDirectory(PatientDirectoryPort):
    def find(self, patient_id: UUID) -> PatientRef | None:
        return PatientRef(patient_id=patient_id, user_id=UUID(int=50)) if patient_id == PATIENT_ID else None


class FakeAssignments(CareTeamAssignmentPort):
    def __init__(self, ended_at: datetime | None) -> None:
        self._ended_at = ended_at

    def for_patient(self, patient_id: UUID) -> list[CareTeamAssignment]:
        return [CareTeamAssignment(doctor_user_id=DOCTOR_ID, patient_id=patient_id, ended_at=self._ended_at)]


def doctor(user_id: UUID) -> Actor:
    return Actor(user_id=user_id, clinic_id=UUID(int=9), role=Role.DOCTOR)


def test_unassigned_doctor_gets_not_found_and_subject_is_not_called() -> None:
    subject = RecordingSubject()
    proxy = PatientRecordAccessProxy(
        subject, FakeDirectory(), FakeAssignments(None), PatientAccessPolicy(), FixedClock(NOW)
    )

    with pytest.raises(InsumapError) as error:
        proxy.read_record(doctor(UUID(int=2)), PATIENT_ID, AccessPurpose.CARE)

    assert error.value.code is ErrorCode.NOT_FOUND
    assert subject.calls == 0


def test_ended_assignment_removes_access() -> None:
    clock = FixedClock(NOW)
    proxy = PatientRecordAccessProxy(
        RecordingSubject(), FakeDirectory(), FakeAssignments(NOW + timedelta(hours=1)),
        PatientAccessPolicy(), clock,
    )
    assert proxy.read_record(doctor(DOCTOR_ID), PATIENT_ID, AccessPurpose.CARE)

    clock.advance(timedelta(hours=2))

    with pytest.raises(InsumapError):
        proxy.read_record(doctor(DOCTOR_ID), PATIENT_ID, AccessPurpose.CARE)
```

**Antipatrones**
- `__getattr__` para delegar (rompe `mypy --strict` y esconde qué se protege).
- Verificar la asignación en cada caso de uso, o capturar los errores de la IA en cada caso de uso.
- Que el caso de uso reciba el repositorio y el proxy "a elección".
- Responder `403` a un médico no asignado: revela que el paciente existe.
- Leer la clínica del paciente desde la ruta o el cuerpo: el aislamiento lo fija la RLS con el contexto de la transacción.

### P12. Chain of Responsibility: `GlucoseReadingValidationHandler` y `AlertEscalationHandler`

- **Dónde vive:** `insumap/domain/monitoring/validation/` e `insumap/domain/alerts/escalation.py`. La corre el dominio, así sirve igual para la API, los lotes offline y las importaciones.
- **Regla:** el orden es una regla del negocio. Los bloqueantes (rango, fecha) van primero y lanzan error (`422`, no se guarda); las banderas (duplicado, tasa de cambio, unidad) se acumulan y la lectura queda `FLAGGED`. Los parámetros (rango medible, tolerancia, ventana de duplicado) vienen de la BD en `ValidationParams`.

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Self, final, override

from insumap.shared.errors import ErrorCode, InsumapError


@dataclass(frozen=True, slots=True, kw_only=True)
class ValidationParams:
    """Read per clinic from the database, never written in code."""

    min_mg_dl: Decimal
    max_mg_dl: Decimal
    future_tolerance: timedelta
    duplicate_window: timedelta


@dataclass(frozen=True, slots=True, kw_only=True)
class ReadingCandidate:
    value_mg_dl: Decimal
    measured_at: datetime
    now: datetime
    params: ValidationParams
    last_value_mg_dl: Decimal | None
    last_measured_at: datetime | None


class GlucoseReadingValidationHandler(ABC):
    """Handler of the chain.

    Pattern: P12 Chain of Responsibility
    """

    def __init__(self) -> None:
        self._next: GlucoseReadingValidationHandler | None = None

    @final
    def set_next(self, handler: GlucoseReadingValidationHandler) -> GlucoseReadingValidationHandler:
        self._next = handler
        return handler

    @final
    def validate(self, reading: ReadingCandidate, issues: tuple[str, ...] = ()) -> tuple[str, ...]:
        flag = self.check(reading)  # a blocking handler raises here
        found = issues + ((flag,) if flag is not None else ())
        return found if self._next is None else self._next.validate(reading, found)

    @abstractmethod
    def check(self, reading: ReadingCandidate) -> str | None:
        """Raise to block, return an issue code to flag, or None to pass."""


@final
class RangeCheckHandler(GlucoseReadingValidationHandler):
    @override
    def check(self, reading: ReadingCandidate) -> str | None:
        params = reading.params
        if not params.min_mg_dl <= reading.value_mg_dl <= params.max_mg_dl:
            raise InsumapError(ErrorCode.GLUCOSE_OUT_OF_RANGE)
        return None


@final
class TimestampCheckHandler(GlucoseReadingValidationHandler):
    @override
    def check(self, reading: ReadingCandidate) -> str | None:
        if reading.measured_at > reading.now + reading.params.future_tolerance:
            raise InsumapError(ErrorCode.READING_IN_FUTURE)
        return None


@final
class DuplicateCheckHandler(GlucoseReadingValidationHandler):
    @override
    def check(self, reading: ReadingCandidate) -> str | None:
        if (
            reading.last_value_mg_dl == reading.value_mg_dl
            and reading.last_measured_at is not None
            and reading.measured_at - reading.last_measured_at <= reading.params.duplicate_window
        ):
            return "DUPLICATE_SUSPECTED"
        return None


def build_validation_chain() -> GlucoseReadingValidationHandler:
    """Blocking handlers first, flags after (RateOfChange and UnitConsistency follow)."""
    head = RangeCheckHandler()
    head.set_next(TimestampCheckHandler()).set_next(DuplicateCheckHandler())
    return head
```

La cadena de escalamiento sigue la misma forma: cada nivel decide los destinatarios y, si no tiene, pasa al siguiente.

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import final, override
from uuid import UUID


@dataclass(frozen=True, slots=True, kw_only=True)
class EscalationContext:
    patient_user_id: UUID | None
    primary_doctor_id: UUID | None
    team_doctor_ids: tuple[UUID, ...]
    clinic_admin_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class EscalationOutcome:
    level: int
    recipients: tuple[UUID, ...]


class AlertEscalationHandler(ABC):
    """Pattern: P12 Chain of Responsibility"""

    level: int

    def __init__(self) -> None:
        self._next: AlertEscalationHandler | None = None

    @final
    def set_next(self, handler: AlertEscalationHandler) -> AlertEscalationHandler:
        self._next = handler
        return handler

    @final
    def escalate(self, ctx: EscalationContext, *, from_level: int) -> EscalationOutcome | None:
        if self.level >= from_level:
            recipients = self.recipients(ctx)
            if recipients:
                return EscalationOutcome(level=self.level, recipients=recipients)
        return None if self._next is None else self._next.escalate(ctx, from_level=from_level)

    @abstractmethod
    def recipients(self, ctx: EscalationContext) -> tuple[UUID, ...]: ...


@final
class PatientEscalationHandler(AlertEscalationHandler):
    level = 0

    @override
    def recipients(self, ctx: EscalationContext) -> tuple[UUID, ...]:
        return (ctx.patient_user_id,) if ctx.patient_user_id else ()


@final
class PrimaryDoctorEscalationHandler(AlertEscalationHandler):
    level = 1

    @override
    def recipients(self, ctx: EscalationContext) -> tuple[UUID, ...]:
        return (ctx.primary_doctor_id,) if ctx.primary_doctor_id else ()
```

**Prueba** (`test_glucose_reading_validation_handler.py` y `test_alert_escalation_handler.py`): el orden (un valor fuera de rango y en el futuro responde `GLUCOSE_OUT_OF_RANGE`, el primero), la detención en el primer bloqueante, la acumulación de banderas y que un valor válido devuelve `()`. Escalamiento: `from_level=1` ignora el nivel 0; un nivel sin destinatarios pasa al siguiente; sin ningún destinatario devuelve `None`. Los parámetros de la prueba son un `ValidationParams` de prueba.

**Antipatrones**
- Una función con una lista de `if` (orden implícito, sin pruebas por etapa) o un middleware HTTP (no corre en lotes ni en importaciones).
- Que un manejador bloqueante marque `FLAGGED` en vez de lanzar, o al revés.
- Escribir el rango o los minutos de tolerancia en el manejador.
- Que un manejador conozca al siguiente por clase (`DuplicateCheckHandler()` dentro de `RangeCheckHandler`): se enlaza solo en el armado.

### P13. Command: `CommandBus` y sus comandos

- **Dónde vive:** `insumap/application/commands/` (base, bus y `AuditingCommandHandler`); cada comando y su handler en su módulo (`application/ai/commands.py`, `application/treatment/commands.py`, ...).
- **Alcance:** el bus solo despacha **decisiones** (aprobar, modificar o rechazar una recomendación, activar un plan, emitir credenciales, asignar un médico). Registrar una lectura usa su caso de uso.
- **Regla:** cada comando es un objeto inmutable que lleva al actor. El contenedor envuelve **cada** handler con `AuditingCommandHandler` (P09). Un comando sin handler hace fallar el **armado** del bus, no la primera petición.

```python
# insumap/application/commands/base.py
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast, final, override

from insumap.application.common.actor import Actor
from insumap.shared.errors import ErrorCode, InsumapError


@dataclass(frozen=True, slots=True, kw_only=True)
class Command[R]:
    """Base of every decision. ``R`` is the type its handler returns."""

    actor: Actor


class CommandHandler[C: Command[object], R](ABC):
    @abstractmethod
    def handle(self, command: C) -> R: ...


type Registration = tuple[type[Command[object]], CommandHandler[Command[object], object]]


def bind[C: Command[object], R](command_type: type[C], handler: CommandHandler[C, R]) -> Registration:
    """Typed registration: the handler must accept exactly this command type.

    mypy cannot tie ``R`` to the ``R`` of ``Command[R]`` (PEP 695 bounds cannot
    mention another type parameter), so the result type is checked by the
    handler test, not by the registration.
    """
    return (
        cast("type[Command[object]]", command_type),
        cast("CommandHandler[Command[object], object]", handler),
    )


class CommandBus(ABC):
    @abstractmethod
    def dispatch[R](self, command: Command[R]) -> R: ...


@final
class InMemoryCommandBus(CommandBus):
    """Invoker of P13. It only routes; authorization lives in the handlers.

    Pattern: P13 Command
    """

    def __init__(
        self, registrations: list[Registration], *, required: frozenset[type[Command[object]]]
    ) -> None:
        self._handlers: Mapping[type[Command[object]], CommandHandler[Command[object], object]] = dict(
            registrations
        )
        missing = required - set(self._handlers)
        if missing:
            names = sorted(command.__name__ for command in missing)
            raise InsumapError(ErrorCode.COMMAND_NOT_HANDLED, detail={"commands": names})

    @override
    def dispatch[R](self, command: Command[R]) -> R:
        handler = self._handlers.get(type(command))
        if handler is None:
            raise InsumapError(ErrorCode.COMMAND_NOT_HANDLED)
        return cast(R, handler.handle(command))
```

```python
# insumap/application/ai/commands.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import final, override
from uuid import UUID

from insumap.application.commands.base import Command, CommandHandler
from insumap.domain.identity.permissions import PermissionCode
from insumap.shared.errors import ErrorCode, InsumapError
from insumap.shared.field_limits import FieldLimits


@dataclass(frozen=True, slots=True, kw_only=True)
class RejectRecommendationCommand(Command[None]):
    recommendation_id: UUID
    reason: str


class RecommendationDecisionPort(ABC):
    """Port of ``application.ai.ports``: one operation per decision."""

    @abstractmethod
    def reject(self, recommendation_id: UUID, doctor_user_id: UUID, reason: str) -> None: ...


@final
class RejectRecommendationCommandHandler(CommandHandler[RejectRecommendationCommand, None]):
    def __init__(self, decisions: RecommendationDecisionPort) -> None:
        self._decisions = decisions

    @override
    def handle(self, command: RejectRecommendationCommand) -> None:
        command.actor.require(PermissionCode.RECOMMENDATIONS_DECIDE)
        reason = command.reason.strip()
        if not FieldLimits.REASON_MIN_LENGTH <= len(reason) <= FieldLimits.REASON_MAX_LENGTH:
            raise InsumapError(ErrorCode.REASON_REQUIRED)
        self._decisions.reject(command.recommendation_id, command.actor.user_id, reason)
```

`RecommendationDecisionPort` vive en `application.ai.ports` (aquí solo `reject`; el real tiene también `approve` y `modify`). Los límites del motivo (`REASON_MIN_LENGTH` y `REASON_MAX_LENGTH`) están **propuestos** en [`input-validation.md`](input-validation.md).

**Prueba** (`test_command_bus.py` y una por handler): el bus despacha al handler correcto; un comando sin handler falla al armar; `bind` rechaza con mypy un handler de otro comando (el tipo de resultado `R` lo verifica la prueba del handler, no `bind`); `RejectRecommendationCommandHandler` exige el permiso y el motivo (`REASON_REQUIRED` con 9 y 501 caracteres, pasa con 10 y 500) y llama a `reject` una sola vez; el handler decorado deja una entrada de auditoría.

**Antipatrones**
- Un método de servicio por decisión con la auditoría repetida en cada uno, o `lambda` en un diccionario.
- Que el bus autorice o audite: eso es del handler y del decorador P09.
- Un comando mutable o con el `actor` tomado del cuerpo de la petición: el actor sale del token.
- Usar el bus para registrar lecturas o para consultas.

### P14. Iterator: `GlucoseWindowIterator`

- **Dónde vive:** `insumap/domain/metrics/window_iterator.py`. Entrega `GlucoseWindow` (sección 2.4) por día local o por franja nocturna, en la zona de la clínica. Los límites de la franja nocturna y la suficiencia mínima de datos vienen del perfil de metas (BD).
- Es una clase con nombre que usa un generador **por dentro** (permitido por la sección 1.1 del catálogo).

```python
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import final
from zoneinfo import ZoneInfo

from insumap.domain.metrics.window import GlucosePoint, GlucoseWindow


@dataclass(frozen=True, slots=True, kw_only=True)
class WindowSpec:
    """Where and how to cut windows. Night limits and ``min_points`` come from the target profile."""

    zone: ZoneInfo
    first_day: date
    days: int
    starts_at: time
    ends_at: time
    min_points: int

    @classmethod
    def daily(cls, *, zone: ZoneInfo, first_day: date, days: int, min_points: int) -> WindowSpec:
        midnight = time(0, 0)
        return cls(
            zone=zone, first_day=first_day, days=days,
            starts_at=midnight, ends_at=midnight, min_points=min_points,
        )  # fmt: skip


@final
class GlucoseWindowIterator:
    """Iterates local-day or night windows over a series of readings.

    Pattern: P14 Iterator
    """

    def __init__(self, points: Sequence[GlucosePoint], spec: WindowSpec) -> None:
        self._points = tuple(sorted(points, key=lambda point: point.at))
        self._spec = spec

    def __iter__(self) -> Iterator[GlucoseWindow]:
        spec = self._spec
        for offset in range(spec.days):
            day = spec.first_day + timedelta(days=offset)
            end_day = day if spec.ends_at > spec.starts_at else day + timedelta(days=1)
            start = datetime.combine(day, spec.starts_at, tzinfo=spec.zone)
            end = datetime.combine(end_day, spec.ends_at, tzinfo=spec.zone)
            inside = tuple(p for p in self._points if start <= p.at < end)
            yield GlucoseWindow(
                start=start, end=end, points=inside,
                has_enough_data=len(inside) >= spec.min_points,
            )  # fmt: skip
```

**Prueba** (`test_glucose_window_iterator.py`): el día local en `America/Bogota` (una lectura a las 03:00 UTC cae en el día anterior); la ventana nocturna usa los límites del perfil de prueba y cruza la medianoche; una ventana sin datos suficientes queda marcada; las lecturas se entregan ordenadas aunque lleguen desordenadas. Si la imagen es `python:3.13-slim`, `zoneinfo` necesita el paquete `tzdata` (verificar al crear el esqueleto).

**Antipatrones**
- Un generador suelto o un `groupby` de pandas dentro de cada métrica.
- Calcular el día con `date()` en UTC o con la zona del servidor.
- Escribir `22:00` y `06:00` en el código: son del perfil.

### P15. Mediator

**No aplica en el backend.** Vive solo en `insumap-frontend` (`DashboardFiltersMediator`). El `CommandBus` es un *invoker* de P13, no un mediador. No se crea ninguna clase `*Mediator` en este repositorio ni se reutiliza el ID.

### P16. Memento: `TreatmentPlanMemento`

- **Dónde vive:** `insumap/domain/treatment/`. El originador es `TreatmentPlan` (`create_memento()` y `from_memento()`, sección 2.2). El cuidador son los casos de uso y handlers que cambian el plan; guardan el memento en `care.treatment_plan_snapshots` **sin conocer su contenido**.
- **Regla de restauración:** restaurar nunca modifica una versión existente: reconstruye con `from_memento()` y crea una versión nueva en `DRAFT` con `copy_for_new_version()` (P05).

```python
from abc import ABC, abstractmethod
from datetime import datetime
from typing import final
from uuid import UUID

from insumap.application.common.ids import IdGenerator
from insumap.domain.treatment.plan import TreatmentPlan, TreatmentPlanMemento
from insumap.shared.time import Clock


class PlanSnapshotPort(ABC):
    @abstractmethod
    def save(self, plan_id: UUID, memento: TreatmentPlanMemento) -> None: ...


@final
class PlanSnapshotCaretaker:
    """Takes the snapshot before every change; it never reads the memento."""

    def __init__(self, snapshots: PlanSnapshotPort, clock: Clock) -> None:
        self._snapshots = snapshots
        self._clock = clock

    def snapshot_before_change(self, plan: TreatmentPlan) -> None:
        self._snapshots.save(plan.plan_id, plan.create_memento(self._clock.now()))


def restore_as_new_draft(
    memento: TreatmentPlanMemento, *, ids: IdGenerator, created_at: datetime
) -> TreatmentPlan:
    plan = TreatmentPlan.from_memento(memento)
    return plan.copy_for_new_version(
        new_plan_id=ids.new_id(),
        item_ids=tuple(ids.new_id() for _ in plan.items),
        created_at=created_at,
    )
```

**Prueba** (`test_treatment_plan_memento.py`): el memento no cambia si el plan cambia (es inmutable); ida y vuelta por `json.loads(memento.payload)` sin pérdida (incluidos `Decimal` y `UUID`); restaurar crea un `DRAFT` nuevo con `based_on_plan_id` y no modifica el original.

**Antipatrones**
- Releer la versión anterior desde las tablas (los borradores se editan en su lugar y se perderían los pasos intermedios) o `pickle` (inseguro y opaco).
- Un memento con referencias a objetos vivos (entidades, ORM): solo datos primitivos y tuplas.
- Que el cuidador abra el memento y decida con su contenido.

### P17. Observer: `DomainEventPublisher`

- **Dónde vive:** el puerto en `insumap/application/events/`; `InProcessDomainEventPublisher` en `insumap/infrastructure/events/`; los eventos en `insumap/domain/<módulo>/events.py`.
- **Regla:** los eventos se publican **después del commit**, nunca dentro de la transacción. La entidad trae el evento en `pending_events`, el repositorio lo entrega a la unidad de trabajo y esta lo publica cuando `commit()` retorna. Un suscriptor que falla se registra (tipo de evento y `request_id`, sin datos de salud) y no afecta a los demás.

```python
import logging
from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import cast, final, override

from insumap.domain.common.events import DomainEvent

logger = logging.getLogger(__name__)


class EventSubscriber[E: DomainEvent](ABC):
    @abstractmethod
    def handle(self, event: E) -> None: ...


class DomainEventPublisher(ABC):
    """Pattern: P17 Observer"""

    @abstractmethod
    def publish_all(self, events: Sequence[DomainEvent]) -> None: ...


@final
class InProcessDomainEventPublisher(DomainEventPublisher):
    """Calls the subscribers registered by event type, in order, in-process."""

    def __init__(self) -> None:
        self._subscribers: dict[type[DomainEvent], list[EventSubscriber[DomainEvent]]] = {}

    def subscribe[E: DomainEvent](self, event_type: type[E], subscriber: EventSubscriber[E]) -> None:
        # one cast at registration: publish_all only passes events of the same type
        registry = self._subscribers.setdefault(event_type, [])
        registry.append(cast("EventSubscriber[DomainEvent]", subscriber))

    @override
    def publish_all(self, events: Sequence[DomainEvent]) -> None:
        for event in events:
            for subscriber in self._subscribers.get(type(event), []):
                try:
                    subscriber.handle(event)
                except Exception:  # one failing subscriber must not stop the rest
                    logger.exception("Subscriber failed", extra={"event_type": type(event).__name__})
```

```python
# insumap/infrastructure/persistence/unit_of_work.py (solo la parte de eventos; el contexto de la RLS está en security.md sección 11)
from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import final

from insumap.application.events.publisher import DomainEventPublisher
from insumap.domain.common.events import DomainEvent


class Transaction(ABC):
    @abstractmethod
    def commit(self) -> None: ...

    @abstractmethod
    def rollback(self) -> None: ...


@final
class SqlAlchemyUnitOfWork:
    def __init__(self, transaction: Transaction, publisher: DomainEventPublisher) -> None:
        self._transaction = transaction
        self._publisher = publisher
        self._pending: list[DomainEvent] = []

    def collect(self, events: Sequence[DomainEvent]) -> None:
        self._pending.extend(events)

    def commit(self) -> None:
        self._transaction.commit()  # if it raises, nothing is published
        events, self._pending = self._pending, []
        self._publisher.publish_all(events)

    def rollback(self) -> None:
        self._transaction.rollback()
        self._pending = []
```

**Prueba** (`test_domain_event_publisher.py`; la de integración está en `tests/integration`): un `Transaction` de prueba que registra el orden de llamadas confirma que se entrega después de `commit`; una transacción revertida no entrega nada; un `commit` que lanza no entrega nada; un suscriptor que falla no impide a los demás.

Ejemplo de prueba (`tests/unit/patterns/test_domain_event_publisher.py`):

```python
class RecordingTransaction(Transaction):
    def __init__(self, order: list[str]) -> None:
        self._order = order

    def commit(self) -> None:
        self._order.append("commit")

    def rollback(self) -> None:
        self._order.append("rollback")


class RecordingSubscriber(EventSubscriber[DomainEvent]):
    def __init__(self, name: str, order: list[str], *, fails: bool = False) -> None:
        self._name, self._order, self._fails = name, order, fails

    def handle(self, event: DomainEvent) -> None:
        self._order.append(self._name)
        if self._fails:
            raise RuntimeError("subscriber failure")


def test_events_are_delivered_after_commit_and_a_failing_subscriber_does_not_stop_others() -> None:
    order: list[str] = []
    publisher = InProcessDomainEventPublisher()
    publisher.subscribe(DomainEvent, RecordingSubscriber("first", order, fails=True))
    publisher.subscribe(DomainEvent, RecordingSubscriber("second", order))
    uow = SqlAlchemyUnitOfWork(RecordingTransaction(order), publisher)
    uow.collect([DomainEvent(event_id=UUID(int=1), occurred_at=NOW)])

    uow.commit()

    assert order == ["commit", "first", "second"]


def test_rollback_delivers_nothing() -> None:
    order: list[str] = []
    publisher = InProcessDomainEventPublisher()
    publisher.subscribe(DomainEvent, RecordingSubscriber("first", order))
    uow = SqlAlchemyUnitOfWork(RecordingTransaction(order), publisher)
    uow.collect([DomainEvent(event_id=UUID(int=1), occurred_at=NOW)])

    uow.rollback()
    uow.commit()

    assert order == ["rollback", "commit"]
```

**Antipatrones**
- Eventos de sesión de SQLAlchemy (`after_commit`, `before_flush`) o `blinker` (sección 1.1 del catálogo); llamar a los efectos al final de cada caso de uso.
- Publicar dentro del `with` de la transacción.
- Que el dominio conozca al publicador: solo declara los eventos.
- Registrar el contenido del evento en el log de error.

### P18. State: `AlertState`, `RecommendationState`, `PatientAccountState`, `CircuitBreakerState`

- **Dónde vive:** `insumap/domain/alerts/`, `insumap/domain/ai/`, `insumap/domain/onboarding/` e `insumap/infrastructure/ai/` (circuit breaker).
- **Regla:** una clase por estado; las transiciones no permitidas lanzan `InvalidStateTransitionError` (`409 INVALID_STATE_TRANSITION`); el valor persistido es un `StrEnum` y `from_status()` reconstruye el estado con `match` y `assert_never`. El `match` se usa **solo** en `from_status()`; la lógica por estado vive en la clase.

```python
# insumap/domain/ai/recommendation_state.py
from abc import ABC
from enum import StrEnum
from typing import assert_never, final, override

from insumap.shared.errors import ErrorCode, InsumapError


class RecommendationStatus(StrEnum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    APPROVED_WITH_CHANGES = "APPROVED_WITH_CHANGES"
    REJECTED = "REJECTED"
    APPLIED = "APPLIED"
    EXPIRED = "EXPIRED"


@final
class InvalidStateTransitionError(InsumapError):
    def __init__(self, machine: str, status: str, action: str) -> None:
        super().__init__(
            ErrorCode.INVALID_STATE_TRANSITION,
            params={"machine": machine, "status": status, "action": action},
        )


class RecommendationState(ABC):
    """Base of the recommendation machine.

    Pattern: P18 State
    """

    status: RecommendationStatus

    def approve(self) -> RecommendationState:
        raise self._invalid("approve")

    def approve_with_changes(self) -> RecommendationState:
        raise self._invalid("approve_with_changes")

    def reject(self) -> RecommendationState:
        raise self._invalid("reject")

    def apply(self) -> RecommendationState:
        raise self._invalid("apply")

    def expire(self) -> RecommendationState:
        raise self._invalid("expire")

    @final
    def _invalid(self, action: str) -> InvalidStateTransitionError:
        return InvalidStateTransitionError("recommendation", self.status.value, action)

    @staticmethod
    def from_status(status: RecommendationStatus) -> RecommendationState:
        match status:
            case RecommendationStatus.PROPOSED:
                return ProposedState()
            case RecommendationStatus.APPROVED:
                return ApprovedState()
            case RecommendationStatus.APPROVED_WITH_CHANGES:
                return ApprovedWithChangesState()
            case RecommendationStatus.REJECTED:
                return RejectedState()
            case RecommendationStatus.APPLIED:
                return AppliedState()
            case RecommendationStatus.EXPIRED:
                return ExpiredState()
            case _:
                assert_never(status)


@final
class ProposedState(RecommendationState):
    status = RecommendationStatus.PROPOSED

    @override
    def approve(self) -> RecommendationState:
        return ApprovedState()

    @override
    def approve_with_changes(self) -> RecommendationState:
        return ApprovedWithChangesState()

    @override
    def reject(self) -> RecommendationState:
        return RejectedState()

    @override
    def expire(self) -> RecommendationState:
        return ExpiredState()


@final
class ApprovedState(RecommendationState):
    status = RecommendationStatus.APPROVED

    @override
    def apply(self) -> RecommendationState:
        return AppliedState()


@final
class ApprovedWithChangesState(RecommendationState):
    status = RecommendationStatus.APPROVED_WITH_CHANGES

    @override
    def apply(self) -> RecommendationState:
        return AppliedState()


@final
class RejectedState(RecommendationState):
    status = RecommendationStatus.REJECTED  # terminal: no transitions


@final
class AppliedState(RecommendationState):
    status = RecommendationStatus.APPLIED  # terminal


@final
class ExpiredState(RecommendationState):
    status = RecommendationStatus.EXPIRED  # terminal
```

`AlertState` (`OPEN → ACKNOWLEDGED → RESOLVED` y `OPEN → ESCALATED → ACKNOWLEDGED → RESOLVED`; subir de nivel dentro de `ESCALATED` no cambia el estado) y `PatientAccountState` (`IMPORTED → INVITED → ACTIVE ⇄ SUSPENDED`, `INVITED → INVITED`, `INVITED → IMPORTED` y cualquier no terminal `→ DEACTIVATED`) tienen **la misma forma**: una base con las acciones (`acknowledge`, `escalate`, `resolve`; `issue_credentials`, `activate`, `suspend`, `reactivate`, `deactivate`, `revoke_invitation`), una clase por estado y `from_status()`. Las tablas de transiciones están en [`Arquitectura.md`](../docs/Arquitectura.md), secciones 8 y 9, y en [`Actores-y-permisos.md`](../docs/Actores-y-permisos.md), sección 5. Las transiciones de la cuenta llevan motivo (suspender, desactivar) y el efecto de seguridad (`tv + 1`, revocar familias) lo aplica el caso de uso al confirmarlas, no el estado.

El circuito de la IA usa el `Clock` inyectado, así que se prueba sin esperar tiempo real:

```python
# insumap/infrastructure/ai/circuit_breaker.py
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import final, override

from insumap.shared.time import Clock


@final
class CircuitBreaker:
    """Context of the circuit. Thresholds come from environment settings."""

    def __init__(self, *, failure_threshold: int, open_for: timedelta, clock: Clock) -> None:
        self.failure_threshold = failure_threshold
        self.open_for = open_for
        self._clock = clock
        self._state: CircuitBreakerState = ClosedState()
        self.failures = 0
        self.opened_at: datetime | None = None

    @property
    def state_name(self) -> str:
        return self._state.name

    def now(self) -> datetime:
        return self._clock.now()

    def transition_to(self, state: CircuitBreakerState) -> None:
        self._state = state

    def allow_request(self) -> bool:
        return self._state.allow_request(self)

    def record_success(self) -> None:
        self._state.on_success(self)

    def record_failure(self) -> None:
        self._state.on_failure(self)


class CircuitBreakerState(ABC):
    """Pattern: P18 State"""

    name: str

    @abstractmethod
    def allow_request(self, breaker: CircuitBreaker) -> bool: ...

    @abstractmethod
    def on_success(self, breaker: CircuitBreaker) -> None: ...

    @abstractmethod
    def on_failure(self, breaker: CircuitBreaker) -> None: ...


def _open(breaker: CircuitBreaker) -> None:
    breaker.opened_at = breaker.now()
    breaker.transition_to(OpenState())


@final
class ClosedState(CircuitBreakerState):
    name = "CLOSED"

    @override
    def allow_request(self, breaker: CircuitBreaker) -> bool:
        return True

    @override
    def on_success(self, breaker: CircuitBreaker) -> None:
        breaker.failures = 0

    @override
    def on_failure(self, breaker: CircuitBreaker) -> None:
        breaker.failures += 1
        if breaker.failures >= breaker.failure_threshold:
            _open(breaker)


@final
class OpenState(CircuitBreakerState):
    name = "OPEN"

    @override
    def allow_request(self, breaker: CircuitBreaker) -> bool:
        if breaker.opened_at is not None and breaker.now() - breaker.opened_at >= breaker.open_for:
            breaker.transition_to(HalfOpenState())
            return True
        return False

    @override
    def on_success(self, breaker: CircuitBreaker) -> None:
        return None

    @override
    def on_failure(self, breaker: CircuitBreaker) -> None:
        return None


@final
class HalfOpenState(CircuitBreakerState):
    name = "HALF_OPEN"

    @override
    def allow_request(self, breaker: CircuitBreaker) -> bool:
        return True

    @override
    def on_success(self, breaker: CircuitBreaker) -> None:
        breaker.failures = 0
        breaker.transition_to(ClosedState())

    @override
    def on_failure(self, breaker: CircuitBreaker) -> None:
        _open(breaker)
```

**Prueba** (`test_alert_state.py`, `test_recommendation_state.py`, `test_patient_account_state.py`, `test_circuit_breaker_state.py`): una tabla `parametrize` de todas las combinaciones (estado, acción) con su resultado esperado: cada transición válida pasa, cada inválida lanza `InvalidStateTransitionError` y los terminales no tienen salidas; `from_status()` cubre todo el `StrEnum` (si se agrega un valor, mypy falla por `assert_never`). Circuito: tantos fallos como el umbral abren; con el `FixedClock` avanzado más allá de `open_for` pasa a `HALF_OPEN`; el éxito cierra y el fallo reabre (ejemplo abajo).

Ejemplo de prueba del circuito (`tests/unit/patterns/test_circuit_breaker_state.py`), sin esperar tiempo real:

```python
def test_circuit_opens_after_threshold_and_half_opens_after_the_open_period() -> None:
    clock = FixedClock(NOW)
    breaker = CircuitBreaker(failure_threshold=2, open_for=timedelta(seconds=30), clock=clock)

    breaker.record_failure()
    breaker.record_failure()
    assert breaker.state_name == "OPEN"
    assert not breaker.allow_request()

    clock.advance(timedelta(seconds=31))
    assert breaker.allow_request()
    assert breaker.state_name == "HALF_OPEN"

    breaker.record_success()
    assert breaker.state_name == "CLOSED"
```

**Antipatrones**
- Un `Enum` con un `if` por transición repartido en los casos de uso, o `pybreaker`/`tenacity` para el circuito (sección 1.1 del catálogo).
- Un `match` sobre el estado en cada lugar que lo usa.
- Cambiar el estado asignando el `status` de la entidad directamente, sin pasar por el estado.
- Medir el tiempo de apertura con `time.time()`.

### P19. Strategy: `RiskScoringStrategy`, `GlycemicTargetStrategy` y `TitrationStrategy`

- **Dónde vive:** `insumap/domain/triage/`, `insumap/domain/metrics/`, `insumap/domain/treatment/` e `insumap/application/triage/` (`AiRiskScoringStrategy`, que usa un puerto). Se elige **por un código guardado en la BD** (perfil, configuración de la clínica) y se registra con cada resultado.
- **Regla:** los números de cada estrategia (umbrales, metas, cambio máximo) llegan del perfil o del protocolo (BD); la clase decide **cómo** se calcula, nunca **con qué números**.

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import final, override

from insumap.application.ai.ports import AiServicePort
from insumap.domain.metrics.window import GlucoseWindow


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


@dataclass(frozen=True, slots=True, kw_only=True)
class RiskScore:
    level: RiskLevel
    strategy_code: str


@dataclass(frozen=True, slots=True, kw_only=True)
class RiskFeatures:
    subject_ref: str
    tbr_pct: float
    tir_pct: float


@dataclass(frozen=True, slots=True, kw_only=True)
class TideThresholds:
    """From alerts.alert_rules."""

    tbr_pct_high: float
    tir_pct_low: float


class RiskScoringStrategy(ABC):
    """Pattern: P19 Strategy"""

    code: str

    @abstractmethod
    def score(self, features: RiskFeatures) -> RiskScore: ...


@final
class RuleBasedRiskStrategy(RiskScoringStrategy):
    code = "RULES_TIDE"

    def __init__(self, thresholds: TideThresholds) -> None:
        self._t = thresholds

    @override
    def score(self, features: RiskFeatures) -> RiskScore:
        high = features.tbr_pct >= self._t.tbr_pct_high or features.tir_pct <= self._t.tir_pct_low
        return RiskScore(level=RiskLevel.HIGH if high else RiskLevel.LOW, strategy_code=self.code)


@final
class AiRiskScoringStrategy(RiskScoringStrategy):
    code = "AI_IA2"

    def __init__(self, ai: AiServicePort, *, high_from: float, medium_from: float) -> None:
        self._ai = ai
        self._high_from = high_from
        self._medium_from = medium_from

    @override
    def score(self, features: RiskFeatures) -> RiskScore:
        result = self._ai.score_risk(
            features.subject_ref, {"tbr_pct": features.tbr_pct, "tir_pct": features.tir_pct}
        )
        level = (
            RiskLevel.HIGH
            if result.score >= self._high_from
            else RiskLevel.MEDIUM if result.score >= self._medium_from else RiskLevel.LOW
        )
        return RiskScore(level=level, strategy_code=self.code)


@dataclass(frozen=True, slots=True, kw_only=True)
class TargetProfile:
    """From care.target_profiles (versioned)."""

    low_mg_dl: Decimal
    high_mg_dl: Decimal
    max_tbr_pct: Decimal
    min_tir_pct: Decimal


class GlycemicTargetStrategy(ABC):
    code: str

    @abstractmethod
    def is_on_target(self, window: GlucoseWindow, profile: TargetProfile) -> bool: ...


def _pct(count: int, total: int) -> Decimal:
    return Decimal(count) * 100 / Decimal(total) if total else Decimal(0)


@final
class AdultStandardTargetStrategy(GlycemicTargetStrategy):
    code = "ADULT_STANDARD"

    @override
    def is_on_target(self, window: GlucoseWindow, profile: TargetProfile) -> bool:
        total = len(window.points)
        in_range = sum(1 for p in window.points if profile.low_mg_dl <= p.mg_dl <= profile.high_mg_dl)
        return _pct(in_range, total) >= profile.min_tir_pct


@final
class OlderOrHighRiskTargetStrategy(GlycemicTargetStrategy):
    """Hypoglycemia first: time below range decides before time in range."""

    code = "OLDER_OR_HIGH_RISK"

    @override
    def is_on_target(self, window: GlucoseWindow, profile: TargetProfile) -> bool:
        total = len(window.points)
        below = sum(1 for p in window.points if p.mg_dl < profile.low_mg_dl)
        if _pct(below, total) > profile.max_tbr_pct:
            return False
        return AdultStandardTargetStrategy().is_on_target(window, profile)


@dataclass(frozen=True, slots=True, kw_only=True)
class TitrationProtocol:
    """From care.protocol_templates."""

    fasting_low_mg_dl: Decimal
    fasting_high_mg_dl: Decimal
    step_units: Decimal
    max_change_units: Decimal


class TitrationStrategy(ABC):
    code: str

    @abstractmethod
    def suggest(self, median_fasting_mg_dl: Decimal, protocol: TitrationProtocol) -> Decimal | None:
        """Units to add (positive) or remove (negative); None means no change."""


@final
class FastingGlucoseTitrationStrategy(TitrationStrategy):
    code = "FASTING_GLUCOSE"

    @override
    def suggest(self, median_fasting_mg_dl: Decimal, protocol: TitrationProtocol) -> Decimal | None:
        if median_fasting_mg_dl > protocol.fasting_high_mg_dl:
            return min(protocol.step_units, protocol.max_change_units)
        if median_fasting_mg_dl < protocol.fasting_low_mg_dl:
            return -min(protocol.step_units, protocol.max_change_units)
        return None
```

`PregnancyTargetStrategy` tiene la misma forma que las otras dos metas, con el perfil de embarazo de `care.target_profiles` ([`Metricas-clinicas.md`](../docs/Metricas-clinicas.md)). La estrategia llega al caso de uso por un `StrategyRegistry` simple que mapea el `code` guardado a la clase y falla si el código no existe; se arma en `container.py`.

**Prueba** (`test_risk_scoring_strategy.py`, `test_glycemic_target_strategy.py`, `test_titration_strategy.py`): casos justo en el límite, por encima y por debajo, con perfiles y protocolos **declarados en la prueba**; ningún ajuste supera `max_change_units`; la estrategia de IA con un doble de `AiServicePort`; la de reglas no llama a la IA.

**Antipatrones**
- Funciones sueltas elegidas con `if`, o `lambda` en un diccionario (no se pueden persistir por código ni probar por nombre).
- Un `70` o un `180` dentro de una estrategia.
- Que una estrategia lea la BD o el reloj: recibe todo por argumento.

### P20. Template Method: `ReportGenerator.generate()` y `PatientImportPipeline.run()`

- **Dónde vive:** `insumap/infrastructure/reports/generators.py` (`ReportGenerator`); la plantilla `PatientImportPipeline` en `insumap/application/onboarding/pipeline.py` y las subclases en `insumap/infrastructure/integration/fhir/` y `.../csv/`.
- **Regla:** el método plantilla es `@final`: nadie puede saltarse un paso ni cambiar el orden. Las subclases solo completan los pasos abstractos.

```python
# insumap/infrastructure/reports/generators.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import final, override

from insumap.infrastructure.reports.documents import ReportDocumentFactory


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportContext:
    title: str
    is_demo: bool
    disclaimer: str  # from messages_es.json
    demo_mark: str  # from messages_es.json


class ReportGenerator(ABC):
    """Pattern: P20 Template Method"""

    def __init__(self, documents: ReportDocumentFactory) -> None:
        self._documents = documents

    @final
    def generate(self, context: ReportContext) -> str:
        parts = [self.write_header(context)]
        parts.extend(self.write_sections(context))
        parts.append(self.write_footer(context))
        return "\n".join(parts)

    def write_header(self, context: ReportContext) -> str:
        return self._documents.create_header(context.title).render()

    @abstractmethod
    def write_sections(self, context: ReportContext) -> list[str]: ...

    def write_footer(self, context: ReportContext) -> str:
        return self._documents.create_footer(
            is_demo=context.is_demo, disclaimer=context.disclaimer, demo_mark=context.demo_mark
        ).render()


@final
class PatientReport(ReportGenerator):
    @override
    def write_sections(self, context: ReportContext) -> list[str]:
        return ["<patient-sections/>"]  # AGP, TIR and events from the facade


@final
class ClinicReport(ReportGenerator):
    @override
    def write_sections(self, context: ReportContext) -> list[str]:
        return ["<clinic-kpis/>"]  # aggregates only, no individual clinical data


@final
class PreVisitSummary(ReportGenerator):
    @override
    def write_sections(self, context: ReportContext) -> list[str]:
        return ["<pre-visit/>"]
```

```python
# insumap/application/onboarding/pipeline.py
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import final
from uuid import UUID

from insumap.application.onboarding.integration import (
    ClinicIntegrationFactory,
    PatientImportCandidate,
)
from insumap.shared.errors import InsumapError


@dataclass(frozen=True, slots=True, kw_only=True)
class RowOutcome:
    row_number: int
    status: str  # CREATED, SKIPPED_DUPLICATE or REJECTED
    issues: tuple[str, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class ImportSummary:
    batch_id: UUID
    outcomes: tuple[RowOutcome, ...]


class ImportRepositoryPort(ABC):
    @abstractmethod
    def existing_mrns(self) -> frozenset[str]: ...

    @abstractmethod
    def persist(
        self, batch_id: UUID, accepted: Sequence[PatientImportCandidate], outcomes: Sequence[RowOutcome]
    ) -> None: ...


class PatientImportPipeline(ABC):
    """Fixed order: read, parse, validate, map, deduplicate, persist, emit.

    Pattern: P20 Template Method
    """

    def __init__(self, repository: ImportRepositoryPort) -> None:
        self._repository = repository

    @final
    def run(self, raw: bytes, *, batch_id: UUID) -> ImportSummary:
        content = self.read(raw)
        factory = self.integration_factory()  # one family per run (P03)
        parser, mapper, validator = (
            factory.create_parser(),
            factory.create_mapper(),
            factory.create_validator(),
        )
        known = set(self._repository.existing_mrns())
        accepted: list[PatientImportCandidate] = []
        outcomes: list[RowOutcome] = []
        for number, row in enumerate(parser.parse(content), start=1):
            try:
                candidate = mapper.to_candidate(row)
            except InsumapError as error:
                outcomes.append(RowOutcome(row_number=number, status="REJECTED", issues=(str(error.detail.get("issue")),)))
                continue
            issues = validator.validate(candidate)
            if issues:
                outcomes.append(RowOutcome(row_number=number, status="REJECTED", issues=issues))
            elif candidate.mrn in known:
                outcomes.append(RowOutcome(row_number=number, status="SKIPPED_DUPLICATE", issues=()))
            else:
                known.add(candidate.mrn)
                accepted.append(candidate)
                outcomes.append(RowOutcome(row_number=number, status="CREATED", issues=()))
        self._repository.persist(batch_id, accepted, outcomes)
        return ImportSummary(batch_id=batch_id, outcomes=tuple(outcomes))  # PatientsImported goes out after the commit

    @abstractmethod
    def read(self, raw: bytes) -> bytes:
        """Primitive step: decode the file (UTF-8 only) and reject what is not valid."""

    @abstractmethod
    def integration_factory(self) -> ClinicIntegrationFactory:
        """Primitive step: the P03 family of this format."""
```

`FhirPatientImportPipeline` y `CsvPatientImportPipeline` solo implementan `read()` (el CSV quita el BOM) e `integration_factory()`. Un archivo grande se lee con el límite de bytes de `FieldLimits` antes de llegar a `run()`.

**Prueba** (`test_report_generator.py` y `test_patient_import_pipeline.py`): el orden de llamadas (subclase de prueba que registra cada paso); la marca "Datos simulados" aparece en el pie solo con `is_demo`; una fila inválida no aborta el lote; un duplicado queda como `SKIPPED_DUPLICATE`; `generate` y `run` no se pueden sobrescribir (`mypy` lo impide con `@final`).

**Antipatrones**
- Una función por formato que repite los pasos comunes.
- Un método plantilla sin `@final`, o pasos que la subclase puede saltarse.
- Que una subclase persista antes de deduplicar.
- Guardar el archivo original o la fila cruda: `import_rows` guarda número de fila, estado y códigos.

### P21. Visitor: `ClinicalEventVisitor`

- **Dónde vive:** los elementos y el visitante abstracto en `insumap/domain/monitoring/clinical_event.py`; los visitantes de exportación (`CsvExportVisitor`, `FhirExportVisitor`) en `insumap/infrastructure/` porque conocen formatos externos.
- **Regla:** un método por tipo; agregar un tipo de evento obliga a implementar su método en **cada** visitante y mypy lo detecta. La unión cerrada se usa en `match` solo con `assert_never` como control de exhaustividad.

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import final, override


class ClinicalEventVisitor[R](ABC):
    """Pattern: P21 Visitor"""

    @abstractmethod
    def visit_glucose_reading(self, event: GlucoseReading) -> R: ...

    @abstractmethod
    def visit_insulin_dose(self, event: InsulinDose) -> R: ...

    @abstractmethod
    def visit_meal(self, event: Meal) -> R: ...

    @abstractmethod
    def visit_physical_activity(self, event: PhysicalActivity) -> R: ...

    @abstractmethod
    def visit_symptom(self, event: Symptom) -> R: ...


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class GlucoseReading:
    at: datetime
    mg_dl: Decimal

    def accept[R](self, visitor: ClinicalEventVisitor[R]) -> R:
        return visitor.visit_glucose_reading(self)


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class InsulinDose:
    at: datetime
    kind: str
    units: Decimal

    def accept[R](self, visitor: ClinicalEventVisitor[R]) -> R:
        return visitor.visit_insulin_dose(self)


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class Meal:
    at: datetime
    carbs_g: Decimal

    def accept[R](self, visitor: ClinicalEventVisitor[R]) -> R:
        return visitor.visit_meal(self)


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class PhysicalActivity:
    at: datetime
    minutes: int

    def accept[R](self, visitor: ClinicalEventVisitor[R]) -> R:
        return visitor.visit_physical_activity(self)


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class Symptom:
    at: datetime
    code: str

    def accept[R](self, visitor: ClinicalEventVisitor[R]) -> R:
        return visitor.visit_symptom(self)


type ClinicalEvent = GlucoseReading | InsulinDose | Meal | PhysicalActivity | Symptom

FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _csv_cell(text: str) -> str:
    """Neutralize spreadsheet formulas (Seguridad 13.4)."""
    return f"'{text}" if text.startswith(FORMULA_PREFIXES) else text


@final
class CsvExportVisitor(ClinicalEventVisitor[str]):
    """One CSV line per event; it carries no identification data."""

    @override
    def visit_glucose_reading(self, event: GlucoseReading) -> str:
        return f"{event.at.isoformat()},glucose,{event.mg_dl}"

    @override
    def visit_insulin_dose(self, event: InsulinDose) -> str:
        return f"{event.at.isoformat()},insulin,{_csv_cell(event.kind)}:{event.units}"

    @override
    def visit_meal(self, event: Meal) -> str:
        return f"{event.at.isoformat()},meal,{event.carbs_g}"

    @override
    def visit_physical_activity(self, event: PhysicalActivity) -> str:
        return f"{event.at.isoformat()},activity,{event.minutes}"

    @override
    def visit_symptom(self, event: Symptom) -> str:
        return f"{event.at.isoformat()},symptom,{_csv_cell(event.code)}"


@final
class TimelineVisitor(ClinicalEventVisitor[tuple[datetime, str]]):
    @override
    def visit_glucose_reading(self, event: GlucoseReading) -> tuple[datetime, str]:
        return event.at, "GLUCOSE"

    @override
    def visit_insulin_dose(self, event: InsulinDose) -> tuple[datetime, str]:
        return event.at, "INSULIN"

    @override
    def visit_meal(self, event: Meal) -> tuple[datetime, str]:
        return event.at, "MEAL"

    @override
    def visit_physical_activity(self, event: PhysicalActivity) -> tuple[datetime, str]:
        return event.at, "ACTIVITY"

    @override
    def visit_symptom(self, event: Symptom) -> tuple[datetime, str]:
        return event.at, "SYMPTOM"
```

**Prueba** (`test_clinical_event_visitor.py`): cada tipo va a su método (un visitante de prueba que cuenta); la línea de tiempo sale ordenada por hora; el CSV no incluye identificadores y una celda `=HYPERLINK(...)` sale con `'`. Un visitante al que le falte un método no se puede instanciar (`TypeError`), y mypy lo rechaza al escribirlo.

**Antipatrones**
- `isinstance` o `match` repetido en cada exportador, o `functools.singledispatch` (sección 1.1 del catálogo).
- Un visitante que modifica los eventos (son inmutables).
- Agregar un tipo de evento sin actualizar todos los visitantes "después".

### P22. Interpreter (opcional): `AlertRuleInterpreter`

- **Dónde vive:** `insumap/domain/alerts/rule_dsl.py`. Analiza texto como `glucose < 70 for 15m and rate < -2 per min` y lo traduce al árbol P08. La precedencia es `and` sobre `or`. Nunca `eval`: una gramática pequeña con errores de dominio (`ALERT_RULE_SYNTAX_ERROR` con la posición) y sin ejecutar código.
- **Contexto:** `RuleDslLimits` (cotas permitidas para los números del texto) viene de la configuración de la clínica en la BD; el dominio no las escribe.

```python
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import final, override

from insumap.domain.alerts.rules import (
    AllOfRule,
    AlertRule,
    AnyOfRule,
    DurationRule,
    RateOfChangeRule,
    ThresholdRule,
)
from insumap.shared.errors import ErrorCode, InsumapError

TOKEN = re.compile(r"\s*(?:(?P<num>-?\d+(?:\.\d+)?)|(?P<word>[a-z]+)|(?P<op><))")


@dataclass(frozen=True, slots=True, kw_only=True)
class RuleDslLimits:
    min_threshold: Decimal
    max_threshold: Decimal
    max_minutes: int


class RuleExpression(ABC):
    @abstractmethod
    def to_rule(self) -> AlertRule: ...


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class ComparisonExpression(RuleExpression):
    below: Decimal

    @override
    def to_rule(self) -> AlertRule:
        return ThresholdRule(below_mg_dl=self.below)


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class ForDurationExpression(RuleExpression):
    below: Decimal
    minutes: int

    @override
    def to_rule(self) -> AlertRule:
        return DurationRule(below_mg_dl=self.below, lasting=timedelta(minutes=self.minutes))


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class RateExpression(RuleExpression):
    drop_per_minute: Decimal

    @override
    def to_rule(self) -> AlertRule:
        return RateOfChangeRule(drop_per_minute_mg_dl=self.drop_per_minute)


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class AndExpression(RuleExpression):
    parts: tuple[RuleExpression, ...]

    @override
    def to_rule(self) -> AlertRule:
        return AllOfRule([part.to_rule() for part in self.parts])


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class OrExpression(RuleExpression):
    parts: tuple[RuleExpression, ...]

    @override
    def to_rule(self) -> AlertRule:
        return AnyOfRule([part.to_rule() for part in self.parts])


def _syntax_error(position: int) -> InsumapError:
    return InsumapError(ErrorCode.ALERT_RULE_SYNTAX_ERROR, detail={"position": position})


@final
class AlertRuleInterpreter:
    """Recursive-descent parser: or_expr > and_expr > term.

    Pattern: P22 Interpreter
    """

    def __init__(self, limits: RuleDslLimits) -> None:
        self._limits = limits
        self._tokens: list[tuple[str, int]] = []
        self._i = 0

    def parse(self, text: str) -> RuleExpression:
        self._tokens = self._tokenize(text)
        self._i = 0
        expression = self._or()
        if self._i != len(self._tokens):
            raise _syntax_error(self._tokens[self._i][1])
        return expression

    def _tokenize(self, text: str) -> list[tuple[str, int]]:
        tokens: list[tuple[str, int]] = []
        position = 0
        while position < len(text):
            match = TOKEN.match(text, position)
            if match is None or match.end() == position:
                if text[position:].strip() == "":
                    break
                raise _syntax_error(position)
            tokens.append((match.group().strip(), match.start() + len(match.group()) - len(match.group().lstrip())))
            position = match.end()
        return tokens

    def _peek(self) -> str | None:
        return self._tokens[self._i][0] if self._i < len(self._tokens) else None

    def _take(self, expected: str | None = None) -> str:
        if self._i >= len(self._tokens):
            raise _syntax_error(self._tokens[-1][1] + 1 if self._tokens else 0)
        token, position = self._tokens[self._i]
        if expected is not None and token != expected:
            raise _syntax_error(position)
        self._i += 1
        return token

    def _number(self) -> Decimal:
        position = self._tokens[self._i][1] if self._i < len(self._tokens) else 0
        try:
            return Decimal(self._take())
        except InvalidOperation:
            raise _syntax_error(position) from None

    def _or(self) -> RuleExpression:
        parts = [self._and()]
        while self._peek() == "or":
            self._take("or")
            parts.append(self._and())
        return parts[0] if len(parts) == 1 else OrExpression(parts=tuple(parts))

    def _and(self) -> RuleExpression:
        parts = [self._term()]
        while self._peek() == "and":
            self._take("and")
            parts.append(self._term())
        return parts[0] if len(parts) == 1 else AndExpression(parts=tuple(parts))

    def _term(self) -> RuleExpression:
        subject = self._take()
        if subject == "glucose":
            self._take("<")
            below = self._bounded(self._number())
            if self._peek() == "for":
                self._take("for")
                minutes = int(self._number())
                self._take("m")
                if not 0 < minutes <= self._limits.max_minutes:
                    raise _syntax_error(self._tokens[self._i - 2][1])
                return ForDurationExpression(below=below, minutes=minutes)
            return ComparisonExpression(below=below)
        if subject == "rate":
            self._take("<")
            value = self._number()
            self._take("per")
            self._take("min")
            return RateExpression(drop_per_minute=-value)
        raise _syntax_error(self._tokens[self._i - 1][1])

    def _bounded(self, value: Decimal) -> Decimal:
        if not self._limits.min_threshold <= value <= self._limits.max_threshold:
            raise _syntax_error(self._tokens[self._i - 1][1])
        return value
```

**Prueba** (`test_alert_rule_interpreter.py`): precedencia de `and` sobre `or` (`a or b and c` se agrupa como `a or (b and c)`); unidades y cotas (`for 0m` y un umbral fuera de las cotas de prueba se rechazan); texto inválido (`glucose > 70`, `glucose < for`) con la `position` del error en `detail`; el árbol traducido evalúa igual que el construido a mano con P08; una cadena como `__import__('os')` solo produce `ALERT_RULE_SYNTAX_ERROR`.

**Antipatrones**
- `eval`, `ast.literal_eval` o `string.Template` (sección 1.1 del catálogo): no validan la gramática ni dan errores de dominio.
- Expresiones regulares sueltas sin gramática.
- Aceptar números sin las cotas del contexto, o guardar el árbol sin guardar también el texto original.

### P23. Flyweight (opcional): `InsulinProductFlyweightFactory`

- **Dónde vive:** `insumap/domain/treatment/insulin_product.py`. El catálogo es una semilla de `insumap-database`; se lee **una vez** al armar la fábrica en `container.py`.
- **Regla:** el estado intrínseco (código, nombre, tipo, inicio y duración de acción, concentración) es inmutable y compartido; el extrínseco (unidades, hora, paciente) queda en la dosis. El mismo código devuelve **la misma instancia** (`is`).

```python
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import final

from insumap.shared.errors import ErrorCode, InsumapError


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class InsulinProduct:
    code: str
    name: str
    kind: str
    onset_minutes: int
    duration_minutes: int
    concentration_u_ml: Decimal


@final
class InsulinProductFlyweightFactory:
    """Pool of shared, immutable insulin products.

    Pattern: P23 Flyweight
    """

    def __init__(self, catalog: Iterable[InsulinProduct]) -> None:
        pool: dict[str, InsulinProduct] = {}
        for product in catalog:
            pool.setdefault(product.code, product)
        self._pool: Mapping[str, InsulinProduct] = MappingProxyType(pool)

    def get(self, code: str) -> InsulinProduct:
        try:
            return self._pool[code]
        except KeyError:
            raise InsumapError(
                ErrorCode.UNKNOWN_INSULIN_PRODUCT, params={"code": code}
            ) from None
```

**Prueba** (`test_insulin_product_flyweight_factory.py`): el mismo código devuelve la misma instancia (`is`); códigos distintos, instancias distintas; un código desconocido falla; el pool queda inmutable tras armarse (`MappingProxyType`); un catálogo con un código repetido conserva el primero.

**Antipatrones**
- `functools.lru_cache` sobre una función de carga, o la caché de identidad de SQLAlchemy (no sale de la capa de persistencia).
- Un pool mutable que cualquiera puede ensanchar en tiempo de ejecución.
- Guardar el estado extrínseco (unidades, paciente) en el producto compartido.

## 4. Armado en `container.py`

Los patrones se ensamblan **solo** en `build_container(settings)` (hoy la clase `Container` de `insumap/container.py` arma `Settings`, `Clock`, el catálogo y el logging; el resto se agrega por fase). El orden de las capas es visible en una sola lectura:

```python
# Fragmento ilustrativo de insumap/container.py (los nombres de puertos son ilustrativos)
clock: Clock = SystemClock.instance()  # P01

# Lectura clínica: auditoría por fuera, proxy en medio, repositorio por dentro (P09 y P11).
patient_records: PatientRecordPort = PhiAccessAuditDecorator(
    PatientRecordAccessProxy(
        subject=PatientRecordRepository(uow_factory),
        patients=patient_directory,
        assignments=care_team_assignments,
        policy=PatientAccessPolicy(),
        clock=clock,
    ),
    log=data_access_log,
    clock=clock,
)

# IA: el caso de uso solo ve el puerto; el proxy aplica circuito y respaldo (P06, P11, P18).
ai_service: AiServicePort = RemoteAiServiceProxy(
    remote=AiServiceClientAdapter(http_client, settings.ai_service_token, settings.ai_timeout_seconds),
    fallback=RuleBasedAiFallbackAdapter(...),
    breaker=CircuitBreaker(failure_threshold=settings.ai_circuit_failure_threshold, open_for=..., clock=clock),
    enabled=settings.ai_enabled,
)

# Comandos: cada handler decorado con la auditoría (P13 y P09); un comando sin handler falla aquí.
command_bus = InMemoryCommandBus(
    [
        bind(RejectRecommendationCommand, AuditingCommandHandler(RejectRecommendationCommandHandler(decisions), audit_log, clock)),
        # ... uno por comando
    ],
    required=ALL_COMMAND_TYPES,
)

# Eventos: los suscriptores se registran por tipo (P17).
publisher = InProcessDomainEventPublisher()
publisher.subscribe(GlucoseReadingRecorded, EvaluateAlertsOnReadingRecorded(...))
```

Reglas del armado:
- Ningún caso de uso, fachada ni router recibe el repositorio **y** el proxy: solo el puerto armado arriba.
- Los parámetros de entorno (`AI_TIMEOUT_*`, `AI_CIRCUIT_*`, `AI_ENABLED`) salen de `Settings`; los clínicos, de puertos que leen la BD.
- `import-linter` impide que `api` importe `container`; la prueba `tests/unit/test_container.py` (ya existe) crece con una comprobación por cadena: el puerto de lectura clínica es un `PhiAccessAuditDecorator` cuyo `inner` es un `PatientRecordAccessProxy`.

## 5. Lista de verificación de un patrón nuevo o modificado

- [ ] Clase propia con `Pattern: Pnn <Name>` en el docstring y los paquetes de la sección 3 de [`architecture.md`](architecture.md).
- [ ] `@final` en las hojas y en el método plantilla; `@override` en cada método sobrescrito; sin `Any`.
- [ ] Sin `datetime.now()`, `uuid4()`, `os.getenv` ni valores clínicos en el código; hora e ids por argumento.
- [ ] Errores como `*Error` con `ErrorCode` agregado a `messages_es.json` y a `STATUS_BY_CODE`.
- [ ] Prueba en `tests/unit/patterns/test_<clase>.py` sin FastAPI ni BD, con `FixedClock` y `SequentialIdGenerator`.
- [ ] Si el patrón toca datos clínicos: prueba de integración con dos clínicas y un médico no asignado ([`testing-plan.md`](testing-plan.md)).
- [ ] Armado en `container.py` y `uv run lint-imports` en verde.
- [ ] Anotado en "Patrones de diseño involucrados" del PR; el catálogo se actualiza si cambia la clase principal.

## 6. Contradicciones y vacíos detectados

Esta guía **no** resuelve estos puntos en silencio. Cada uno necesita una decisión del documento dueño.

| # | Dónde | Qué se observa | Qué hace esta guía |
|---|---|---|---|
| 1 | Catálogo (P09) y [`Seguridad.md`](../docs/Seguridad.md) 7.2 | El catálogo dice que `AuditingCommandHandler` registra "éxito o fallo". Seguridad dice que la fila va "en la misma transacción de la acción: si la acción falla, no hay fila", y su prueba exige que no quede fila. | El esqueleto sigue el catálogo (éxito en la misma transacción, fallo por `record_failure` en transacción independiente). Falta decidir. |
| 2 | `docs/` y código: `DomainError` | Arquitectura y `configuration.md` hablan de `DomainError` en `shared.errors`; el código tiene `InsumapError`. | Se usa `InsumapError`. |
| 3 | `docs/` y código: ubicación del reloj | Arquitectura y el catálogo ubican `SystemClock` en `shared/time/system_clock.py`; el código está en `shared/time.py`. | Se usa la ruta del código. |
| 4 | Catálogo (P01) y código | La prueba de `SystemClock` debería estar en `tests/unit/patterns/test_system_clock.py`; está en `tests/unit/shared/`. | Se pide moverla al implementar la carpeta `patterns/`. |
| 5 | [`testing-plan.md`](testing-plan.md) y código | El reloj de prueba se llama `FrozenClock` (con `advance(minutes=...)`); el código tiene `FixedClock` (con `advance(timedelta)`) en `tests/support/`. Arquitectura 2.5 pone las fábricas en `tests/factories/`. | Se usa `FixedClock` y `tests/support/`. |
| 6 | `configuration.md` y esta guía | `MG_DL_PER_MMOL_L` aparece como `float` (18.016). | Se usa `Decimal("18.016")` para no arrastrar error de coma flotante; confirmar. |
| 7 | Arquitectura 2.1 | La tabla de capas pone `ErrorCode` y `DomainError` en `shared.errors` como paquete; en el código es el módulo `shared/errors.py`. | Se usa el módulo. |
| 8 | Catálogo (P18) y Arquitectura 11 | El catálogo y Actores-y-permisos devuelven una invitación vencida a `IMPORTED`; Arquitectura 11 dice que "la cuenta sigue `INVITED` hasta que se reenvíe". | `PatientAccountState` sigue el catálogo y Actores-y-permisos. |
| 9 | Catálogo (P03) y Arquitectura 8 | Arquitectura describe la importación como `multipart/form-data`; Seguridad 13.3 exige cuerpo crudo (`application/fhir+json`, `text/csv`). | `PatientImportPipeline.read()` recibe `bytes`, válido para ambos. |
| 10 | Catálogo (P11) y Arquitectura 4 | Para `PLATFORM_ADMIN` el catálogo no dice el código; Arquitectura dice `403`. | `PatientAccessPolicy` responde `FORBIDDEN`. |
| 11 | P22 | La cota de los números del DSL (`RuleDslLimits`) no figura en ningún documento. | Se propone como parámetro de la clínica en la BD. |
| 12 | P14 | El paquete `tzdata` no figura entre las dependencias de `pyproject.toml`; la imagen `python:3.13-slim` no trae la base de zonas. | Verificar al implementar. |

Relacionados: [Patrones de diseño](../docs/Patrones-de-diseno.md), [Arquitectura](../docs/Arquitectura.md), [`architecture.md`](architecture.md), [`security.md`](security.md), [`testing-plan.md`](testing-plan.md), [`configuration.md`](configuration.md)
