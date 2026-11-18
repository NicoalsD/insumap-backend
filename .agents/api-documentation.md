# Documentación de la API (OpenAPI y Swagger)

> Reglas para documentar `/api/v1` con FastAPI y Pydantic v2. La documentación es parte del contrato: el frontend genera sus tipos desde el documento OpenAPI, así que un endpoint sin documentar no está terminado. Las descripciones van en español. Los identificadores (`operation_id`, nombres de clase, campos) van en inglés.

## 1. Configuración base

| Elemento | Valor | Estado |
|---|---|---|
| Biblioteca | FastAPI, que genera OpenAPI 3.1 desde los modelos de Pydantic v2 | Canónico |
| Swagger UI | `/docs` | Canónico |
| Documento OpenAPI | `/openapi.json` | Canónico |
| Versión de la API | Prefijo `/api/v1` en cada `APIRouter` | Canónico |
| Disponibilidad | En todos los entornos. Solo documenta; ejecutar una petición protegida requiere token | Canónico |
| Desactivar en producción | Si el equipo decide apagarlo, se hace con un campo de `Settings`, nunca con código suelto | Pendiente de decisión |

Configuración de la aplicación:

```python
from importlib.metadata import version

from fastapi import FastAPI

app = FastAPI(
    title="Insumap API",
    version=version("insumap"),
    description=(
        "API REST de Insumap, plataforma académica de monitoreo de pacientes con diabetes. "
        "Usa datos simulados. No es un dispositivo médico y no reemplaza el criterio clínico."
    ),
    docs_url="/docs",
    openapi_url="/openapi.json",
    openapi_tags=OPENAPI_TAGS,
)
```

Reglas:

- La versión sale de los metadatos del paquete, no de un literal.
- El aviso de proyecto académico y datos simulados va en la descripción de la API, como en la sección 1.1 de `AGENTS.md`.
- Los textos que escribimos van en español. Los controles propios de Swagger UI (botones como "Try it out") siguen en inglés si no se personaliza la plantilla. Esa limitación se documenta y no se oculta.
- `OPENAPI_TAGS` es la lista de tags con su descripción en español (sección 4).

## 2. Esquemas de seguridad

FastAPI genera `components.securitySchemes` a partir de las dependencias de seguridad. Cada operación muestra el candado solo si usa una de ellas.

| Modo | Nombre del esquema | Endpoints | Cómo se declara |
|---|---|---|---|
| JWT bearer | `bearerAuth` | Casi todos los de `/api/v1` | Dependencia `current_principal`, que usa `HTTPBearer(scheme_name="bearerAuth", bearerFormat="JWT", auto_error=False)` |
| Sin autenticación | Ninguno | `/health`, `/api/v1/auth/login`, `/api/v1/auth/refresh`, `/api/v1/public/**`, `/docs`, `/openapi.json` | Sin dependencia de seguridad. El candado no aparece |
| Cookie de refresh | Ninguno | `/api/v1/auth/refresh` | La descripción explica la cookie `HttpOnly` de refresh. No se modela como `apiKey` |

Detalles:

- `auto_error=False` evita que FastAPI responda por su cuenta cuando falta el encabezado. La dependencia devuelve el `401` canónico (sección 5), con el mismo cuerpo que cualquier otro error de autenticación.
- El esquema `bearerAuth` describe el access token de 15 minutos (`JWT_ACCESS_MINUTES`) y que se obtiene con `POST /api/v1/auth/login`.
- Un endpoint nuevo que no es público usa `current_principal` (o una dependencia que lo incluya). Si olvida la dependencia, la prueba de la matriz de autorización lo detecta, porque la denegación por defecto ya está en la matriz.

## 3. Reglas por operación

Cada operación del `*Router` declara:

| Parámetro de la ruta | Obligatorio | Contenido |
|---|---|---|
| `summary` | Sí | Frase corta en español, máximo 60 caracteres |
| `description` | Sí | Qué hace, qué regla aplica, qué devuelve, idempotencia si aplica. Sin detalles de implementación |
| `tags` | Sí | Un tag del recurso, de la sección 4 |
| `operation_id` | Sí | Identificador único en inglés, `snake_case`, verbo y sustantivo |
| `status_code` | Sí, si no es `200` | `201` al crear, `204` sin cuerpo |
| `response_model` | Sí | Modelo `*Response` explícito. Nunca se devuelve un `dict` ni un modelo de dominio |
| `responses` | Sí | Un `ErrorResponse` por cada error que el endpoint puede devolver |
| `Path`, `Query`, `Header` con `description` y `examples` | Sí, en parámetros | Descripción en español y un ejemplo ficticio |

Ejemplo de referencia:

```python
@router.post(
    "/readings",
    status_code=201,
    response_model=GlucoseReadingResponse,
    operation_id="record_glucose_reading",
    summary="Registrar una lectura de glucosa",
    description=(
        "Registra una lectura de glucosa del paciente autenticado. Es idempotente por "
        "`client_reading_id`: repetir la misma petición devuelve la lectura original. "
        "Si el valor está fuera del rango físico, responde 422 y no guarda nada."
    ),
    tags=["Registros del paciente"],
    responses={
        401: {"model": ErrorResponse, "description": "Token ausente, inválido o vencido."},
        403: {"model": ErrorResponse, "description": "El rol no puede registrar lecturas."},
        409: {"model": ErrorResponse, "description": "El identificador ya existe con otro contenido."},
        422: {"model": ErrorResponse, "description": "Valor fuera de rango o campo inválido."},
    },
)
async def record_glucose_reading(
    body: RecordGlucoseReadingRequest,
    principal: Annotated[Principal, Depends(current_principal)],
    use_case: Annotated[RecordGlucoseReadingUseCase, Depends(get_record_glucose_reading_use_case)],
) -> GlucoseReadingResponse:
    result = await use_case.execute(to_record_input(body, principal))
    return GlucoseReadingResponse.from_result(result)
```

Reglas:

- El router solo llama a un caso de uso o a una fachada. La función no consulta repositorios ni adaptadores.
- Las dependencias (`Depends`) las arma `container.py`; el router no crea instancias.
- Declarar `422` de forma explícita hace que el esquema de error sea `ErrorResponse`, no el `HTTPValidationError` por defecto de FastAPI. Se confirma con la prueba del documento OpenAPI (sección 9).
- Un error que el endpoint no puede devolver no se documenta. Un error que sí puede devolver y no está documentado hace fallar la revisión.
- La docstring de la función no se usa como descripción: la descripción va en `description=`, explícita.

## 4. Tags por recurso

Los tags son etiquetas visibles en Swagger y van en español. Se definen una vez en `OPENAPI_TAGS`, con su descripción:

```python
OPENAPI_TAGS: list[dict[str, str]] = [
    {"name": "Autenticación", "description": "Login, activación de cuenta, MFA y renovación de sesión."},
    {"name": "Registros del paciente", "description": "Glucosa, insulina, comidas, actividad y síntomas."},
    {"name": "Alertas", "description": "Alertas clínicas, su estado y su historial."},
]
```

Tabla de tags propuesta. Los prefijos definitivos se confirman en `docs/API.md`:

| Tag | Prefijo | Seguridad predominante |
|---|---|---|
| Autenticación | `/api/v1/auth` | Mixta: login y refresh sin token, el resto con token |
| Usuarios y membresías | `/api/v1/users`, `/api/v1/memberships` | Token |
| Clínicas | `/api/v1/clinics` | Token (`PLATFORM_ADMIN`) |
| Importación y credenciales | `/api/v1/imports`, `/api/v1/credentials` | Token (`CLINIC_ADMIN`) |
| Equipo de atención | `/api/v1/care-team` | Token (`CLINIC_ADMIN`) |
| Registros del paciente | `/api/v1/readings`, `/api/v1/insulin-doses`, `/api/v1/meals`, `/api/v1/activities`, `/api/v1/symptoms` | Token (`PATIENT`) |
| Plan de tratamiento | `/api/v1/treatment-plans` | Token (`DOCTOR`, `PATIENT` para lectura) |
| Métricas glucémicas | `/api/v1/patients/{id}/metrics` | Token (`DOCTOR` asignado) |
| Alertas | `/api/v1/alerts` | Token |
| Recomendaciones IA | `/api/v1/recommendations` | Token (`DOCTOR`) |
| Dashboard médico | `/api/v1/dashboard` | Token (`DOCTOR`) |
| Reportes | `/api/v1/reports` | Token |
| Mensajería | `/api/v1/messages` | Token |
| Auditoría | `/api/v1/audit-log` | Token (`CLINIC_ADMIN`) |
| Público | `/api/v1/public` | Sin autenticación |
| Salud | `/health` | Sin autenticación |

## 5. Respuestas de error

Todas las respuestas de error usan el formato canónico (sección 5.4 de `AGENTS.md`):

```json
{
  "error": {
    "code": "GLUCOSE_OUT_OF_RANGE",
    "message": "El valor de glucosa está fuera del rango permitido.",
    "detail": { "field": "value_mg_dl" }
  }
}
```

El modelo se define una sola vez, en `insumap.api.errors`:

```python
from pydantic import JsonValue


class ErrorBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(description="Código estable en inglés, de ErrorCode.", examples=["GLUCOSE_OUT_OF_RANGE"])
    message: str = Field(description="Mensaje en español, tomado de messages_es.")
    detail: dict[str, JsonValue] = Field(
        default_factory=dict,
        description="Datos adicionales sin información personal. Los errores de validación van en 'errors'.",
    )


class ErrorResponse(BaseModel):
    error: ErrorBody
```

`detail` es un objeto JSON, no solo valores escalares. Así cabe la lista de errores por campo de una validación:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Hay campos inválidos en la petición.",
    "detail": {
      "errors": [
        {"field": "body.value_mg_dl", "message": "El valor debe ser un entero."}
      ]
    }
  }
}
```

Respuestas comunes:

| HTTP | Descripción en Swagger | Códigos de ejemplo |
|---|---|---|
| `401` | Token ausente, inválido o vencido. Sesión revocada. | `UNAUTHORIZED`, `SESSION_REVOKED` |
| `403` | Sin permiso para esta acción. | `FORBIDDEN` |
| `404` | Recurso inexistente, de otra clínica o de un paciente no asignado. | `NOT_FOUND` |
| `409` | Conflicto de estado o de idempotencia. | `CONFLICT`, `DUPLICATE_READING` |
| `413` | Cuerpo demasiado grande. | `PAYLOAD_TOO_LARGE` |
| `422` | Validación de entrada o regla de negocio no cumplida. | `VALIDATION_ERROR`, `GLUCOSE_OUT_OF_RANGE` |
| `429` | Límite de peticiones alcanzado. | `RATE_LIMITED` |
| `500` | Error interno. Sin detalles. | `INTERNAL_ERROR` |

Reglas:

- Los códigos de ejemplo son orientativos. La lista definitiva está en `ErrorCode`, y esta guía no crea códigos nuevos.
- Un `404` de otra clínica y un `404` de un recurso inexistente tienen el mismo cuerpo. No se revela que el recurso existe.
- El login responde "Usuario o contraseña incorrectos" en todos los casos de credenciales fallidas.
- Un manejador global convierte `RequestValidationError` al formato canónico con `VALIDATION_ERROR`. Al convertirlo se quitan los campos `input` y `ctx` de cada error, porque repetirían valores como contraseñas.
- Un manejador global convierte las excepciones no controladas en `500 INTERNAL_ERROR`, sin traza ni nombre de clase.
- El mapeo de excepciones de negocio a HTTP vive solo en el manejador de `api`. Los casos de uso no conocen HTTP.

## 6. Esquemas y ejemplos

Reglas para los modelos `*Request` y `*Response`:

- Son clases de Pydantic v2 con `ConfigDict(extra="forbid")` en las entradas. La documentación no muestra campos que la API no acepta.
- Cada campo tiene `description` en español y `examples` con un valor ficticio.
- Las longitudes salen de `FieldLimits` (`max_length=FieldLimits.X`). Nunca se escribe `maxLength` a mano: Pydantic lo genera.
- Las unidades van en el nombre del campo: `value_mg_dl`, no `value`. Los decimales usan punto en JSON.
- Las fechas son ISO 8601 con zona: `2026-10-09T14:30:00Z`. Los campos de tipo fecha-hora usan `AwareDatetime`.
- Las contraseñas, los códigos de activación y los tokens se documentan como de entrada. Las respuestas no los devuelven, y la descripción lo dice.

```python
class RecordGlucoseReadingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_reading_id: UUID = Field(
        description="Identificador generado por la app. Hace la petición idempotente.",
        examples=["00000000-0000-7000-8000-000000000001"],
    )
    value_mg_dl: int = Field(
        description="Glucosa en mg/dL, de sensor o capilar.",
        examples=[112],
    )
    measured_at: AwareDatetime = Field(
        description="Momento de la medición, con zona horaria.",
        examples=["2026-10-09T14:30:00Z"],
    )
    note: str | None = Field(
        default=None,
        max_length=FieldLimits.GLUCOSE_NOTE_MAX_LENGTH,
        description="Nota libre del paciente. No incluir datos de identificación.",
        examples=["Antes del desayuno"],
    )
```

Datos de los ejemplos:

- Nombres: "Paciente de Prueba Uno", "Médica de Prueba Dos".
- Correos: solo el dominio reservado `example.test`.
- Documentos: inválidos a propósito, como `DOC-DE-PRUEBA-0001`.
- Teléfonos: no aparecen en ningún ejemplo.
- Identificadores: UUID de formato válido sin significado, como `00000000-0000-7000-8000-000000000001`.
- Clínica: "Clínica de Prueba Demo", con la marca de datos simulados visible en la respuesta.

## 7. Paginación

Los listados usan cursor opaco. Los límites salen de `FieldLimits`:

| Parámetro | Tipo | Límites | Descripción |
|---|---|---|---|
| `limit` | entero | Entre 1 y `FieldLimits.PAGE_SIZE_MAX` | Tamaño de la página |
| `cursor` | cadena | Opaca | Cursor de la página siguiente. Lo devuelve la respuesta anterior |

La respuesta de un listado tiene `items` y `next_cursor`, que es `null` cuando no hay más páginas.

## 8. Operation IDs y versionado

- `operation_id` es único en toda la API, en inglés, en `snake_case`, con verbo y sustantivo: `record_glucose_reading`, `list_alerts`, `approve_recommendation`.
- Los `operation_id` se usan como nombres de métodos en los clientes generados. Cambiarlos es un cambio incompatible para el frontend.
- Prueba: `tests/api/test_openapi_document.py` verifica que todos los `operation_id` son únicos y cumplen `^[a-z][a-z0-9_]*$`.
- La versión va en el prefijo: `/api/v1`. Un cambio incompatible crea `/api/v2`; uno compatible (un campo opcional nuevo) se queda en `v1`.
- Un endpoint que se retira primero se marca como `deprecated=True` y su descripción indica el reemplazo, durante al menos una versión.

## 9. Publicación y snapshot del documento

- `GET /openapi.json` devuelve el documento. `GET /docs` abre Swagger UI. Ambos son públicos porque solo documentan.
- Ejecutar una petición protegida desde Swagger requiere un token obtenido con `POST /api/v1/auth/login`.
- El documento se versiona como `docs/openapi.json`. Un script del proyecto lo regenera desde la aplicación.
- `tests/api/test_openapi_document.py` compara el documento generado con `docs/openapi.json` y falla si no coinciden. Así, un cambio en la API exige actualizar la copia en el mismo PR.
- El frontend genera sus tipos desde la copia, sin escribirlos a mano:

```bash
npx openapi-typescript ../insumap-backend/docs/openapi.json -o src/api/schema.d.ts
```

- El archivo generado en el frontend no se edita a mano.

## 10. Lista de verificación de un endpoint nuevo

- [ ] `summary` y `description` en español.
- [ ] `tags` del recurso, de la sección 4.
- [ ] `operation_id` único, en inglés, en `snake_case`.
- [ ] `response_model` explícito y código de éxito correcto (`200`, `201` o `204`).
- [ ] `responses` con un `ErrorResponse` por cada error que el endpoint puede devolver, incluido `422`.
- [ ] Dependencia de seguridad, o ninguna si el endpoint es público, según la sección 2.
- [ ] Parámetros con `description` y `examples` ficticios.
- [ ] Ejemplos sin datos personales ni valores reales.
- [ ] Longitudes desde `FieldLimits`, sin `maxLength` escrito a mano.
- [ ] `docs/openapi.json` regenerado en el mismo PR.
- [ ] Pruebas de API: validación (`422`), `401`, `403`, `404` de otra clínica o de paciente no asignado y caso feliz con el formato canónico.

Relacionados: [`AGENTS.md`](../AGENTS.md) (secciones 5.4 y 6), [`testing-plan.md`](testing-plan.md), [`configuration.md`](configuration.md), [`deployment.md`](deployment.md)
