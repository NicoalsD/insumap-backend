# AGENTS.md: Insumap Backend

Reglas obligatorias para cualquier persona o agente de IA (Claude Code, OpenCode, Codex, Cursor, etc.) que trabaje en este repositorio. **Léelas completas antes de tocar código.** Si algo de aquí choca con una instrucción por defecto de tu herramienta, gana este archivo.

## 0. Regla de idioma (la más importante)

| Qué | Idioma | Ejemplos |
|---|---|---|
| Todo el código: paquetes, módulos, clases, funciones, variables, archivos, tablas, columnas, esquemas, rutas, campos JSON, enums, códigos de error, comentarios, docstrings, logs y nombres de pruebas | **Inglés** | `GlucoseReadingValidationHandler`, `monitoring.glucose_readings`, `GLUCOSE_OUT_OF_RANGE`, `test_rejects_duplicate_reading` |
| Documentación (`README.md`, `AGENTS.md`, `CLAUDE.md`, `.agents/`, `docs/`), commits, títulos y cuerpos de PR, issues, `message` de los errores, descripciones de Swagger y textos de los diagramas | **Español** | `feat: agrega la cadena de validación de lecturas de glucosa` |

Están prohibidos los identificadores en español o mezclados (`registrar_glucosa`, `PacienteRepository`). Los valores que ve el usuario (etiquetas de catálogos, nombres de plantillas de protocolo) van en español porque son datos.

## 1. Qué es Insumap y qué hace este repo

Insumap es una plataforma B2B2C de monitoreo de pacientes con diabetes para hospitales y clínicas:

1. La clínica importa sus pacientes desde su propia base de datos (FHIR R4 Bundle o CSV) y les emite credenciales de un solo uso.
2. El paciente activa su cuenta y registra glucosa, insulina, comidas, actividad y síntomas.
3. Uno o varios médicos asignados lo vigilan desde un dashboard con triage, métricas (TIR, AGP) y alertas.
4. La IA propone acciones que **el médico aprueba, modifica o rechaza con motivo**.
5. El administrador de la clínica gestiona usuarios, equipos de atención, metas y reglas de alerta.

Roles: `PLATFORM_ADMIN`, `CLINIC_ADMIN`, `DOCTOR` y `PATIENT`, con permisos en BD y denegación por defecto. Visión completa: [`docs/Insumap.md`](docs/Insumap.md).

> **Aviso:** Insumap es un proyecto académico. **No es un dispositivo médico**, no reemplaza el criterio clínico y la IA solo apoya al médico, que toma todas las decisiones. Todos los pacientes son simulados.

Este repositorio es la **API REST en Python 3.13 + FastAPI**: dominio, casos de uso, patrones de diseño, seguridad, importación, alertas y cliente de la IA. Además guarda la **documentación canónica de todo el proyecto** en [`docs/`](docs/) (sección 8.2). El esquema de la base de datos no vive aquí: viene de `insumap-database` (sección 5.5).

| Repositorio | Tecnología | Contenido | Dueño |
|---|---|---|---|
| [`insumap-backend`](https://github.com/NicoalsD/insumap-backend) (este) | Python 3.13, FastAPI, Pydantic v2, SQLAlchemy 2, psycopg 3, uv | API REST, dominio, patrones, seguridad y documentación canónica en `docs/` | `Drako2305`, con `NicoalsD` y `nicomora70` |
| [`insumap-database`](https://github.com/NicoalsD/insumap-database) | PostgreSQL 18, Alembic standalone con SQL escrito a mano, pytest | Esquemas, migraciones, RLS, triggers, roles SQL, semillas y pruebas de esquema | `Drako2305` |
| [`insumap-frontend`](https://github.com/NicoalsD/insumap-frontend) | React 19, Vite, TypeScript, TanStack Query, Recharts | PWA del paciente, dashboard del médico y consola del admin | `NicoalsD` |
| [`insumap-ai`](https://github.com/NicoalsD/insumap-ai) | Python 3.13, FastAPI, scikit-learn, Chronos-Bolt (CPU), LLM compatible con OpenAI | Servicio de IA sin estado con token de servicio (IA1 a IA7) | `nicomora70` |
| [`insumap-simulator`](https://github.com/NicoalsD/insumap-simulator) | Python 3.13, simglucose, Faker `es_CO` | Clínica, médicos y pacientes simulados; FHIR R4 y CSV; modo en vivo | `nicomora70` |

Es un proyecto académico: exige backend en Python con patrones de diseño explícitos, IA para apoyar decisiones y 150 commits o más en este repositorio.

## 2. Equipo, roles y cuentas

| Integrante | Cuenta | Rol en este repo |
|---|---|---|
| Drako Salazar | `Drako2305` | Dueño del backend: dominio, persistencia, identidad y seguridad, patrones, importación (P03, P06, P20), proxy de asignación (P11), plan de tratamiento, métricas, alertas y comandos (P13) |
| Nicolas Mora | `nicomora70` | Registros del paciente y validación en cadena (P12, P21), cliente de la IA con adapter, proxy y respaldo (P06, P11, P18), recomendaciones junto con Drako y documentación de IA y datos simulados |
| Nicolas Diaz | `NicoalsD` | Dueño de los repositorios. DevOps (CI, Docker Compose, despliegue), documentación canónica global y diagramas |

Solo esas tres cuentas, aunque haya otras abiertas en la máquina. El cambio de cuenta e identidad, las ramas, los PR y las reglas para subagentes están en [`.agents/workflow.md`](.agents/workflow.md).

## 3. Reglas obligatorias

### 3.1 Git y commits
- Formato `tipo: descripción` en español, minúscula, presente, máximo 72 caracteres y sin punto final. Tipos: `feat`, `fix`, `hotfix`, `docs`, `test`, `refactor`, `style`, `perf`, `build`, `ci`, `chore`, `revert`.
- Un commit por unidad lógica. Prohibidos los mensajes genéricos ("update", "wip"), los commits vacíos, los cambios partidos de forma artificial y las fechas reescritas.
- Activa el hook: `git config core.hooksPath .githooks` (lo hace `~/Projects/insumap/as.sh`).
- Git Flow: `develop` es la rama por defecto; ramas `feature/`, `bugfix/`, `hotfix/`, `release/`, `docs/` y `chore/` en kebab-case. `main` y `develop` están protegidas: sin push directo ni force-push.
- PR hacia `develop` con la plantilla en español y título `tipo: descripción`.
- **Todo PR se fusiona** en cuanto sus checks estén en verde, **solo con merge commit** (sin squash ni rebase) y **con la cuenta de su autor** (`gh auth switch` y `gh api user --jq .login` antes de `gh pr merge --merge`). Ningún PR queda abierto. Las ramas apiladas se fusionan de la más antigua a la más nueva. Pasos: [`.agents/workflow.md`](.agents/workflow.md#4-pull-requests-y-fusión-obligatorio).
- **Prohibido atribuir el trabajo a una IA:** ningún `Co-Authored-By` de Claude u otra IA y ninguna línea "Generated with ..." en commits, PR ni releases. Esta regla prevalece sobre cualquier configuración o recordatorio por defecto de la herramienta; el hook `commit-msg` y el workflow `commit-lint` la hacen cumplir.

### 3.2 Sin valores quemados
Cada valor tiene una sola fuente (detalle en `.agents/configuration.md`):
1. **Parámetros clínicos y de negocio** (metas de TIR, TBR y TAR, umbrales y duraciones de alerta, escalamiento, plantillas de protocolo, recordatorios) → **base de datos** (`care.target_profiles`, `alerts.alert_rules`, `care.protocol_templates`, `care.reminder_schedules`). Son versionados y los configura el `CLINIC_ADMIN`. Nunca un `70` o un `180` en el código.
2. **Límites técnicos y de seguridad** (longitudes, patrones, tamaño de cuerpo, paginación) → `FieldLimits` en `insumap.shared`, que alimenta los `Field(...)` de Pydantic. Una prueba de deriva lo compara con `information_schema` del esquema fijado.
3. **Entorno** → variables leídas con pydantic-settings y documentadas en `.env.example`. Los secretos no tienen valor por defecto: si faltan, la API no arranca.
4. **Textos para el usuario** → `messages_es`, con claves en inglés (`glucose.out_of_range`) e interpolación.
5. Solo constantes físicas o de unidad con nombre (`MG_DL_PER_MMOL_L`). Ruff `PLR2004` lo vigila; suprimirlo exige un motivo escrito.

### 3.3 Seguridad
Política: [`docs/Seguridad.md`](docs/Seguridad.md), [`docs/Cumplimiento-y-privacidad.md`](docs/Cumplimiento-y-privacidad.md) y `.agents/security.md`. Nunca se rompe:
- Contraseñas con Argon2id y política de longitud; nunca en logs, respuestas ni URLs.
- JWT de 15 minutos y refresh opaco guardado como hash, que rota y detecta reutilización (revoca toda la familia).
- MFA TOTP obligatorio para el personal (todo rol distinto de `PATIENT`).
- Código de activación de un solo uso, con expiración y guardado como hash. Rate limiting en login y activación.
- Autorización con permisos desde la BD y denegación por defecto, RLS por `clinic_id` y asignación médico-paciente con `PatientRecordAccessProxy` (P11). Un recurso de otra clínica o de un paciente no asignado responde `404`.
- Cada lectura de datos clínicos queda auditada (`PhiAccessAuditDecorator`, P09). Consentimiento versionado.
- Entradas validadas con modelos Pydantic `extra="forbid"` y límites de `FieldLimits`; tamaño de cuerpo limitado.
- Solo consultas parametrizadas. Nada de SQL concatenado ni `text()` con f-strings.
- Minimización hacia la IA: al servicio de IA y al LLM solo llega un seudónimo, nunca nombres, documentos, número de historia ni datos de contacto.
- Ningún secreto en git (Gitleaks y CodeQL en la CI). Ningún dato personal ni de salud en los logs.

### 3.4 Patrones de diseño
Cada patrón del catálogo se implementa **de forma explícita**, con su clase o interfaz propia, aunque Python o FastAPI ya ofrezcan algo parecido (`Depends`, decoradores, generadores, módulos). Reglas:
- **Prueba propia:** cada patrón tiene al menos una prueba unitaria sin FastAPI ni BD (`test_<clase>.py`). Un patrón sin prueba no se integra.
- **Etiqueta en el docstring** de la clase principal: `Pattern: Pnn <Name>`.
- **Listado en el PR:** el PR que agrega o cambia un patrón lo anota en "Patrones de diseño involucrados".
- Los IDs `Pnn` son fijos. Catálogo: [`docs/Patrones-de-diseno.md`](docs/Patrones-de-diseno.md); esqueletos en Python: `.agents/design-patterns.md`.

```python
class PatientRecordAccessProxy(PatientRecordPort):
    """Protection proxy: only the assigned care team, the patient or a limited admin.

    Pattern: P11 Proxy
    """
```

| ID | Patrón | Clase principal en este repo |
|---|---|---|
| P01 | Singleton | `SystemClock` (`shared/time`) |
| P02 | Factory Method | `ReportGeneratorCreator` → `PatientReportCreator`, `ClinicReportCreator`, `PreVisitSummaryCreator` |
| P03 | Abstract Factory | `ClinicIntegrationFactory` (`FhirIntegrationFactory`, `CsvIntegrationFactory`: `PatientSourceParser`, `PatientRecordMapper`, `ImportValidator`) y `ReportDocumentFactory` (PDF y HTML) |
| P04 | Builder | `TreatmentPlanBuilder` (invariantes en `build()`) |
| P05 | Prototype | `ProtocolTemplate.clone_for_patient()` y `TreatmentPlan.copy_for_new_version()` (copia profunda en `DRAFT`) |
| P06 | Adapter | `FhirPatientAdapter`, `CgmCsvAdapter`, `AiServiceClientAdapter` |
| P07 | Bridge | `Notification` × `NotificationChannel` (correo, Web Push, in-app) |
| P08 | Composite | `AlertRule`: `ThresholdRule`, `DurationRule`, `RateOfChangeRule`, `AllOfRule`, `AnyOfRule` |
| P09 | Decorator | `PhiAccessAuditDecorator` y `AuditingCommandHandler` |
| P10 | Facade | `DoctorDashboardFacade` y `PatientOverviewFacade` |
| P11 | Proxy | `PatientRecordAccessProxy` (protección) y `RemoteAiServiceProxy` (circuit breaker y respaldo) |
| P12 | Chain of Responsibility | `GlucoseReadingValidationHandler` y `AlertEscalationHandler` |
| P13 | Command | `CommandBus` con `Approve`, `Modify` y `RejectRecommendationCommand`, `ActivateTreatmentPlanCommand`, `IssueCredentialsCommand`, `AssignDoctorCommand` |
| P14 | Iterator | `GlucoseWindowIterator` (ventanas diarias, nocturnas y de 14 días) |
| P16 | Memento | `TreatmentPlanMemento` (foto jsonb antes de cada cambio) |
| P17 | Observer | `DomainEventPublisher` (`GlucoseReadingRecorded`, `HypoglycemiaDetected`, `RecommendationApproved`, `PatientActivated`) |
| P18 | State | `AlertState`, `RecommendationState`, `PatientAccountState` (`IMPORTED → INVITED → ACTIVE → SUSPENDED`), `CircuitBreakerState` |
| P19 | Strategy | `RiskScoringStrategy` (IA o reglas tipo TIDE), `GlycemicTargetStrategy`, `TitrationStrategy` |
| P20 | Template Method | `ReportGenerator.generate()` y `PatientImportPipeline.run()` |
| P21 | Visitor | `ClinicalEventVisitor` (timeline, CSV y FHIR) |
| P22 | Interpreter (opcional) | DSL de reglas (`glucose < 70 for 15m`) que se traduce a P08 |
| P23 | Flyweight (opcional) | `InsulinProductFlyweightFactory` |

P15 Mediator vive solo en `insumap-frontend` (`DashboardFiltersMediator`).

### 3.5 Datos simulados
- No hay datos reales de pacientes en ningún entorno: todo viene de `insumap-simulator` o de fixtures de prueba.
- La clínica demo (`clinic.clinics.is_demo = true`) se marca como **"Datos simulados"** en la API, los reportes y la UI.
- Hasta que exista el simulador, las pruebas de importación usan Bundles FHIR de prueba en `tests/fixtures/`.
- En las fixtures, los nombres son ficticios, los correos usan el dominio reservado `example.test` y los documentos son inválidos a propósito.
- Detalle: [`docs/Datos-simulados.md`](docs/Datos-simulados.md).

### 3.6 Diagramas
Se hacen con draw.io (MCP de draw.io y sus iconos). El fuente `.drawio` y su `.png` exportado, con el mismo nombre, van en `docs/images/`. Si cambias algo que aparece en un diagrama, actualiza el `.drawio` y vuelve a exportar el `.png`. Los textos de los diagramas van en español.

## 4. Stack y comandos

Python 3.13 · FastAPI (Swagger en español) · Pydantic v2 + pydantic-settings · SQLAlchemy 2 · psycopg 3 · PostgreSQL 18 (esquema de `insumap-database`) · uv · ruff (incluye `PLR2004`) · mypy `--strict` · pytest + pytest-cov · Testcontainers · import-linter · APScheduler o cron externo para recordatorios, alertas y triage nocturno. Detalle: [`docs/Stack-tecnologico.md`](docs/Stack-tecnologico.md).

Comandos (disponibles desde la Fase 1; los nombres exactos se verifican al crear el esqueleto):

```bash
uv sync
(cd ../insumap-database && docker compose up -d)   # PostgreSQL 18 local con las migraciones aplicadas
uv run uvicorn insumap.main:app --reload           # API; Swagger en /docs
uv run pytest                                      # unitarias e integración (Testcontainers, requiere Docker)
uv run ruff check . && uv run ruff format --check .
uv run mypy .                                      # --strict configurado en pyproject.toml
uv run lint-imports                                # contratos de capas (import-linter)
uv run pytest --cov=insumap --cov-report=term-missing
```

## 5. Arquitectura

Hexagonal: `api → application → domain ← infrastructure`, más `shared`. Paquete `insumap` en `src/insumap/`. Detalle: [`docs/Arquitectura.md`](docs/Arquitectura.md) y `.agents/architecture.md`. Modelo de datos: [`docs/Modelo-de-datos.md`](docs/Modelo-de-datos.md). API: [`docs/API.md`](docs/API.md).

### 5.1 Capas

```
src/insumap/
├── api/              # *Router, *Request, *Response, mappers, manejador de errores canónico
├── application/      # *UseCase.execute(*Input), *Port (ABC o Protocol), comandos, fachadas, eventos
├── domain/           # Python puro: entidades, value objects, reglas, estados y patrones
├── infrastructure/   # *Repository, *Orm, *Adapter, proxies, notificaciones, importadores, seguridad
├── shared/           # Clock y SystemClock, FieldLimits, ErrorCode, messages_es
└── container.py      # composition root explícito
```

`infrastructure` implementa los puertos de `application`. `shared` no depende de ninguna capa.

### 5.2 Reglas que siempre aplican
1. `domain` es Python puro: no importa `fastapi`, `sqlalchemy`, `pydantic`, `psycopg` ni `httpx`. import-linter lo verifica, como el `ARCH-01` de CAUDAL.
2. Un router no llama a un repositorio ni a un adaptador: solo a un caso de uso o a una fachada.
3. Las dependencias se arman solo en `container.py`. Nada de service locators ni instancias globales repartidas por los módulos.
4. La hora solo llega por el `Clock` inyectado. Solo `SystemClock` lee la hora del sistema; `datetime.now()`, `datetime.utcnow()`, `date.today()` y `time.time()` están prohibidos en el resto del código. Las pruebas usan un reloj fijo.
5. Toda escritura pasa por un caso de uso y una unidad de trabajo. Dentro de cada transacción se fijan `app.clinic_id` y `app.user_id` con `SET LOCAL` para que actúe la RLS. En la práctica se usa `SELECT set_config('app.clinic_id', :clinic_id, true)`, que equivale y acepta parámetros. Nunca se fijan a nivel de conexión.
6. Los eventos de dominio (P17) se publican **después del commit**, nunca dentro de la transacción.
7. Los datos clínicos no se borran ni se editan: se corrigen con una fila nueva (append-only con correcciones).
8. Las excepciones de negocio son `*Error` con un `ErrorCode`; el mapeo a HTTP vive solo en el manejador de errores de `api`.
9. Nada de `utils.py` ni `helpers.py` con lógica de negocio: la lógica va en un concepto con nombre.

### 5.3 Convenciones de nombres

| Tipo | Patrón | Ejemplo |
|---|---|---|
| Router (clase que arma un `APIRouter` con casos de uso inyectados) | `*Router` | `GlucoseReadingRouter` |
| Entrada HTTP | `*Request` | `RecordGlucoseReadingRequest` |
| Salida HTTP | `*Response` | `GlucoseReadingResponse` |
| Entrada de caso de uso | `*Input` | `RecordGlucoseReadingInput` |
| Caso de uso | `*UseCase` con `execute()` | `RecordGlucoseReadingUseCase.execute(input)` |
| Puerto | `*Port` | `GlucoseReadingPort`, `AiServicePort` |
| Adaptador | `*Adapter` | `AiServiceClientAdapter` |
| Repositorio (SQLAlchemy) | `*Repository` | `GlucoseReadingRepository` |
| Modelo ORM | `*Orm` | `GlucoseReadingOrm` |
| Comando y su handler | `*Command`, `*CommandHandler` | `ApproveRecommendationCommand`, `ApproveRecommendationCommandHandler` |
| Evento de dominio | Concepto en pasado | `HypoglycemiaDetected` |
| Excepción de negocio | `*Error`, con `ErrorCode` | `RecommendationStateError` |
| Prueba | `test_*.py` | `test_glucose_reading_validation_handler.py` |

### 5.4 Formato canónico de error

```json
{"error": {"code": "ENGLISH_CODE", "message": "mensaje en español", "detail": {}}}
```

- `code`: valor de `ErrorCode`, en inglés y en mayúsculas (`GLUCOSE_OUT_OF_RANGE`, `SESSION_REVOKED`).
- `message`: texto en español tomado de `messages_es`.
- `detail`: objeto opcional (por ejemplo, errores por campo) sin datos personales.
- Una excepción no controlada responde con este formato y `INTERNAL_ERROR`, sin traza ni nombre de clase.

### 5.5 Contrato con `insumap-database`
- El esquema lo define `insumap-database`. Este repo nunca crea ni altera tablas: nada de `metadata.create_all` ni Alembic propio. Los `*Orm` solo mapean.
- `db-schema.lock` fija la etiqueta `db-vX.Y.Z` en uso. La CI hace checkout de `NicoalsD/insumap-database` en esa etiqueta, levanta PostgreSQL 18 y corre `alembic upgrade head` antes de las pruebas de integración. En local, las pruebas con Testcontainers aplican las mismas migraciones.
- La API se conecta como `insumap_app`: sin DDL y sujeta a RLS.
- Un cambio de esquema va primero en `insumap-database` (PR, merge y etiqueta). Después se sube `db-schema.lock` aquí, en el mismo PR que usa el cambio.
- La prueba de deriva compara `FieldLimits` con `information_schema`. Si falla, se corrige con una migración nueva en `insumap-database` y una constante aquí, nunca editando la BD a mano.

### 5.6 Integración con la IA
- `AiServiceClientAdapter` (P06) llama a `insumap-ai` con token de servicio (`AI_SERVICE_TOKEN`) y timeouts. `RemoteAiServiceProxy` (P11) agrega el circuit breaker (`CircuitBreakerState`, P18) y el respaldo determinista por reglas.
- Cada salida de IA se guarda en el esquema `ai` con la versión del modelo, la explicación y la decisión del médico.
- Las recomendaciones pasan por comandos (P13) con motivo obligatorio al modificar o rechazar. **La IA nunca da dosis al paciente.**
- Contrato: [`docs/Contrato-IA.md`](docs/Contrato-IA.md). Módulo: [`docs/Modulo-IA.md`](docs/Modulo-IA.md).

## 6. Checklist para una funcionalidad nueva

1. Ubica la historia de usuario y el requisito ([`docs/Historias-de-usuario.md`](docs/Historias-de-usuario.md), [`docs/Requerimientos.md`](docs/Requerimientos.md)) y sus commits previstos en [`docs/Plan-de-commits.md`](docs/Plan-de-commits.md).
2. Si cambia el esquema: migración en `insumap-database` primero, nueva etiqueta y `db-schema.lock` actualizado. Si hace falta un permiso, se agrega como semilla allá, no en código.
3. Límites nuevos en `FieldLimits`, con su prueba de deriva.
4. Dominio y patrón en `insumap.domain`, con pruebas unitarias y la etiqueta `Pattern: Pnn <Name>`.
5. Puerto, caso de uso (`*UseCase.execute(*Input)`) y prueba con dobles de los puertos.
6. `*Repository` y `*Orm`, con prueba de integración en Testcontainers (incluida la RLS entre clínicas).
7. `*Request` y `*Response` con `extra="forbid"`; `*Router` con descripción de Swagger en español; dependencias en `container.py`.
8. Pruebas de API: validación, `401`, `403`, `404` de otra clínica o de un paciente no asignado y caso feliz.
9. Auditoría (P09) si la acción lee datos clínicos o cambia datos de seguridad; evento (P17) publicado después del commit si dispara efectos.
10. `uv run lint-imports` y cobertura del dominio.
11. Actualiza `docs/API.md`, el diccionario de datos, `.env.example` y los diagramas afectados.
12. Commits pequeños `tipo: descripción`; PR hacia `develop` con los patrones listados.

## 7. Definition of Done

- [ ] CI en verde: `commit-lint`, `ruff`, `mypy --strict`, `lint-imports`, pytest (unitarias e integración contra la etiqueta de `db-schema.lock`), Gitleaks y CodeQL.
- [ ] Cobertura: dominio ≥ 90 %, global ≥ 80 %.
- [ ] Sin valores quemados ni secretos; `.env.example` al día.
- [ ] Entradas validadas, permisos y RLS probados, errores con el formato canónico.
- [ ] Swagger documenta el endpoint en español.
- [ ] Cada patrón nuevo tiene clase propia, prueba, etiqueta `Pattern: Pnn <Name>` y aparece en el PR.
- [ ] Documentación y diagramas actualizados.
- [ ] Commits con la cuenta del integrante responsable y sin atribución a IA.

## 8. Documentación de apoyo

### 8.1 Guías operativas (`.agents/`)

| Estado | Archivo | Contenido |
|---|---|---|
| [x] | [`.agents/workflow.md`](.agents/workflow.md) | Cuentas, ramas, commits, PR, subagentes y versiones (idéntico en los 5 repos) |
| [ ] | `.agents/architecture.md` | Paquetes, dónde va cada cosa, convenciones de nombres |
| [ ] | `.agents/design-patterns.md` | Patrones del backend con esqueletos en Python |
| [ ] | `.agents/security.md` | Implementación de los controles de seguridad |
| [ ] | `.agents/input-validation.md` | Tabla canónica de campos, límites y patrones |
| [ ] | `.agents/configuration.md` | Dónde va cada tipo de valor |
| [ ] | `.agents/api-documentation.md` | Reglas de Swagger y OpenAPI |
| [ ] | `.agents/testing-plan.md` | Estrategia y matriz de pruebas |
| [ ] | `.agents/deployment.md` | Docker, Render y Neon |

### 8.2 Documentación canónica (`docs/`, Fase 0)

| Estado | Archivo | Contenido |
|---|---|---|
| [ ] | `docs/Insumap.md` | Visión del producto |
| [ ] | `docs/Requerimientos.md` | Requisitos funcionales y no funcionales |
| [ ] | `docs/Historias-de-usuario.md` | Historias por rol |
| [ ] | `docs/Actores-y-permisos.md` | Actores, roles y matriz de permisos |
| [ ] | `docs/Arquitectura.md` | C4, capas y reglas de dependencia |
| [ ] | `docs/Modelo-de-datos.md` y `docs/Diccionario-de-datos.md` | Esquemas, tablas y columnas |
| [x] | `docs/API.md` | Endpoints, permisos y errores |
| [ ] | `docs/Patrones-de-diseno.md` | Catálogo P01 a P23 |
| [ ] | `docs/Modulo-IA.md` y `docs/Contrato-IA.md` | Casos IA1 a IA7, evaluación y contrato backend-IA |
| [ ] | `docs/Datos-simulados.md` | Clínica demo, escenarios y modos del simulador |
| [x] | `docs/Seguridad.md` y `docs/Cumplimiento-y-privacidad.md` | Controles y normativa colombiana con fuentes verificadas |
| [ ] | `docs/Metricas-clinicas.md` | TIR, TBR, TAR, CV, GMI y AGP con sus fuentes |
| [ ] | `docs/Stack-tecnologico.md` | Tecnologías y versiones |
| [ ] | `docs/Roles-y-planeacion.md` y `docs/Plan-de-commits.md` | Reparto por integrante y plan de commits `B###`, `D###`, `F###`, `A###`, `S###` |
| [ ] | `docs/images/` | Diagramas draw.io (`.drawio` + `.png`) |
