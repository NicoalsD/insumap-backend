# Plan de pruebas del backend

> Estrategia de pruebas de `insumap-backend` para agentes y para el equipo. Define qué se prueba en cada nivel, qué cubre cada módulo, cómo se nombran las pruebas, con qué datos y con qué comandos. Los jobs de CI se describen como previstos para la Fase 1; sus nombres definitivos se fijan en el workflow.

## 1. Pirámide de pruebas

| Nivel | Qué prueba | Herramientas | Requiere BD o Docker | Ejecución típica |
|---|---|---|---|---|
| Unitaria de dominio | Entidades, value objects, reglas (P08), estados (P18), cálculos de TIR, TBR, TAR, CV y GMI | pytest | No | Segundos. Siempre. |
| Unitaria de aplicación | Casos de uso con puertos falsos (fakes escritos a mano) | pytest | No | Segundos. Siempre. |
| Patrones | Una prueba por cada patrón P01 a P23 (sección 4.3) | pytest | No | Segundos. Siempre. |
| Arquitectura | Reglas de capas con import-linter y reglas AST (reloj, valores quemados) | `lint-imports`, pytest con `ast` | No | Segundos. Siempre. |
| API | Validación (422), autenticación (401), permisos (403), otra clínica o paciente no asignado (404), caso feliz y formato canónico de error | pytest + `TestClient` de FastAPI (httpx) | No con fakes; con BD en la suite de integración | Segundos. Siempre. |
| Contrato con la IA | Adaptador y proxy frente a un servidor HTTP simulado: respuesta válida, timeout, 5xx, token incorrecto, circuit breaker | pytest + `respx` | No | Segundos. Siempre. |
| Integración | Repositorios, `*Orm`, RLS entre clínicas, tablas append-only desde la API, `set_config` por transacción, eventos después del commit | pytest + Testcontainers con PostgreSQL 18 | Sí (Docker) | Minutos. En cada PR y en `develop` y `main`. |
| Deriva | `FieldLimits` contra `information_schema`; catálogo de mensajes contra `ErrorCode` | pytest + Testcontainers | Sí | Parte de la integración. |
| Seguridad | Matriz de autorización por rol, entradas maliciosas, JWT, refresh, cabeceras, logs | Mezcla de los anteriores | Parte con BD | Parte de API e integración. |

Regla: si una prueba puede escribirse en un nivel más bajo, se escribe ahí. Una prueba de integración no reemplaza una prueba de dominio. Un test de API no repite lo que ya prueba el caso de uso; solo verifica HTTP.

## 2. Cobertura

| Alcance | Umbral mínimo | Comando | Dónde se verifica |
|---|---|---|---|
| `insumap.domain` | 90 % (líneas) | `uv run coverage report --include="src/insumap/domain/*" --fail-under=90` | Job de cobertura en CI |
| Proyecto completo | 80 % (líneas) | `uv run pytest --cov=insumap --cov-fail-under=80` | Job de cobertura en CI |

Notas:

- Las ramas (`branch = true` en `[tool.coverage.run]`) se reportan. El umbral inicial es de líneas; si el equipo decide exigir ramas, se documenta aquí.
- Las exclusiones (`container.py`, código generado, `__main__`) se listan en `[tool.coverage.report]` de `pyproject.toml` y se revisan en cada PR.
- Un PR que baja la cobertura por debajo de un umbral no se fusiona.
- La cobertura mide ejecución, no calidad. Un test sin aserciones significativas no cuenta como cobertura útil; se revisa en el PR.

## 3. Estructura y matriz de módulos

### 3.1 Estructura de carpetas

```
tests/
├── conftest.py          # fixtures globales: reloj fijo, Settings de prueba, app de prueba
├── factories/           # constructores de datos de prueba (sin Faker, sin datos reales)
├── fixtures/            # Bundles FHIR y CSV de prueba, con aviso de datos de prueba
├── unit/                # dominio, aplicación y utilidades; sin FastAPI ni BD
│   └── patterns/        # una prueba por patrón (P01 a P23)
├── architecture/        # import-linter y reglas AST
├── api/                 # HTTP con FastAPI; fakes por defecto
├── contract/            # adaptadores de la IA frente a un servidor simulado
└── integration/         # Testcontainers PostgreSQL 18 + migraciones de insumap-database
```

### 3.2 Matriz de casos por módulo

La columna "Nivel" indica dónde vive la prueba principal. Los módulos M1 a M13 son los del producto, descritos en [`docs/Insumap.md`](../docs/Insumap.md).

| Módulo | Casos clave | Nivel |
|---|---|---|
| M1 Identidad y acceso | Argon2id con política de longitud; activación de un solo uso con expiración y guardada como hash; rate limit en login y activación; MFA TOTP obligatorio para todo rol distinto de `PATIENT`; rotación del refresh y detección de reutilización (revoca la familia) | Dominio, aplicación, API, integración, seguridad |
| M2 Clínicas y usuarios | Permisos desde la BD con denegación por defecto; usuario sin membresía recibe `403`; clínica con `is_demo = true` marcada en la respuesta | Aplicación, API, integración |
| M3 Onboarding desde la BD de la clínica | Bundle FHIR R4 y CSV válidos e inválidos; deduplicación por número de historia de la clínica; cuenta creada en `IMPORTED`; pipeline de importación (P20) con su parser, mapper y validador (P03) | Dominio, aplicación, integración |
| M4 Equipo de atención | Un médico principal por paciente; médico no asignado recibe `404`; asignación solo por `CLINIC_ADMIN` de la misma clínica | Aplicación, API, integración |
| M5 Registros del paciente | Cadena de validación (P12): rango físico, duplicado, salto anormal, fecha futura, antigüedad; corrección con fila nueva sin borrar el original; idempotencia por identificador del cliente (mismo contenido `200`, otro contenido `409`); `422` sin guardar | Dominio, aplicación, API, integración |
| M6 Plan de tratamiento | Invariantes del `TreatmentPlanBuilder` (P04); plantilla clonada en `DRAFT` (P05); memento antes de cada cambio (P16); activación solo desde `DRAFT` con el comando (P13) | Dominio, aplicación, integración |
| M7 Métricas glucémicas | TIR, TBR, TAR, CV y GMI con las metas de la versión vigente del perfil; ventanas diarias, nocturnas y de 14 días (P14); zona horaria de la clínica; reloj fijo | Dominio |
| M8 Alertas y notificaciones | Regla compuesta (P08) con duración; escalamiento (P12); estado de la alerta (P18); notificación por canal (P07); las notificaciones no contienen datos clínicos en el asunto | Dominio, aplicación, integración |
| M9 IA y soporte a decisiones | Respaldo por reglas cuando la IA no responde (P11); circuit breaker abierto (P18); la recomendación sin decisión del médico no se aplica; el payload hacia la IA solo contiene el seudónimo, nunca nombre, documento ni contacto; la IA nunca propone dosis al paciente | Dominio, aplicación, contrato, integración |
| M10 Dashboard médico y reportes | Fachada del dashboard (P10) sin filtrar pacientes no asignados; reporte generado por fábrica (P02) y plantilla (P20); la marca "Datos simulados" aparece en la API y en el reporte | Aplicación, API |
| M11 Mensajería y seguimiento | Un paciente solo escribe a su médico asignado; hilo de otro paciente responde `404` | API, integración |
| M12 Auditoría y cumplimiento | Cada lectura clínica deja fila en `audit.data_access_log` (P09); la cadena de hashes del log detecta alteraciones; el consentimiento queda versionado | Aplicación, integración, seguridad |
| M13 Datos simulados | Bundles del simulador solo se importan a clínicas de prueba o demo; la marca "Datos simulados" es visible; los ejemplos de la API no contienen datos reales | Aplicación, API |

## 4. Nombres, patrones y reglas de pruebas

### 4.1 Nombres

| Elemento | Convención | Ejemplo |
|---|---|---|
| Archivo | `test_*.py`, en la carpeta del nivel | `tests/unit/patterns/test_glucose_reading_validation_handler.py` |
| Función de prueba | `test_` seguido de una frase en inglés, en `snake_case`, que describe el comportamiento | `test_rejects_duplicate_reading` |
| Agrupación | Clase `Test...` opcional, sin estado compartido | `class TestGlucoseReadingValidation:` |
| Fixture | Sustantivo que describe lo que entrega | `frozen_clock`, `patient_in_clinic_a` |
| Marcador | Pruebas de integración con `@pytest.mark.integration` | `pytest -m "not integration"` |

Reglas:

- El nombre dice qué comportamiento se verifica, no qué método se llama.
- Una prueba verifica un comportamiento. Si el nombre necesita "y", son dos pruebas.
- Los nombres de prueba van en inglés. Los textos de error que se verifican pueden estar en español, porque es lo que ve el usuario.
- Los identificadores de la prueba no usan español (`test_registra_glucosa` está prohibido).

### 4.2 Fixtures y factories

- **Reloj:** `FrozenClock` implementa el protocolo `Clock` con un instante fijo y `advance(minutes=...)`. Ninguna prueba depende de la hora real.
- **Fakes:** cada puerto tiene un fake en memoria escrito a mano, por ejemplo `InMemoryGlucoseReadingRepository`. Los dobles de `unittest.mock` solo se usan para verificar llamadas a puertos externos (correo, Web Push).
- **Factories:** funciones con valores por defecto ficticios, por ejemplo `make_glucose_reading(value_mg_dl=112)`. Son funciones simples, no un framework.
- **App de prueba:** la fábrica `create_app(settings, container)` se llama con `Settings` de prueba y un contenedor con fakes. Así la API no toca la BD.
- **BD de integración:** una fixture de sesión levanta `PostgresContainer("postgres:18")`. Otra fixture aplica `alembic upgrade head` desde el checkout de `insumap-database` indicado por `INSUMAP_DATABASE_DIR`, en la etiqueta de `db-schema.lock`.
- **Rol de las pruebas de RLS:** el usuario de la imagen de Testcontainers es superusuario, y un superusuario se salta la RLS. Por eso las pruebas de integración de RLS nunca abren sesiones con ese usuario. Las migraciones pueden correr con el superusuario o con `insumap_migrator`, pero las sesiones de repositorio y de RLS usan `insumap_app`, que no es superusuario ni dueño de las tablas. Si la migración no le da un login utilizable, la fixture de BD lo crea con una contraseña de prueba. Una prueba al inicio de la suite confirma el rol: `rolsuper` y `rolbypassrls` deben ser falsos para `current_user`. Si no lo son, toda la suite de RLS falla antes de correr.
- **Aislamiento:** cada prueba de integración corre en una transacción que se revierte. Las pruebas de una unidad de trabajo que hace `commit` se truncan al terminar, porque la transacción externa no las deshace.
- **Argon2id:** en el perfil de pruebas se usan parámetros bajos para acelerar. Una prueba específica verifica los parámetros de producción una sola vez, sin hacer un hash completo más de una vez.

### 4.3 Patrones: una prueba por patrón

Cada patrón del catálogo (`docs/Patrones-de-diseno.md`) tiene al menos una prueba unitaria sin FastAPI ni BD, en `tests/unit/patterns/`. Un patrón sin prueba no se integra.

| ID | Patrón | Clase principal | Archivo de prueba |
|---|---|---|---|
| P01 | Singleton | `SystemClock` | `test_system_clock.py` |
| P02 | Factory Method | `ReportGeneratorCreator` | `test_report_generator_creator.py` |
| P03 | Abstract Factory | `ClinicIntegrationFactory` | `test_clinic_integration_factory.py` |
| P04 | Builder | `TreatmentPlanBuilder` | `test_treatment_plan_builder.py` |
| P05 | Prototype | `ProtocolTemplate.clone_for_patient()` | `test_protocol_template.py` |
| P06 | Adapter | `FhirPatientAdapter`, `CgmCsvAdapter`, `AiServiceClientAdapter` | `test_fhir_patient_adapter.py` |
| P07 | Bridge | `Notification` × `NotificationChannel` | `test_notification.py` |
| P08 | Composite | `AlertRule` (`AllOfRule`, `AnyOfRule`) | `test_alert_rule.py` |
| P09 | Decorator | `PhiAccessAuditDecorator` | `test_phi_access_audit_decorator.py` |
| P10 | Facade | `DoctorDashboardFacade` | `test_doctor_dashboard_facade.py` |
| P11 | Proxy | `PatientRecordAccessProxy` y `RemoteAiServiceProxy` | `test_patient_record_access_proxy.py`, `test_remote_ai_service_proxy.py` |
| P12 | Chain of Responsibility | `GlucoseReadingValidationHandler` | `test_glucose_reading_validation_handler.py` |
| P13 | Command | `CommandBus` y sus comandos | `test_command_bus.py` |
| P14 | Iterator | `GlucoseWindowIterator` | `test_glucose_window_iterator.py` |
| P15 | Mediator | Solo en `insumap-frontend` (`DashboardFiltersMediator`) | No aplica en este repo |
| P16 | Memento | `TreatmentPlanMemento` | `test_treatment_plan_memento.py` |
| P17 | Observer | `DomainEventPublisher` | `test_domain_event_publisher.py` |
| P18 | State | `AlertState`, `RecommendationState`, `PatientAccountState`, `CircuitBreakerState` | `test_alert_state.py` |
| P19 | Strategy | `RiskScoringStrategy`, `GlycemicTargetStrategy`, `TitrationStrategy` | `test_risk_scoring_strategy.py` |
| P20 | Template Method | `ReportGenerator.generate()` y `PatientImportPipeline.run()` | `test_report_generator.py` |
| P21 | Visitor | `ClinicalEventVisitor` | `test_clinical_event_visitor.py` |
| P22 | Interpreter (opcional) | `AlertRuleInterpreter`: DSL de reglas traducida a P08 | `test_alert_rule_interpreter.py` |
| P23 | Flyweight (opcional) | `InsulinProductFlyweightFactory` | `test_insulin_product_flyweight_factory.py` |

Reglas:

- Cada prueba de patrón tiene la etiqueta `Pattern: Pnn <Name>` en su docstring de módulo o en la clase bajo prueba.
- La prueba verifica el comportamiento del patrón (por ejemplo, que el memento restaura el estado anterior), no solo que la clase existe.
- P17 también se prueba en integración: el evento se publica después del `commit`, nunca dentro de la transacción.

### 4.4 Reglas de PR

- Un cambio de comportamiento sin prueba no se acepta.
- Un bug corregido lleva una prueba de regresión que falla antes del arreglo y pasa después.
- Una regla clínica nueva se agrega primero como prueba del dominio.
- Un patrón nuevo lleva su prueba y aparece en "Patrones de diseño involucrados" del PR.
- Los datos de prueba cumplen la sección 5.

## 5. Datos de prueba

Reglas:

- **Ningún dato de prueba es real.** No se copian datos de producción, de una exportación ni de personas reales.
- **Pacientes y personal:** nombres evidentemente ficticios, como "Paciente de Prueba Uno" o "Médica de Prueba Dos". Usuarios de prueba: `test.doctor`, `test.patient`.
- **Correos:** solo el dominio reservado `example.test`, por ejemplo `paciente.uno@example.test`.
- **Documentos de identidad:** inválidos a propósito, por ejemplo `DOC-DE-PRUEBA-0001`, para que nunca sean reales.
- **Teléfonos:** solo en pruebas que verifican el rechazo de datos personales, con un número ficticio como `300 000 0000`.
- **Clínica de prueba:** "Clínica de Prueba Demo" con `is_demo = true`, cuando la prueba necesita la marca "Datos simulados".
- **Contraseñas de prueba:** constantes en un módulo de fixtures (`tests/factories/passwords.py`). Nunca se usan fuera de las pruebas.
- **Fixtures FHIR y CSV:** viven en `tests/fixtures/`. Los Bundles FHIR llevan `meta.tag` con el aviso "Datos de prueba, no reales". El archivo CSV empieza su nombre con `prueba-`.
- **Series de lecturas:** se generan con funciones deterministas (valores fijos o semilla fija). Ninguna prueba importa datos de `insumap-simulator` ni de una exportación.
- **Reloj:** las pruebas usan `FrozenClock`. Ninguna depende de la hora real.
- **Ejemplos de la API:** los mismos datos ficticios que las fixtures (sección 6 de la guía de documentación de la API).

## 6. Pruebas de seguridad

Cada caso tiene una prueba automatizada (API o integración). Los límites y tiempos se leen de `Settings` o de `FieldLimits` en la prueba; no se escriben a mano.

| Área | Caso | Resultado esperado |
|---|---|---|
| Matriz de autorización | Cada ruta de `app.routes` aparece en la matriz con su resultado para `PLATFORM_ADMIN`, `CLINIC_ADMIN`, `DOCTOR`, `PATIENT` y sin token | Coincide con la matriz. Una ruta sin entrada en la matriz hace fallar la prueba (denegación por defecto) |
| Autorización | `DOCTOR` pide un paciente que no tiene asignado | `404` con el mismo cuerpo que un paciente inexistente |
| Autorización | Usuario de otra clínica pide un recurso por identificador | `404` |
| Autorización | `PATIENT` pide los datos de otro paciente | `404` |
| Permisos | Rol sin permiso, por ejemplo `CLINIC_ADMIN` que intenta aprobar una recomendación clínica | `403` |
| RLS | Consulta directa con `app.clinic_id` de otra clínica | Cero filas (prueba de integración) |
| RLS | Sesión sin `app.clinic_id` | Cero filas en tablas con RLS |
| RLS | Sesión de prueba con rol superusuario o `BYPASSRLS` | La suite se detiene antes de correr las pruebas de RLS (sección 4.2) |
| Login | Usuario inexistente y contraseña incorrecta | Mismo mensaje y tiempo comparable (hash señuelo) |
| Login | Límite de intentos por IP y por cuenta | `429 RATE_LIMITED` al superar el límite de `Settings` |
| Tokens | JWT con `alg` distinto del configurado, incluido `none` | `401` |
| Tokens | `iss` o `aud` incorrectos, `exp` vencido | `401` |
| Tokens | Cambio de contraseña: un token emitido antes deja de ser válido | `401` |
| Refresh | Reutilizar un refresh ya rotado | `401 SESSION_REVOKED`, revocación de toda la familia y evento en `iam.security_events` |
| Entrada | Campo desconocido | `422`, por `extra="forbid"` |
| Entrada | Cuerpo mayor al límite de `FieldLimits` | `413 PAYLOAD_TOO_LARGE` |
| Entrada | Caracteres bidi (U+202A a U+202E, U+2066 a U+2069) o de ancho cero (U+200B a U+200F, U+FEFF) en texto libre | `422` |
| Entrada | Payloads de SQL en parámetros de consulta | Nunca `500`; el valor se trata como texto (consulta parametrizada) |
| Entrada | Paginación fuera de los límites de `FieldLimits`, cursor alterado | `422` en ambos casos, con el código de error que corresponda |
| SQL | Consultas con concatenación o f-strings | No existen: ruff `S608` (SQL con cadenas construidas) está activo, y una prueba recorre los repositorios con parámetros |
| Errores | Excepción no controlada | `500` con `INTERNAL_ERROR`, sin traza ni nombre de la clase |
| Errores | Errores de validación de Pydantic | Sin los campos `input` ni `ctx`, para que no repitan datos sensibles como contraseñas |
| Logs | Petición con `Authorization`, `Cookie`, `password` o `token` | Esos valores aparecen redactados (con `caplog`) |
| Cabeceras | Respuesta de la API | `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` y las demás que defina `docs/Seguridad.md` |
| CORS | Origen no listado en `CORS_ORIGINS` | Sin cabecera `Access-Control-Allow-Origin`. Nunca `*` con credenciales |
| Minimización | Payload enviado a `insumap-ai` | Solo el seudónimo; ni nombre, documento ni contacto (contrato con servidor simulado) |
| Auditoría | Lectura de datos clínicos | Una fila en `audit.data_access_log` por lectura (P09) |
| Inmutabilidad | Corrección de una lectura | La API inserta una fila nueva; el original permanece. Los triggers que rechazan `UPDATE` y `DELETE` se prueban en `insumap-database` |
| IA | Recomendación sin decisión del médico | No aparece como aplicada ni se entrega como instrucción al paciente |

## 7. Pruebas de deriva

- `tests/integration/test_field_limits_drift.py` compara cada límite de `FieldLimits` con `information_schema.columns` del esquema fijado en `db-schema.lock`.
- `tests/unit/shared/test_messages_catalog.py` verifica que cada `ErrorCode` tenga su clave en `messages_es.json`, derivada con la convención de [`configuration.md`](configuration.md), sección 7.
- `tests/api/test_openapi_document.py` compara el documento OpenAPI generado con la copia versionada en `docs/openapi.json` (ver la guía de documentación de la API).

Si una prueba de deriva falla, el cambio se corrige en la fuente (`FieldLimits`, `ErrorCode` o la migración). Nunca se edita la base a mano.

## 8. Pruebas de arquitectura

- `uv run lint-imports` aplica los contratos de capas definidos en `pyproject.toml`: `api → application → domain ← infrastructure`, con `shared` independiente.
- Contrato de dominio: `insumap.domain` no importa `fastapi`, `sqlalchemy`, `pydantic`, `psycopg` ni `httpx`.
- `tests/architecture/test_no_wall_clock.py` recorre el AST de `src/insumap` y falla por llamadas a la hora del sistema fuera de `SystemClock`.
- `tests/architecture/test_no_literal_limits.py` busca `max_length=` con literales numéricos en `api/` y `application/`.
- Las excepciones se listan en la prueba, con comentario y enlace a la decisión. Ninguna excepción se agrega sin revisión.

## 9. Comandos

Todos los comandos se ejecutan desde la raíz del repositorio.

| Propósito | Comando |
|---|---|
| Suite rápida, sin Docker | `uv run pytest -m "not integration"` |
| Solo unitarias y patrones | `uv run pytest tests/unit` |
| Arquitectura | `uv run pytest tests/architecture` y `uv run lint-imports` |
| API | `uv run pytest tests/api` |
| Contrato con la IA | `uv run pytest tests/contract` |
| Integración (requiere Docker) | `uv run pytest -m integration` |
| Un archivo | `uv run pytest tests/unit/patterns/test_glucose_reading_validation_handler.py` |
| Una prueba por nombre | `uv run pytest -k rejects_duplicate_reading` |
| Cobertura global | `uv run pytest --cov=insumap --cov-report=term-missing --cov-fail-under=80` |
| Cobertura del dominio | `uv run coverage report --include="src/insumap/domain/*" --fail-under=90` |
| Formato y estilo | `uv run ruff check . && uv run ruff format --check .` |
| Tipos | `uv run mypy .` (`--strict` en `pyproject.toml`) |

Requisitos:

- Python 3.13 y `uv`.
- Docker Engine para Testcontainers.
- Para la integración en local, un checkout de `insumap-database` en la etiqueta de `db-schema.lock`:

```bash
git -C ../insumap-database fetch --tags
git -C ../insumap-database checkout "$(cat db-schema.lock)"
INSUMAP_DATABASE_DIR=../insumap-database uv run pytest -m integration
```

En CI, el job de integración hace checkout de `NicoalsD/insumap-database` en la misma etiqueta, aplica las migraciones y corre las mismas pruebas.

Marcadores: `integration` está registrado en `[tool.pytest.ini_options]`. Una prueba de integración sin el marcador es un error de revisión.

## 10. Matriz: tipo, cobertura, herramienta y CI

| Tipo de prueba | Qué cubre | Herramienta | Cuándo corre en CI |
|---|---|---|---|
| Unitaria de dominio | Reglas, estados, cálculos (TIR, AGP), value objects | pytest | Cada PR |
| Unitaria de aplicación | Casos de uso con fakes de puertos | pytest | Cada PR |
| Patrones | Un test por patrón P01 a P23 | pytest | Cada PR |
| Arquitectura | Capas, reloj, literales de límites | import-linter, pytest con `ast` | Cada PR |
| API | Validación 422, 401, 403, 404, caso feliz, formato de error | pytest + `TestClient` | Cada PR |
| Contrato con la IA | Adaptador y proxy frente a servidor simulado | pytest + `respx` | Cada PR |
| Seguridad (sin BD) | Matriz de autorización, entradas maliciosas, JWT, cabeceras, logs | pytest | Cada PR |
| Integración | Repositorios, RLS, append-only, transacciones, eventos después del commit | pytest + Testcontainers PostgreSQL 18 | Cada PR (con checkout de `insumap-database`), y en `develop` y `main` |
| Deriva | `FieldLimits` contra la BD; catálogo de mensajes contra `ErrorCode`; OpenAPI contra snapshot | pytest + Testcontainers | Cada PR (la parte de BD, con la integración) |
| Cobertura | Umbrales de dominio y global | `coverage` | Cada PR; bloquea la fusión |
| Estilo y tipos | Formato, lint, `PLR2004`, `mypy --strict` | ruff, mypy | Cada PR |
| Secretos y análisis estático | Secretos en el historial y análisis de seguridad | Gitleaks, CodeQL | Cada PR |

Los nombres definitivos de los jobs se fijan en el workflow de la Fase 1. Un PR no se fusiona con un job en rojo.

## 11. Relacionados

- [`AGENTS.md`](../AGENTS.md) (secciones 3.4, 5 y 7)
- [`configuration.md`](configuration.md): cómo se configuran las pruebas y la `FieldLimits`
- [`api-documentation.md`](api-documentation.md): documentación OpenAPI y snapshot
- [`deployment.md`](deployment.md): cómo llega a producción lo que pasó estas pruebas
