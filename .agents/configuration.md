# Configuración sin valores quemados

> Guía operativa para agentes y para el equipo del backend. Define dónde vive cada valor de `insumap-backend`. Las reglas resumidas están en [`AGENTS.md`](../AGENTS.md), sección 3.2; esta guía es la versión detallada con ejemplos, tablas y pasos.

## 1. Regla única

**Un valor vive en una sola capa.** Antes de escribir un número, un texto, una URL o una clave en el backend, decide dónde va. Si no encaja en ninguna fila de la tabla de la sección 2, el diseño está mal: revísalo antes de seguir.

Nunca se repite un valor en dos capas. Si ya existe en `FieldLimits`, se usa la constante; no se copia el número en el DTO, en el ORM ni en un test.

## 2. Dónde va cada tipo de valor

| Tipo de valor | Ejemplos | Destino | Cómo se usa en el código |
|---|---|---|---|
| Parámetro clínico o de negocio | Metas de TIR, TBR y TAR; umbrales y duración de alertas; plantillas de protocolo; reglas de titulación; horarios de recordatorio | Tablas `care.target_profiles`, `alerts.alert_rules`, `care.protocol_templates` y `care.reminder_schedules` en `insumap-database` | El caso de uso lee la versión vigente desde un puerto (`TargetProfilePort`) y pasa el valor al dominio como parámetro. Nunca es una constante. |
| Límite técnico o de seguridad | Longitud de campos, patrones, tamaño máximo de cuerpo, tamaño de página | `insumap.shared.field_limits.FieldLimits` | `Field(max_length=FieldLimits.X)` en los `*Request`. La prueba de deriva lo compara con `information_schema`. |
| Constante física o de unidad | Factor de conversión mg/dL a mmol/L | Constante con nombre en `insumap.shared` | Se usa el nombre (`MG_DL_PER_MMOL_L`), nunca el número. |
| Variable de entorno | URL de la base, orígenes CORS, duración de tokens, timeouts de la IA, interruptores | `insumap.shared.config.Settings` (pydantic-settings) y `.env.example` | Se crea una sola vez en el composition root (`container.py`) y se inyecta. |
| Secreto | `JWT_SECRET`, claves de cifrado, token de la IA, contraseña SMTP, clave VAPID privada | Variables del gestor de la plataforma (Render) o `.env` local, que no se versiona | Campo `SecretStr` **sin valor por defecto**. Si falta, la API no arranca. |
| Texto para el usuario | Mensajes de error, avisos, textos de notificación | `src/insumap/shared/i18n/messages_es.json` | Clave en inglés con puntos (`glucose.out_of_range`) e interpolación con `{nombre}`. |

## 3. Prohibido

- Escribir una regla clínica o de negocio en código, en un `Enum`, en una migración o en un archivo de configuración. Por ejemplo, `if value < 70` o `HYPO_THRESHOLD = 70`: incluso con nombre, un umbral clínico es un parámetro de la BD.
- Escribir un límite técnico como literal en un `Field`, en una entidad o en el ORM (`mapped_column(String(120))`). La longitud del esquema la define `insumap-database`; el backend solo la refleja desde `FieldLimits`.
- Leer `os.environ` o `os.getenv` fuera de `Settings`. Ningún servicio, router o adaptador lee el entorno por su cuenta.
- Dar un valor por defecto inseguro a un secreto (`jwt_secret: str = "dev"`).
- Escribir un texto visible directamente en un router, en una excepción de negocio o en una respuesta. Todo pasa por `messages_es`.
- Obtener la hora con `datetime.now()`, `datetime.utcnow()`, `date.today()` o `time.time()`. La hora solo llega por el `Clock` inyectado (sección 8).
- Suprimir un linter sin motivo escrito. `# noqa: PLR2004` exige una razón en el mismo comentario y revisión en el PR.
- Poner un valor real en `.env.example`. Los secretos y las URLs reales llevan marcador.

## 4. Parámetros clínicos: cómo se leen y cómo cambian

Los parámetros clínicos son datos versionados que configura el `CLINIC_ADMIN` de cada clínica. Viven en `insumap-database` y el backend los lee.

Flujo de lectura (ejemplo):

1. El router recibe la petición y llama a `EvaluateGlycemicStatusUseCase.execute(input)`.
2. El caso de uso pide a `TargetProfilePort` el perfil vigente de la clínica del paciente. La RLS limita la consulta a la clínica de la sesión.
3. El perfil entra a `GlycemicTargetStrategy` (P19) como un objeto de valor. El dominio no sabe de dónde vino.

Flujo de cambio:

1. Un cambio crea una **versión nueva**. La versión anterior queda inmutable.
2. La versión nueva se activa con un motivo escrito. El cambio queda en la auditoría (P09).
3. Las recomendaciones ya emitidas conservan la versión del perfil con la que se calcularon.

Reglas adicionales:

- Los valores de consenso internacional (TIR 70 a 180 mg/dL, por ejemplo) son **semillas** de `insumap-database`, no constantes del código.
- Si un cambio de regla pide tocar código o una migración del esquema, el diseño está mal.
- Las fixtures de prueba declaran sus propios perfiles de prueba. Los tests no dependen de los valores de producción.

## 5. Límites técnicos: `FieldLimits`

`insumap.shared.field_limits.FieldLimits` es la **única fuente** de longitudes, patrones, tamaños de cuerpo y tamaños de página. Los `*Request` y los filtros de consulta lo usan.

```python
from typing import Final


class FieldLimits:
    """Fuente única de límites técnicos. La prueba de deriva la compara con la BD."""

    PATIENT_FULL_NAME_MAX_LENGTH: Final[int] = 120  # valor de ejemplo de la forma
    GLUCOSE_NOTE_MAX_LENGTH: Final[int] = 500  # valor de ejemplo de la forma
```

```python
class RecordGlucoseReadingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, max_length=FieldLimits.GLUCOSE_NOTE_MAX_LENGTH)
```

Reglas:

- Cada límite tiene su nombre en `FieldLimits`; ningún `max_length=` lleva un número escrito a mano.
- La prueba de deriva `tests/integration/test_field_limits_drift.py` consulta `information_schema.columns` (`character_maximum_length`) en la base del tag fijado y compara cada límite con su columna. Si falla, se corrige con una migración nueva en `insumap-database` y, después, con la constante aquí. **Nunca se edita la base a mano.**
- `extra="forbid"` en todos los `*Request`: un campo desconocido responde `422`.
- Los límites de cuerpo (por ejemplo, el de importación) también son `FieldLimits`, no un literal en el middleware.

## 6. Entorno: `Settings`

Todas las variables de entorno pasan por `insumap.shared.config.Settings`, una clase de pydantic-settings. Es el único lugar que lee el entorno.

```python
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str
    database_url: SecretStr  # secreto: sin valor por defecto
    jwt_secret: SecretStr  # secreto: sin valor por defecto
    jwt_access_minutes: int = 15  # no es secreto: el valor por defecto está permitido
    scheduler_enabled: bool = False
```

Reglas:

- **Secretos sin valor por defecto.** Si `JWT_SECRET` falta, `Settings()` lanza `ValidationError` y el proceso termina antes de aceptar tráfico. El mensaje nombra el campo, nunca el valor.
- Los secretos son `SecretStr`. Así no aparecen en `repr`, en logs ni en respuestas.
- Un valor no secreto puede tener valor por defecto, pero el valor vive en `Settings`, no en el código que lo usa.
- `Settings` se construye una sola vez en `container.py` y se pasa a quien lo necesite.
- `.env` no se versiona (está en `.gitignore`). `.env.example` sí, con marcadores.

### 6.1 Variables iniciales

| Variable | Para qué sirve | Secreta | Valor por defecto o ejemplo seguro |
|---|---|---|---|
| `APP_ENV` | Entorno de ejecución: `local` (desarrollo), `test` o `production` | No | `local` |
| `LOG_LEVEL` | Nivel de logs | No | `INFO` |
| `DATABASE_URL` | URL de la app con el usuario `insumap_app` (en AWS, el PostgreSQL del host: `@db:5432/insumap`). Driver `postgresql+psycopg://` | Sí | `postgresql+psycopg://insumap_app:cambia-esto-password@localhost:5432/insumap` |
| `DATABASE_URL_UNPOOLED` | Conexión directa sin pooler (plan anterior con Neon; en AWS no se usa). Es la conexión que necesitan las migraciones, que ejecuta `insumap-database`. La API no la usa en el tráfico normal. Con el rol `insumap_app`, nunca con `insumap_migrator` | Sí | `cambia-esto-url-directa-app` |
| `FORWARDED_ALLOW_IPS` | Lista de IP del proxy de confianza para `X-Forwarded-For`. La lee uvicorn, no `Settings`; es una excepción documentada | No | `127.0.0.1` (valor por defecto de uvicorn); en AWS, `*` (solo CloudFront llega al host) |
| `INSUMAP_DATABASE_DIR` | Ruta al checkout de `insumap-database` en la etiqueta de `db-schema.lock`. Solo pruebas de integración | No | `../insumap-database` |
| `JWT_SECRET` | Firma de los access tokens | Sí | `cambia-esto-jwt-secret` |
| `JWT_ACCESS_MINUTES` | Vida del access token | No | `15` |
| `REFRESH_TOKEN_DAYS` | Vida del refresh token opaco, en días | No | Entero fijado en `docs/Seguridad.md` (pendiente) |
| `CORS_ORIGINS` | Orígenes permitidos de la PWA, separados por comas | No | `http://localhost:5173` |
| `ALLOWED_HOSTS` | Valores de `Host` que acepta la API, separados por comas; `*.dominio` admite subdominios y `*` solo se rechaza. Un `Host` ajeno recibe `400 VALIDATION_ERROR`. En `local` y `test`, si falta, vale `localhost,127.0.0.1,testserver`; en `production` no tiene valor por defecto y la API no arranca sin ella | No | `localhost,127.0.0.1` |
| `AI_SERVICE_URL` | URL base de `insumap-ai` | No | `http://localhost:8001` |
| `AI_SERVICE_TOKEN` | Token de servicio para llamar a `insumap-ai` | Sí | `cambia-esto-token-ia` |
| `AI_TIMEOUT_SECONDS` | Tiempo máximo de cada llamada a la IA antes de usar el respaldo | No | Decimal en segundos, acordado con el equipo de IA |
| `FIELD_ENCRYPTION_KEY` | Clave para cifrar campos sensibles, como el documento del paciente | Sí | `cambia-esto-clave-cifrado-32-bytes-base64` |
| `LOOKUP_HMAC_KEY` | Clave HMAC para buscar por documento sin guardarlo en claro | Sí | `cambia-esto-clave-hmac` |
| `SMTP_HOST` | Servidor de correo transaccional | No | `smtp.example.test` |
| `SMTP_PORT` | Puerto SMTP | No | `587` |
| `SMTP_USER` | Usuario SMTP | No | `cambia-esto-usuario-smtp` |
| `SMTP_PASSWORD` | Contraseña SMTP | Sí | `cambia-esto-password-smtp` |
| `SMTP_FROM` | Remitente de los correos | No | `no-reply@example.test` |
| `VAPID_PUBLIC_KEY` | Clave pública para Web Push | No | `cambia-esto-vapid-public` |
| `VAPID_PRIVATE_KEY` | Clave privada para Web Push | Sí | `cambia-esto-vapid-private` |
| `VAPID_SUBJECT` | Contacto del servicio de Web Push | No | `mailto:cambia-esto@example.test` |
| `SCHEDULER_ENABLED` | Activa el scheduler interno (recordatorios, evaluación de alertas, triage nocturno) | No | `false` en réplicas adicionales |

Notas:

- La tabla refleja la lista inicial. Una variable nueva se documenta aquí en el mismo PR.
- `DATABASE_URL_UNPOOLED` nunca contiene credenciales de `insumap_migrator`. Las migraciones se corren desde `insumap-database` (ver [`deployment.md`](deployment.md), sección 6).
- `FORWARDED_ALLOW_IPS` es la única variable que no lee `Settings`. La lee uvicorn, así que no tiene campo propio. Se documenta aquí para que el equipo la vea junto a las demás.
- `.env.example` usa los mismos nombres. Los secretos llevan el marcador `cambia-esto-...`.

### 6.2 Ejemplo de `.env.example`

```dotenv
APP_ENV=local
LOG_LEVEL=INFO
DATABASE_URL=postgresql+psycopg://insumap_app:cambia-esto-password@localhost:5432/insumap
JWT_SECRET=cambia-esto-jwt-secret
JWT_ACCESS_MINUTES=15
CORS_ORIGINS=http://localhost:5173
ALLOWED_HOSTS=localhost,127.0.0.1
AI_SERVICE_URL=http://localhost:8001
AI_SERVICE_TOKEN=cambia-esto-token-ia
SCHEDULER_ENABLED=false
```

### 6.3 Cómo agregar una variable de entorno

1. Agregar el campo a `Settings`. Si es secreto, sin valor por defecto y como `SecretStr`.
2. Agregar la variable a `.env.example` con marcador (`cambia-esto-...`) o con un valor de desarrollo que no sea real.
3. Agregar una fila a la tabla de la sección 6.1: nombre, para qué, si es secreta y el valor por defecto o ejemplo.
4. Si es secreta, agregarla al secreto `insumap/app` de Secrets Manager y a `infra/aws/host/deploy.sh`, y verificar que no aparece en logs. Si no es secreta y difiere en AWS, agregarla a `deploy.sh`.
5. Prueba: `tests/unit/shared/test_settings.py` debe cubrir el caso en que falta el secreto.

## 7. Textos para el usuario: `messages_es.json`

Los textos visibles viven en `src/insumap/shared/i18n/messages_es.json`. Las claves van en inglés, con puntos, y los valores en español:

```json
{
  "glucose.out_of_range": "El valor {value} mg/dL está fuera del rango permitido.",
  "session.revoked": "La sesión ya no es válida. Inicia sesión de nuevo.",
  "internal.error": "Ocurrió un error interno. Inténtalo de nuevo más tarde."
}
```

Convención de claves: la clave sale del código, sin cambiar de idioma.

- El primer segmento del código (antes del primer guion bajo) es el dominio. El resto va después del punto y en minúsculas.
- `GLUCOSE_OUT_OF_RANGE` usa `glucose.out_of_range`. `SESSION_REVOKED` usa `session.revoked`. Un código sin guion bajo, como `CONFLICT`, usa `conflict`.
- Cada `ErrorCode` tiene exactamente una clave. Ningún texto de error tiene una segunda clave con otro nombre para el mismo mensaje.
- Los textos que no son errores (avisos, notificaciones) usan la misma convención de dominio y clave, sin `ErrorCode`.
- La interpolación usa nombres (`{value}`), no posiciones.
- Un mensaje nunca incluye datos personales ni de salud. Si el mensaje necesita un valor clínico, se usa solo el valor no identificable, como en el ejemplo.
- `tests/unit/shared/test_messages_catalog.py` falla si un `ErrorCode` no tiene clave derivada con esta regla, si sobra una clave sin `ErrorCode` ni uso, o si una clave tiene placeholders que no coinciden con los del texto.

## 8. Constantes físicas y la regla de PLR2004

Solo se permiten constantes **físicas o de unidad** con nombre:

```python
from typing import Final

MG_DL_PER_MMOL_L: Final[float] = 18.016
```

Límites de esta regla:

- Un nombre no convierte un valor clínico en constante. `HYPO_THRESHOLD: Final = 70` sigue siendo un parámetro clínico y va en `care.target_profiles` o en `alerts.alert_rules`.
- Ruff `PLR2004` (magic value comparison) marca los literales en comparaciones (`if value < 70`). No marca otros números, como argumentos por defecto o aritmética. Por eso la revisión del PR también busca números sueltos.
- Configuración de ruff en `pyproject.toml`: `PLR2004` activo en `[tool.ruff.lint]`. Las pruebas también cumplen la regla, salvo excepciones con motivo.

## 9. La hora: solo por `Clock`

La hora no es configuración, pero sigue la misma regla de una sola fuente:

- El puerto `Clock` (protocolo) define `now()`. `SystemClock` (P01, Singleton) es la única clase que lee el reloj del sistema.
- Los casos de uso y el dominio reciben `Clock` por inyección.
- Las pruebas usan un `FrozenClock` con instante fijo.
- Una prueba de arquitectura (`tests/architecture/test_no_wall_clock.py`) recorre el AST de `src/insumap` y falla si aparece una llamada a `datetime.now`, `datetime.utcnow`, `date.today` o `time.time` fuera de `SystemClock`.

## 10. Cómo cambiar un valor

| Qué cambia | Pasos |
|---|---|
| Parámetro clínico (meta, umbral, plantilla) | Nueva versión del parámetro en la BD, con el motivo, desde la consola del `CLINIC_ADMIN`. Sin tocar código ni migraciones. |
| Límite técnico | Cambiar la constante en `FieldLimits`. Si la base también cambia, una migración nueva en `insumap-database`, una etiqueta nueva y `db-schema.lock` actualizado en el mismo PR. |
| Variable de entorno | Los cinco pasos de la sección 6.3. |
| Texto para el usuario | Agregar la clave en `messages_es.json` y usarla por su nombre. La prueba de catálogo confirma que existe. |
| Constante física | Agregar la constante con nombre en `insumap.shared`, con su unidad en el nombre. |

## 11. Lista rápida antes de un PR

- [ ] No hay números clínicos ni de negocio en código, en enums ni en migraciones.
- [ ] Los límites de entrada usan `FieldLimits`, sin literales.
- [ ] Las variables nuevas están en `Settings`, en `.env.example` y en la tabla 6.1.
- [ ] Los secretos nuevos son `SecretStr` y no tienen valor por defecto.
- [ ] Los textos nuevos están en `messages_es.json` con clave en inglés.
- [ ] No hay `os.getenv` fuera de `Settings` ni llamadas a la hora del sistema fuera de `SystemClock`.
- [ ] Pasan `tests/integration/test_field_limits_drift.py`, `tests/unit/shared/test_settings.py`, `tests/unit/shared/test_messages_catalog.py` y `tests/architecture/test_no_wall_clock.py`.
- [ ] `uv run ruff check .` pasa, incluido `PLR2004`.

Relacionados: [`AGENTS.md`](../AGENTS.md) (sección 3.2), [`testing-plan.md`](testing-plan.md), [`deployment.md`](deployment.md), [`api-documentation.md`](api-documentation.md)
