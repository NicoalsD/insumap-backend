# API REST de Insumap

Referencia de la API REST del backend (`/api/v1`): convenciones, formato de error, catálogo de códigos y catálogo de endpoints por módulo, con su permiso, sus errores y su trazabilidad a requisitos e historias de usuario.

> **Aviso:** Insumap es un proyecto académico, no es un dispositivo médico y la IA solo apoya al médico. Los pacientes son simulados.

## 0. Cómo leer este documento

| Aspecto | Regla |
|---|---|
| Fuente | Este archivo es la fuente canónica de las rutas, los permisos y los errores. [`Seguridad.md`](Seguridad.md), [`Arquitectura.md`](Arquitectura.md) y [`.agents/api-documentation.md`](../.agents/api-documentation.md) lo citan. Los permisos salen de [`Actores-y-permisos.md`](Actores-y-permisos.md) y no se crean aquí. |
| Estado | Fase 0 (documentación). Hoy el código implementa solo `GET /health`, `GET /ready`, el formato canónico de error, el encabezado `X-Request-ID` y el límite de tamaño del cuerpo. El resto del catálogo es el contrato que se construye en las fases 1 a 12. |
| Código frente a documentos | Donde el código actual difiere de otro documento, este archivo describe el **código** y registra la diferencia en la sección 10. |
| Ruta fijada o propuesta | La columna **Ruta** de las tablas de cada módulo vale `F` si algún documento fija la ruta exacta (`Seguridad.md`, `Arquitectura.md`, `Modulo-IA.md` o el código) y `P` si los documentos fijan solo la capacidad y la ruta es una propuesta de este archivo. Las `P` se pueden ajustar antes de implementarlas, siempre que cambie también este archivo. |
| Campos sin definir | Un campo o un valor de enumeración que ningún documento define se escribe como "por definir" y se lista en la sección 10. No se inventan. |
| Prioridad | `MVP` (fases 1 a 9) salvo que la fila diga `Post-MVP` (fases 10 a 12). |
| Notación de errores | Cada endpoint lista sus errores con los conjuntos `C1` a `C5` de la sección 6.4 y sus códigos propios. |
| Patrones | `Pnn` es el ID del patrón del catálogo ([`Patrones-de-diseno.md`](Patrones-de-diseno.md)) que el documento asigna al endpoint. `-` significa que no hay patrón asignado. |

## 1. Convenciones generales

### 1.1 Versionado y rutas

- Prefijo `/api/v1` en cada `APIRouter`. Un cambio incompatible crea `/api/v2`; un campo opcional nuevo se queda en `v1`. Un endpoint que se retira se marca `deprecated=True` durante al menos una versión (`.agents/api-documentation.md`, sección 8).
- `GET /health` y `GET /ready` viven **fuera** de `/api/v1`. `GET /docs` (Swagger UI) y `GET /openapi.json` también, y son públicos porque solo documentan. Se pueden apagar con el campo `api_docs_enabled` de `Settings`.
- **Casing:** los segmentos fijos de la ruta van en `kebab-case` (`/password-reset/request`, `/credential-invitations`, `/logout-all`, `/field-limits`), como los fijan los documentos de seguridad. Los parámetros de ruta, los parámetros de consulta y los campos JSON van en `snake_case` (`patient_id`, `window`, `value_mg_dl`). Los valores de enumeración van en `UPPER_SNAKE_CASE`.
- Los identificadores son UUID (v7). Una ruta nunca lleva el `patient_id` del propio paciente: las rutas `_own` toman el `patient_id` del token (regla V3 de `Actores-y-permisos.md`). El prefijo `/patients/me` es la forma de nombrar "mi expediente".
- Cada operación tiene un `operation_id` único, en inglés, `snake_case`, con verbo y sustantivo (`^[a-z][a-z0-9_]*$`). Los clientes generados usan esos nombres como métodos: cambiarlos rompe al frontend.
- El documento OpenAPI se versiona como `docs/openapi.json`; el frontend genera sus tipos desde esa copia.

### 1.2 Formato de datos

| Tema | Regla |
|---|---|
| Cuerpo | JSON UTF-8 (`Content-Type: application/json`). Las entradas usan `extra="forbid"`: un campo desconocido responde `422 VALIDATION_ERROR`. Excepciones documentadas: importación FHIR (`application/fhir+json`), CSV (`text/csv`) y los documentos binarios de reportes. |
| Instantes | ISO 8601 con zona (`2026-11-15T14:30:00Z`). Se guardan en UTC. La API devuelve UTC con `Z`. Una entrada sin zona se rechaza con `422`. |
| Zona de presentación | Las ventanas diarias y nocturnas de las métricas, los recordatorios y el triage nocturno se calculan en la zona de la clínica (`clinic.clinics.timezone`, por defecto `America/Bogota`). La conversión para mostrar la hace el frontend. |
| Fechas | `YYYY-MM-DD` para fechas sin hora (`birth_date`, `measured_on`). |
| Glucosa | Siempre en **mg/dL** en las respuestas. La entrada de una lectura acepta `mg/dL` o `mmol/L`; el dominio la convierte con la constante `MG_DL_PER_MMOL_L`. Las unidades van en el nombre del campo (`value_mg_dl`, `carbs_g`, `units`). |
| Decimales | Con punto. Las métricas llevan hasta 2 decimales en la respuesta. |
| Texto | Normalizado como lo define la política de entradas. Los límites de longitud salen de `FieldLimits` y los publica `GET /api/v1/meta/field-limits`. Este archivo no repite longitudes: las toma de `FieldLimits`. |
| Datos simulados | Toda respuesta de la clínica demo (`is_demo = true`) y de sus recursos incluye `simulated: true` (RF-96, HU-55). En una clínica no demo el campo vale `false` o no aparece. Las respuestas de clínica incluyen además `is_demo`. Ver la sección 10 (G6). |
| Secretos | Las contraseñas, los códigos de activación, los tokens y los códigos de respaldo son solo de entrada, salvo la excepción de una sola vez de la emisión y del enrolamiento. Las respuestas nunca los repiten. |
| Sin borrado clínico | Los datos clínicos son append-only. No existe `DELETE` sobre un registro clínico: se corrige o se anula con una fila nueva y motivo (RF-39). |

### 1.3 Cabeceras

| Cabecera | Dirección | Uso |
|---|---|---|
| `Authorization: Bearer <jwt>` | Petición | Access token. Más de 2.048 bytes se rechaza antes de decodificar. |
| `X-Request-ID` | Petición y respuesta | Correlación. El código acepta un valor entrante de 1 a 64 caracteres `[A-Za-z0-9._-]` y, si no cumple, genera un UUID4. Toda respuesta lo devuelve, también las de error. El `request_id` **no** va en el cuerpo del error. |
| `X-Requested-With: insumap-web` | Petición | Obligatoria en `POST /auth/refresh`, `/auth/logout` y `/auth/logout-all` (defensa CSRF). |
| `Retry-After` | Respuesta | Segundos de espera en todo `429 RATE_LIMITED`. |
| `Location` | Respuesta | URL del recurso creado en un `201`. |
| `Cache-Control` | Respuesta | `no-store` en toda respuesta de `/api/v1`, salvo `GET /meta/field-limits` (`public, max-age=300`). |
| `Idempotency-Key` | Petición | Permitida por la política de CORS, pero **ningún endpoint la usa** en esta versión: la idempotencia va en el cuerpo (sección 4). Ver G9. |
| `Content-Type` en importaciones | Petición | `application/fhir+json` (FHIR) o `text/csv` (CSV). Otro tipo responde `415 UNSUPPORTED_MEDIA_TYPE`. |

Política de CORS que exige [`Seguridad.md`](Seguridad.md): orígenes explícitos de `CORS_ORIGINS`, `allow_credentials=True`, métodos `GET`, `POST`, `PUT`, `PATCH` y `DELETE`, cabeceras `Authorization`, `Content-Type`, `X-Requested-With`, `X-Request-ID` e `Idempotency-Key`, y se exponen `X-Request-ID` y `Retry-After`. El código actual permite solo `Authorization`, `Content-Type` y `X-Request-ID` y expone solo `X-Request-ID`: hay que ampliarlo antes de la fase 3 (G26).

## 2. Autenticación y sesión

### 2.1 Esquemas

| Modo | Esquema OpenAPI | Endpoints |
|---|---|---|
| JWT bearer | `bearerAuth` (HTTP bearer, formato JWT) | Casi todos los de `/api/v1` |
| Sin autenticación | Ninguno | `/health`, `/ready`, `/docs`, `/openapi.json`, `/api/v1/auth/login`, `/auth/mfa/verify`, `/auth/password-reset/*`, `/auth/email-verification/confirm`, `/auth/activation/*`, `/api/v1/meta/field-limits` y `/api/v1/public/**` |
| Cookie de refresh | Ninguno (se explica en la descripción) | `/api/v1/auth/refresh`, `/auth/logout` y `/auth/logout-all` |

La dependencia de seguridad usa `HTTPBearer(auto_error=False)`: la ausencia del encabezado devuelve el `401` canónico, no el de FastAPI.

### 2.2 Access token y refresh

| Aspecto | Valor |
|---|---|
| Access token | JWT HS256 de 15 minutos (`JWT_ACCESS_MINUTES`). Solo en memoria del frontend: nunca en `localStorage`, `sessionStorage`, IndexedDB ni cookies. Claims: `iss`, `aud`, `sub`, `role`, `clinic_id` (`null` solo para `PLATFORM_ADMIN`), `tv`, `sid`, `amr`, `jti`, `iat`, `nbf`, `exp`. Los permisos **no** van en el token: `GET /auth/me` los devuelve. |
| `amr` | `["pwd"]` para pacientes y para personal sin MFA verificado. `["pwd", "otp"]` para personal con MFA verificado. |
| Refresh token | Opaco de 256 bits, guardado solo como SHA-256. Rota en cada uso. Reutilizar uno ya rotado revoca toda la familia y responde `401 SESSION_REVOKED`. |
| Cookie | `Set-Cookie: __Secure-insumap_rt=<token>; HttpOnly; Secure; SameSite=Strict; Path=/api/v1/auth; Max-Age=<segundos>`. Sin `Domain`. El refresh **no** viaja en el cuerpo. |
| Vida del refresh | Paciente: 30 días de inactividad y 90 días absolutos. Personal: 12 horas (un turno), luego login con MFA. |
| Mismo sitio | El frontend y la API deben quedar en el mismo sitio (regla `rewrites` de Vercel hacia `/api/*` o dominio propio) para que la cookie sea `SameSite=Strict`. |
| Cliente sin navegador | El simulador en modo `live` conserva la cookie y envía `X-Requested-With: insumap-web` para renovar (G17). |

### 2.3 Estados del login

`POST /auth/login` responde con un campo `status`:

| `status` | Significado | Qué trae |
|---|---|---|
| `AUTHENTICATED` | Sesión completa. En el login la reciben los pacientes. El personal la recibe de `POST /auth/mfa/verify` o de `POST /auth/mfa/enrollment/confirm`, que responden con la misma forma. | `access_token` y la cookie de refresh. |
| `MFA_CHALLENGE` | El personal tiene MFA activo y debe verificar un código. | `challenge_token` (5 minutos, 5 intentos). |
| `MFA_ENROLLMENT_REQUIRED` | El personal no tiene MFA. | Un `access_token` de enrolamiento (`amr: ["pwd"]`, sin refresh). Solo sirve para `/auth/mfa/enrollment*`, `GET /auth/me` y `/auth/logout`. |

### 2.4 Qué responde cada capa de acceso

| Situación | HTTP | Código |
|---|---|---|
| Sin token, mal formado, vencido o con firma incorrecta | 401 | `UNAUTHENTICATED` |
| El `tv` del token no coincide, la cuenta dejó de estar activa o se reutilizó un refresh | 401 | `SESSION_REVOKED` |
| Clínica suspendida con una sesión abierta | 403 | `CLINIC_SUSPENDED` |
| Personal sin `otp` en `amr` en una ruta distinta del enrolamiento | 403 | `MFA_REQUIRED` |
| Cuenta no `ACTIVE` al iniciar sesión (con contraseña correcta) | 403 | `ACCOUNT_NOT_ACTIVE` |
| Consentimiento retirado o de una versión vencida | 403 | `CONSENT_REQUIRED` |
| El rol no tiene el permiso del endpoint | 403 | `FORBIDDEN` |
| Recurso inexistente, de otra clínica, de un paciente no asignado o ajeno | 404 | `NOT_FOUND` |

Reglas:

1. **Denegación por defecto.** Todo endpoint exige autenticación y un permiso, salvo los públicos y las acciones sobre la propia cuenta (`GET /auth/me`, cambiar contraseña, cerrar sesión, administrar MFA propio, notificaciones propias).
2. **`403` antes que `404`.** El permiso se verifica antes de buscar el recurso: un rol sin el permiso recibe `403 FORBIDDEN` aunque el id no exista. Quien tiene el permiso y pide un recurso ajeno recibe `404 NOT_FOUND`, con el mismo cuerpo, cabeceras y tiempo que un `404` real (no revela que existe).
3. **Alcance.** `_own` usa el `patient_id` del token. `_assigned` exige una asignación vigente en `clinic.care_team_assignments` (`PatientRecordAccessProxy`, P11). Sin sufijo es la clínica del usuario.
4. **El administrador no ve datos clínicos.** `PLATFORM_ADMIN` y `CLINIC_ADMIN` no tienen permisos de lectura clínica; sus listados devuelven solo campos administrativos.
5. **Auditoría.** Toda lectura de datos clínicos escribe una fila en `audit.data_access_log` antes de responder (`PhiAccessAuditDecorator`, P09). Si la auditoría falla, la lectura no responde. Todo comando que cambia seguridad o decisiones clínicas escribe en `audit.audit_log` (`AuditingCommandHandler`, P09).
6. **Ruta de la propia sesión.** `consents/*`, `GET /auth/me` y el cierre de sesión no exigen consentimiento vigente: un paciente con una versión nueva por aceptar debe poder aceptarla.

## 3. Paginación

Los listados usan **cursor opaco**.

| Parámetro | Tipo | Regla |
|---|---|---|
| `limit` | entero | Entre 1 y `FieldLimits.PAGE_SIZE_MAX` (100). Por defecto `FieldLimits.PAGE_SIZE_DEFAULT` (20). |
| `cursor` | texto | Opaco. Lo devuelve la respuesta anterior en `next_cursor`. Un cursor inválido responde `422 VALIDATION_ERROR`. |

Respuesta de un listado: `{"items": [...], "next_cursor": "..." | null}`. `next_cursor` es `null` en la última página. Los listados con filtros usan parámetros de consulta en `snake_case` (`status`, `from`, `to`, `patient_id`). Un filtro de rango de fechas usa instantes ISO 8601 con zona. Un listado no cuenta el total.

## 4. Idempotencia

- **Lecturas de glucosa:** `client_reading_id` (UUID generado por la app). Repetir el mismo contenido para el mismo paciente responde `200` con la lectura original; el mismo `client_reading_id` con otro contenido responde `409 CONFLICT`. Una lectura nueva responde `201` con `Location`.
- **Lotes offline:** cada elemento lleva su `client_reading_id`. Reenviar el lote no duplica nada y cada elemento devuelve `CREATED`, `DUPLICATE` o `REJECTED` con causa (RF-32, RNF-20).
- **Servicio de IA:** los `POST` hacia `insumap-ai` son funciones de la entrada y no usan clave. Es un contrato interno, no de esta API.
- **Comandos de estado** (aprobar, reconocer, activar, suspender): no usan clave. Repetirlos sobre un estado que ya cambió responde `409 INVALID_STATE_TRANSITION`.
- Insulina, comidas, actividad, síntomas y laboratorio no tienen identificador de cliente definido en los documentos (G9).

## 5. Límites de tasa y de tamaño

Al excederlos: `429 RATE_LIMITED` con `Retry-After`, o `413 PAYLOAD_TOO_LARGE`. Los valores salen de las variables de `Settings` y de `FieldLimits`; aquí se resumen los de [`Seguridad.md`](Seguridad.md), secciones 12 y 13.3.

| Familia | Endpoints | Clave | Límite |
|---|---|---|---|
| Login | `POST /auth/login` | IP | 20 por minuto, más el bloqueo escalonado por pareja (correo, IP) y por correo |
| MFA | `POST /auth/mfa/verify`, `/mfa/enrollment/confirm` | IP | 20 por minuto, más 5 intentos por reto |
| Activación | `POST /auth/activation/verify`, `/activation/complete` | IP | 10 por minuto y 50 por hora |
| Solicitud de restablecimiento | `POST /auth/password-reset/request` | IP y correo | 5 por hora por IP; 3 por hora por correo (el exceso se ignora y se responde `202`) |
| Restablecimiento y verificación | `POST /auth/password-reset/complete`, `/auth/email-verification/confirm` | IP | 10 por minuto |
| Refresh | `POST /auth/refresh` | Usuario | 30 por minuto |
| Emisión de credenciales | `POST /patients/{patient_id}/credential-invitations`; lote | Clínica | 300 por hora; lote: 10 por hora |
| Importación | FHIR y CSV | Clínica | 10 por hora |
| Asistente (IA6) | `POST /assistant/messages` | Paciente | 20 por hora y 100 por día |
| Resumen clínico (IA5) | `POST /patients/{patient_id}/clinical-summaries` | Médico | 30 por hora |
| Reportes y exportaciones | Reportes PDF y HTML, exportaciones | Usuario | 20 por hora |
| Registros del paciente | Glucosa, insulina, comidas, actividad, síntomas y lotes | Usuario | 120 por minuto |
| Mensajes | `POST /messages` | Usuario | 30 por minuto |
| Públicos sin sesión | `GET /meta/field-limits` | IP | 60 por minuto |
| API general autenticada | Todo lo demás | Usuario | 300 por minuto |

| Límite de tamaño | Valor |
|---|---|
| Cuerpo JSON general | `FieldLimits.MAX_REQUEST_BODY_BYTES` (1 MiB en el código; la política pide 64 KiB, G5) |
| Lote de lecturas offline | 512 KiB y 500 elementos |
| Bundle FHIR R4 | 10 MiB, 5.000 entradas y 32 niveles de profundidad |
| CSV de pacientes | 2 MiB, 5.000 filas, 40 columnas y 1.000 caracteres por celda |
| CSV de CGM | 10 MiB y 100.000 filas |
| Credenciales en lote | 100 pacientes por petición |

Las importaciones se leen como **cuerpo crudo** (no multipart) contando bytes; se corta con `413` al pasar el límite aunque falte o mienta `Content-Length`. Como los límites de importación superan el límite global, esas rutas necesitan una excepción en el middleware de tamaño (G5).

## 6. Errores

### 6.1 Formato canónico

Toda respuesta de error, de cualquier endpoint, usa este cuerpo:

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "El recurso solicitado no existe.",
    "detail": {}
  }
}
```

| Campo | Tipo | Descripción |
|---|---|---|
| `error.code` | enum `ErrorCode` | Código estable en inglés y mayúsculas. El cliente decide qué hacer por el código, nunca por el texto. |
| `error.message` | texto | Mensaje en español tomado de `messages_es.json` con la clave en inglés del código (`not.found`) y sus parámetros. |
| `error.detail` | objeto | Datos que la persona puede corregir. Nunca trazas, SQL, rutas internas, nombres de clase, secretos ni datos personales. Vacío si no hay nada que agregar. |

- El estado HTTP de cada código lo asigna solo el manejador de errores de `api`. Una prueba verifica que todo `ErrorCode` tiene su estado.
- Una excepción no controlada responde `500 INTERNAL_ERROR` sin traza ni nombre de clase, con el `X-Request-ID` en la cabecera.
- Una ruta inexistente responde `404 NOT_FOUND` y un método no permitido (`405`) también responde `404 NOT_FOUND`. Cualquier otro `4xx` de FastAPI que no tiene código propio responde `422 VALIDATION_ERROR`.
- El login responde "Usuario o contraseña incorrectos" en todos los casos de credenciales fallidas.

### 6.2 Errores de validación

`422 VALIDATION_ERROR` lleva en `detail.errors` la lista de campos inválidos:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "La solicitud tiene campos no válidos. Revisa los datos enviados.",
    "detail": {
      "errors": [
        {"field": "body.value", "type": "missing"}
      ]
    }
  }
}
```

- **Hoy** (código): cada elemento trae `field` (ruta con puntos, `body.value`) y `type` (tipo de error de Pydantic). Nunca `input` ni `ctx`, porque repetirían valores como contraseñas.
- **Propuestas pendientes** que cambian ese elemento: `message` en español ([`.agents/api-documentation.md`](../.agents/api-documentation.md), sección 5) y `code` estable como `FIELD_TOO_LONG` ([`Seguridad.md`](Seguridad.md), decisión 17). Ver G4. Este archivo no promete esos campos hasta que el código los emita.
- Un error de regla de negocio con varios incumplimientos (invariantes de un plan, columnas faltantes de un CSV) usa `VALIDATION_ERROR` y la misma lista `detail.errors`, con un elemento por incumplimiento. Los valores de `type` o `code` de cada invariante están por definir (G16).

### 6.3 Catálogo de códigos

**Estado:** `Código` = existe hoy en `ErrorCode` (`src/insumap/shared/errors.py`) y su mensaje está en `messages_es.json`. `Doc` = lo exigen los documentos y falta agregarlo a `ErrorCode` y a `messages_es.json`; su mensaje es una propuesta cuya fuente se indica. Los ocho códigos de `Código` usan el texto exacto del catálogo.

| Código | HTTP | Estado | Mensaje en español | Cuándo |
|---|---|---|---|---|
| `VALIDATION_ERROR` | 422 | Código | La solicitud tiene campos no válidos. Revisa los datos enviados. | Formato, tipo, longitud, campo desconocido o regla de entrada (contraseña que no cumple la política, cursor inválido). |
| `NOT_FOUND` | 404 | Código | El recurso solicitado no existe. | Recurso inexistente, de otra clínica, de un paciente no asignado o ajeno; ruta inexistente; método no permitido. |
| `UNAUTHENTICATED` | 401 | Código | Necesitas iniciar sesión para continuar. | Token ausente, mal formado, vencido o no verificable; refresh desconocido o vencido; `challenge_token` vencido, usado o agotado. Los otros documentos lo llaman `UNAUTHORIZED` (G1). |
| `FORBIDDEN` | 403 | Código | No tienes permiso para realizar esta acción. | El rol no tiene el permiso, o falló la verificación CSRF del refresh. |
| `CONFLICT` | 409 | Código | La solicitud entra en conflicto con el estado actual del recurso. | Duplicado (nombre de clínica), `client_reading_id` con otro contenido, retirar al único médico principal, bloqueo optimista. |
| `RATE_LIMITED` | 429 | Código | Hiciste demasiadas solicitudes. Inténtalo de nuevo más tarde. | Límite de tasa o bloqueo de login. Incluye `Retry-After`. |
| `PAYLOAD_TOO_LARGE` | 413 | Código | El cuerpo de la solicitud supera el tamaño máximo permitido. | El cuerpo supera el límite de su ruta. |
| `INTERNAL_ERROR` | 500 | Código | Ocurrió un error interno. Inténtalo de nuevo más tarde. | Error no esperado. Sin detalle. |
| `SESSION_REVOKED` | 401 | Doc | Tu sesión terminó. Inicia sesión de nuevo. (propuesto) | El `tv` no coincide, la cuenta dejó de estar activa o se reutilizó un refresh revocado. El frontend vuelve al login. |
| `INVALID_CREDENTIALS` | 401 | Doc | Usuario o contraseña incorrectos. ([`Seguridad.md`](Seguridad.md) 2.2) | Correo o contraseña incorrectos, cuenta sin contraseña, TOTP o código de respaldo incorrecto o ya usado. |
| `ACCOUNT_NOT_ACTIVE` | 403 | Doc | Tu cuenta no está activa. Comunícate con tu clínica. (propuesto) | Solo en el login con contraseña correcta: cuenta `SUSPENDED` o `DEACTIVATED`, o personal con `is_active = false`. |
| `CLINIC_SUSPENDED` | 403 | Doc | Tu clínica está suspendida. Comunícate con el administrador de la plataforma. (propuesto) | Login con contraseña correcta o petición de una sesión abierta de una clínica suspendida (RF-10). |
| `MFA_REQUIRED` | 403 | Doc | Debes activar el segundo factor para continuar. (propuesto) | Personal sin `otp` en `amr` en una ruta distinta del enrolamiento. |
| `CONSENT_REQUIRED` | 403 | Doc | Debes aceptar el consentimiento vigente para continuar. (propuesto) | Activación sin aceptar, consentimiento retirado o de una versión vencida. |
| `EMAIL_UNAVAILABLE` | 409 | Doc | El correo ya pertenece a otra cuenta. (propuesto) | Activación con un correo que ya existe. |
| `CONSENT_VERSION_OUTDATED` | 409 | Doc | La versión del aviso de privacidad ya no es la vigente. (propuesto) | Se aceptó una versión que no es la vigente. |
| `INVALID_STATE_TRANSITION` | 409 | Doc | La transición de estado no está permitida. (propuesto) | Cuenta, alerta, recomendación o plan en un estado que no admite la acción. |
| `INVITATION_INVALID` | 410 | Doc | El código no es válido o venció. Pide uno nuevo a tu clínica. ([`Seguridad.md`](Seguridad.md) 3.5) | Cualquier fallo de activación, restablecimiento o verificación de correo: código o token mal formado, inexistente, vencido, usado, reemplazado, revocado o bloqueado, o fecha de nacimiento incorrecta. Mismo mensaje y mismo tiempo en todos los casos. |
| `REASON_REQUIRED` | 422 | Doc | Indica un motivo de 10 a 500 caracteres. (propuesto, RF-70) | Falta el motivo al suspender o desactivar, corregir un registro, modificar o rechazar una recomendación. |
| `GLUCOSE_OUT_OF_RANGE` | 422 | Doc | La glucosa está fuera del rango medible. ([`Arquitectura.md`](Arquitectura.md) 13) | Valor fuera del rango fisiológico de la clínica. No se guarda nada. |
| `READING_IN_FUTURE` | 422 | Doc | La lectura tiene una fecha futura. (propuesto) | Marca de tiempo más allá de la tolerancia ([`Arquitectura.md`](Arquitectura.md) 3). La HU-15 la describe como `VALIDATION_ERROR` (G20). |
| `READING_TOO_OLD` | 422 | Doc | La lectura es más antigua que el máximo permitido. (propuesto) | Marca de tiempo anterior al retraso máximo configurado. |
| `UNSUPPORTED_MEDIA_TYPE` | 415 | Doc | El tipo de contenido no es compatible con este endpoint. (propuesto) | Importación con un `Content-Type` distinto de `application/fhir+json` o `text/csv`, XML o archivo comprimido ([`Seguridad.md`](Seguridad.md) 13.3). |

Notas del catálogo:

- Hoy `410` y `415` no se pueden emitir: el manejador asigna un estado solo a los ocho códigos de `Código`. Agregar los de `Doc` exige una entrada en `ErrorCode`, en `STATUS_BY_CODE` y en `messages_es.json` en el mismo PR.
- No hay códigos de IA en esta API: los de `insumap-ai` (`INVALID_SERVICE_TOKEN`, `MODEL_NOT_READY`) son del contrato interno y el backend los convierte en respaldo, nunca en un error público.
- Una IA caída no es un error: la respuesta es `200` con `is_fallback: true` y `fallback_reason` (`AI_TIMEOUT`, `CIRCUIT_OPEN`, `AI_ERROR` o `INSUFFICIENT_DATA`).
- `DUPLICATE_READING` aparece como ejemplo en `.agents/api-documentation.md`, pero [`Arquitectura.md`](Arquitectura.md) responde `409 CONFLICT` (G20). No es un código de este catálogo.
- `GET /ready` responde `503` con el cuerpo `{"status": "unavailable"}` (modelo `HealthResponse`), no con el formato canónico.

### 6.4 Conjuntos de errores por endpoint

Cada endpoint declara solo los errores que puede devolver. Para no repetirlos, esta tabla define conjuntos que cada endpoint cita.

| Conjunto | Errores | Aplica a |
|---|---|---|
| `C1` | `401 UNAUTHENTICATED`, `401 SESSION_REVOKED`, `403 FORBIDDEN`, `403 CLINIC_SUSPENDED` (no aplica a `PLATFORM_ADMIN`), `429 RATE_LIMITED`, `500 INTERNAL_ERROR` | Todo endpoint autenticado |
| `C2` | `403 MFA_REQUIRED` | Endpoint llamado por personal (`CLINIC_ADMIN`, `DOCTOR`, `PLATFORM_ADMIN`), salvo `/auth/mfa/enrollment*`, `GET /auth/me` y `/auth/logout` |
| `C3` | `403 CONSENT_REQUIRED` | Endpoint llamado por `PATIENT`, salvo `consents/*`, `GET /auth/me` y `/auth/logout` |
| `C4` | `422 VALIDATION_ERROR` y, si hay cuerpo, `413 PAYLOAD_TOO_LARGE` | Todo endpoint con parámetros, consulta o cuerpo |
| `C5` | `404 NOT_FOUND` | Endpoint con un id de recurso en la ruta, o que opera sobre un recurso de otro actor |

Los endpoints públicos no llevan `C1`: llevan `429 RATE_LIMITED` y `500 INTERNAL_ERROR` y, si aplica, `C4`. Un endpoint de personal y de paciente a la vez (por ejemplo `GET /alerts`) cita `C2` y `C3`: cada llamada recibe el que corresponde a su rol.

## 7. Tags y prefijos

Los tags de Swagger van en español. Esta tabla confirma los prefijos que propuso `.agents/api-documentation.md` y agrega los que faltaban. Los cambios respecto de esa propuesta: la emisión de credenciales usa `/credential-invitations` (fijado por [`Seguridad.md`](Seguridad.md)) en lugar de `/credentials`, y `/memberships` no tiene endpoints porque ningún requisito lo exige (G13).

| Tag | Prefijos | Módulo |
|---|---|---|
| Salud | `/health`, `/ready` | Transversal |
| Metadatos | `/api/v1/meta` | Transversal |
| Público | `/api/v1/public` | M1, M12 |
| Autenticación | `/api/v1/auth` | M1 |
| Clínicas | `/api/v1/clinics`, `/api/v1/sites` | M2 |
| Usuarios y membresías | `/api/v1/users` | M2 |
| Pacientes | `/api/v1/patients` (vista administrativa, estado y expediente) | M3, M5, M10 |
| Importación y credenciales | `/api/v1/imports`, `/api/v1/credential-invitations`, `/api/v1/patients/{patient_id}/credential-invitations` | M3 |
| Equipo de atención | `/api/v1/care-team` | M4 |
| Registros del paciente | `/api/v1/readings`, `/insulin-doses`, `/meals`, `/activities`, `/symptoms`, `/lab-results`, `/timeline` | M5 |
| Plan de tratamiento | `/api/v1/protocol-templates`, `/treatment-plans`, `/target-profiles`, `/reminders` | M6 |
| Métricas glucémicas | `/api/v1/patients/{patient_id}/metrics`, `/forecast` | M7, M9 |
| Alertas | `/api/v1/alert-rules`, `/alerts` | M8 |
| Notificaciones | `/api/v1/notifications`, `/notification-preferences` | M8 |
| Recomendaciones IA | `/api/v1/recommendations`, `/patients/{patient_id}/risk`, `/pattern-findings`, `/clinical-summaries`, `/assistant`, `/dropout-risks`, `/ai-evaluations` | M9 |
| Dashboard médico | `/api/v1/dashboard`, `/clinical-notes`, `/clinic-kpis` | M10 |
| Reportes | `/api/v1/reports` | M10 |
| Mensajería | `/api/v1/messages`, `/follow-ups` | M11 |
| Auditoría | `/api/v1/audit-log`, `/security-events` | M12 |
| Consentimiento y privacidad | `/api/v1/consents`, `/privacy-requests` | M12 |

## 8. Catálogo de endpoints

Cada endpoint tiene un bloque con la misma forma:

```text
#### `MÉTODO /ruta`
- Operación: `operation_id` · Permiso: código(s) · Ruta: F o P · Trazabilidad: HU y RF · Patrón: Pnn · Éxito: HTTP
- Solicitud: ...
- Respuesta: ...
- Errores: conjuntos y códigos propios
```

- Las rutas se escriben sin el prefijo `/api/v1`, salvo `/health` y `/ready`. Todas las rutas de este catálogo cuelgan de `/api/v1`.
- Los campos que un documento nombra (`client_reading_id`, `activation_code`, `birth_date`, `is_fallback`, etc.) son canónicos. Los demás nombres de campo son **propuestos** y se confirman en `Modelo-de-datos.md` y `Diccionario-de-datos.md`, que aún no existen en el repositorio (G25).
- Los permisos van como códigos de `iam.permissions`. "autenticado" significa que solo exige sesión (acciones sobre la propia cuenta). "público" significa sin sesión.
- Un listado devuelve `{"items": [...], "next_cursor": ...}` (sección 3) y acepta `limit` y `cursor`; no se repite en cada bloque.
- Las respuestas de recursos clínicos del paciente incluyen `simulated` (sección 1.2).

### 8.1 Salud y metadatos

#### `GET /health`
- Operación: `get_health` · Permiso: público · Ruta: F · Trazabilidad: RNF-18 · Patrón: - · Éxito: 200
- Solicitud: sin parámetros. Vive fuera de `/api/v1`.
- Respuesta: `{"status": "ok"}`. Prueba de vida: no consulta la base de datos ni la IA, para que la suspensión de Neon no marque el servicio como caído.
- Errores: ninguno propio. Nunca responde `401`.

#### `GET /ready`
- Operación: `get_readiness` · Permiso: público · Ruta: F · Trazabilidad: RNF-18, RNF-08 · Patrón: - · Éxito: 200
- Solicitud: sin parámetros. Vive fuera de `/api/v1`.
- Respuesta: `{"status": "ok"}` si la API puede recibir tráfico.
- Errores: `503` con `{"status": "unavailable"}` (modelo `HealthResponse`, no el formato canónico) si una dependencia no está lista.

#### `GET /meta/field-limits`
- Operación: `get_field_limits` · Permiso: público · Ruta: F · Trazabilidad: RNF-05, RNF-15 · Patrón: - · Éxito: 200
- Solicitud: sin parámetros.
- Respuesta: `limits` (objeto con un campo por constante de `FieldLimits`, en `snake_case` y sin datos personales). Hoy: `request_id_max_length`, `email_max_length`, `password_min_length`, `password_max_length`, `max_request_body_bytes`, `page_size_default` y `page_size_max`. Crece con `FieldLimits`. `Cache-Control: public, max-age=300`. La forma exacta del objeto la fija esta propuesta (G25).
- Errores: `429 RATE_LIMITED`, `500 INTERNAL_ERROR`.

### 8.2 Autenticación y activación (M1, M3)

#### `POST /auth/login`
- Operación: `login` · Permiso: público · Ruta: F · Trazabilidad: HU-01, RF-01, RF-05 · Patrón: P18 · Éxito: 200
- Solicitud: `email` (se normaliza con NFKC, recorte y minúsculas; máximo `email_max_length`), `password` (máximo `password_max_length`).
- Respuesta: `status` (`AUTHENTICATED`, `MFA_CHALLENGE` o `MFA_ENROLLMENT_REQUIRED`, sección 2.3). Con `AUTHENTICATED`: `access_token` y la cookie de refresh. Con `MFA_CHALLENGE`: `challenge_token`. Con `MFA_ENROLLMENT_REQUIRED`: `access_token` de enrolamiento, sin refresh. Se verifica siempre un Argon2id por intento, exista o no el correo.
- Errores: `401 INVALID_CREDENTIALS` (mensaje genérico; también para cuentas `IMPORTED` o `INVITED`, que no tienen contraseña), `403 ACCOUNT_NOT_ACTIVE` y `403 CLINIC_SUSPENDED` (solo tras verificar una contraseña correcta), `429 RATE_LIMITED` con `Retry-After` (bloqueo por pareja correo-IP, por correo o por IP), `422`, `413`, `500`.

#### `POST /auth/mfa/verify`
- Operación: `verify_mfa_challenge` · Permiso: público (con `challenge_token`) · Ruta: F · Trazabilidad: HU-02, RF-03 · Patrón: - · Éxito: 200
- Solicitud: `challenge_token`, `code` (TOTP de 6 dígitos o código de respaldo `XXXXX-XXXXX`).
- Respuesta: `status: AUTHENTICATED`, `access_token` con `amr: ["pwd", "otp"]` y la cookie de refresh.
- Errores: `401 INVALID_CREDENTIALS` (código incorrecto, repetido o ya usado; cuenta para el bloqueo), `401 UNAUTHENTICATED` (reto vencido, usado o agotado: 5 minutos y 5 intentos), `429`, `422`, `413`, `500`.

#### `POST /auth/mfa/enrollment`
- Operación: `start_mfa_enrollment` · Permiso: token de enrolamiento (personal sin MFA) · Ruta: F · Trazabilidad: HU-02, RF-03 · Patrón: - · Éxito: 200
- Solicitud: sin cuerpo.
- Respuesta: `secret` (base32, 32 caracteres) y `otpauth_uri` (`otpauth://totp/Insumap:<correo>?secret=...&issuer=Insumap`). Se devuelven una sola vez, con `Cache-Control: no-store`. El QR se dibuja en el navegador.
- Errores: `401 UNAUTHENTICATED`, `401 SESSION_REVOKED`, `403 FORBIDDEN` (rol sin MFA, es decir `PATIENT`), `429`, `500`. Nunca `MFA_REQUIRED`.

#### `POST /auth/mfa/enrollment/confirm`
- Operación: `confirm_mfa_enrollment` · Permiso: token de enrolamiento · Ruta: F · Trazabilidad: HU-02, RF-03 · Patrón: - · Éxito: 200
- Solicitud: `code` (TOTP vigente).
- Respuesta: igual que `AUTHENTICATED` más `recovery_codes` (10 códigos `XXXXX-XXXXX`, de un solo uso, mostrados una sola vez). El factor queda activo solo tras confirmar.
- Errores: `401 INVALID_CREDENTIALS` (TOTP incorrecto o repetido), `401 UNAUTHENTICATED`, `401 SESSION_REVOKED`, `403 FORBIDDEN`, `429`, `422`, `500`.

#### `POST /auth/mfa/recovery-codes`
- Operación: `regenerate_mfa_recovery_codes` · Permiso: autenticado (personal con sesión completa) · Ruta: F · Trazabilidad: HU-02, RF-03 · Patrón: P09 · Éxito: 200
- Solicitud: `code` (TOTP vigente).
- Respuesta: `recovery_codes` nuevos, una sola vez. Los anteriores quedan invalidados.
- Errores: C1, C2, C4; `401 INVALID_CREDENTIALS` (TOTP incorrecto).

#### `GET /auth/me`
- Operación: `get_current_user` · Permiso: autenticado · Ruta: F · Trazabilidad: HU-01, RF-07, RF-08, HU-55 · Patrón: - · Éxito: 200
- Solicitud: sin parámetros. También la puede llamar el personal sin MFA verificado y el paciente con consentimiento pendiente.
- Respuesta: `user` (`id`, `email`, `full_name`), `role`, `clinic` (`id`, `name`, `is_demo`, `simulated`; `null` para `PLATFORM_ADMIN`), `permissions` (lista de códigos leída de la base de datos), `mfa_enabled`, `consent_required`.
- Errores: `401 UNAUTHENTICATED`, `401 SESSION_REVOKED`, `429`, `500`.

#### `POST /auth/refresh`
- Operación: `refresh_session` · Permiso: cookie de refresh · Ruta: F · Trazabilidad: HU-03, RF-02 · Patrón: - · Éxito: 200
- Solicitud: sin cuerpo. Cabecera obligatoria `X-Requested-With: insumap-web`. Si `Origin` está presente debe estar en `CORS_ORIGINS`; si `Sec-Fetch-Site` es `cross-site` se rechaza.
- Respuesta: `access_token` nuevo y la cookie de refresh rotada. El refresh anterior queda revocado (`ROTATED`). No hay ventana de gracia.
- Errores: `401 UNAUTHENTICATED` (refresh desconocido o vencido, sin más detalle), `401 SESSION_REVOKED` (refresh ya rotado: se revoca toda la familia, `tv + 1` y se registra el evento de seguridad), `403 FORBIDDEN` (falla CSRF), `429` (30 por minuto por usuario), `500`.

#### `POST /auth/logout`
- Operación: `logout` · Permiso: autenticado (cookie y JWT) · Ruta: F · Trazabilidad: HU-03, RF-02 · Patrón: - · Éxito: 204
- Solicitud: sin cuerpo. Exige `X-Requested-With: insumap-web`. Revoca la familia de la cookie y borra la cookie. El frontend descarta el access token de memoria.
- Errores: `401 UNAUTHENTICATED`, `401 SESSION_REVOKED`, `403 FORBIDDEN` (falla CSRF), `429`, `500`.

#### `POST /auth/logout-all`
- Operación: `logout_all_sessions` · Permiso: autenticado (cookie y JWT) · Ruta: F · Trazabilidad: HU-03, RF-02 · Patrón: - · Éxito: 204
- Solicitud: sin cuerpo. Exige `X-Requested-With: insumap-web`. Revoca todas las familias y hace `tv + 1`: los access tokens vigentes mueren por el chequeo del `tv`.
- Errores: iguales a `logout`.

#### `POST /auth/password/change`
- Operación: `change_password` · Permiso: autenticado · Ruta: F · Trazabilidad: HU-03, RF-04 · Patrón: P09 · Éxito: 200
- Solicitud: `current_password`, `new_password` (12 a 128 caracteres tras NFKC; sin reglas de composición; no puede estar en la lista de contraseñas comunes, contener el correo, nombre o documento, ni repetir una de las últimas 5).
- Respuesta: sesión nueva del dispositivo actual (`status: AUTHENTICATED`, `access_token` y cookie nueva). Las demás sesiones quedan revocadas (`tv + 1`).
- Errores: C1, C4; `401 INVALID_CREDENTIALS` (contraseña actual incorrecta). La política incumplida responde `422 VALIDATION_ERROR`.

#### `POST /auth/password-reset/request`
- Operación: `request_password_reset` · Permiso: público · Ruta: F · Trazabilidad: HU-03, RF-06 · Patrón: P07 · Éxito: 202
- Solicitud: `email`.
- Respuesta: siempre `202` sin datos, exista o no el correo. Si la cuenta existe, está activa y su correo está verificado, se envía un enlace de un solo uso (30 minutos, token de 256 bits en el fragmento `#token=`).
- Errores: `422`, `413`. El exceso de tasa (5 por hora por IP, 3 por hora por correo) se ignora y se responde `202`; solo el límite por minuto de la API responde `429`.

#### `POST /auth/password-reset/complete`
- Operación: `complete_password_reset` · Permiso: público (con token de un solo uso) · Ruta: F · Trazabilidad: HU-03, RF-06, RF-04 · Patrón: - · Éxito: 204
- Solicitud: `token`, `new_password` (misma política).
- Respuesta: sin cuerpo. Se hace `tv + 1` y se revocan todas las familias. El usuario inicia sesión de nuevo (G14).
- Errores: `410 INVITATION_INVALID` (enlace usado, vencido o inexistente), `429` (10 por minuto por IP), `422`, `413`, `500`.

#### `POST /auth/email-verification/confirm`
- Operación: `confirm_email_verification` · Permiso: público (con token de un solo uso) · Ruta: F · Trazabilidad: HU-10, RF-24 · Patrón: - · Éxito: 204
- Solicitud: `token` (24 horas de vigencia).
- Respuesta: sin cuerpo. El correo queda verificado.
- Errores: `410 INVITATION_INVALID`, `429`, `422`, `413`, `500`.

#### `POST /auth/activation/verify`
- Operación: `verify_activation_code` · Permiso: público · Ruta: F · Trazabilidad: HU-10, RF-24, RF-22, HU-05 · Patrón: P18 · Éxito: 200
- Solicitud: `activation_code` (`XXXX-XXXX-XXXX-XXXX`; se normaliza a mayúsculas sin guiones, `O` a `0`, `I` y `L` a `1`), `birth_date` (obligatoria para pacientes; las invitaciones de personal no la piden, G17).
- Respuesta: `activation_token` (opaco, 15 minutos, un solo uso), `clinic_name`, `privacy_notice_version_id` (versión vigente; su texto sale de `GET /public/privacy-notices/{privacy_notice_version_id}`) y `email_required` (propuesto: indica si hay que pedir el correo). **No** devuelve el nombre del paciente ni otros datos personales.
- Errores: `410 INVITATION_INVALID` (un solo error para código mal formado, inexistente, vencido, usado, reemplazado, revocado, bloqueado o fecha incorrecta; 5 fallos de fecha con un código real bloquean la invitación), `429` (10 por minuto y 50 por hora por IP), `422`, `413`, `500`.

#### `POST /auth/activation/complete`
- Operación: `complete_activation` · Permiso: público (con `activation_token`) · Ruta: F · Trazabilidad: HU-10, HU-05, RF-24, RF-90, RF-04 · Patrón: P18, P17 · Éxito: 200
- Solicitud: `activation_token`, `new_password` (misma política), `email` (obligatorio si la importación no lo traía; queda sin verificar y se envía un enlace de 24 horas), `consent` (`privacy_notice_version_id`, `accepted`, `ai_external_processing`; este último es un consentimiento aparte y opcional para el asistente con LLM externo).
- Respuesta: para un paciente, `status: AUTHENTICATED`, `access_token` y la cookie de refresh; la cuenta pasa de `INVITED` a `ACTIVE`, la invitación a `USED` y se guarda el consentimiento, todo en una transacción. Para personal, `status: MFA_ENROLLMENT_REQUIRED` con el token de enrolamiento. El evento `PatientActivated` se publica después del commit.
- Errores: `403 CONSENT_REQUIRED` (sin `accepted: true`; la cuenta sigue `INVITED`), `409 CONSENT_VERSION_OUTDATED`, `409 EMAIL_UNAVAILABLE`, `410 INVITATION_INVALID` (incluye un `activation_token` inválido), `429`, `422` (política de contraseña), `413`, `500`.

### 8.3 Clínicas, sedes y personal (M2)

#### `POST /clinics`
- Operación: `create_clinic` · Permiso: `clinics.manage` · Ruta: P · Trazabilidad: HU-04, RF-09 · Patrón: - · Éxito: 201
- Solicitud: `name`, `tax_id` (identificación fiscal), `is_demo` (booleano, por defecto `false`), `timezone` (nombre IANA, por defecto `America/Bogota`).
- Respuesta: `id`, `name`, `tax_id`, `status` (`ACTIVE`), `is_demo`, `simulated`, `timezone`, `created_at`. La clínica nace aislada como tenant.
- Errores: C1, C2, C4; `409 CONFLICT` (nombre repetido).

#### `GET /clinics`
- Operación: `list_clinics` · Permiso: `clinics.manage` · Ruta: P · Trazabilidad: HU-04, RF-09, RF-10 · Patrón: - · Éxito: 200
- Solicitud: `status` (`ACTIVE` o `SUSPENDED`), `is_demo`, `limit`, `cursor`.
- Respuesta: listado de clínicas con los campos de `POST /clinics`. Nunca datos de pacientes.
- Errores: C1, C2, C4.

#### `GET /clinics/{clinic_id}`
- Operación: `get_clinic` · Permiso: `clinics.manage` · Ruta: P · Trazabilidad: HU-04, RF-09 · Patrón: - · Éxito: 200
- Solicitud: `clinic_id` en la ruta.
- Respuesta: los campos de `POST /clinics` más `suspended_at` y el motivo de la suspensión si aplica.
- Errores: C1, C2, C4, C5.

#### `PATCH /clinics/{clinic_id}`
- Operación: `update_clinic` · Permiso: `clinics.manage` · Ruta: P · Trazabilidad: HU-04, RF-10 · Patrón: P09 · Éxito: 200
- Solicitud: `name`, `tax_id`, `is_demo`, `timezone` (todos opcionales). Marcar o desmarcar la clínica como demo también lo hace este endpoint.
- Respuesta: la clínica actualizada.
- Errores: C1, C2, C4, C5; `409 CONFLICT` (nombre repetido).

#### `POST /clinics/{clinic_id}/suspend`
- Operación: `suspend_clinic` · Permiso: `clinics.manage` · Ruta: P · Trazabilidad: HU-04, RF-10 · Patrón: P09, P18 · Éxito: 200
- Solicitud: `reason` (10 a 500 caracteres). Se revocan las sesiones de su personal y sus pacientes y ninguno puede iniciar sesión.
- Respuesta: la clínica con `status: SUSPENDED`.
- Errores: C1, C2, C4, C5; `409 INVALID_STATE_TRANSITION` (ya suspendida), `422 REASON_REQUIRED`.

#### `POST /clinics/{clinic_id}/reactivate`
- Operación: `reactivate_clinic` · Permiso: `clinics.manage` · Ruta: P · Trazabilidad: HU-04, RF-10 · Patrón: P09, P18 · Éxito: 200
- Solicitud: sin cuerpo.
- Respuesta: la clínica con `status: ACTIVE`. Restablece el acceso de su personal y sus pacientes.
- Errores: C1, C2, C4, C5; `409 INVALID_STATE_TRANSITION` (no está suspendida).

#### `POST /clinics/{clinic_id}/admins`
- Operación: `create_clinic_admin` · Permiso: `clinic_admins.manage` · Ruta: P · Trazabilidad: HU-04, RF-11 · Patrón: P13, P09 · Éxito: 201
- Solicitud: `email`, `full_name`.
- Respuesta: `user_id`, `email`, `role: CLINIC_ADMIN`, `invitation_expires_at`. La invitación `STAFF_ACTIVATION` (7 días) va solo por correo; el código no se devuelve. El administrador debe enrolar MFA en su primer ingreso.
- Errores: C1, C2, C4, C5; `409 CONFLICT` (el correo ya pertenece a otra cuenta).

#### `POST /clinics/{clinic_id}/admins/{user_id}/reset-access`
- Operación: `reset_clinic_admin_access` · Permiso: `clinic_admins.manage` · Ruta: P · Trazabilidad: HU-04, RF-11, RF-03 · Patrón: P09 · Éxito: 204
- Solicitud: `reason` (10 a 500 caracteres). Restablece el MFA del administrador (`tv + 1`, familias revocadas, aviso al titular) y emite una invitación nueva por correo. Nadie restablece su propio MFA.
- Respuesta: sin cuerpo.
- Errores: C1, C2, C4, C5; `422 REASON_REQUIRED`.

#### `GET /clinics/current`
- Operación: `get_current_clinic` · Permiso: `clinics.read` · Ruta: P · Trazabilidad: RF-14, RF-96, HU-55 · Patrón: - · Éxito: 200
- Solicitud: sin parámetros. La clínica sale del token.
- Respuesta: `id`, `name`, `status`, `is_demo`, `simulated`, `timezone`. El simulador usa `is_demo` para verificar que apunta a una clínica demo antes de enviar lecturas.
- Errores: C1, C2.

#### `POST /sites`
- Operación: `create_site` · Permiso: `sites.manage` · Ruta: P · Trazabilidad: RF-15 (Post-MVP) · Patrón: - · Éxito: 201
- Solicitud: `name` (más campos de la sede por definir).
- Respuesta: `id`, `name`, `simulated`.
- Errores: C1, C2, C4; `409 CONFLICT` (nombre repetido).

#### `GET /sites`
- Operación: `list_sites` · Permiso: `sites.manage` · Ruta: P · Trazabilidad: RF-15 (Post-MVP) · Patrón: - · Éxito: 200
- Solicitud: `limit`, `cursor`.
- Respuesta: sedes de la clínica.
- Errores: C1, C2, C4.

#### `PATCH /sites/{site_id}`
- Operación: `update_site` · Permiso: `sites.manage` · Ruta: P · Trazabilidad: RF-15 (Post-MVP) · Patrón: - · Éxito: 200
- Solicitud: `name`.
- Respuesta: la sede actualizada.
- Errores: C1, C2, C4, C5; `409 CONFLICT`.

#### `PUT /users/{user_id}/sites`
- Operación: `set_user_sites` · Permiso: `sites.manage` · Ruta: P · Trazabilidad: RF-15 (Post-MVP) · Patrón: P09 · Éxito: 200
- Solicitud: `site_ids` (lista de sedes de la misma clínica; un médico puede pertenecer a varias).
- Respuesta: el personal con sus sedes.
- Errores: C1, C2, C4, C5 (usuario o sede de otra clínica).

#### `POST /users`
- Operación: `create_user` · Permiso: `users.manage` · Ruta: P · Trazabilidad: HU-05, RF-12 · Patrón: P09 · Éxito: 201
- Solicitud: `email`, `full_name`, `role` (`DOCTOR` o `CLINIC_ADMIN`), `professional_license` (registro profesional) y `specialty` (especialidad). El usuario queda en la clínica del creador.
- Respuesta: `id`, `email`, `role`, `is_active`, `invitation_expires_at`. Recibe una invitación `STAFF_ACTIVATION` solo por correo y debe enrolar MFA en su primer ingreso. El código no se devuelve.
- Errores: C1, C2, C4; `409 CONFLICT` (correo ya registrado).

#### `GET /users`
- Operación: `list_users` · Permiso: `users.read` · Ruta: P · Trazabilidad: HU-05, RF-12 · Patrón: - · Éxito: 200
- Solicitud: `role`, `is_active`, `limit`, `cursor`.
- Respuesta: personal de la clínica del usuario (`id`, `email`, `full_name`, `role`, `is_active`, `specialty`).
- Errores: C1, C2, C4.

#### `GET /users/{user_id}`
- Operación: `get_user` · Permiso: `users.read` · Ruta: P · Trazabilidad: HU-05, RF-14 · Patrón: - · Éxito: 200
- Solicitud: `user_id` en la ruta.
- Respuesta: el personal con su perfil profesional y su estado de MFA (`mfa_enabled`).
- Errores: C1, C2, C4, C5 (personal de otra clínica responde `404`).

#### `PATCH /users/{user_id}`
- Operación: `update_user` · Permiso: `users.manage` · Ruta: P · Trazabilidad: HU-05, RF-12 · Patrón: P09 · Éxito: 200
- Solicitud: `full_name`, `professional_license`, `specialty` (opcionales). El cambio de rol no está definido (G13).
- Respuesta: el personal actualizado.
- Errores: C1, C2, C4, C5.

#### `POST /users/{user_id}/deactivate`
- Operación: `deactivate_user` · Permiso: `users.manage` · Ruta: P · Trazabilidad: HU-05, RF-13 · Patrón: P13, P09 · Éxito: 200
- Solicitud: sin cuerpo. Revoca todas las sesiones del usuario (`tv + 1`) y sus asignaciones de pacientes quedan pendientes de reasignar.
- Respuesta: el personal con `is_active: false` y `patients_pending_reassignment` (cantidad). La lista de esos pacientes sale de `GET /patients?without_doctor=true`.
- Errores: C1, C2, C4, C5; `409 INVALID_STATE_TRANSITION` (ya desactivado).

#### `POST /users/{user_id}/unlock`
- Operación: `unlock_user` · Permiso: `users.manage` · Ruta: F · Trazabilidad: RF-05, HU-01 · Patrón: P09 · Éxito: 204
- Solicitud: sin cuerpo. Quita el bloqueo global del correo (20 fallos en 60 minutos). Queda auditado y registra `ACCOUNT_UNLOCKED`.
- Respuesta: sin cuerpo.
- Errores: C1, C2, C4, C5.

#### `POST /users/{user_id}/mfa-reset`
- Operación: `reset_user_mfa` · Permiso: `users.manage` · Ruta: P · Trazabilidad: HU-02, RF-03 · Patrón: P09 · Éxito: 204
- Solicitud: `reason` (10 a 500 caracteres). Incrementa `tv`, revoca las familias, registra `MFA_RESET` (severidad alta) y avisa al titular. En el siguiente login el usuario enrola de nuevo. Nadie restablece su propio MFA.
- Respuesta: sin cuerpo.
- Errores: C1, C2, C4, C5; `403 FORBIDDEN` (quien lo pide es el propio titular), `422 REASON_REQUIRED`.

### 8.4 Pacientes, importación y credenciales (M3)

#### `GET /patients`
- Operación: `list_patients` · Permiso: `patients.read_roster` · Ruta: P · Trazabilidad: HU-09, HU-05, RF-13, RF-21 · Patrón: P11, P09 · Éxito: 200
- Solicitud: `account_status` (`IMPORTED`, `INVITED`, `ACTIVE`, `SUSPENDED`, `DEACTIVATED`), `without_doctor` (booleano: pacientes sin médico vigente), `import_batch_id`, `limit`, `cursor`.
- Respuesta: vista administrativa (`PatientAdministrativeView`): `id`, `full_name`, `mrn`, `document_last4`, `account_status`, `primary_doctor_id`, `assigned_doctor_count`, `invitation_status`, `simulated`. Nunca datos clínicos ni el documento completo. Escribe una sola fila `PATIENT_LIST` en `audit.data_access_log`.
- Errores: C1, C2, C4.

#### `GET /patients/{patient_id}`
- Operación: `get_patient_administrative_view` · Permiso: `patients.read_roster` · Ruta: P · Trazabilidad: HU-09, HU-14, RF-30 · Patrón: P11, P09 · Éxito: 200
- Solicitud: `patient_id` en la ruta.
- Respuesta: la vista administrativa con los médicos asignados y el estado de la invitación. El `DOCTOR` no usa esta ruta: su detalle clínico es `GET /patients/{patient_id}/overview`.
- Errores: C1, C2, C4, C5.

#### `POST /patients/{patient_id}/suspend`
- Operación: `suspend_patient` · Permiso: `patients.manage_status` · Ruta: P · Trazabilidad: HU-11, RF-26 · Patrón: P18, P09 · Éxito: 200
- Solicitud: `reason` (obligatorio). Revoca las sesiones del paciente (`tv + 1`).
- Respuesta: el paciente con `account_status: SUSPENDED`.
- Errores: C1, C2, C4, C5; `409 INVALID_STATE_TRANSITION` (solo `ACTIVE` pasa a `SUSPENDED`), `422 REASON_REQUIRED`.

#### `POST /patients/{patient_id}/reactivate`
- Operación: `reactivate_patient` · Permiso: `patients.manage_status` · Ruta: P · Trazabilidad: HU-11, RF-26 · Patrón: P18, P09 · Éxito: 200
- Solicitud: `reason` (opcional).
- Respuesta: el paciente con `account_status: ACTIVE`.
- Errores: C1, C2, C4, C5; `409 INVALID_STATE_TRANSITION` (solo `SUSPENDED` pasa a `ACTIVE`; `DEACTIVATED` es terminal).

#### `POST /patients/{patient_id}/deactivate`
- Operación: `deactivate_patient` · Permiso: `patients.manage_status` · Ruta: P · Trazabilidad: HU-11, RF-26 · Patrón: P18, P09 · Éxito: 200
- Solicitud: `reason` (obligatorio). Desde `IMPORTED`, `INVITED`, `ACTIVE` o `SUSPENDED`. Revoca sesiones e invitación pendiente. Es terminal.
- Respuesta: el paciente con `account_status: DEACTIVATED`.
- Errores: C1, C2, C4, C5; `409 INVALID_STATE_TRANSITION`, `422 REASON_REQUIRED`.

#### `GET /imports/csv-template`
- Operación: `download_csv_import_template` · Permiso: `patients.import` · Ruta: P · Trazabilidad: HU-07, RF-17 · Patrón: P03 · Éxito: 200
- Solicitud: sin parámetros.
- Respuesta: `text/csv` UTF-8 con la plantilla de columnas. Incluye `mrn` y `birth_date` como obligatorias; las demás columnas están por definir (G16).
- Errores: C1, C2.

#### `POST /imports/fhir`
- Operación: `create_fhir_import_preview` · Permiso: `patients.import` · Ruta: P · Trazabilidad: HU-06, HU-54, RF-16, RF-18, RF-97 · Patrón: P03, P06, P20 · Éxito: 201
- Solicitud: cuerpo crudo `application/fhir+json` con un Bundle FHIR R4 (`collection` o `transaction`). Solo `Patient`, `Practitioner`, `Condition`, `Observation` (LOINC) y `MedicationRequest`; otros tipos quedan como incidencia de fila sin detener el lote. Máximo 10 MiB, 5.000 entradas y 32 niveles. Exige `birth_date` en cada paciente. Un Bundle con la marca `SIMULATED` solo entra en una clínica demo.
- Respuesta: `batch_id`, `source: FHIR`, `status` (por definir), `totals` (válidas, con advertencia, con error, `SKIPPED_DUPLICATE`), `simulated`. **No crea ninguna cuenta**: es solo la previsualización. Una fila inválida no impide ver las demás.
- Errores: C1, C2, C4, `415 UNSUPPORTED_MEDIA_TYPE` (XML o archivo comprimido), `413` (más de 10 MiB), `429` (10 por hora por clínica); la regla de origen simulado no tiene código definido (G16).

#### `POST /imports/csv`
- Operación: `create_csv_import_preview` · Permiso: `patients.import` · Ruta: P · Trazabilidad: HU-07, HU-54, RF-17, RF-18, RF-97 · Patrón: P03, P06, P20 · Éxito: 201
- Solicitud: cuerpo crudo `text/csv` UTF-8, separador `,` o `;` detectado en el encabezado (sin BOM). Máximo 2 MiB, 5.000 filas, 40 columnas y 1.000 caracteres por celda.
- Respuesta: igual que `POST /imports/fhir` con `source: CSV`.
- Errores: C1, C2, C4, `415`, `413`, `429`. Columnas faltantes responde `422 VALIDATION_ERROR` con el nombre de la columna en `detail.errors`. Un archivo que no es UTF-8 responde `422` sin procesar filas.

#### `GET /imports`
- Operación: `list_import_batches` · Permiso: `import_batches.read` · Ruta: P · Trazabilidad: HU-08, RF-20 · Patrón: - · Éxito: 200
- Solicitud: `source` (`FHIR` o `CSV`), `limit`, `cursor`.
- Respuesta: lotes con `batch_id`, `source`, `status`, `created_by`, `created_at`, `totals`, `simulated`.
- Errores: C1, C2, C4.

#### `GET /imports/{batch_id}`
- Operación: `get_import_batch` · Permiso: `import_batches.read` · Ruta: P · Trazabilidad: HU-08, RF-20 · Patrón: - · Éxito: 200
- Solicitud: `batch_id` en la ruta.
- Respuesta: totales (creados, omitidos, con error), autor, origen y fecha. Sirve para consultar el avance tras confirmar.
- Errores: C1, C2, C4, C5.

#### `GET /imports/{batch_id}/rows`
- Operación: `list_import_rows` · Permiso: `import_batches.read` · Ruta: P · Trazabilidad: HU-06, HU-07, HU-08, RF-18, RF-20 · Patrón: - · Éxito: 200
- Solicitud: `status` (filtro), `limit`, `cursor`.
- Respuesta: por fila `row_number`, `status` (`SKIPPED_DUPLICATE` es el único valor que los documentos nombran; los demás están por definir), `issue_codes` y `patient_id` si se creó. No devuelve la fila cruda: el archivo original no se guarda.
- Errores: C1, C2, C4, C5.

#### `GET /imports/{batch_id}/errors`
- Operación: `download_import_errors` · Permiso: `import_batches.read` · Ruta: P · Trazabilidad: HU-08, RF-20 · Patrón: - · Éxito: 200
- Solicitud: `batch_id` en la ruta.
- Respuesta: `text/csv` con `row`, `column` y `cause` por cada fila con error, sin datos clínicos. Las celdas que empiezan con `=`, `+`, `-`, `@`, tabulador o retorno de carro se prefijan con `'` contra la inyección de fórmulas.
- Errores: C1, C2, C4, C5.

#### `POST /imports/{batch_id}/confirm`
- Operación: `confirm_import` · Permiso: `patients.import` · Ruta: P · Trazabilidad: HU-06, HU-07, RF-18, RF-19, RF-21 · Patrón: P20, P03, P09 · Éxito: 202
- Solicitud: sin cuerpo. Confirma el lote completo: crea solo las filas válidas como pacientes `IMPORTED`, deduplica por MRN de la clínica (`SKIPPED_DUPLICATE`, sin crear un segundo paciente) y guarda el documento cifrado y con hash. Corre en segundo plano (objetivo de 1.000 filas en 60 s).
- Respuesta: el lote con su `status` de procesamiento. El avance se consulta con `GET /imports/{batch_id}`. Cada cuenta nace sin contraseña y sin acceso.
- Errores: C1, C2, C4, C5; `409 INVALID_STATE_TRANSITION` (el lote ya se confirmó).

#### `POST /patients/{patient_id}/credential-invitations`
- Operación: `issue_patient_credentials` · Permiso: `credentials.issue` · Ruta: F · Trazabilidad: HU-09, RF-22, RF-23, RF-25, HU-05 · Patrón: P13, P09, P07, P18 · Éxito: 201
- Solicitud: `channel` (`PRINT` o `EMAIL`). Emitir de nuevo sobre un paciente `INVITED` es el reenvío: la invitación anterior queda `REVOKED` y se crea un código nuevo. Sobre un paciente `ACTIVE` emite una invitación `PASSWORD_RESET` (para quien no tiene correo verificado).
- Respuesta: `invitation_id`, `purpose` (`PATIENT_ACTIVATION` o `PASSWORD_RESET`), `status: PENDING`, `channel`, `expires_at` (7 días), `delivery_status` (por definir) y, solo para `PRINT`, `activation_code` en claro. El código aparece **solo en esta respuesta**, con `Cache-Control: no-store`; la API no lo guarda ni lo repite. La hoja imprimible (PDF o HTML) se genera en esta respuesta y no se almacena; en una clínica demo puede venir también la hoja JSON (`sheet_id`, `clinic_id`, `issued_at`, `expires_at`, `items` con `patient_mrn`, `activation_code` y `expires_at`). La forma de pedir cada formato está por definir (G11). El paciente pasa a `INVITED`.
- Errores: C1, C2, C4, C5; `409 INVALID_STATE_TRANSITION` (paciente `SUSPENDED` o `DEACTIVATED`), `429` (300 por hora por clínica). Un correo que falla queda registrado como envío fallido; reintentar es emitir de nuevo.

#### `POST /credential-invitations/batch`
- Operación: `issue_credentials_batch` · Permiso: `credentials.issue` · Ruta: F · Trazabilidad: HU-09, RF-22, RF-25 · Patrón: P13, P09, P07 · Éxito: 200
- Solicitud: `patient_ids` (hasta 100 por petición), `channel`.
- Respuesta: un elemento por paciente con su resultado y, para `PRINT`, el código en claro una sola vez, con `Cache-Control: no-store`. Los valores del resultado están por definir (G16).
- Errores: C1, C2, C4, `429` (10 lotes por hora por clínica).

#### `POST /credential-invitations/{invitation_id}/revoke`
- Operación: `revoke_credential_invitation` · Permiso: `credentials.revoke` · Ruta: F · Trazabilidad: HU-09, RF-23 · Patrón: P13, P09, P18 · Éxito: 204
- Solicitud: sin cuerpo. La invitación pasa a `REVOKED` y el paciente vuelve a `IMPORTED`; el código se rechaza después con `410 INVITATION_INVALID`.
- Respuesta: sin cuerpo.
- Errores: C1, C2, C4, C5; `409 INVALID_STATE_TRANSITION` (la invitación no está pendiente).

### 8.5 Equipo de atención (M4)

#### `GET /care-team/assignments`
- Operación: `list_care_team_assignments` · Permiso: `care_team.read` · Ruta: P · Trazabilidad: HU-12, HU-13, RF-29 · Patrón: P11 · Éxito: 200
- Solicitud: `patient_id`, `doctor_id`, `status` (`ACTIVE` o `ENDED`), `limit`, `cursor`. El `CLINIC_ADMIN` ve las de su clínica; el `DOCTOR`, solo las propias.
- Respuesta: `id`, `patient_id`, `doctor_id`, `is_primary`, `started_at`, `ended_at`, `end_reason`. Con `status=ENDED` es el historial con fechas y motivo.
- Errores: C1, C2, C4.

#### `POST /care-team/assignments`
- Operación: `assign_doctor` · Permiso: `care_team.assign` · Ruta: P · Trazabilidad: HU-12, RF-27, RF-28 · Patrón: P13, P09 · Éxito: 201
- Solicitud: `patient_id`, `doctor_id` (médico activo de la misma clínica), `is_primary`. Un paciente con equipo tiene exactamente un médico principal; el primer médico asignado queda como principal.
- Respuesta: la asignación.
- Errores: C1, C2, C4; `404 NOT_FOUND` (médico o paciente de otra clínica o inexistente), `409 CONFLICT` (ya hay una asignación vigente de ese médico).

#### `POST /care-team/assignments/{assignment_id}/make-primary`
- Operación: `set_primary_doctor` · Permiso: `care_team.assign` · Ruta: P · Trazabilidad: HU-12, RF-28 · Patrón: P13, P09 · Éxito: 200
- Solicitud: sin cuerpo. El anterior principal deja de serlo en la misma operación.
- Respuesta: la asignación con `is_primary: true`.
- Errores: C1, C2, C4, C5; `409 INVALID_STATE_TRANSITION` (la asignación ya terminó).

#### `POST /care-team/assignments/{assignment_id}/reassign`
- Operación: `reassign_doctor` · Permiso: `care_team.assign` · Ruta: P · Trazabilidad: HU-13, RF-29 · Patrón: P13, P09 · Éxito: 201
- Solicitud: `new_doctor_id`, `reason`. Termina la asignación actual y crea la del médico nuevo, que hereda `is_primary`.
- Respuesta: la asignación nueva.
- Errores: C1, C2, C4, C5; `404 NOT_FOUND` (médico nuevo de otra clínica), `409 INVALID_STATE_TRANSITION`, `422 REASON_REQUIRED`.

#### `POST /care-team/assignments/{assignment_id}/end`
- Operación: `end_assignment` · Permiso: `care_team.assign` · Ruta: P · Trazabilidad: HU-13, RF-29, V10 · Patrón: P13, P09 · Éxito: 200
- Solicitud: `reason` y, si es el médico principal, `new_primary_assignment_id`. El médico retirado deja de ver al paciente y recibe `404` sobre él; sus decisiones previas siguen en la auditoría.
- Respuesta: la asignación con `ended_at`.
- Errores: C1, C2, C4, C5; `409 CONFLICT` (retirar al único médico principal sin reemplazo), `409 INVALID_STATE_TRANSITION` (ya terminó), `422 REASON_REQUIRED`.
