# Insumap - Backend

API REST de Insumap en Python (FastAPI) con arquitectura hexagonal y patrones de diseño explícitos. Gestiona identidad, clínicas, importación de pacientes, registros, planes de tratamiento, métricas, alertas y recomendaciones de IA con aprobación médica.

Aquí vive también la **documentación canónica** del proyecto, en `docs/`.

## Estado

En construcción (Fase 0: documentación y planeación).

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

> Disponible desde la Fase 1.

```bash
uv sync                                         # instala dependencias
uv run uvicorn insumap.main:app --reload        # API en http://localhost:8000
uv run pytest                                   # pruebas con cobertura
uv run ruff check .                             # lint
uv run mypy .                                   # tipos (strict)
uv run lint-imports                             # contratos de arquitectura
```

La API queda en `http://localhost:8000` y Swagger en `http://localhost:8000/docs`. Requiere la base de datos de `insumap-database`.

## Documentación

- [`AGENTS.md`](AGENTS.md): reglas para agentes y convenciones del repositorio.
- [`CONTRIBUTING.md`](CONTRIBUTING.md): cómo contribuir (cuentas, ramas, commits y PR).
- [Índice de documentación canónica](https://github.com/NicoalsD/insumap-backend/tree/develop/docs).

## Equipo

- Nicolas Diaz ([`NicoalsD`](https://github.com/NicoalsD))
- Drako Salazar ([`Drako2305`](https://github.com/Drako2305))
- Nicolas Mora ([`nicomora70`](https://github.com/nicomora70))

> Proyecto académico. No es un dispositivo médico ni reemplaza el criterio del médico tratante. Los datos de pacientes son simulados.
