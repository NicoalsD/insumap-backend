# Insumap - Backend

API REST de Insumap en Python (FastAPI) con arquitectura hexagonal y patrones de diseño explícitos. Gestiona identidad, clínicas, importación de pacientes, registros, planes de tratamiento, métricas, alertas y recomendaciones de IA con aprobación médica.

Aquí vive también la **documentación canónica** del proyecto, en `docs/`.

## Estado

En construcción. Hecho: fundaciones transversales, `GET /api/v1/meta/field-limits` e identidad y sesión (`/api/v1/auth/*`: login, MFA TOTP, `/me`, refresh rotativo, logout y activación del paciente) sobre el esquema `db-v0.1.0`.

## Repositorios de Insumap

| Repositorio | Rol |
|---|---|
| [insumap-backend](https://github.com/NicoalsD/insumap-backend) | API, dominio, patrones, seguridad y documentación canónica |
| [insumap-database](https://github.com/NicoalsD/insumap-database) | Esquemas, migraciones, RLS, roles SQL y semillas (PostgreSQL 18) |
| [insumap-frontend](https://github.com/NicoalsD/insumap-frontend) | PWA del paciente, dashboard del médico y consola del admin |
| [insumap-ai](https://github.com/NicoalsD/insumap-ai) | Servicio de IA: pronóstico, triage, patrones y LLM con guardrails |
| [insumap-simulator](https://github.com/NicoalsD/insumap-simulator) | Clínica, médicos y pacientes simulados; exporta FHIR y CSV |

## Stack

Python 3.13, FastAPI, Pydantic v2, SQLAlchemy 2, psycopg 3, uv, ruff, mypy `--strict`, pytest, Testcontainers e import-linter.

## Inicio rápido

```bash
uv sync                                         # instala dependencias
cp .env.example .env                            # variables de entorno locales
docker compose up -d db                         # PostgreSQL 18 en localhost:5432
```

Aplica el esquema desde el repositorio `insumap-database` (este repositorio nunca crea ni migra tablas):

```bash
cd ../insumap-database && uv run alembic upgrade head
```

Levanta la API:

```bash
uv run uvicorn insumap.main:app --reload        # API en http://localhost:8000
```

- Swagger: `http://localhost:8000/docs`
- Salud: `GET http://localhost:8000/health`

Para correr también la API en un contenedor: `docker compose up -d --build`.

Verificación completa (la misma que corre el CI):

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run lint-imports && uv run pytest
```

### Pruebas de integración

Corren la API real (repositorios, Argon2id, JWT y TOTP) contra PostgreSQL 18 con las migraciones de `insumap-database` en la etiqueta de `db-schema.lock`, conectada como `insumap_app` y sujeta a la RLS.

```bash
# Con una base desechable propia (superusuario); si no se define, usan Testcontainers
export INSUMAP_TEST_DATABASE_URL=postgresql://insumap:<clave>@localhost:5432/insumap_test
export INSUMAP_DATABASE_REPO_PATH=../insumap-database     # en la etiqueta de db-schema.lock
uv run pytest -m integration
```

Sin `INSUMAP_TEST_DATABASE_URL` ni Docker, se saltan con el motivo.

### Datos de demostración (solo local)

Con la base migrada y las variables de la API definidas, `DATABASE_URL_MIGRATOR=<url de superusuario> uv run python -m tests.support.db_seed` crea la clínica demo, tres cuentas ficticias (`example.test`) y una invitación de activación. La contraseña y el código de activación son las constantes `DEMO_PASSWORD` y `ACTIVATION_CODE` del módulo; el script no los imprime. Nunca se apunta a una base compartida.

## Documentación

- [`AGENTS.md`](AGENTS.md): reglas para agentes y convenciones del repositorio.
- [`CONTRIBUTING.md`](CONTRIBUTING.md): cómo contribuir (cuentas, ramas, commits y PR).
- [Índice de documentación canónica](https://github.com/NicoalsD/insumap-backend/tree/develop/docs).

## Equipo

- Nicolas Diaz ([`NicoalsD`](https://github.com/NicoalsD))
- Drako Salazar ([`Drako2305`](https://github.com/Drako2305))
- Nicolas Mora ([`nicomora70`](https://github.com/nicomora70))

> Proyecto académico. No es un dispositivo médico ni reemplaza el criterio del médico tratante. Los datos de pacientes son simulados.
