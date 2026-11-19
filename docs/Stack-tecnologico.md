# Stack tecnológico

El stack de Insumap responde a tres tipos de restricciones:

- **Académicas:** backend en Python con patrones de diseño explícitos, IA obligatoria para apoyar decisiones, código en inglés y POO, y 150 commits o más en `insumap-backend`.
- **Del producto:** los datos de salud son datos sensibles (Ley 1581 de 2012). Por eso se exigen aislamiento por clínica, auditoría de cada lectura clínica, consentimiento versionado y minimización hacia la IA. El paciente usa una PWA instalable, diseñada primero para escritorio y usable desde el celular; el médico y el administrador usan un dashboard web diseñado primero para escritorio. Detalle en [Cumplimiento-y-privacidad.md](Cumplimiento-y-privacidad.md).
- **De presupuesto y operación:** costo cercano a cero, un equipo de tres personas y ningún dato real de pacientes. Por eso todo corre en planes gratuitos o de bajo costo, la IA corre en CPU y los pacientes son simulados.

Diagramas relacionados: [contenedores (C4)](images/c4-contenedores.png) · [despliegue](images/despliegue.png).

> **Aviso:** Insumap es un proyecto académico. **No es un dispositivo médico**, no reemplaza el criterio clínico y la IA solo apoya al médico, que toma todas las decisiones. Todos los pacientes son simulados.

## Cómo leer este documento

Cada tabla por repositorio tiene las columnas **Tecnología**, **Versión**, **Uso**, **Por qué** y **Alternativa descartada y motivo**. Cuando el motivo es una cifra o una limitación técnica, se dice cuál. Cuando es criterio del equipo, también se dice.

- **Versiones verificadas el 2026-11-15** en las fuentes oficiales: PyPI, el registro de npm, [endoflife.date](https://endoflife.date), Docker Hub, Hugging Face, el índice CPU de PyTorch y las páginas de releases de GitHub.
- Las versiones del backend son las que ya resolvió `pyproject.toml` en `develop` (esqueleto de la Fase 1). Las de los demás repos son las que se fijarán al crear cada esqueleto.
- **La fuente de verdad de una versión es el lockfile del repo** (`uv.lock` o `package-lock.json`), no esta tabla. Si difieren, gana el lockfile y se corrige este documento en el mismo PR.
- "A confirmar en la Fase 1" significa que la versión o la compatibilidad no se pudo comprobar sin instalar, y se valida al crear el esqueleto.
- Una actualización de versión mayor es un commit `build:` propio, con sus pruebas en verde.

## 1. Resumen de versiones

| Componente | Versión fijada | Repos | Verificación (2026-11-15) |
|---|---|---|---|
| Python | 3.13 (`.python-version`; parche vigente 3.13.18) | backend, database, ai, simulator | endoflife.date: 3.13.18 del 2026-10-25, soporte hasta 2029-10-31 |
| PostgreSQL | 18 (18.7; imagen `postgres:18.7`) | database, backend (pruebas) | endoflife.date: 18.7 del 2026-11-09, soporte hasta 2030-11-14. Tag `18.7` en Docker Hub. Neon ya sirve 18.7 |
| uv | 0.13.8 | repos Python | Release de GitHub `astral-sh/uv` del 2026-11-12 |
| Node.js | 26 LTS (26.13.1) | frontend | endoflife.date: LTS desde 2026-10-28, soporte hasta 2029-04-30. Es la versión por defecto de Vercel |
| FastAPI | 0.163.1 | backend, ai | PyPI, 2026-11-15 |
| React | 19.3.1 | frontend | npm, 2026-10-14 |
| TypeScript | **6.0.3** (no 7.x) | frontend | npm. Ver la sección 9.1 |
| chronos-forecasting | 2.3.2 | ai | PyPI, 2026-09-08 |
| PyTorch (CPU) | 2.15.0 | ai | Rueda `cp313` `manylinux_2_28_x86_64` en el índice CPU de PyTorch |
| simglucose | 0.2.11 | simulator | PyPI, 2024-05-17. Instalación en 3.13 a confirmar en la Fase 1 (sección 9.2) |

## 2. Backend (`insumap-backend`)

| Tecnología | Versión | Uso | Por qué | Alternativa descartada y motivo |
|---|---|---|---|---|
| **Python** | 3.13 | Lenguaje del backend. `requires-python = ">=3.13,<3.14"` | Exigencia de la materia. Es la misma versión en los cuatro repos Python, tiene soporte hasta 2029-10 y es la que soportan hoy todas las dependencias de IA (ruedas CPU de PyTorch `cp313` verificadas). | **Python 3.14 (3.14.10) o 3.15 (3.15.2):** ya existen. Se descartan para no depender de que simglucose, PyTorch y Chronos publiquen ruedas para ellas. Se revisa en la Fase 12. |
| **FastAPI** | 0.163.1 | API REST, OpenAPI y Swagger en español en `/docs` | Genera el contrato OpenAPI desde los modelos tipados. `Depends` solo se usa en el borde: las dependencias se arman en `container.py`. | **Django REST Framework:** su ORM y sus migraciones chocan con la arquitectura hexagonal y con un esquema que vive en `insumap-database`. **Flask:** no trae validación tipada ni OpenAPI integrados. |
| **uvicorn[standard]** | 0.54.0 | Servidor ASGI, un worker por contenedor | El plan gratuito tiene 512 MB de RAM (sección 8). Se escala con instancias, no con workers. | **gunicorn con workers de uvicorn:** cada worker suma memoria; no cabe con holgura en 512 MB. |
| **Pydantic v2** | 2.14.3 | `*Request` y `*Response` con `extra="forbid"` y límites de `FieldLimits`; plugin de mypy | Validación rápida y tipada que alimenta OpenAPI. Solo vive en `api` e `infrastructure`: `domain` es Python puro (lo verifica import-linter). | **marshmallow:** obliga a describir el esquema dos veces, para validar y para OpenAPI. |
| **pydantic-settings** | 2.16.3 | Configuración por variables de entorno, documentadas en `.env.example` | Tipos y validación al arrancar. Los secretos no tienen valor por defecto: si faltan, la API no arranca. | **`os.environ` y python-dotenv sueltos:** sin tipos ni validación; los errores aparecen en producción. |
| **SQLAlchemy 2** | 2.1.8 | Mapeo `*Orm`, `*Repository` y unidad de trabajo; `set_config('app.clinic_id', ..., true)` por transacción | Mapea un esquema ajeno sin crearlo (nada de `metadata.create_all`). Unidad de trabajo explícita para fijar el contexto de RLS en cada transacción. | **SQLModel:** mezcla el modelo Pydantic y el ORM en una sola clase, lo que rompe la separación entre `api` e `infrastructure`. **SQL crudo con psycopg:** no ofrece unidad de trabajo. |
| **psycopg 3** (`[binary]`) | 3.3.9 | Driver de PostgreSQL | Driver mantenido y con parámetros del lado del servidor. La compatibilidad con el pooler de Neon en modo transacción queda pendiente en [`.agents/deployment.md`](../.agents/deployment.md). | **psycopg2:** generación anterior; el proyecto nace en la nueva. **asyncpg:** solo asíncrono, sin la API DB-API que usa la unidad de trabajo síncrona. |
| **httpx** | 0.28.1 | `AiServiceClientAdapter` (P06), con timeouts por fase; cliente de pruebas de la API | Cliente con timeouts finos y el mismo modelo que el `TestClient` de FastAPI. | **requests:** sin timeouts separados por fase ni modo asíncrono. **httpx2 2.16.0** (`pydantic/httpx2`): es su sucesor y lo usa el SDK de OpenAI 3.x (sección 9.4). Se revisa en la Fase 9. |
| **argon2-cffi** | 25.1.0 | Hash de contraseñas con Argon2id. Parámetros en [Seguridad.md](Seguridad.md) | Argon2id es *memory-hard*. Es la implementación de referencia en Python. | **bcrypt:** no es *memory-hard* y trunca a 72 bytes. |
| **PyJWT** | 2.15.1 | JWT de acceso de 15 minutos, con `algorithms` explícito, `iss`, `aud` y `exp` | Un solo emisor y un solo validador: basta HS256 con una biblioteca pequeña. | **Authlib:** cubre OAuth completo, mucho más de lo que se usa. |
| **cryptography** | 50.0.2 | Cifrado del documento del paciente y del secreto TOTP (AES-GCM con `FIELD_ENCRYPTION_KEY`) | Primitivas auditadas y mantenidas. PyJWT también la usa para algoritmos asimétricos. | **PyCryptodome:** equivalente; sumaría una segunda biblioteca criptográfica. |
| **pyotp** | 2.12.0 (propuesta) | MFA TOTP obligatorio para el personal | Implementa la RFC 6238 sin estado. Se confirma en la Fase 3. | **TOTP propio:** reimplementar criptografía es un riesgo sin beneficio. |
| **structlog** | 26.1.0 (propuesta) | Logs JSON con `request_id` y procesador de redacción (sin datos personales ni de salud) | Procesadores encadenados: la redacción es un paso explícito y probable. | **`logging` con python-json-logger 4.2.0:** válido. La elección entre ambos se cierra en la Fase 1 (`.agents/configuration.md`). |
| **APScheduler** | 3.11.3 | Recordatorios, evaluación de alertas y triage nocturno | Programación dentro del proceso, sin broker. La rama 4.0 sigue en alfa (4.0.0a6). Ojo con el plan gratuito de Render (sección 8.1). | **Celery con Redis:** el broker es un servicio más que no cabe en el plan gratuito. **Cron de Render:** no está disponible en el plan Free. |
| **python-multipart** | 0.0.33 (propuesta) | Carga de archivos FHIR y CSV en la importación (M3) | FastAPI lo exige para `UploadFile`. Se agrega en la Fase 4. | **JSON en base64:** infla el cuerpo y complica el límite de tamaño. |
| **uv** | 0.13.8 | Entorno, dependencias y `uv.lock`; imagen `ghcr.io/astral-sh/uv:0.13.8` en el `Dockerfile` | Una sola herramienta, rápida y con lockfile reproducible. | **poetry o pip-tools:** más lentos y con más piezas. |
| **ruff** | 0.17.5 | Lint y formato. Reglas `E, W, F, I, B, UP, N, PL, S, SIM, RUF`; `PLR2004` activo en `src/` | Una sola herramienta reemplaza a flake8, isort, black y buena parte de pylint. `PLR2004` vigila los valores quemados. | **flake8 + black + isort + pylint:** cuatro configuraciones para lo mismo. |
| **mypy** | 2.4.1 | `strict = true` con el plugin de Pydantic | Tipado estricto en todo el paquete `insumap`. | **pyright:** válido; mypy tiene el plugin de Pydantic ya configurado. |
| **pytest + pytest-cov** | 9.2.0 + 7.1.0 | Pruebas unitarias, de API, de contrato e integración; `--cov-fail-under=80` | Estándar del ecosistema, con marcadores (`integration`) y cobertura de ramas. | **unittest:** más código por prueba y sin fixtures componibles. |
| **Testcontainers** (`[postgres]`) | 4.15.0 | Integración contra PostgreSQL 18 real con las migraciones de `insumap-database` | La RLS, los triggers append-only y los roles SQL solo se prueban contra el motor real. Se agrega al esqueleto en la Fase 1. | **SQLite o una base en memoria:** no reproduce RLS, triggers ni roles. |
| **import-linter** | 2.16 | Contratos de capas (equivalente al `ARCH-01` de CAUDAL), ya definidos en `pyproject.toml` | Convierte la arquitectura hexagonal en una prueba que falla. | **Revisión manual:** no escala y se olvida. |
| **pip-audit** | 2.10.1 | Vulnerabilidades conocidas de las dependencias, en CI | Lee el entorno resuelto por uv. | **Solo Dependabot:** avisa, pero no bloquea el PR. |

## 3. Base de datos (`insumap-database`)

| Tecnología | Versión | Uso | Por qué | Alternativa descartada y motivo |
|---|---|---|---|---|
| **PostgreSQL** | 18 (18.7) | Ocho esquemas (`iam`, `clinic`, `care`, `monitoring`, `alerts`, `ai`, `messaging`, `audit`). Ver [Modelo-de-datos.md](Modelo-de-datos.md) | `ENABLE` y `FORCE ROW LEVEL SECURITY` por `clinic_id`, triggers append-only, `jsonb` para las fotos de los planes, `timestamptz` y `uuidv7()` nativo en la versión 18. Neon lo soporta. | **MySQL:** no tiene RLS equivalente. **MongoDB:** el dominio es relacional (asignaciones, versiones, auditoría con cadena de hashes) y necesita restricciones fuertes. |
| **Alembic** (standalone) | 1.20.1 | Migraciones con SQL escrito a mano (`op.execute`), sin modelos ni `autogenerate`; etiquetas `db-vX.Y.Z` | Versiona y ordena las migraciones en Python, el mismo lenguaje del equipo, sin ocultar el SQL de RLS, roles y triggers. | **Flyway:** sumaría un runtime de Java a un stack Python (CAUDAL lo usó porque su backend era Java). **`autogenerate`:** necesita modelos y no genera RLS, roles ni triggers. |
| **psycopg 3 + SQLAlchemy** | 3.3.9 + 2.1.8 | Driver de Alembic; SQLAlchemy entra solo como dependencia de Alembic | Mismas versiones que el backend. | Ninguna: Alembic exige SQLAlchemy. |
| **pytest + Testcontainers** | 9.2.0 + 4.15.0 | Pruebas de esquema: aislamiento entre clínicas, append-only, privilegios de cada rol y cadena de hashes | Se prueban contra PostgreSQL 18 limpio, igual que en CI. | **Pruebas manuales en psql:** no se repiten en cada PR. |
| **ruff, mypy, uv** | 0.17.5, 2.4.1, 0.13.8 | Lint, tipos y entorno de los módulos Python de migraciones y pruebas | Mismas herramientas y versiones que el backend. | Ninguna. |
| **Docker Compose** | Incluido en Docker Engine | PostgreSQL 18 local con las migraciones aplicadas | Mismo motor y versión que en la nube. | **PostgreSQL instalado a mano:** difícil de reproducir entre equipos. |

## 4. Frontend (`insumap-frontend`)

| Tecnología | Versión | Uso | Por qué | Alternativa descartada y motivo |
|---|---|---|---|---|
| **Node.js + npm** | 26 LTS (26.13.1) | Build, pruebas y servidor de desarrollo | Es la LTS activa y la versión por defecto de Vercel. Cumple los `engines` de React Router 8 (`>=22.22.0`), jsdom 31 y Vitest 5. npm viene con Node (lo fija el `AGENTS.md` del frontend). | **Node 24 LTS (24.22.3, soporte hasta 2028-04-30):** queda como respaldo si alguna herramienta falla en 26. **pnpm:** una herramienta más; npm basta. |
| **React** | 19.3.1 | PWA del paciente, dashboard del médico y consola del admin | Experiencia del equipo y ecosistema de PWA, gráficas y pruebas. | **Vue o Svelte:** sin experiencia del equipo. |
| **TypeScript** | **6.0.3** | Tipado estricto (`strict`, `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`) | typescript-eslint 8.72.2 declara `typescript >=4.8.4 <6.1.0` como dependencia par. | **TypeScript 7.0.2** (compilador nativo): es el `latest` de npm, pero rompe el lint con tipos (sección 9.1). |
| **Vite + @vitejs/plugin-react** | 8.3.8 + 6.3.0 | Build y servidor de desarrollo | Rápido y sin servidor en producción: el build es estático. | **Next.js:** su valor es el renderizado en el servidor, que una app autenticada no necesita, y agrega un runtime que la PWA no usa. |
| **React Router** | 8.5.1 | Rutas por rol (`PATIENT`, `DOCTOR`, `CLINIC_ADMIN`, `PLATFORM_ADMIN`) | Modelo de rutas maduro. Exige React `>=19.2.7`, que se cumple. | **TanStack Router:** válido, menos conocido por el equipo. |
| **TanStack Query** | 5.107.1 | Estado del servidor: caché, reintentos e invalidación | Separa el estado del servidor del de la UI. Los reintentos cubren el arranque en frío de Render. | **Redux Toolkit:** más ceremonia para un estado que casi todo viene de la API. |
| **Zod** | 4.6.7 | Validación de formularios y de las respuestas en el adapter de DTO a modelo de vista | Un esquema da tipos y validación en tiempo de ejecución. | **Yup:** inferencia de tipos más débil. |
| **Recharts** | 3.10.1 | AGP (bandas de percentiles), barras de TIR y cuantiles del pronóstico | Componentes declarativos de áreas y líneas, compatibles con React 19. | **Chart.js:** más código para las bandas. **D3 directo:** potente, pero demasiado bajo nivel para el alcance. |
| **Vitest + @vitest/coverage-v8 + jsdom** | 5.1.0 + 5.1.0 + 31.0.1 | Pruebas unitarias y de componentes, con cobertura | Mismo pipeline que Vite y sin configuración aparte. | **Jest:** requiere configuración extra para ESM y Vite. |
| **Testing Library** | `react` 16.3.3, `user-event` 14.6.11, `jest-dom` 7.0.1 | Pruebas centradas en lo que ve el usuario | Empuja a consultar por rol y etiqueta, lo que también mejora la accesibilidad. | **Enzyme:** sin soporte para React moderno. |
| **MSW** | 3.0.6 | Simula la API en pruebas y en desarrollo | Intercepta a nivel de red: el código de la app no cambia. | **Mocks manuales de `fetch`:** frágiles y repartidos por las pruebas. |
| **Playwright + @axe-core/playwright** | 1.65.1 + 4.14.0 | Flujos extremo a extremo y accesibilidad (WCAG 2.2 AA) | Navegador real; axe falla la prueba si hay violaciones. | **Cypress:** un solo navegador por ejecución y menos control de varias pestañas. |
| **ESLint + typescript-eslint** | 10.15.0 + 8.72.2 (`@eslint/js` 10.0.1, `eslint-plugin-react-hooks` 7.1.1) | Calidad: `no-magic-numbers` y prohibición de `dangerouslySetInnerHTML` (la regla exacta se elige en la Fase 1) | Reglas de seguridad y de valores quemados aplicadas en CI. | **Solo el formateador:** no detecta errores ni valores quemados. |
| **vite-plugin-pwa** | 2.0.0 (candidato) | Manifest, service worker y caché | Declara Vite 8 como dependencia par. La herramienta de PWA se elige en la Fase 1, como dice el `AGENTS.md` del frontend. | **Service worker escrito a mano:** más riesgo de errores de caché. |

## 5. IA (`insumap-ai`)

| Tecnología | Versión | Uso | Por qué | Alternativa descartada y motivo |
|---|---|---|---|---|
| **FastAPI, Pydantic, pydantic-settings, uvicorn** | 0.163.1, 2.14.3, 2.16.3, 0.54.0 | Contrato de [Contrato-IA.md](Contrato-IA.md), salud y configuración | Mismas versiones que el backend. Swagger en español. | **Flask:** sin validación tipada integrada. |
| **chronos-forecasting** | 2.3.2 | Pronóstico de glucosa con cuantiles (IA1), modo *zero-shot* | Modelo preentrenado: no necesita historial real. Pide `torch >=2.2,<3`, `transformers <6` y `accelerate`. El equipo ya lo usó en caudal-ia. | **Entrenar un modelo propio con datos simulados:** aprendería el simulador, no a los pacientes. |
| **Chronos-Bolt** (`amazon/chronos-bolt-tiny`, `amazon/chronos-bolt-small`) | Pesos en Hugging Face, licencia Apache-2.0 | Modelos por defecto, elegidos por variable de entorno | Pequeños y pensados para CPU. Tamaños según la ficha pública: `tiny` 9M y `small` 48M (ver [Modulo-IA.md](Modulo-IA.md), sección 9). | **`chronos-bolt-base` o Chronos-2 (`amazon/chronos-2`):** más memoria; no caben con holgura en 512 MB. Chronos-2 admite covariables y queda como opción futura. |
| **PyTorch CPU** | 2.15.0 | Ejecución de Chronos | Índice `https://download.pytorch.org/whl/cpu` en `[tool.uv.sources]`; sin librerías CUDA. | **PyTorch con CUDA:** varios GB de dependencias y sin GPU en el hosting. |
| **scikit-learn** | 1.9.1 | Triage calibrado (IA2), Isolation Forest (IA3) y riesgo de abandono (IA7) | Modelos clásicos, explicables y rápidos en CPU. | **XGBoost o LightGBM:** suman dependencias nativas sin una ganancia que justifique el costo con cohortes simuladas. |
| **numpy + pandas** | 2.5.5 + 3.1.1 | Ventanas de la serie CGM y características | Estándar del ecosistema. pandas 3 es versión mayor: los cambios de comportamiento por defecto se revisan al crear el esqueleto. | **polars:** válido; Chronos y scikit-learn trabajan con pandas y numpy. |
| **SDK `openai`** | 3.51.0 (propuesta) | Cliente del LLM compatible con OpenAI (`LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`) para IA5 e IA6 | Un solo cliente sirve para DeepSeek, Qwen vía OpenRouter o Gemini cambiando la URL base. Depende de `httpx2`. El proveedor se elige en la Fase 10. | **Llamar con httpx directo:** válido y con menos dependencias; se decide en la Fase 10. **LangChain:** una capa grande que ocultaría el `PromptBuilder` (P04) y los guardrails (P12). |
| **uv, ruff, mypy, pytest** | 0.13.8, 0.17.5, 2.4.1, 9.2.0 | Entorno, lint (`PLR2004`), tipos y pruebas sin red | Mismo estilo que los demás repos Python. Las pruebas usan `OfflineProviderFactory`. | **poetry + black + flake8:** más piezas para lo mismo. |

## 6. Simulador (`insumap-simulator`)

| Tecnología | Versión | Uso | Por qué | Alternativa descartada y motivo |
|---|---|---|---|---|
| **simglucose** | 0.2.11 | Series CGM de DM1 con el simulador UVA/Padova, detrás de `SimglucoseAdapter` (P06) | Implementación abierta (MIT) del simulador aceptado para DM1. | **Modelo de glucosa propio:** no tendría la validación del UVA/Padova. Riesgo de instalación en la sección 9.2. |
| **Faker** (`es_CO`) | 40.54.0 | Nombres, direcciones y teléfonos ficticios de Colombia | El locale `es_CO` existe en el repo de Faker (proveedores `person` y `address`). | **Listas de nombres propias:** más trabajo y menos variedad. |
| **numpy + pandas** | 2.5.5 + 3.1.1 | Series, escenarios y exportación CSV | Mismas versiones que `insumap-ai`, que consume los datasets. | Ninguna. |
| **Pydantic v2 + pydantic-settings** | 2.14.3 + 2.16.3 | Modelos FHIR R4 propios (`Patient`, `Practitioner`, `Condition`, `Observation` con LOINC, `MedicationRequest`, `Bundle`), escenarios y configuración | El importador del backend espera FHIR **R4 (4.0.1)**. Se modelan solo los recursos que se usan. | **fhir.resources 8.3.0:** desde la 7.0 trae R5 por defecto y R4B (4.3.0), pero ya no R4 (sección 9.3). |
| **httpx** | 0.28.1 | Modo `live`: envía lecturas a la API con tokens de paciente | Mismo cliente que el backend. | **requests:** sin modo asíncrono para varios pacientes a la vez. |
| **Typer** | 0.29.1 (candidato) | CLI `insumap-sim backfill`, `live`, `dataset` | Construye la CLI desde funciones tipadas. La herramienta de CLI se elige al crear el esqueleto. | **argparse:** más código para lo mismo. |
| **uv, ruff, mypy, pytest** | 0.13.8, 0.17.5, 2.4.1, 9.2.0 | Entorno, lint, tipos y pruebas deterministas con semilla | Mismas herramientas que los demás repos Python. | Ninguna. |

## 7. CI con GitHub Actions

Los cinco repos son públicos y están bajo la cuenta personal `NicoalsD`. Eso da CodeQL y minutos de Actions sin costo, y gitleaks-action sin licencia (la licencia solo se exige a organizaciones).

### 7.1 Jobs por repositorio

| Job | Herramienta | backend | database | frontend | ai | simulator |
|---|---|---|---|---|---|---|
| `commit-lint` | `.githooks/commit-msg` sobre título, cuerpo y commits del PR (ya existe) | Sí | Sí | Sí | Sí | Sí |
| `lint` | `ruff check` y `ruff format --check` / ESLint | Sí | Sí | Sí | Sí | Sí |
| `types` | `mypy --strict` / `mypy` / `tsc --noEmit` | Sí | Sí | Sí | Sí | Sí |
| `architecture` | `lint-imports` | Sí | | | | |
| `migrations` | `alembic upgrade head` sobre PostgreSQL 18 limpio y pruebas de esquema | | Sí | | | |
| `tests` | pytest (unitarias e integración con Testcontainers; el backend hace checkout de `insumap-database` en la etiqueta de `db-schema.lock`) / Vitest | Sí | Sí | Sí | Sí (sin red) | Sí |
| `e2e` | Playwright con axe | | | Sí | | |
| `coverage` | `coverage` / `@vitest/coverage-v8` con los umbrales de la sección 10 | Sí | | Sí | Sí | Sí |
| `codeql` | CodeQL (`python`, `javascript-typescript`), en cada PR y semanal | Sí | Sí | Sí | Sí | Sí |
| `gitleaks` | gitleaks-action | Sí | Sí | Sí | Sí | Sí |
| `audit` | `pip-audit` / `npm audit --audit-level=high` | Sí | Sí | Sí | Sí | Sí |
| Dependabot | Ecosistemas `uv`, `npm`, `github-actions` y `docker`; semanal | Sí | Sí | Sí | Sí | Sí |

### 7.2 Versiones de las actions

| Action | Versión vigente | Uso |
|---|---|---|
| `actions/checkout` | v7.0.1 | Todos los jobs. `commit-lint.yml` todavía usa `@v4` y se actualiza en la Fase 1 |
| `astral-sh/setup-uv` | v10.3.3 | Jobs Python |
| `actions/setup-node` | v7.1.0 | Jobs del frontend |
| `github/codeql-action` | v4 (v4.39.3) | CodeQL |
| `gitleaks/gitleaks-action` | v3.0.0 | Secretos |
| `actions/upload-artifact` | v7.0.2 | Reportes de cobertura y de Playwright |
| `actions/dependency-review-action` | v5.0.0 (opcional) | Revisión de dependencias nuevas en el PR |

Reglas:

- Toda action se fija a un **SHA de commit** con la versión en un comentario. Dependabot (`github-actions`) propone las actualizaciones.
- Dependabot soporta el ecosistema `uv`, pero su tabla de ecosistemas lista uv v0.11 y el proyecto usa 0.13.8. Que sus PR regeneren bien `uv.lock` queda a confirmar en la Fase 1.
- GitHub Actions entra a AWS con OIDC (roles por repo y rama); no hay llaves de AWS ni secretos de despliegue en GitHub.
- Las pruebas de CI nunca llaman al LLM ni descargan pesos de modelos.

## 8. Hosting e infraestructura

Plan vigente desde el 2026-11-19: todo en una cuenta de AWS (us-east-1), con unos USD 72 de crédito y una vida de una semana. Detalle y pasos en [`.agents/deployment.md`](../.agents/deployment.md); plantilla en [`infra/aws/insumap.yaml`](../infra/aws/insumap.yaml).

| Servicio de AWS | Qué aloja | Costo aproximado por semana | Alternativa descartada y motivo |
|---|---|---|---|
| **EC2 `t3.small`** (Amazon Linux 2023, Docker Compose) con IP elástica y EBS gp3 de 20 GB | API `insumap-backend` y PostgreSQL 18 en el mismo host | Unos USD 4,5 (instancia, IPv4 pública y disco) | **RDS + ECS Fargate:** más de USD 25 por semana con el balanceador, sin ganancia para una demo. **App Runner:** no aloja PostgreSQL. |
| **CloudFront + S3** (OAC, CloudFront Function para la SPA) | Build de `insumap-frontend` y proxy `/api/*` hacia el host | Centavos con el tráfico de una demo | **Amplify Hosting:** no sirve la API en el mismo origen sin un proxy extra. |
| **ECR** | Imágenes de la API (5 últimas) | Centavos | **Construir en el host:** gasta la memoria que necesitan la API y la base. |
| **Secrets Manager + KMS** | Llaves de la API y contraseñas de la base | Unos USD 0,35 | **Variables de GitHub o archivos en el host:** sin cifrado con llave propia ni auditoría. |
| **SSM Run Command** + **IAM OIDC** | Despliegue desde GitHub Actions sin SSH ni llaves de larga duración | Sin costo | **SSH con llave en GitHub:** puerto 22 abierto y un secreto que rotar. |
| **GitHub** | Código, Actions, CodeQL, Dependabot, secret scanning | Free, repos públicos | **CI propio:** operación adicional para el equipo. |

Total estimado: menos de USD 10 por semana. Los despliegues viejos (Render, Vercel y Neon) no se usan.

### 8.1 Consecuencias del plan (decisiones pendientes)

1. **Una sola instancia.** No hay alta disponibilidad ni respaldos automáticos: la base solo tiene datos simulados y se regenera con la semilla.
2. **Correo:** sigue pendiente un proveedor (SES o uno con API HTTPS) para invitaciones y recordatorios.
3. **Scheduler:** cuando exista en el código, corre como otro servicio del mismo `compose.yaml`; al haber un solo host no hay riesgo de duplicar alertas.
4. **Memoria:** API, PostgreSQL y la IA futura comparten 2 GB más 2 GB de swap. Si no alcanza, se sube a `t3.medium`.
5. **Datos fuera de Colombia:** us-east-1 aloja los datos en el exterior. Con datos simulados no aplica; con datos reales es una transmisión internacional que exige contrato. Ver [Cumplimiento-y-privacidad.md](Cumplimiento-y-privacidad.md), sección 11.

## 9. Compatibilidades verificadas que cambian una decisión

### 9.1 TypeScript 7 y typescript-eslint
`typescript@latest` es 7.0.2 (compilador nativo, 2026-07-08), pero `typescript-eslint` 8.72.2 declara `typescript >=4.8.4 <6.1.0`. Por eso se fija **TypeScript 6.0.3** (2026-04-16). Además, `openapi-typescript` 7.13.0 declara `typescript ^5.x`, así que generar tipos desde el OpenAPI queda fuera hasta que publique soporte para la versión 6. El paso a TypeScript 7 se revisa en la Fase 12.

### 9.2 simglucose en Python 3.13 (a confirmar en la Fase 1)
- **Release en PyPI:** el último es 0.2.11, del 2024-05-17.
- **Dependencias fijadas:** `gym==0.9.4`, de 2017 y solo como código fuente, y `gymnasium~=0.29.1`, cuyos clasificadores llegan hasta Python 3.11.
- **Actividad del repositorio** (`jxx123/simglucose`, MIT, sin archivar): `pushed_at` marca 2026-07-23, pero el último commit en `master` es del 2025-04-18.
- **Plan si la instalación falla en 3.13:**
  1. Instalar con `--no-deps` y declarar solo lo que usa el modelo del paciente (`scipy`, `numpy`, `pandas`).
  2. Si no basta, incorporar el modelo UVA/Padova dentro de `SimglucoseAdapter`, citando la licencia MIT.

  En los dos casos el resto del simulador no cambia, porque el adapter aísla la dependencia.

### 9.3 FHIR R4 frente a fhir.resources
- **Qué ofrece la biblioteca:** desde la versión 7.0, `fhir.resources` trae R5 por defecto y R4B (4.3.0) como subpaquete, y retiró R4.
- **Qué usa Insumap:** importa FHIR **R4 (4.0.1)**, la misma versión de la guía de implementación del Resumen Digital de Atención (RDA) de MinSalud ([vulcano.ihcecol.gov.co/guia](https://vulcano.ihcecol.gov.co/guia/), v1.0.3).
- **Decisión:** el backend y el simulador modelan con Pydantic v2 solo los recursos que usan. La validación contra el validador oficial de HL7 queda a confirmar en la Fase 4.

### 9.4 httpx y httpx2
El backend fija `httpx` 0.28.1, sin releases desde 2024-12-06. El SDK `openai` 3.x ya depende de `httpx2` (2.16.0, mantenido en `pydantic/httpx2`) y `fastapi[standard]` también lo incluye. Si `insumap-ai` adopta el SDK de OpenAI, tendrá los dos clientes. La decisión de unificar se toma en la Fase 9.

### 9.5 APScheduler 4
La rama 4.0 sigue en alfa (4.0.0a6). Se fija 3.11.3 y no se usan APIs de la 4.

## 10. Puertas de calidad

Un PR no se fusiona si una puerta que bloquea está en rojo.

| Puerta | Herramienta | Umbral | Repos | Bloquea el merge |
|---|---|---|---|---|
| Formato de commits y PR | `commit-lint` | Cero mensajes inválidos y ninguna atribución a IA | Los cinco | Sí |
| Lint y valores quemados | ruff (`PLR2004`) / ESLint (`no-magic-numbers`) | Cero errores | Los cinco | Sí |
| Tipos | `mypy --strict` (backend), `mypy` (database, ai, simulator), `tsc --noEmit` | Cero errores | Los cinco | Sí |
| Arquitectura | `lint-imports` | Cero contratos rotos | backend | Sí |
| Pruebas | pytest / Vitest / Playwright | 100 % en verde | Los cinco | Sí |
| **Cobertura del dominio** | `coverage` / `@vitest/coverage-v8` | **≥ 90 %** de líneas (`insumap.domain` en el backend, el dominio en ai y simulator, `src/core` en el frontend) | backend, frontend, ai, simulator | Sí |
| **Cobertura global** | `coverage` / `@vitest/coverage-v8` | **≥ 80 %** de líneas | backend, frontend, ai, simulator | Sí |
| Migraciones y esquema | Alembic + pytest | `upgrade head` limpio; RLS, append-only, roles y cadena de hashes probados | database (y el backend en integración) | Sí |
| Deriva de `FieldLimits` | pytest | Cero diferencias con `information_schema` | backend | Sí |
| Accesibilidad | axe en Playwright | Cero violaciones | frontend | Sí |
| Secretos | gitleaks | Cero hallazgos | Los cinco | Sí |
| Análisis de seguridad | CodeQL | Sin hallazgos altos ni críticos abiertos (propuesta) | Los cinco | Sí (propuesta) |
| Dependencias vulnerables | `pip-audit` / `npm audit --audit-level=high` | Sin vulnerabilidades altas ni críticas (propuesta) | Los cinco | Sí (propuesta) |
| Actualizaciones | Dependabot | Se atienden por prioridad | Los cinco | No |

Comandos de cobertura del backend (de [`.agents/testing-plan.md`](../.agents/testing-plan.md)):

```bash
uv run pytest --cov=insumap --cov-report=term-missing --cov-fail-under=80
uv run coverage report --include="src/insumap/domain/*" --fail-under=90
```

## 11. Herramientas del equipo

| Tecnología | Uso | Por qué | Alternativa descartada y motivo |
|---|---|---|---|
| **draw.io** (MCP de draw.io y sus iconos) | Diagramas: fuente `.drawio` y `.png` en `docs/images/` | Formato abierto y editable, con iconos oficiales de cada tecnología. | **Mermaid:** sin iconos de despliegue ni control del diseño. |
| **Docker Engine + Compose** | PostgreSQL local, imagen de la API y Testcontainers | Mismo entorno que la nube. | **Instalación manual:** difícil de reproducir. |
| **gh CLI** y `~/Projects/insumap/as.sh` | Operaciones de GitHub con la cuenta del integrante que corresponde | Un comando por operación y verificación de la cuenta activa. Ver [`.agents/workflow.md`](../.agents/workflow.md). | **Interfaz web:** sirve para revisar, no para automatizar. |
| **Git Flow** con `develop` por defecto | Ramas, PR con merge commit y versiones etiquetadas | Flujo conocido por el equipo y compatible con los rulesets. | **Trunk-based:** las fases cierran con versiones etiquetadas (`v0.1.0`, `v0.9.0`, `v1.0.0`). |

## 12. Notas de mantenimiento

- Un valor clínico o de negocio (metas de TIR, umbrales de alerta) se cambia en la base de datos, no en el código ni en este documento.
- Cambiar una versión es un commit `build:` con sus pruebas. Si cambia una versión de la sección 1, se actualiza esta tabla en el mismo PR.
- Una tecnología nueva se registra aquí, con su alternativa y su motivo, antes de implementarla.
- Las cifras de los planes gratuitos cambian sin aviso: se vuelven a verificar antes de la Fase 12.

Relacionados: [Arquitectura.md](Arquitectura.md) · [Modulo-IA.md](Modulo-IA.md) · [Seguridad.md](Seguridad.md) · [Cumplimiento-y-privacidad.md](Cumplimiento-y-privacidad.md) · [Datos-simulados.md](Datos-simulados.md) · [`.agents/deployment.md`](../.agents/deployment.md) · [`.agents/testing-plan.md`](../.agents/testing-plan.md)
