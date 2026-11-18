# Patrones de diseño de Insumap

> Catálogo global de los patrones del proyecto (P01 a P23) y de los patrones arquitectónicos. Cubre los cinco repositorios. Este documento fija la intención, las clases, la prueba y el dueño de cada patrón. Los esqueletos en Python 3.13 para el backend están en [`.agents/design-patterns.md`](../.agents/design-patterns.md). Los IDs `Pnn` son fijos: no se renumeran ni se reutilizan.

## 1. Introducción

### 1.1 Regla: implementación explícita aunque Python ya lo ofrezca

Insumap implementa cada patrón con su propia clase o interfaz, aunque Python, FastAPI o SQLAlchemy ya traigan un mecanismo parecido. La regla tiene cuatro razones:

1. **La intención queda escrita en el dominio.** Un `RecommendationState` con sus transiciones se lee, se revisa en un PR y se busca por su etiqueta. Un `@lru_cache` o un `Depends` no dicen qué problema del negocio resuelven.
2. **Las pruebas no dependen del framework.** Un patrón explícito se prueba con pytest puro, sin FastAPI, sin BD y con un reloj fijo.
3. **El mecanismo no es el problema.** Python sabe copiar objetos, pero no sabe que la copia de un plan nace en `DRAFT`, con versión nueva e identificadores nuevos para cada ítem. FastAPI sabe inyectar dependencias, pero no sabe que la auditoría va por fuera del proxy de acceso.
4. **Es un curso de patrones.** Cada patrón debe poder señalarse en el código (`Pattern: Pnn <Name>` en el docstring), en la prueba y en el PR.

Usar el mecanismo del lenguaje **dentro** de la clase del patrón está permitido (por ejemplo, un generador dentro de `GlucoseWindowIterator.__iter__`). Reemplazar la clase del patrón por el mecanismo no.

| Mecanismo de Python o del framework | Se parece a | Qué hace Insumap | Por qué no basta el mecanismo |
|---|---|---|---|
| Instancia a nivel de módulo (`clock = SystemClock()`) | P01 Singleton | `SystemClock` con `instance()` y `@final`, inyectado como `Clock` | Un global de módulo solo se sustituye en pruebas con *monkeypatch*. Con la interfaz `Clock`, las pruebas pasan un `FixedClock`. |
| `functools.lru_cache` y `functools.cache` | P01, P23 | `InsulinProductFlyweightFactory` con su pool; `CachingForecaster` (P09) en la IA | La caché de una función no separa estado intrínseco de extrínseco, no tiene clave de dominio y no se prueba como pool compartido. |
| Sintaxis `@decorator` de funciones | P09 Decorator | Clases que envuelven un objeto con la misma interfaz: `PhiAccessAuditDecorator(PatientRecordPort)` | El `@` se aplica al definir la función, no al componer objetos. No se puede quitar ni reordenar en `container.py` ni probar aislado. |
| Generadores y `__iter__` | P14 Iterator | `GlucoseWindowIterator`, una clase con nombre (puede usar un generador por dentro) | Las reglas de la ventana (zona de la clínica, límites nocturnos del perfil, huecos de datos) necesitan un nombre y una prueba propia. |
| `copy.deepcopy`, `copy.copy`, `copy.replace` (3.13) y `dataclasses.replace` | P05 Prototype | `ProtocolTemplate.clone_for_patient()` y `TreatmentPlan.copy_for_new_version()` | La copia tiene reglas de negocio: identificador nuevo, estado `DRAFT`, versión siguiente, identificadores nuevos para los ítems, referencia al origen y sin eventos pendientes. `deepcopy` copiaría todo eso tal cual. |
| `Depends` de FastAPI | Inyección y fábricas | Composition root en `container.py` | `Depends` ata el armado a HTTP. La cadena auditoría, proxy y repositorio debe leerse en un lugar y servir también al scheduler. |
| Eventos de sesión de SQLAlchemy (`after_commit`, `before_flush`) | P17 Observer | `DomainEventPublisher` llamado por la unidad de trabajo | Ata el dominio al ORM y esconde el orden de ejecución. |
| Señales de terceros (`blinker`) | P17 Observer | `DomainEventPublisher` propio | Agregan una dependencia sin resolver el "después del commit". |
| `match` con `assert_never` sobre uniones cerradas | P18, P21 | Se usa en las fábricas de estado (`from_status`) y como control de exhaustividad; las operaciones viven en estados y visitantes con clase | Un `match` repetido en cada lugar duplica la lógica por tipo. El visitante la concentra y mypy obliga a cubrir cada caso. |
| `functools.singledispatch` | P21 Visitor | `ClinicalEventVisitor` | No garantiza que cada tipo tenga su método ni agrupa la operación en una clase. |
| `enum.Enum` con métodos | P18 State | Una clase por estado; el `StrEnum` queda como valor persistido | Las transiciones con motivo, guardas y efectos crecen; en un enum terminan en un `if` gigante. |
| Funciones de primera clase y `lambda` | P13, P19 | `*Command` y `*Strategy` con nombre | La estrategia se guarda por código y se reconstruye; el comando se autoriza, se audita y se registra. |
| Middleware de Starlette | P12 Chain of Responsibility | Cadenas de dominio propias | El middleware es HTTP. La validación de lecturas corre también en lotes offline y en importaciones. |
| `contextlib.contextmanager` | Unit of Work | `UnitOfWork` (`abc.ABC`) con `__enter__` y `__exit__` | Es un puerto: se sustituye por un doble en las pruebas de casos de uso. |
| `pybreaker` y `tenacity` | P18, P11 | `CircuitBreaker` con `CircuitBreakerState` propio | Las transiciones usan el `Clock` inyectado y se prueban sin esperar tiempo real. Sin dependencia nueva. |
| `__getattr__` (proxy dinámico) | P11 Proxy | Proxy con la misma interfaz declarada | Un proxy dinámico rompe `mypy --strict` y esconde qué métodos se protegen. |
| `eval`, `ast.literal_eval` o `string.Template` | P22 Interpreter | `AlertRuleInterpreter` con su gramática | `eval` es inseguro y una plantilla no valida la gramática ni produce errores de dominio. |
| `typing.Protocol` en todas partes | Interfaces | `abc.ABC` para los `*Port` y los participantes de un patrón; `Protocol` solo para interfaces mínimas como `Clock` | Con `ABC`, "implementa el puerto" es explícito y mypy detecta métodos faltantes al instanciar. |

### 1.2 Cómo leer el catálogo

Cada patrón tiene:

- **Problema en Insumap:** por qué hace falta aquí.
- **Participantes:** el rol GoF de cada clase.
- **Dónde vive:** repositorio y paquete. En `insumap-backend`, paquetes de `src/insumap/` (ver [Arquitectura](Arquitectura.md), sección 2.5). En los otros repositorios, la ruta es propuesta hasta crear su esqueleto.
- **Por qué este patrón** y **alternativa descartada.**
- **Prueba:** en el backend, `tests/unit/patterns/` según [`.agents/testing-plan.md`](../.agents/testing-plan.md). Los nombres de los otros repositorios son propuestos.
- **Dueño:** la cuenta responsable de cada clase. [Plan de commits](Plan-de-commits.md) la usa como autor.

Los nombres de clase están en inglés (regla de idioma). Los nombres GoF de los patrones se conservan.

### 1.3 Ambigüedades resueltas

| Tema | Decisión |
|---|---|
| P15 Mediator | Solo existe en `insumap-frontend` (`DashboardFiltersMediator`). El backend no tiene colegas de UI que coordinar; el `CommandBus` es un *invoker* de P13, no un mediador. |
| P03 en `insumap-ai` frente a P02 en `insumap-ai` | `AiProviderFactory` (P03) decide la **familia** y garantiza que las tres piezas (`TextGenerator`, `Forecaster`, `RiskModel`) sean coherentes: todas reales (`OpenAiCompatibleProviderFactory`) o todas deterministas (`OfflineProviderFactory`). Nunca mezcla un LLM remoto con un modelo de riesgo de pruebas. `ForecasterCreator` (P02) decide la **clase** del pronosticador **dentro** de esa ranura: `ChronosForecasterCreator` (Chronos-Bolt tiny o small) o `LinearTrendForecasterCreator`. La fábrica abstracta delega su `create_forecaster()` en el creador con que se configuró; la familia offline siempre usa `LinearTrendForecasterCreator`. Ninguna clase toma las dos decisiones. |
| P03 en el backend | Hay dos fábricas abstractas: `ClinicIntegrationFactory` (familias FHIR y CSV de importación) y `ReportDocumentFactory` (familias PDF y HTML de reportes). |
| P03 y P20 en la importación | `PatientImportPipeline` (P20) fija el orden de los pasos; cada pipeline concreto pide su familia a `integration_factory()` una sola vez por corrida. La fábrica decide *con qué piezas*; la plantilla decide *en qué orden*. |
| P05 entre clases distintas | `ProtocolTemplate.clone_for_patient()` produce un `TreatmentPlan`: la plantilla es el prototipo del **contenido** del plan (ítems, perfil de metas y recordatorios), que se copia en profundidad. `TreatmentPlan.copy_for_new_version()` es el prototipo clásico (misma clase). |
| P09 y P11 en la lectura clínica | El orden es fijo: `PhiAccessAuditDecorator(PatientRecordAccessProxy(PatientRecordRepository))`. La auditoría va por fuera para registrar también los accesos denegados. |
| IDs del frontend | Sus patrones usan los IDs globales: P15 Mediator, P06 Adapter, P10 Facade, P19 Strategy y P08 Composite. Solo `DashboardFiltersMediator` está fijado; los demás nombres son propuestos y los confirma `NicoalsD`. |
| P14 en la IA | `SlidingWindowIterator` es P14 (ventanas de contexto y de evaluación). |
| P22 | La clase principal es `AlertRuleInterpreter`, que traduce el DSL de reglas al árbol de P08. |

### 1.4 Tabla resumen

| ID | Patrón | Backend (clase principal) | IA | Simulador | Frontend | Dueños |
|---|---|---|---|---|---|---|
| P01 | Singleton | `SystemClock` | `ModelRegistry` | | | Drako2305, nicomora70 |
| P02 | Factory Method | `ReportGeneratorCreator` | `ForecasterCreator` | `ScenarioCreator` | | NicoalsD, nicomora70 |
| P03 | Abstract Factory | `ClinicIntegrationFactory`, `ReportDocumentFactory` | `AiProviderFactory` | | | Drako2305, NicoalsD, nicomora70 |
| P04 | Builder | `TreatmentPlanBuilder` | `PromptBuilder` | `VirtualPatientBuilder` | | Drako2305, nicomora70 |
| P05 | Prototype | `ProtocolTemplate.clone_for_patient()`, `TreatmentPlan.copy_for_new_version()` | | `PatientArchetype.clone_with_variation()` | | Drako2305, nicomora70 |
| P06 | Adapter | `FhirPatientAdapter`, `CgmCsvAdapter`, `AiServiceClientAdapter` | `OpenAiCompatibleTextGeneratorAdapter`, `ChronosForecasterAdapter` | `SimglucoseAdapter` | `ApiDtoAdapter` (propuesto) | Drako2305, nicomora70, NicoalsD |
| P07 | Bridge | `Notification` × `NotificationChannel` | | | | NicoalsD |
| P08 | Composite | `AlertRule` | | | `DashboardWidget` (propuesto) | Drako2305, NicoalsD |
| P09 | Decorator | `PhiAccessAuditDecorator`, `AuditingCommandHandler` | `PhiRedactingTextGenerator`, `CachingForecaster` | | | Drako2305, nicomora70 |
| P10 | Facade | `DoctorDashboardFacade`, `PatientOverviewFacade` | | | `InsumapApi` (propuesto) | Drako2305, NicoalsD |
| P11 | Proxy | `PatientRecordAccessProxy`, `RemoteAiServiceProxy` | | | | Drako2305, nicomora70 |
| P12 | Chain of Responsibility | `GlucoseReadingValidationHandler`, `AlertEscalationHandler` | `GuardrailHandler` | | | nicomora70, Drako2305 |
| P13 | Command | `CommandBus` y sus comandos | | | | Drako2305 |
| P14 | Iterator | `GlucoseWindowIterator` | `SlidingWindowIterator` | `TimeStepIterator` | | Drako2305, nicomora70 |
| P15 | Mediator | Ninguno (solo frontend) | | | `DashboardFiltersMediator` | NicoalsD |
| P16 | Memento | `TreatmentPlanMemento` | | | | Drako2305 |
| P17 | Observer | `DomainEventPublisher` | | | | Drako2305 |
| P18 | State | `AlertState`, `RecommendationState`, `PatientAccountState`, `CircuitBreakerState` | | | | Drako2305, nicomora70 |
| P19 | Strategy | `RiskScoringStrategy`, `GlycemicTargetStrategy`, `TitrationStrategy` | | `GlucoseDynamicsStrategy` | `ChartRendererStrategy` (propuesto) | Drako2305, nicomora70, NicoalsD |
| P20 | Template Method | `ReportGenerator.generate()`, `PatientImportPipeline.run()` | `InferencePipeline` | `ExportPipeline` | | NicoalsD, Drako2305, nicomora70 |
| P21 | Visitor | `ClinicalEventVisitor` | | | | nicomora70 |
| P22 | Interpreter (opcional) | `AlertRuleInterpreter` | | | | Drako2305 |
| P23 | Flyweight (opcional) | `InsulinProductFlyweightFactory` | | | | Drako2305 |

## 2. Patrones arquitectónicos

| Patrón | Dónde se aplica | Reglas y referencias |
|---|---|---|
| Hexagonal (puertos y adaptadores) | Todo el backend; también `insumap-ai` en menor escala. | Capas `api`, `application`, `domain`, `infrastructure` y `shared`. Contratos `ARCH-01` a `ARCH-12` en [Arquitectura](Arquitectura.md), sección 2.3. |
| Composition root | `container.py` del backend. | Única fuente de armado; `Depends` solo para el actor. ADR-07 de [Arquitectura](Arquitectura.md). |
| Repository y Unit of Work | Persistencia del backend. | Puertos `*Port` en `application`; `*Repository` con `*Orm`; `SqlAlchemyUnitOfWork` fija `app.clinic_id` y `app.user_id` con `set_config(..., true)`. Sección 5 de [Arquitectura](Arquitectura.md). |
| DTO y Mapper | API del backend. | `*Request` y `*Response` (Pydantic) en `api`; `*Input` y `*Result` (dataclasses) en `application`. Ningún `*Orm` ni entidad sale por HTTP. |
| Circuit Breaker | Llamadas a `insumap-ai`. | `CircuitBreakerState` (P18) dentro de `RemoteAiServiceProxy` (P11). |
| Domain Events | Efectos posteriores al commit. | `DomainEventPublisher` (P17). Sin outbox (ADR-06). |
| Idempotency Key | Lecturas y lotes offline. | `client_reading_id` del cliente: mismo contenido responde `200`; otro contenido, `409`. |
| Registro append-only | Registros clínicos, decisiones y auditoría. | Triggers de `insumap-database`; correcciones con `supersedes_id`; `audit.audit_log` con cadena de hashes. |
| Seudonimización | Todo lo que sale hacia `insumap-ai`. | `AiSubject` con `subject_ref`; los tipos no tienen campos de identificación (ADR-10). |

## 3. Catálogo de patrones

### P01. Singleton

- **Intención.** Garantizar una única instancia de un recurso compartido con un punto de acceso conocido.
- **Problema en Insumap.** Muchas reglas dependen de la hora: la tolerancia de una lectura en el futuro, el vencimiento de un código de activación o de una recomendación, los tiempos de escalamiento y las ventanas de métricas. Deben ser reproducibles en pruebas, y solo un objeto debe leer el reloj del sistema.
- **Participantes.** `Singleton` = `SystemClock` (constructor protegido, `instance()`). Los casos de uso reciben la interfaz `Clock` (`typing.Protocol` con `now() -> datetime` en UTC). En pruebas, `FixedClock`.
- **Dónde vive.**
  - Backend: `insumap.shared.time` (`Clock`, `SystemClock`).
  - IA: `ModelRegistry` carga Chronos-Bolt y los modelos de scikit-learn una sola vez y expone sus versiones.
- **Por qué este patrón.** El reloj del sistema es un recurso único, y la regla `ARCH-09` exige un único lugar que lo lea.
- **Alternativa descartada.** Llamar a `datetime.now(UTC)` donde se necesite (irreproducible) o un global de módulo (solo se sustituye con *monkeypatch*).
- **Prueba.** Backend: `tests/unit/patterns/test_system_clock.py` (misma instancia, `datetime` con zona UTC). IA: `test_model_registry.py` (carga una sola vez, aun con hilos).
- **Dueño.** `Drako2305` (backend). `nicomora70` (IA).

### P02. Factory Method

- **Intención.** Definir una interfaz para crear un objeto y dejar que las subclases decidan qué clase concreta instanciar.
- **Problema en Insumap.** Hay tres reportes con contenido distinto: el reporte del paciente (AGP, TIR y eventos), el reporte de la clínica (KPIs para el admin, sin datos clínicos individuales) y el resumen previo a la consulta (IA5 o su plantilla). El adaptador que genera reportes no debe conocer los generadores concretos.
- **Participantes.** `Creator` = `ReportGeneratorCreator`, con el método fábrica abstracto `create_generator(factory)` y la operación pública `generator_for(factory)`. `ConcreteCreator` = `PatientReportCreator`, `ClinicReportCreator` y `PreVisitSummaryCreator`. `Product` = `ReportGenerator` (P20) y sus subclases `PatientReport`, `ClinicReport` y `PreVisitSummary`.
- **Dónde vive.**
  - Backend: `insumap.infrastructure.reports`. El caso de uso usa el puerto `ReportRenderingPort`, implementado por `ReportRenderingAdapter`.
  - IA: `ForecasterCreator`, con `ChronosForecasterCreator` y `LinearTrendForecasterCreator` (ver la frontera con P03 en la sección 1.3).
  - Simulador: `ScenarioCreator` crea un escenario concreto (hipos nocturnas, fenómeno del alba, dosis omitidas, abandono) desde su definición en datos.
- **Por qué este patrón.** Cada tipo de reporte tiene su creador con nombre, y agregar un tipo no cambia el adaptador.
- **Alternativa descartada.** Un diccionario de `lambda` o un `if`/`elif` por tipo de reporte dentro del adaptador.
- **Prueba.** Backend: `tests/unit/patterns/test_report_generator_creator.py` (cada creador devuelve su generador). IA: `test_forecaster_creator.py`. Simulador: `test_scenario_creator.py`.
- **Dueño.** `NicoalsD` (backend). `nicomora70` (IA y simulador).

### P03. Abstract Factory

- **Intención.** Crear familias de objetos relacionados sin especificar sus clases concretas.
- **Problema en Insumap.**
  - La clínica entrega su población como Bundle FHIR R4 o como CSV. Cada formato necesita un parser, un mapper al candidato de importación y un validador **del mismo formato**. Mezclar un parser FHIR con un mapper CSV es un error que debe ser imposible.
  - Los reportes salen en PDF (para imprimir) y en HTML (para la app), con las mismas piezas: encabezado, secciones, tablas, pie con la marca "Datos simulados" y el aviso de que no es un dispositivo médico.
  - En la IA, el modo productivo y el modo offline deben producir piezas coherentes entre sí.
- **Participantes.**
  - Importación: `AbstractFactory` = `ClinicIntegrationFactory` (`create_parser()`, `create_mapper()`, `create_validator()` y `source_format`). `ConcreteFactory` = `FhirIntegrationFactory` y `CsvIntegrationFactory`. `AbstractProduct` = `PatientSourceParser`, `PatientRecordMapper` e `ImportValidator`. `Product` = `FhirBundleParser`, `FhirPatientAdapter` (que es el mapper FHIR, ver P06) y `FhirImportValidator`; `CsvPatientParser`, `CsvPatientRecordMapper` y `CsvImportValidator`.
  - Reportes: `ReportDocumentFactory` con `PdfReportDocumentFactory` y `HtmlReportDocumentFactory`.
  - IA: `AiProviderFactory` con `OpenAiCompatibleProviderFactory` y `OfflineProviderFactory`; productos `TextGenerator`, `Forecaster` y `RiskModel`.
- **Dónde vive.**
  - Backend: la interfaz `ClinicIntegrationFactory` y los productos abstractos en `insumap.application.onboarding`; las familias en `insumap.infrastructure.integration.fhir` y `insumap.infrastructure.integration.csv`. `ReportDocumentFactory` en `insumap.infrastructure.reports`.
  - IA: `AiProviderFactory`; la familia se elige con `AI_PROVIDER_FAMILY` (`openai_compatible` u `offline`).
- **Por qué este patrón.** La coherencia de la familia es la regla. Con una fábrica por familia, una corrida de importación pide su familia una sola vez y todas las piezas comparten formato.
- **Alternativa descartada.** Elegir cada pieza por separado con un `if source_format == ...` en cada paso, o registrar parser, mapper y validador como dependencias sueltas. Ninguna garantiza que las tres sean del mismo formato.
- **Prueba.** Backend: `tests/unit/patterns/test_clinic_integration_factory.py` (cada familia produce piezas del mismo `source_format`; un Bundle FHIR de `tests/fixtures/` pasa por las tres piezas FHIR) y `test_report_document_factory.py` (todas las piezas de una familia reportan el mismo formato; el HTML escapa el contenido). IA: `test_ai_provider_factory.py` (la familia offline no hace llamadas de red).
- **Dueño.** `Drako2305` (`ClinicIntegrationFactory`). `NicoalsD` (`ReportDocumentFactory`). `nicomora70` (`AiProviderFactory`).

### P04. Builder

- **Intención.** Separar la construcción de un objeto complejo de su representación, validando el resultado al final.
- **Problema en Insumap.** Un plan de tratamiento tiene paciente, perfil de metas, insulinas basales y de bolo, razón insulina/carbohidratos, factor de sensibilidad, horarios de medición y recordatorios. Las dosis deben estar dentro de los límites del protocolo, los horarios no pueden solaparse y las metas deben ser coherentes (RF-45). Un plan inválido no debe existir como objeto.
- **Participantes.** `Builder` = `TreatmentPlanBuilder` con `for_patient()`, `with_target_profile()`, `from_template_items()`, `add_item()` y `add_reminder()`. `build()` valida las invariantes y devuelve un `TreatmentPlan` inmutable en `DRAFT`, o lanza `TreatmentPlanInvariantError` con la lista de invariantes incumplidas. `Director` = el caso de uso que crea o edita el plan.
- **Dónde vive.**
  - Backend: `insumap.domain.treatment`.
  - IA: `PromptBuilder` arma el prompt de IA5 e IA6 paso a paso (rol, datos seudonimizados, restricciones, formato de salida).
  - Simulador: `VirtualPatientBuilder` arma el paciente simulado (identidad, clínica, arquetipo y escenario).
- **Por qué este patrón.** La validación de invariantes es del dominio y debe ocurrir en un solo punto antes de que el plan exista.
- **Alternativa descartada.** Un constructor con muchos argumentos opcionales, o un modelo Pydantic con validadores (Pydantic no puede entrar al dominio, `ARCH-01`).
- **Prueba.** Backend: `tests/unit/patterns/test_treatment_plan_builder.py` (rechaza dosis fuera del límite del protocolo, horarios solapados y campos obligatorios ausentes; devuelve todas las invariantes incumplidas juntas). IA: `test_prompt_builder.py`. Simulador: `test_virtual_patient_builder.py`.
- **Dueño.** `Drako2305` (backend). `nicomora70` (IA y simulador).

### P05. Prototype

- **Intención.** Crear objetos nuevos copiando uno existente, sin depender de sus clases concretas.
- **Problema en Insumap.**
  - El médico parte de una plantilla de la clínica (por ejemplo, "Basal-bolo adulto DM1") y la personaliza para un paciente (RF-44). La plantilla no debe cambiar.
  - Cada cambio del plan crea una versión nueva copiada de la anterior (RF-46). La aprobación de una recomendación (RF-71) y la restauración de una foto (RF-47) también producen una versión nueva.
  - En el simulador, cada paciente es un clon de un arquetipo con variación sembrada.
- **Participantes.** `Prototype` = `ProtocolTemplate` (prototipo del contenido del plan) y `TreatmentPlan` (prototipo de sí mismo). Operaciones:
  - `ProtocolTemplate.clone_for_patient(...) -> TreatmentPlan`: copia profunda de ítems, perfil de metas y recordatorios; el plan nace en `DRAFT`, versión 1, con `template_id` apuntando a la plantilla.
  - `TreatmentPlan.copy_for_new_version(...) -> TreatmentPlan`: copia profunda en `DRAFT`, versión siguiente, con `based_on_plan_id` apuntando al origen.
  - En ambas, cada ítem recibe un identificador nuevo, los identificadores y la hora llegan como argumentos (`IdGenerator` y `Clock`), los eventos pendientes no se copian y el origen no cambia.
  - `Client` = `CreatePlanFromTemplateUseCase`, `ApproveRecommendationCommandHandler` y `RestoreTreatmentPlanUseCase`.
- **Dónde vive.**
  - Backend: `insumap.domain.treatment`.
  - Simulador: `PatientArchetype.clone_with_variation(rng)`.
- **Por qué este patrón.** El plan nuevo se define "como el anterior, salvo...". Copiar el prototipo y aplicar el cambio es más claro y más seguro que reconstruirlo campo por campo.
- **Alternativa descartada.** `copy.deepcopy` o `copy.replace`: copiarían el identificador, el estado, la versión, los identificadores de los ítems y los eventos pendientes, que deben cambiar. Esconder esas reglas en `__deepcopy__` las haría invisibles.
- **Prueba.** Backend: `tests/unit/patterns/test_protocol_template.py` (el plan nace en `DRAFT`, la plantilla queda igual, los ítems no comparten identidad con los de la plantilla) y `tests/unit/patterns/test_treatment_plan_prototype.py` (versión siguiente, `based_on_plan_id` correcto, el origen `ACTIVE` no cambia). Simulador: `test_patient_archetype.py` (misma semilla, mismo clon).
- **Dueño.** `Drako2305` (backend). `nicomora70` (simulador).

### P06. Adapter

- **Intención.** Convertir la interfaz de un componente externo en la que espera el cliente.
- **Problema en Insumap.** Hay formatos que el dominio no debe conocer: los recursos FHIR R4 (`Patient`, `Condition`), los CSV que exportan los sensores CGM (con columnas y unidades propias del fabricante), el JSON del servicio de IA, la API del LLM, la librería simglucose y los DTO de la API en el frontend.
- **Participantes.**
  - `FhirPatientAdapter`: `Target` = `PatientRecordMapper`; `Adaptee` = recursos `Patient` y `Condition` de FHIR R4; produce `PatientImportCandidate`.
  - `CgmCsvAdapter`: `Target` = `CgmReadingSource`; `Adaptee` = filas del CSV del fabricante (en mg/dL o mmol/L); produce candidatos de lectura en mg/dL que luego pasan por P12.
  - `AiServiceClientAdapter`: `Target` = `AiServicePort`; `Adaptee` = la API HTTP de `insumap-ai` ([Contrato IA](Contrato-IA.md)).
- **Dónde vive.**
  - Backend: `insumap.infrastructure.integration.fhir`, `insumap.infrastructure.integration.cgm` e `insumap.infrastructure.ai`.
  - IA: `OpenAiCompatibleTextGeneratorAdapter` (API compatible con OpenAI a `TextGenerator`) y `ChronosForecasterAdapter` (Chronos-Bolt a `Forecaster`).
  - Simulador: `SimglucoseAdapter` aísla simglucose detrás de `GlucoseDynamicsStrategy`.
  - Frontend: `ApiDtoAdapter` (propuesto), de DTO de la API a modelo de vista; convierte mg/dL a mmol/L solo para mostrar.
- **Por qué este patrón.** Cada adaptador es el único lugar que conoce su formato y valida al convertir (cuantiles en orden, códigos de diagnóstico, unidades).
- **Alternativa descartada.** Mapear los diccionarios externos dentro de los casos de uso, o usar un modelo Pydantic del formato externo en el dominio.
- **Prueba.** Backend: `tests/unit/patterns/test_fhir_patient_adapter.py` (Bundle válido; `Patient` sin identificador de historia; `Condition` sin código de diabetes), `test_cgm_csv_adapter.py` (mmol/L convertido a mg/dL; columna faltante) y `tests/contract/test_ai_service_client_adapter.py` (servidor simulado con `200`, `401`, `422`, `503` y timeout). IA: `test_chronos_forecaster_adapter.py`. Simulador: `test_simglucose_adapter.py`. Frontend: `ApiDtoAdapter.test.ts`.
- **Dueño.** `Drako2305` (`FhirPatientAdapter`). `nicomora70` (`CgmCsvAdapter`, `AiServiceClientAdapter`, IA y simulador). `NicoalsD` (frontend).

### P07. Bridge

- **Intención.** Separar una abstracción de su implementación para que ambas varíen de forma independiente.
- **Problema en Insumap.** Un mismo aviso (alerta de hipoglucemia, recordatorio de dosis, invitación con credenciales, control de seguimiento) puede salir por correo, Web Push o in-app. Con una clase por combinación habría que duplicar cada aviso por cada canal.
- **Participantes.** `Abstraction` = `Notification`, con `RefinedAbstraction` = `HypoglycemiaAlertNotification`, `DoseReminderNotification`, `CredentialInvitationNotification` y `FollowUpNotification`. `Implementor` = `NotificationChannel`, con `ConcreteImplementor` = `EmailChannel`, `WebPushChannel` e `InAppChannel`.
- **Dónde vive.** Backend: abstracción e interfaz del implementador en `insumap.application.notifications`; canales en `insumap.infrastructure.notifications`.
- **Por qué este patrón.** La abstracción tiene reglas propias: los canales externos (correo y push) nunca llevan datos clínicos (solo "Tienes una alerta nueva en Insumap"); el código de activación solo viaja en la invitación; la clínica demo lleva la marca "Datos simulados". Los canales solo saben entregar.
- **Alternativa descartada.** Una clase por combinación aviso × canal, o un `if channel == ...` dentro de cada aviso.
- **Prueba.** `tests/unit/patterns/test_notification.py` (cada aviso en cada canal; ningún mensaje de correo o push contiene valores de glucosa, nombres ni el diagnóstico).
- **Dueño.** `NicoalsD`.

### P08. Composite

- **Intención.** Tratar objetos individuales y compuestos de la misma forma.
- **Problema en Insumap.** Las reglas de alerta combinan condiciones: "glucosa < 54 mg/dL" o "glucosa < 70 mg/dL durante 15 minutos y bajando más de 2 mg/dL por minuto". El evaluador debe recorrer cualquier combinación de forma uniforme. Los umbrales vienen de `alerts.alert_rules`, nunca del código.
- **Participantes.** `Component` = `AlertRule` (`evaluate(window, now) -> RuleMatch | None`). `Leaf` = `ThresholdRule`, `DurationRule` y `RateOfChangeRule`. `Composite` = `AllOfRule` y `AnyOfRule`. `Client` = el evaluador de alertas.
- **Dónde vive.**
  - Backend: `insumap.domain.alerts`.
  - Frontend: `DashboardWidget` (propuesto), con grupos de widgets y widgets hoja (TIR, alertas, triage).
- **Por qué este patrón.** El admin arma árboles de reglas; el evaluador no distingue hojas de compuestos.
- **Alternativa descartada.** Una tabla plana de condiciones con un campo "operador lógico", que no permite anidar.
- **Prueba.** Backend: `tests/unit/patterns/test_alert_rule.py` (`AllOfRule` exige todas, `AnyOfRule` basta con una, anidación de tres niveles, árbol vacío rechazado). Frontend: `DashboardWidget.test.tsx`.
- **Dueño.** `Drako2305` (backend). `NicoalsD` (frontend).

### P09. Decorator

- **Intención.** Agregar responsabilidades a un objeto envolviéndolo, sin cambiar su clase.
- **Problema en Insumap.** Cada lectura de datos clínicos debe quedar auditada (quién vio qué, cuándo y con qué propósito) y cada comando debe dejar rastro, sin que cada repositorio o handler lo recuerde. En la IA, el texto debe redactarse antes de salir al LLM y los pronósticos pueden cachearse.
- **Participantes.**
  - `PhiAccessAuditDecorator`: `Component` = `PatientRecordPort`; `ConcreteComponent` = `PatientRecordAccessProxy` (que envuelve al repositorio). Registra cada acceso en `audit.data_access_log`; los denegados, en una transacción independiente.
  - `AuditingCommandHandler`: `Component` = `CommandHandler`; registra éxito o fallo en `audit.audit_log` y relanza el error.
- **Dónde vive.**
  - Backend: `insumap.infrastructure.access` (`PhiAccessAuditDecorator`) e `insumap.application.commands` (`AuditingCommandHandler`).
  - IA: `PhiRedactingTextGenerator` y `CachingForecaster`.
- **Por qué este patrón.** La auditoría es parte del contrato de acceso y de los comandos, y debe poder componerse en `container.py` en un orden visible.
- **Alternativa descartada.** Un `@decorator` de función (no se compone por objeto), un middleware HTTP (no ve el paciente ni el propósito) o un trigger de lectura en la BD (PostgreSQL no tiene triggers de `SELECT`).
- **Prueba.** Backend: `tests/unit/patterns/test_phi_access_audit_decorator.py` (acceso concedido deja una fila `GRANTED`; acceso denegado deja una fila `DENIED` y relanza; el componente se llama una vez) y `test_auditing_command_handler.py`. IA: `test_phi_redacting_text_generator.py`.
- **Dueño.** `Drako2305` (backend). `nicomora70` (IA).

### P10. Facade

- **Intención.** Ofrecer una interfaz simple para un subsistema complejo.
- **Problema en Insumap.** El dashboard del médico necesita el triage, las métricas de cada paciente, las alertas abiertas y las recomendaciones pendientes. El detalle del paciente necesita lecturas, métricas por ventana, plan activo, alertas, recomendaciones y el último pronóstico. El router y el frontend no deben orquestar esas consultas.
- **Participantes.** `Facade` = `DoctorDashboardFacade` y `PatientOverviewFacade`. `Subsystems` = `PatientRecordPort` (con proxy y auditoría), los puertos de métricas, alertas y recomendaciones, `GlucoseWindowIterator` y `GlycemicTargetStrategy`.
- **Dónde vive.**
  - Backend: `insumap.application.dashboard`.
  - Frontend: `InsumapApi` (propuesto), la fachada única del cliente HTTP.
- **Por qué este patrón.** Una respuesta por pantalla, con la forma que la pantalla necesita, sin que el router conozca las consultas. Las fachadas nunca llaman a la IA: leen lo guardado.
- **Alternativa descartada.** Que el frontend haga cinco llamadas y combine, o que el router llame varios casos de uso.
- **Prueba.** Backend: `tests/unit/patterns/test_doctor_dashboard_facade.py` (solo pacientes asignados; paciente sin lecturas; clínica demo marcada) y `test_patient_overview_facade.py`. Frontend: `InsumapApi.test.ts`.
- **Dueño.** `Drako2305` (backend). `NicoalsD` (frontend).

### P11. Proxy

- **Intención.** Ofrecer un sustituto de un objeto para controlar el acceso a él.
- **Problema en Insumap.** Hay dos necesidades distintas con la misma forma:
  - **Proxy de protección:** solo el equipo de atención asignado, el propio paciente o el admin con vista limitada pueden leer un expediente.
  - **Proxy remoto con resiliencia:** el soporte a decisiones debe responder aunque `insumap-ai` falle.
- **Participantes.**
  - `PatientRecordAccessProxy`: `Subject` = `PatientRecordPort`; `RealSubject` = `PatientRecordRepository`; decide con `PatientAccessPolicy` (dominio) y las asignaciones de `clinic.care_team_assignments`. Un médico no asignado o un paciente ajeno recibe `404`; el admin que pide datos clínicos, `403`.
  - `RemoteAiServiceProxy`: `Subject` = `AiServicePort`; `RealSubject` = `AiServiceClientAdapter`; colaboradores `CircuitBreaker` (P18) y `RuleBasedAiFallbackAdapter`. Marca cada resultado con `is_fallback` y `fallback_reason`.
- **Dónde vive.** Backend: `insumap.infrastructure.access` e `insumap.infrastructure.ai`.
- **Por qué este patrón.** El proxy tiene la misma interfaz que el sujeto real: el caso de uso no sabe que hay control de acceso ni respaldo, y no puede saltárselos porque el contenedor solo le entrega el proxy.
- **Alternativa descartada.** Verificar la asignación en cada caso de uso (se olvida en alguno) o capturar los errores de la IA en cada caso de uso (respaldos inconsistentes).
- **Prueba.** `tests/unit/patterns/test_patient_record_access_proxy.py` (médico asignado lee; no asignado recibe `NOT_FOUND`; asignación terminada retira el acceso; admin limitado) y `tests/unit/patterns/test_remote_ai_service_proxy.py` (timeout produce `AI_TIMEOUT`; circuito abierto no llama al adaptador y produce `CIRCUIT_OPEN`; `200` con `is_fallback = true` del servicio se respeta).
- **Dueño.** `Drako2305` (`PatientRecordAccessProxy`). `nicomora70` (`RemoteAiServiceProxy`).

### P12. Chain of Responsibility

- **Intención.** Pasar una petición por una cadena de manejadores; cada uno decide si la resuelve o la pasa al siguiente.
- **Problema en Insumap.**
  - Validar cada lectura de glucosa en etapas con su propio código: rango, fecha, duplicado, tasa de cambio y unidad (RF-33). Los bloqueantes van primero y las banderas después.
  - Escalar una alerta no atendida por niveles: paciente, médico principal, equipo de atención y admin de clínica.
  - En la IA, aplicar los guardrails del asistente antes y después del LLM.
- **Participantes.**
  - Validación: `Handler` = `GlucoseReadingValidationHandler` (`set_next()`, `validate()` final y `check()` abstracto). `ConcreteHandler` = `RangeCheckHandler` y `TimestampCheckHandler` (bloqueantes, `422`), y `DuplicateCheckHandler`, `RateOfChangeCheckHandler` y `UnitConsistencyCheckHandler` (marcan `FLAGGED`).
  - Escalamiento: `Handler` = `AlertEscalationHandler`. `ConcreteHandler` = `PatientEscalationHandler`, `PrimaryDoctorEscalationHandler`, `CareTeamEscalationHandler` y `ClinicAdminEscalationHandler`. Si un nivel no tiene destinatarios, pasa al siguiente.
- **Dónde vive.**
  - Backend: `insumap.domain.monitoring.validation` e `insumap.domain.alerts`.
  - IA: `GuardrailHandler` (sin dosis, sin diagnósticos, síntomas de alarma, redacción).
- **Por qué este patrón.** El orden es una regla del negocio y cada etapa tiene su prueba. Agregar una etapa no cambia las demás.
- **Alternativa descartada.** Una función con una lista de `if` (orden implícito, sin pruebas por etapa) o el middleware HTTP (no corre en lotes ni en importaciones).
- **Prueba.** Backend: `tests/unit/patterns/test_glucose_reading_validation_handler.py` (orden, detención en el primer bloqueante, acumulación de banderas) y `test_alert_escalation_handler.py` (sube de nivel al vencer el tiempo; salta un nivel sin destinatarios). IA: `test_guardrail_handler.py`.
- **Dueño.** `nicomora70` (`GlucoseReadingValidationHandler`, IA). `Drako2305` (`AlertEscalationHandler`).

### P13. Command

- **Intención.** Encapsular una petición como objeto para despacharla, autorizarla, auditarla y registrarla.
- **Problema en Insumap.** Las decisiones clínicas y administrativas (aprobar, modificar o rechazar una recomendación, activar un plan, emitir credenciales, asignar un médico) deben validarse (motivo obligatorio al modificar o rechazar), autorizarse con permisos de la BD y quedar auditadas siempre igual.
- **Participantes.** `Command` = clase base `Command`. `ConcreteCommand` = `ApproveRecommendationCommand`, `ModifyRecommendationCommand`, `RejectRecommendationCommand`, `ActivateTreatmentPlanCommand`, `IssueCredentialsCommand` y `AssignDoctorCommand`. `Receiver` = el handler de cada uno (`*CommandHandler`). `Invoker` = `CommandBus` (implementación `InMemoryCommandBus`). `Client` = el router.
- **Dónde vive.** Backend: `insumap.application.commands` (bus y base) y los comandos en su módulo (`application.ai`, `application.treatment`, `application.onboarding`, `application.care_team`).
- **Alcance.** El bus solo despacha decisiones. Registrar una lectura usa su caso de uso (`RecordGlucoseReadingUseCase`), no el bus.
- **Por qué este patrón.** Cada decisión es un objeto inmutable que se puede registrar tal cual en la auditoría, y el bus aplica el mismo decorador (P09) a todos los handlers.
- **Alternativa descartada.** Llamar a un método de servicio por decisión, con la auditoría repetida en cada uno.
- **Prueba.** `tests/unit/patterns/test_command_bus.py` (despacha al handler correcto; un comando sin handler falla al armar el bus) y una prueba por handler (por ejemplo, `test_reject_recommendation_command_handler.py` exige motivo y responde `REASON_REQUIRED`).
- **Dueño.** `Drako2305`.

### P14. Iterator

- **Intención.** Recorrer una colección sin exponer su estructura interna.
- **Problema en Insumap.** Las métricas (TIR, TBR, TAR, CV, GMI) y el AGP se calculan por ventanas: diarias, nocturnas y de 14 días, en la zona horaria de la clínica y con los límites nocturnos del perfil de metas. Las reglas de alerta también evalúan ventanas recientes. Esa lógica no debe repetirse en cada cálculo.
- **Participantes.** `Iterator` = `GlucoseWindowIterator` (entrega `GlucoseWindow` con inicio, fin, lecturas y suficiencia de datos). `Aggregate` = la serie de lecturas vigentes del paciente.
- **Dónde vive.**
  - Backend: `insumap.domain.metrics`.
  - IA: `SlidingWindowIterator` (ventanas de contexto para inferencia y de evaluación para el backtest).
  - Simulador: `TimeStepIterator` (pasos de 1, 5 o 15 minutos de la simulación, sin leer el reloj del sistema).
- **Por qué este patrón.** Las fronteras de las ventanas (medianoche local, cambio de zona, huecos de datos) son reglas clínicas que se prueban una vez.
- **Alternativa descartada.** Un generador suelto o un `groupby` de pandas dentro de cada métrica.
- **Prueba.** Backend: `tests/unit/patterns/test_glucose_window_iterator.py` (ventana nocturna con los límites del perfil; día local en `America/Bogota`; ventana sin datos marcada como insuficiente). IA: `test_sliding_window_iterator.py`. Simulador: `test_time_step_iterator.py`.
- **Dueño.** `Drako2305` (backend). `nicomora70` (IA y simulador).

### P15. Mediator

- **Intención.** Centralizar las interacciones entre componentes para que no se refieran unos a otros directamente.
- **Problema en Insumap.** En el dashboard del médico, los filtros se afectan entre sí: la ventana (24 h, 7, 14 o 30 días), el nivel de riesgo, las banderas tipo TIDE, la búsqueda y "marcar como revisado". Cambiar uno recalcula los demás y la lista de triage.
- **Participantes.** `Mediator` = `DashboardFiltersMediator`. `Colleague` = cada control de filtro y la lista de triage.
- **Dónde vive.** Frontend: `insumap-frontend`, en la funcionalidad del dashboard (ruta propuesta). **No aplica al backend.**
- **Por qué este patrón.** La lógica de filtros cruzados no debe quedar repartida en los componentes visuales.
- **Alternativa descartada.** Estado elevado con `useReducer` y efectos encadenados entre componentes.
- **Prueba.** `DashboardFiltersMediator.test.ts` (cambiar la ventana recalcula las banderas disponibles; "marcar como revisado" saca al paciente de la lista).
- **Dueño.** `NicoalsD`.

### P16. Memento

- **Intención.** Capturar y restaurar el estado interno de un objeto sin violar su encapsulamiento.
- **Problema en Insumap.** Antes de cada cambio del plan (edición de un borrador, activación o aplicación de una recomendación aprobada) se guarda una foto para comparar, explicar qué cambió y poder restaurar una versión anterior (RF-47).
- **Participantes.** `Originator` = `TreatmentPlan` (`create_memento(taken_at)` y `from_memento(memento)`). `Memento` = `TreatmentPlanMemento` (inmutable, solo datos primitivos y tuplas, serializable a `jsonb`). `Caretaker` = los casos de uso y handlers que cambian el plan; guardan el memento en `care.treatment_plan_snapshots` sin conocer su contenido.
- **Dónde vive.** Backend: `insumap.domain.treatment`.
- **Regla de restauración.** Restaurar nunca modifica una versión existente: reconstruye el plan con `from_memento()` y crea una versión nueva en `DRAFT` con `copy_for_new_version()` (P05).
- **Por qué este patrón.** La foto es un contrato de auditoría y debe seguir siendo legible aunque cambie la tabla de ítems.
- **Alternativa descartada.** Releer la versión anterior desde las tablas (los borradores se editan en su lugar y se perderían los pasos intermedios) o `pickle` (inseguro y opaco).
- **Prueba.** `tests/unit/patterns/test_treatment_plan_memento.py` (el memento no cambia si el plan cambia; ida y vuelta por `jsonb` sin pérdida; restaurar crea un `DRAFT` nuevo).
- **Dueño.** `Drako2305`.

### P17. Observer

- **Intención.** Definir una dependencia uno a muchos para que los suscriptores reciban aviso cuando ocurre un hecho.
- **Problema en Insumap.** Registrar una glucosa, abrir una alerta de hipoglucemia, aprobar una recomendación y activar una cuenta disparan efectos (evaluar reglas, notificar, avisar al equipo) que el caso de uso no debe conocer, y que solo deben ocurrir si la transacción confirmó.
- **Participantes.** `Subject` = `DomainEventPublisher` (puerto en `application.events`), implementado por `InProcessDomainEventPublisher` (infraestructura). `ConcreteSubject` = la entidad que trae el evento en `pending_events`. `Observer` = los suscriptores (`EventSubscriber`), registrados por tipo de evento en `container.py`. Eventos: `GlucoseReadingRecorded`, `HypoglycemiaDetected`, `RecommendationApproved` y `PatientActivated`.
- **Dónde vive.** Backend: `insumap.application.events`, `insumap.infrastructure.events` y `insumap.domain.<módulo>.events`.
- **Por qué este patrón.** Los efectos crecen sin tocar los casos de uso, y la unidad de trabajo garantiza el "después del commit".
- **Alternativa descartada.** Eventos de sesión de SQLAlchemy o `blinker` (sección 1.1); llamar a los efectos al final de cada caso de uso.
- **Prueba.** `tests/unit/patterns/test_domain_event_publisher.py` (entrega después del commit; una transacción revertida no entrega nada; un suscriptor que falla no impide a los demás).
- **Dueño.** `Drako2305`.

### P18. State

- **Intención.** Permitir que un objeto cambie su comportamiento cuando cambia su estado interno.
- **Problema en Insumap.** Cuatro máquinas de estado con transiciones que son reglas del negocio:
  - `PatientAccountState`: `IMPORTED → INVITED → ACTIVE`, `ACTIVE ⇄ SUSPENDED`, reenvío `INVITED → INVITED` y cualquier estado no terminal `→ DEACTIVATED` (terminal). Detalle en [Arquitectura](Arquitectura.md), sección 8.
  - `RecommendationState`: `PROPOSED → APPROVED | APPROVED_WITH_CHANGES | REJECTED`; `APPROVED` y `APPROVED_WITH_CHANGES → APPLIED` (al activarse la versión del plan que la incluye); `PROPOSED → EXPIRED`. `REJECTED`, `APPLIED` y `EXPIRED` son terminales.
  - `AlertState`: `OPEN → ACKNOWLEDGED → RESOLVED` y `OPEN → ESCALATED → ACKNOWLEDGED → RESOLVED`. Subir de nivel dentro de `ESCALATED` no cambia el estado.
  - `CircuitBreakerState`: `CLOSED → OPEN` (al llegar al umbral de fallos), `OPEN → HALF_OPEN` (al vencer el tiempo de apertura, medido con el `Clock`), `HALF_OPEN → CLOSED` (éxito) o `HALF_OPEN → OPEN` (fallo).
- **Participantes.** `Context` = `Patient` (cuenta), `Recommendation`, `Alert` y `CircuitBreaker`. `State` = la clase base de cada máquina, cuyas transiciones no permitidas lanzan `InvalidStateTransitionError` (`409 INVALID_STATE_TRANSITION`). `ConcreteState` = una clase por estado. El valor persistido es un `StrEnum` y `from_status()` reconstruye el estado con `match`.
- **Dónde vive.** Backend: `insumap.domain.onboarding`, `insumap.domain.ai`, `insumap.domain.alerts` e `insumap.infrastructure.ai` (`CircuitBreakerState`).
- **Por qué este patrón.** Cada estado sabe qué puede hacer; una transición ilegal es imposible de expresar sin un error.
- **Alternativa descartada.** Un `Enum` con un `if` por transición repartido en los casos de uso; `pybreaker` para el circuito.
- **Prueba.** `tests/unit/patterns/test_alert_state.py`, `test_recommendation_state.py`, `test_patient_account_state.py` y `test_circuit_breaker_state.py`: cada transición válida pasa, cada inválida lanza error y los terminales no tienen salidas.
- **Dueño.** `Drako2305` (`AlertState`, `PatientAccountState` y `RecommendationState`, este último con `nicomora70`). `nicomora70` (`CircuitBreakerState`).

### P19. Strategy

- **Intención.** Definir una familia de algoritmos intercambiables.
- **Problema en Insumap.**
  - El riesgo del triage se calcula con la IA (IA2) o con reglas tipo TIDE, según la configuración de la clínica y la disponibilidad de la IA.
  - Las metas glucémicas se evalúan distinto según el perfil (adulto estándar, adulto mayor o de alto riesgo, embarazo).
  - La titulación de basal (IA4) se propone con reglas parametrizadas por el protocolo, con ML opcional.
- **Participantes.**
  - `RiskScoringStrategy`, con `AiRiskScoringStrategy` (aplicación, usa `AiServicePort`) y `RuleBasedRiskStrategy` (dominio, banderas tipo TIDE con umbrales de `alerts.alert_rules`).
  - `GlycemicTargetStrategy`, con `AdultStandardTargetStrategy`, `OlderOrHighRiskTargetStrategy` y `PregnancyTargetStrategy`, elegidas por el perfil de `care.target_profiles` (ver [Métricas clínicas](Metricas-clinicas.md)). Los números siempre vienen del perfil.
  - `TitrationStrategy`, con `FastingGlucoseTitrationStrategy`. Ningún ajuste supera el cambio máximo del protocolo.
  - `Context` = el caso de uso de triage, el cálculo de métricas y el generador de recomendaciones.
- **Dónde vive.**
  - Backend: `insumap.domain.triage`, `insumap.domain.metrics`, `insumap.domain.treatment` e `insumap.application.triage`.
  - Simulador: `GlucoseDynamicsStrategy`, con `SimglucoseDynamics` (DM1 con CGM) y `SmbgPatternDynamics` (DM2 y gestacional).
  - Frontend: `ChartRendererStrategy` (propuesto): AGP, superposición diaria, barra de TIR y línea de tiempo.
- **Por qué este patrón.** La estrategia se elige por un código guardado en la BD y queda registrada con cada resultado.
- **Alternativa descartada.** Funciones sueltas elegidas con `if`, o `lambda` en un diccionario (no se pueden persistir por código ni probar por nombre).
- **Prueba.** Backend: `tests/unit/patterns/test_risk_scoring_strategy.py`, `test_glycemic_target_strategy.py` y `test_titration_strategy.py` (casos en el límite del umbral, por encima y por debajo). Simulador: `test_glucose_dynamics_strategy.py`. Frontend: `ChartRendererStrategy.test.ts`.
- **Dueño.** `Drako2305` (backend). `nicomora70` (simulador). `NicoalsD` (frontend).

### P20. Template Method

- **Intención.** Definir el esqueleto de un algoritmo y dejar que las subclases completen ciertos pasos.
- **Problema en Insumap.**
  - Todos los reportes siguen el mismo orden: encabezado, secciones, pie con la marca "Datos simulados" (si aplica) y el aviso de que no es un dispositivo médico.
  - Toda importación sigue el mismo orden: leer, parsear, validar, mapear, deduplicar, persistir y emitir, con aislamiento por fila.
- **Participantes.**
  - `ReportGenerator.generate()` (`@final`): llama a `write_header()`, `write_sections()` (abstracto) y `write_footer()`. Subclases `PatientReport`, `ClinicReport` y `PreVisitSummary`.
  - `PatientImportPipeline.run()` (`@final`): implementa en la base deduplicar (por número de historia), persistir (pacientes en `IMPORTED`, `clinic.import_rows`) y emitir (`PatientsImported`). Operaciones primitivas: `read()` (decodificar el archivo) e `integration_factory()` (P03). Subclases `FhirPatientImportPipeline` y `CsvPatientImportPipeline`.
- **Dónde vive.**
  - Backend: `insumap.infrastructure.reports` (`ReportGenerator`); `insumap.application.onboarding` (la plantilla) e `insumap.infrastructure.integration.fhir` y `.csv` (las subclases).
  - IA: `InferencePipeline` (validar, ventanear, inferir, aplicar guardrails, explicar, responder).
  - Simulador: `ExportPipeline` (validar, ordenar, serializar, marcar como simulado y escribir) para FHIR, CSV y dataset.
- **Por qué este patrón.** El orden es una regla: nadie puede persistir antes de deduplicar ni olvidar la marca de datos simulados.
- **Alternativa descartada.** Una función por formato que repite los pasos comunes.
- **Prueba.** Backend: `tests/unit/patterns/test_report_generator.py` (orden de llamadas; la marca aparece en la clínica demo) y `test_patient_import_pipeline.py` (orden fijo; una fila inválida no aborta el lote; un duplicado queda registrado). IA: `test_inference_pipeline.py`. Simulador: `test_export_pipeline.py`.
- **Dueño.** `NicoalsD` (`ReportGenerator`). `Drako2305` (`PatientImportPipeline`). `nicomora70` (IA y simulador).

### P21. Visitor

- **Intención.** Representar una operación sobre los elementos de una estructura sin modificar sus clases.
- **Problema en Insumap.** Los eventos clínicos del paciente (glucosa, dosis de insulina, comida, actividad y síntoma) se recorren para varias operaciones: armar la línea de tiempo, exportar a CSV y exportar a FHIR (`Observation` con LOINC, administración de medicamento). Cada operación debe cubrir todos los tipos.
- **Participantes.** `Visitor` = `ClinicalEventVisitor[R]` (un método por tipo). `ConcreteVisitor` = `TimelineVisitor`, `CsvExportVisitor` y `FhirExportVisitor`. `Element` = la unión cerrada `type ClinicalEvent = GlucoseReading | InsulinDose | Meal | PhysicalActivity | Symptom`. `ConcreteElement` = cada clase, con `accept(visitor)`.
- **Dónde vive.** Backend: `insumap.domain.monitoring.clinical_event` (elementos y visitante abstracto). Los visitantes de exportación viven en `insumap.infrastructure` porque conocen formatos externos.
- **Por qué este patrón.** Agregar un tipo de evento obliga a implementar su método en cada visitante, y mypy lo detecta.
- **Alternativa descartada.** `isinstance` o `match` repetido en cada exportador; `functools.singledispatch`.
- **Prueba.** `tests/unit/patterns/test_clinical_event_visitor.py` (cada tipo va a su método; la línea de tiempo sale ordenada; el CSV no incluye datos de identificación).
- **Dueño.** `nicomora70`.

### P22. Interpreter (opcional)

- **Intención.** Definir una gramática y un intérprete que evalúe sus frases.
- **Problema en Insumap.** El admin escribe reglas de alerta legibles, por ejemplo `glucose < 70 for 15m and rate < -2 per min`, en lugar de armar el árbol a mano. La regla debe validarse antes de guardarse.
- **Participantes.** `AbstractExpression` = `RuleExpression`. `TerminalExpression` = `ComparisonExpression` y `RateExpression`. `NonterminalExpression` = `ForDurationExpression`, `AndExpression` y `OrExpression`. `Context` = las unidades y los límites permitidos. `AlertRuleInterpreter` analiza el texto y traduce el árbol de expresiones al árbol `AlertRule` (P08).
- **Dónde vive.** Backend: `insumap.domain.alerts.rule_dsl`.
- **Por qué este patrón.** Una gramática pequeña con errores de dominio claros (`ALERT_RULE_SYNTAX_ERROR`) y sin ejecutar código.
- **Alternativa descartada.** `eval` (inseguro) o expresiones regulares sueltas (sin gramática).
- **Prueba.** `tests/unit/patterns/test_alert_rule_interpreter.py` (precedencia de `and` sobre `or`; unidades; texto inválido con la posición del error).
- **Dueño.** `Drako2305`.

### P23. Flyweight (opcional)

- **Intención.** Compartir objetos pequeños e inmutables para reducir memoria.
- **Problema en Insumap.** El catálogo de insulinas (código, nombre, tipo, inicio y duración de acción, concentración) se repite en miles de dosis y en los ítems de los planes. Cada fila no debe crear su propia copia.
- **Participantes.** `Flyweight` = `InsulinProduct` (estado intrínseco). `FlyweightFactory` = `InsulinProductFlyweightFactory` (devuelve la instancia compartida por código). El estado extrínseco (unidades, hora, paciente) queda en la dosis.
- **Dónde vive.** Backend: `insumap.domain.treatment`. El catálogo es semilla de `insumap-database`.
- **Por qué este patrón.** El producto es un valor compartido e inmutable que se compara por identidad en las pruebas.
- **Alternativa descartada.** `functools.lru_cache` sobre una función de carga, o la caché de identidad de SQLAlchemy (no sale de la capa de persistencia).
- **Prueba.** `tests/unit/patterns/test_insulin_product_flyweight_factory.py` (el mismo código devuelve la misma instancia; un código desconocido falla).
- **Dueño.** `Drako2305`.

## 4. Matriz patrón × repositorio

| ID | Patrón | `insumap-backend` | `insumap-ai` | `insumap-simulator` | `insumap-frontend` | `insumap-database` |
|---|---|:-:|:-:|:-:|:-:|:-:|
| P01 | Singleton | ✓ | ✓ | | | |
| P02 | Factory Method | ✓ | ✓ | ✓ | | |
| P03 | Abstract Factory | ✓ | ✓ | | | |
| P04 | Builder | ✓ | ✓ | ✓ | | |
| P05 | Prototype | ✓ | | ✓ | | |
| P06 | Adapter | ✓ | ✓ | ✓ | ✓ | |
| P07 | Bridge | ✓ | | | | |
| P08 | Composite | ✓ | | | ✓ | |
| P09 | Decorator | ✓ | ✓ | | | |
| P10 | Facade | ✓ | | | ✓ | |
| P11 | Proxy | ✓ | | | | |
| P12 | Chain of Responsibility | ✓ | ✓ | | | |
| P13 | Command | ✓ | | | | |
| P14 | Iterator | ✓ | ✓ | ✓ | | |
| P15 | Mediator | | | | ✓ | |
| P16 | Memento | ✓ | | | | |
| P17 | Observer | ✓ | | | | |
| P18 | State | ✓ | | | | |
| P19 | Strategy | ✓ | | ✓ | ✓ | |
| P20 | Template Method | ✓ | ✓ | ✓ | | |
| P21 | Visitor | ✓ | | | | |
| P22 | Interpreter (opcional) | ✓ | | | | |
| P23 | Flyweight (opcional) | ✓ | | | | |
| | **Total** | **22** | **9** | **7** | **5** | **0** |

`insumap-database` no implementa patrones GoF (es SQL y migraciones). Aporta las bases de varios patrones arquitectónicos: RLS, append-only y cadena de hashes.

## 5. Relación con el código, las pruebas y los PR

- La clase principal de cada patrón lleva la etiqueta en su docstring, en inglés:

  ```python
  class PatientRecordAccessProxy(PatientRecordPort):
      """Protection proxy: only the assigned care team, the patient or a limited admin.

      Pattern: P11 Proxy
      """
  ```

  Así el catálogo y el código se buscan juntos (`grep -rn "Pattern: P11"`).
- Cada patrón del backend tiene su prueba en `tests/unit/patterns/`, sin FastAPI ni BD (ver [`.agents/testing-plan.md`](../.agents/testing-plan.md)). Un patrón sin prueba no se integra.
- El PR que agrega o cambia un patrón lo lista en "Patrones de diseño involucrados" de la plantilla.
- Si un patrón se elimina o cambia de clase, se actualiza este catálogo en el mismo PR. Los IDs no se reutilizan.

Relacionados: [Arquitectura](Arquitectura.md), [Módulo IA](Modulo-IA.md), [Datos simulados](Datos-simulados.md), [Guía operativa de patrones](../.agents/design-patterns.md), [Plan de pruebas](../.agents/testing-plan.md), [Plan de commits](Plan-de-commits.md)
