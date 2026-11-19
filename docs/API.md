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
- Los identificadores son UUID (v7). Una ruta nunca lleva el `patient_id` del propio paciente: las rutas `_own` toman el `patient_id` del token (regla V3 de `Actores-y-permisos.md`). El prefijo `/patients/own` es la forma de nombrar "mi expediente".
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
| Access token | JWT HS256 de 15 minutos (`JWT_ACCESS_MINUTES`). Solo en memoria del frontend: nunca en `localStorage`, `sessionStorage`, IndexedDB ni cookies. Claims: `iss`, `aud`, `sub`, `role`, `clinic_id` (`null` solo para `PLATFORM_ADMIN`), `tv`, `sid`, `amr`, `jti`, `iat`, `nbf`, `exp`. Los permisos **no** van en el token: `GET /auth/current-user` los devuelve. |
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
| `MFA_ENROLLMENT_REQUIRED` | El personal no tiene MFA. | Un `access_token` de enrolamiento (`amr: ["pwd"]`, sin refresh). Solo sirve para `/auth/mfa/enrollment*`, `GET /auth/current-user` y `/auth/logout`. |

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

1. **Denegación por defecto.** Todo endpoint exige autenticación y un permiso, salvo los públicos y las acciones sobre la propia cuenta (`GET /auth/current-user`, cambiar contraseña, cerrar sesión, administrar MFA propio, notificaciones propias).
2. **`403` antes que `404`.** El permiso se verifica antes de buscar el recurso: un rol sin el permiso recibe `403 FORBIDDEN` aunque el id no exista. Quien tiene el permiso y pide un recurso ajeno recibe `404 NOT_FOUND`, con el mismo cuerpo, cabeceras y tiempo que un `404` real (no revela que existe).
3. **Alcance.** `_own` usa el `patient_id` del token. `_assigned` exige una asignación vigente en `clinic.care_team_assignments` (`PatientRecordAccessProxy`, P11). Sin sufijo es la clínica del usuario.
4. **El administrador no ve datos clínicos.** `PLATFORM_ADMIN` y `CLINIC_ADMIN` no tienen permisos de lectura clínica; sus listados devuelven solo campos administrativos.
5. **Auditoría.** Toda lectura de datos clínicos escribe una fila en `audit.data_access_log` antes de responder (`PhiAccessAuditDecorator`, P09). Si la auditoría falla, la lectura no responde. Todo comando que cambia seguridad o decisiones clínicas escribe en `audit.audit_log` (`AuditingCommandHandler`, P09).
6. **Ruta de la propia sesión.** `consents/*`, `GET /auth/current-user` y el cierre de sesión no exigen consentimiento vigente: un paciente con una versión nueva por aceptar debe poder aceptarla.

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
| `C2` | `403 MFA_REQUIRED` | Endpoint llamado por personal (`CLINIC_ADMIN`, `DOCTOR`, `PLATFORM_ADMIN`), salvo `/auth/mfa/enrollment*`, `GET /auth/current-user` y `/auth/logout` |
| `C3` | `403 CONSENT_REQUIRED` | Endpoint llamado por `PATIENT`, salvo `consents/*`, `GET /auth/current-user` y `/auth/logout` |
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

### 8.0 Resumen e índice

Endpoints por sección. Post-MVP son los que atienden requisitos de las fases 10 a 12; el resto es MVP (fases 1 a 9):

| Sección | Módulo | Endpoints | Post-MVP |
|---|---|---|---|
| 8.1 | Salud y metadatos | 3 | 0 |
| 8.2 | Autenticación y activación (M1, M3) | 15 | 0 |
| 8.3 | Clínicas, sedes y personal (M2) | 20 | 4 |
| 8.4 | Pacientes, importación y credenciales (M3) | 16 | 0 |
| 8.5 | Equipo de atención (M4) | 5 | 0 |
| 8.6 | Registros del paciente y expediente (M5) | 26 | 0 |
| 8.7 | Plan de tratamiento, metas y recordatorios (M6) | 24 | 0 |
| 8.8 | Métricas glucémicas y pronóstico (M7, M9) | 5 | 0 |
| 8.9 | Alertas, reglas y notificaciones (M8) | 15 | 0 |
| 8.10 | IA y soporte a decisiones (M9) | 13 | 4 |
| 8.11 | Dashboard médico, notas y reportes (M10) | 8 | 0 |
| 8.12 | Mensajería y seguimiento (M11, Post-MVP) | 5 | 5 |
| 8.13 | Auditoría, consentimiento y privacidad (M12) | 13 | 7 |
| | **Total** | **168** | **20** |

Índice de todos los endpoints. **R** es `F` (ruta fijada por un documento o por el código) o `P` (propuesta de este archivo). El detalle de cada uno está en su sección.

| Método | Ruta | Operación | Permiso | R | Éxito |
|---|---|---|---|---|---|
| GET | `/health` | `get_health` | público | F | 200 |
| GET | `/ready` | `get_readiness` | público | F | 200 |
| GET | `/meta/field-limits` | `get_field_limits` | público | F | 200 |
| POST | `/auth/login` | `login` | público | F | 200 |
| POST | `/auth/mfa/verify` | `verify_mfa_challenge` | público (con `challenge_token`) | F | 200 |
| POST | `/auth/mfa/enrollment` | `start_mfa_enrollment` | token de enrolamiento (personal sin MFA) | F | 200 |
| POST | `/auth/mfa/enrollment/confirm` | `confirm_mfa_enrollment` | token de enrolamiento | F | 200 |
| POST | `/auth/mfa/recovery-codes` | `regenerate_mfa_recovery_codes` | autenticado (personal con sesión completa) | F | 200 |
| GET | `/auth/current-user` | `get_current_user` | autenticado | F | 200 |
| POST | `/auth/refresh` | `refresh_session` | cookie de refresh | F | 200 |
| POST | `/auth/logout` | `logout` | autenticado (cookie y JWT) | F | 204 |
| POST | `/auth/logout-all` | `logout_all_sessions` | autenticado (cookie y JWT) | F | 204 |
| POST | `/auth/password/change` | `change_password` | autenticado | F | 200 |
| POST | `/auth/password-reset/request` | `request_password_reset` | público | F | 202 |
| POST | `/auth/password-reset/complete` | `complete_password_reset` | público (con token de un solo uso) | F | 204 |
| POST | `/auth/email-verification/confirm` | `confirm_email_verification` | público (con token de un solo uso) | F | 204 |
| POST | `/auth/activation/verify` | `verify_activation_code` | público | F | 200 |
| POST | `/auth/activation/complete` | `complete_activation` | público (con `activation_token`) | F | 200 |
| POST | `/clinics` | `create_clinic` | `clinics.manage` | P | 201 |
| GET | `/clinics` | `list_clinics` | `clinics.manage` | P | 200 |
| GET | `/clinics/{clinic_id}` | `get_clinic` | `clinics.manage` | P | 200 |
| PATCH | `/clinics/{clinic_id}` | `update_clinic` | `clinics.manage` | P | 200 |
| POST | `/clinics/{clinic_id}/suspend` | `suspend_clinic` | `clinics.manage` | P | 200 |
| POST | `/clinics/{clinic_id}/reactivate` | `reactivate_clinic` | `clinics.manage` | P | 200 |
| POST | `/clinics/{clinic_id}/admins` | `create_clinic_admin` | `clinic_admins.manage` | P | 201 |
| POST | `/clinics/{clinic_id}/admins/{user_id}/reset-access` | `reset_clinic_admin_access` | `clinic_admins.manage` | P | 204 |
| GET | `/clinics/current` | `get_current_clinic` | `clinics.read` | P | 200 |
| POST | `/sites` | `create_site` | `sites.manage` | P | 201 |
| GET | `/sites` | `list_sites` | `sites.manage` | P | 200 |
| PATCH | `/sites/{site_id}` | `update_site` | `sites.manage` | P | 200 |
| PUT | `/users/{user_id}/sites` | `set_user_sites` | `sites.manage` | P | 200 |
| POST | `/users` | `create_user` | `users.manage` | P | 201 |
| GET | `/users` | `list_users` | `users.read` | P | 200 |
| GET | `/users/{user_id}` | `get_user` | `users.read` | P | 200 |
| PATCH | `/users/{user_id}` | `update_user` | `users.manage` | P | 200 |
| POST | `/users/{user_id}/deactivate` | `deactivate_user` | `users.manage` | P | 200 |
| POST | `/users/{user_id}/unlock` | `unlock_user` | `users.manage` | F | 204 |
| POST | `/users/{user_id}/mfa-reset` | `reset_user_mfa` | `users.manage` | P | 204 |
| GET | `/patients` | `list_patients` | `patients.read_roster` | P | 200 |
| GET | `/patients/{patient_id}` | `get_patient_administrative_view` | `patients.read_roster` | P | 200 |
| POST | `/patients/{patient_id}/suspend` | `suspend_patient` | `patients.manage_status` | P | 200 |
| POST | `/patients/{patient_id}/reactivate` | `reactivate_patient` | `patients.manage_status` | P | 200 |
| POST | `/patients/{patient_id}/deactivate` | `deactivate_patient` | `patients.manage_status` | P | 200 |
| GET | `/imports/csv-template` | `download_csv_import_template` | `patients.import` | P | 200 |
| POST | `/imports/fhir` | `create_fhir_import_preview` | `patients.import` | P | 201 |
| POST | `/imports/csv` | `create_csv_import_preview` | `patients.import` | P | 201 |
| GET | `/imports` | `list_import_batches` | `import_batches.read` | P | 200 |
| GET | `/imports/{batch_id}` | `get_import_batch` | `import_batches.read` | P | 200 |
| GET | `/imports/{batch_id}/rows` | `list_import_rows` | `import_batches.read` | P | 200 |
| GET | `/imports/{batch_id}/errors` | `download_import_errors` | `import_batches.read` | P | 200 |
| POST | `/imports/{batch_id}/confirm` | `confirm_import` | `patients.import` | P | 202 |
| POST | `/patients/{patient_id}/credential-invitations` | `issue_patient_credentials` | `credentials.issue` | F | 201 |
| POST | `/credential-invitations/batch` | `issue_credentials_batch` | `credentials.issue` | F | 200 |
| POST | `/credential-invitations/{invitation_id}/revoke` | `revoke_credential_invitation` | `credentials.revoke` | F | 204 |
| GET | `/care-team/assignments` | `list_care_team_assignments` | `care_team.read` | P | 200 |
| POST | `/care-team/assignments` | `assign_doctor` | `care_team.assign` | P | 201 |
| POST | `/care-team/assignments/{assignment_id}/make-primary` | `set_primary_doctor` | `care_team.assign` | P | 200 |
| POST | `/care-team/assignments/{assignment_id}/reassign` | `reassign_doctor` | `care_team.assign` | P | 201 |
| POST | `/care-team/assignments/{assignment_id}/end` | `end_assignment` | `care_team.assign` | P | 200 |
| POST | `/readings` | `record_glucose_reading` | `glucose.write_own` | F | 201 |
| POST | `/readings/batch` | `record_glucose_readings_batch` | `glucose.write_own` | P | 200 |
| POST | `/readings/cgm-import` | `import_cgm_readings` | `glucose.write_own` | P | 200 |
| GET | `/readings` | `list_glucose_readings` | `glucose.read_own` | P | 200 |
| GET | `/patients/{patient_id}/readings` | `list_patient_glucose_readings` | `patients.read_assigned` | P | 200 |
| POST | `/insulin-doses` | `record_insulin_dose` | `records.write_own` | P | 201 |
| GET | `/insulin-doses` | `list_insulin_doses` | `records.read_own` | P | 200 |
| GET | `/patients/own/injection-sites` | `get_own_injection_sites` | `records.read_own` | P | 200 |
| POST | `/meals` | `record_meal` | `records.write_own` | P | 201 |
| GET | `/meals` | `list_meals` | `records.read_own` | P | 200 |
| POST | `/activities` | `record_activity` | `records.write_own` | P | 201 |
| GET | `/activities` | `list_activities` | `records.read_own` | P | 200 |
| POST | `/symptoms` | `record_symptoms` | `records.write_own` | P | 201 |
| GET | `/symptoms` | `list_symptoms` | `records.read_own` | P | 200 |
| POST | `/lab-results` | `record_own_lab_result` | `labs.write_own` | P | 201 |
| POST | `/patients/{patient_id}/lab-results` | `record_patient_lab_result` | `labs.write_assigned` | P | 201 |
| GET | `/lab-results` | `list_lab_results` | `records.read_own` | P | 200 |
| GET | `/patients/{patient_id}/lab-results` | `list_patient_lab_results` | `patients.read_assigned` | P | 200 |
| POST | `/records/{record_type}/{record_id}/corrections` | `correct_record` | `records.correct_own` | P | 201 |
| POST | `/records/{record_type}/{record_id}/annulments` | `annul_record` | `records.correct_own` | P | 201 |
| GET | `/timeline` | `get_own_timeline` | `records.read_own` | P | 200 |
| GET | `/patients/{patient_id}/timeline` | `get_patient_timeline` | `patients.read_assigned` | P | 200 |
| GET | `/timeline/export` | `export_own_timeline` | `records.read_own` | P | 200 |
| GET | `/patients/{patient_id}/timeline/export` | `export_patient_timeline` | `patients.read_assigned` | P | 200 |
| GET | `/patients/own` | `get_own_patient_profile` | `patients.read_own` | P | 200 |
| GET | `/patients/own/overview` | `get_own_overview` | `patients.read_own` | P | 200 |
| GET | `/patients/{patient_id}/overview` | `get_patient_overview` | `patients.read_assigned` | F | 200 |
| POST | `/protocol-templates` | `create_protocol_template` | `protocol_templates.manage` | P | 201 |
| GET | `/protocol-templates` | `list_protocol_templates` | `protocol_templates.read` | P | 200 |
| GET | `/protocol-templates/{template_id}` | `get_protocol_template` | `protocol_templates.read` | P | 200 |
| POST | `/protocol-templates/{template_id}/versions` | `create_protocol_template_version` | `protocol_templates.manage` | P | 201 |
| POST | `/protocol-templates/{template_id}/retire` | `retire_protocol_template` | `protocol_templates.manage` | P | 200 |
| POST | `/treatment-plans` | `create_treatment_plan` | `treatment_plans.manage` | P | 201 |
| GET | `/treatment-plans` | `list_treatment_plans` | `treatment_plans.manage` | P | 200 |
| GET | `/treatment-plans/{plan_id}` | `get_treatment_plan` | `treatment_plans.manage` | P | 200 |
| PATCH | `/treatment-plans/{plan_id}` | `update_treatment_plan` | `treatment_plans.manage` | P | 200 |
| POST | `/treatment-plans/{plan_id}/activate` | `activate_treatment_plan` | `treatment_plans.manage` | P | 200 |
| POST | `/treatment-plans/{plan_id}/versions` | `create_treatment_plan_version` | `treatment_plans.manage` | P | 201 |
| GET | `/treatment-plans/{plan_id}/snapshots` | `list_treatment_plan_snapshots` | `treatment_plans.manage` | P | 200 |
| POST | `/treatment-plans/{plan_id}/restore` | `restore_treatment_plan` | `treatment_plans.manage` | P | 201 |
| GET | `/patients/own/treatment-plan` | `get_own_treatment_plan` | `treatment_plans.read_own` | P | 200 |
| POST | `/target-profiles` | `create_target_profile` | `target_profiles.manage` | P | 201 |
| GET | `/target-profiles` | `list_target_profiles` | `target_profiles.manage` o `target_profiles.assign` | P | 200 |
| GET | `/target-profiles/{profile_id}` | `get_target_profile` | `target_profiles.manage` o `target_profiles.assign` | P | 200 |
| POST | `/target-profiles/{profile_id}/versions` | `create_target_profile_version` | `target_profiles.manage` | P | 201 |
| PUT | `/patients/{patient_id}/target-profile` | `assign_target_profile` | `target_profiles.assign` | P | 200 |
| POST | `/patients/{patient_id}/reminders` | `create_reminder` | `reminders.manage_assigned` | P | 201 |
| GET | `/patients/{patient_id}/reminders` | `list_patient_reminders` | `reminders.manage_assigned` | P | 200 |
| PATCH | `/patients/{patient_id}/reminders/{reminder_id}` | `update_patient_reminder` | `reminders.manage_assigned` | P | 200 |
| GET | `/reminders` | `list_own_reminders` | `reminders.manage_own` | P | 200 |
| PATCH | `/reminders/{reminder_id}` | `update_own_reminder` | `reminders.manage_own` | P | 200 |
| GET | `/patients/{patient_id}/metrics` | `get_patient_metrics` | `metrics.read_assigned` | F | 200 |
| GET | `/patients/{patient_id}/metrics/agp` | `get_patient_agp` | `metrics.read_assigned` | P | 200 |
| GET | `/patients/own/metrics` | `get_own_metrics` | `metrics.read_own` | P | 200 |
| GET | `/patients/{patient_id}/forecast` | `get_patient_forecast` | `ai.forecasts.read_assigned` | F | 200 |
| GET | `/patients/own/forecast` | `get_own_forecast` | `ai.forecasts.read_own` | P | 200 |
| POST | `/alert-rules` | `create_alert_rule` | `alert_rules.manage` | P | 201 |
| GET | `/alert-rules` | `list_alert_rules` | `alert_rules.read` | P | 200 |
| GET | `/alert-rules/{rule_id}` | `get_alert_rule` | `alert_rules.read` | P | 200 |
| POST | `/alert-rules/{rule_id}/versions` | `create_alert_rule_version` | `alert_rules.manage` | P | 201 |
| GET | `/alerts` | `list_alerts` | `alerts.read_assigned` o `alerts.read_own` | P | 200 |
| GET | `/alerts/summary` | `get_alert_summary` | `alerts.read_summary` | P | 200 |
| GET | `/alerts/{alert_id}` | `get_alert` | `alerts.read_assigned` o `alerts.read_own` | P | 200 |
| POST | `/alerts/{alert_id}/acknowledge` | `acknowledge_alert` | `alerts.acknowledge` o `alerts.acknowledge_own` | P | 200 |
| POST | `/alerts/{alert_id}/resolve` | `resolve_alert` | `alerts.resolve` | P | 200 |
| GET | `/notifications` | `list_notifications` | `notifications.read_own` | P | 200 |
| POST | `/notifications/{notification_id}/read` | `mark_notification_read` | `notifications.read_own` | P | 204 |
| GET | `/notification-preferences` | `get_notification_preferences` | `notification_preferences.manage_own` | P | 200 |
| PUT | `/notification-preferences` | `update_notification_preferences` | `notification_preferences.manage_own` | P | 200 |
| PUT | `/notification-preferences/web-push-subscription` | `register_web_push_subscription` | `notification_preferences.manage_own` | P | 204 |
| DELETE | `/notification-preferences/web-push-subscription` | `remove_web_push_subscription` | `notification_preferences.manage_own` | P | 204 |
| GET | `/recommendations` | `list_recommendations` | `recommendations.read_assigned` | P | 200 |
| GET | `/recommendations/{recommendation_id}` | `get_recommendation` | `recommendations.read_assigned` | P | 200 |
| POST | `/recommendations/{recommendation_id}/approve` | `approve_recommendation` | `recommendations.decide` | P | 200 |
| POST | `/recommendations/{recommendation_id}/modify` | `modify_recommendation` | `recommendations.decide` | P | 200 |
| POST | `/recommendations/{recommendation_id}/reject` | `reject_recommendation` | `recommendations.decide` | P | 200 |
| GET | `/patients/{patient_id}/risk` | `get_patient_risk` | `ai.risk.read_assigned` | P | 200 |
| GET | `/patients/{patient_id}/pattern-findings` | `list_pattern_findings` | `ai.risk.read_assigned` | P | 200 |
| POST | `/patients/{patient_id}/pattern-findings/{finding_id}/dismiss` | `dismiss_pattern_finding` | `ai.risk.read_assigned` | P | 200 |
| POST | `/patients/{patient_id}/clinical-summaries` | `create_clinical_summary` | `clinical_summaries.generate` | P | 201 |
| GET | `/patients/{patient_id}/clinical-summaries/{summary_id}` | `get_clinical_summary` | `clinical_summaries.generate` | P | 200 |
| POST | `/assistant/messages` | `send_assistant_message` | `assistant.use` | P | 200 |
| GET | `/dropout-risks` | `list_dropout_risks` | `ai.dropout_risk.read` | P | 200 |
| GET | `/ai-evaluations` | `list_ai_evaluations` | `ai_evaluations.read` | P | 200 |
| GET | `/dashboard/triage` | `get_triage_dashboard` | `dashboard.read_assigned` | P | 200 |
| POST | `/dashboard/patients/{patient_id}/review` | `mark_patient_reviewed` | `dashboard.read_assigned` | P | 200 |
| POST | `/patients/{patient_id}/clinical-notes` | `create_clinical_note` | `clinical_notes.manage` | P | 201 |
| GET | `/patients/{patient_id}/clinical-notes` | `list_clinical_notes` | `clinical_notes.manage` | P | 200 |
| POST | `/reports/patient` | `create_patient_report` | `reports.generate_assigned` | P | 200 |
| POST | `/reports/own` | `create_own_report` | `reports.generate_own` | P | 200 |
| POST | `/reports/clinic` | `create_clinic_report` | `reports.generate_clinic` | P | 200 |
| GET | `/clinic-kpis` | `get_clinic_kpis` | `clinic_kpis.read` | P | 200 |
| GET | `/messages` | `list_messages` | `messages.use_own` o `messages.use_assigned` | P | 200 |
| POST | `/messages` | `send_message` | `messages.use_own` o `messages.use_assigned` | P | 201 |
| POST | `/follow-ups` | `create_follow_up` | `follow_ups.manage` | P | 201 |
| GET | `/follow-ups` | `list_follow_ups` | `follow_ups.manage` o `follow_ups.read_own` | P | 200 |
| POST | `/follow-ups/{follow_up_id}/close` | `close_follow_up` | `follow_ups.manage` | P | 200 |
| GET | `/audit-log` | `list_audit_log` | `audit.read` | P | 200 |
| GET | `/audit-log/data-access` | `list_data_access_log` | `audit.read` | P | 200 |
| POST | `/audit-log/verifications` | `verify_audit_chain` | `audit.read` | P | 200 |
| GET | `/security-events` | `list_security_events` | `audit.read` o `audit.read_platform` | P | 200 |
| GET | `/public/privacy-notices/{privacy_notice_version_id}` | `get_privacy_notice` | público | P | 200 |
| GET | `/consents/own` | `get_own_consent` | `consents.manage_own` | P | 200 |
| POST | `/consents/own/acceptances` | `accept_consent` | `consents.manage_own` | P | 201 |
| POST | `/consents/own/withdrawals` | `withdraw_consent` | `consents.manage_own` | P | 200 |
| GET | `/consents` | `list_consent_statuses` | `consents.read_status` | P | 200 |
| POST | `/privacy-requests` | `create_privacy_request` | `privacy_requests.create_own` | P | 201 |
| GET | `/privacy-requests` | `list_privacy_requests` | `privacy_requests.create_own` o `privacy_requests.manage` | P | 200 |
| POST | `/privacy-requests/{request_id}/resolve` | `resolve_privacy_request` | `privacy_requests.manage` | P | 200 |
| GET | `/privacy-requests/{request_id}/export` | `export_privacy_request_data` | `privacy_requests.create_own` | P | 200 |

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

#### `GET /auth/current-user`
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
- Respuesta: `activation_token` (opaco, 15 minutos, un solo uso), `clinic_name`, `privacy_notice_version_id` (versión vigente; su texto sale de `GET /public/privacy-notices/{privacy_notice_version_id}`) y `email_required` (propuesto: indica si hay que pedir el correo). **No** devuelve el nombre del paciente ni otros datos personales. Para una invitación `STAFF_ACTIVATION` (médico o administrador de clínica, también tras `reset-access`) basta el código: no se pide fecha de nacimiento (cualquier `birth_date` se ignora y no cuenta intentos), `privacy_notice_version_id` es `null` porque el personal no consiente y `email_required` es `false`.
- Errores: `410 INVITATION_INVALID` (un solo error para código mal formado, inexistente, vencido, usado, reemplazado, revocado, bloqueado o fecha incorrecta; 5 fallos de fecha con un código real bloquean la invitación), `429` (10 por minuto y 50 por hora por IP), `422`, `413`, `500`.

#### `POST /auth/activation/complete`
- Operación: `complete_activation` · Permiso: público (con `activation_token`) · Ruta: F · Trazabilidad: HU-10, HU-05, RF-24, RF-90, RF-04 · Patrón: P18, P17 · Éxito: 200
- Solicitud: `activation_token`, `new_password` (misma política), `email` (obligatorio si la importación no lo traía; queda sin verificar y se envía un enlace de 24 horas), `consent` (`privacy_notice_version_id`, `accepted`, `ai_external_processing`; este último es un consentimiento aparte y opcional para el asistente con LLM externo). `consent` es obligatorio para pacientes (`422 VALIDATION_ERROR` si falta). El personal solo envía `activation_token` y `new_password`: conserva el correo con que fue invitado y no registra consentimiento; si envía `email` o `consent`, se ignoran.
- Respuesta: para un paciente, `status: AUTHENTICATED`, `access_token` y la cookie de refresh; la cuenta pasa de `INVITED` a `ACTIVE`, la invitación a `USED` y se guarda el consentimiento, todo en una transacción. Para personal, la cuenta pasa de `INVITED` a `ACTIVE` y la invitación `STAFF_ACTIVATION` a `USED`, y responde `status: MFA_ENROLLMENT_REQUIRED` con el token de enrolamiento (sin cookie de refresh): debe enrolar el MFA antes de usar la API, y en los siguientes ingresos el login responde `MFA_ENROLLMENT_REQUIRED` hasta confirmarlo. El evento `PatientActivated` se publica después del commit.
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
- Solicitud: `reason` (10 a 500 caracteres). Revoca todas las sesiones del usuario (`tv + 1`) y termina su membresía. Sus asignaciones de pacientes siguen abiertas y quedan pendientes de reasignar. La base exige el motivo al desactivar (`status_reason`). Nadie se desactiva a sí mismo.
- Respuesta: el personal con `is_active: false` y `patients_pending_reassignment` (cantidad). La lista de esos pacientes sale de `GET /patients?without_doctor=true`.
- Errores: C1, C2, C4, C5; `409 INVALID_STATE_TRANSITION` (ya desactivado), `403 FORBIDDEN` (quien lo pide es el propio titular), `422 REASON_REQUIRED`.

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

### 8.6 Registros del paciente y expediente (M5)

Las rutas de registro (`/readings`, `/insulin-doses`, `/meals`, `/activities`, `/symptoms`, `/lab-results`, `/timeline`) son del paciente autenticado: el `patient_id` sale del token, nunca de la ruta ni del cuerpo. El médico lee los mismos datos con `/patients/{patient_id}/...` y el permiso `patients.read_assigned`. Los registros son append-only: no hay `PUT`, `PATCH` ni `DELETE`. Todo registro nuevo exige consentimiento vigente (`403 CONSENT_REQUIRED`) y la cuenta del paciente en `ACTIVE`.

#### `POST /readings`
- Operación: `record_glucose_reading` · Permiso: `glucose.write_own` · Ruta: F · Trazabilidad: HU-15, HU-56, RF-31, RF-33, RF-98, RNF-20 · Patrón: P12, P17 · Éxito: 201 (200 si repite)
- Solicitud: `client_reading_id` (UUID generado por la app), `value` (número), `unit` (`mg/dL` o `mmol/L`), `measured_at` (ISO 8601 con zona), `source` (`MANUAL`, `SMBG` o `CGM`), `context` (ayunas, antes o después de comer, al acostarse, ejercicio u otro; los valores de la enumeración están por definir, G8), `note` (opcional, longitud de `FieldLimits`).
- Respuesta: `id`, `client_reading_id`, `value_mg_dl` (siempre en mg/dL), `measured_at`, `source`, `context`, `status` (`ACCEPTED` o `FLAGGED`), `issue_codes` (`DUPLICATE_SUSPECTED`, `IMPLAUSIBLE_RATE_OF_CHANGE`, `UNIT_MISMATCH_SUSPECTED`), `simulated`. Una lectura sospechosa se guarda `FLAGGED`, nunca se oculta. Repetir el mismo contenido responde `200` con la original y no duplica nada. Con `201` trae `Location`. La respuesta no espera a las alertas: los suscriptores del evento `GlucoseReadingRecorded` corren después del commit.
- Errores: C1, C3, C4; `409 CONFLICT` (mismo `client_reading_id` con otro contenido), `422 GLUCOSE_OUT_OF_RANGE` (fuera del rango medible de la clínica; no se guarda), `422 READING_IN_FUTURE`, `422 READING_TOO_OLD`.

#### `POST /readings/batch`
- Operación: `record_glucose_readings_batch` · Permiso: `glucose.write_own` · Ruta: P · Trazabilidad: HU-16, RF-32, RF-33, RF-98, RNF-11, RNF-20 · Patrón: P12 · Éxito: 200
- Solicitud: `items` (hasta 500 lecturas, 512 KiB), cada una con los campos de `POST /readings`. Es el envío de la cola offline.
- Respuesta: `items` en el mismo orden, cada uno con `client_reading_id`, `result` (`CREATED`, `DUPLICATE` o `REJECTED`), `reading_id` si se guardó y, si fue rechazada, `reason_code` con el código de error de la validación. Las válidas se guardan aunque otra se rechace. Reenviar el lote devuelve `DUPLICATE` sin duplicar. El lote queda en `monitoring.sync_batches`.
- Errores: C1, C3, C4 (más de 500 elementos responde `422`; más de 512 KiB, `413`).

#### `POST /readings/cgm-import`
- Operación: `import_cgm_readings` · Permiso: `glucose.write_own` · Ruta: P · Trazabilidad: HU-23, RF-41, RF-33 · Patrón: P06, P12 · Éxito: 200
- Solicitud: cuerpo crudo `text/csv` con la exportación del sensor (hasta 10 MiB y 100.000 filas). Lo lee `CgmCsvAdapter`.
- Respuesta: `format` reconocido, `created`, `duplicates` y `rejected` (conteos). Las lecturas pasan por la validación en cadena y se guardan con fuente `CGM`; las repetidas se marcan `DUPLICATE`.
- Errores: C1, C3, C4, `415`; un formato desconocido responde `422 VALIDATION_ERROR` con la lista de formatos admitidos en `detail`.

#### `GET /readings`
- Operación: `list_glucose_readings` · Permiso: `glucose.read_own` · Ruta: P · Trazabilidad: HU-22, RF-42 · Patrón: - · Éxito: 200
- Solicitud: `from`, `to`, `source`, `status`, `limit`, `cursor`.
- Respuesta: lecturas propias con los campos de `POST /readings` y `corrects_id` si es una corrección. El original corregido sigue visible con `status` `CORRECTED`.
- Errores: C1, C3, C4.

#### `GET /patients/{patient_id}/readings`
- Operación: `list_patient_glucose_readings` · Permiso: `patients.read_assigned` · Ruta: P · Trazabilidad: HU-14, HU-46, RF-30, RF-80 · Patrón: P11, P09 · Éxito: 200
- Solicitud: `from`, `to`, `source`, `status`, `limit`, `cursor`.
- Respuesta: las mismas lecturas del paciente asignado. Cada petición escribe una fila `GLUCOSE_READINGS` en `audit.data_access_log` antes de responder.
- Errores: C1, C2, C4, C5 (paciente no asignado o de otra clínica responde `404`).

#### `POST /insulin-doses`
- Operación: `record_insulin_dose` · Permiso: `records.write_own` · Ruta: P · Trazabilidad: HU-17, RF-34 · Patrón: P23 · Éxito: 201
- Solicitud: `insulin_product_id` (producto de un catálogo, G10), `kind` (`BASAL`, `BOLUS` o `CORRECTION`), `units` (decimal dentro del límite técnico), `administered_at`, `injection_site` e `injection_spot` (opcionales; códigos del catálogo de `GET /patients/own/injection-sites`). La API solo registra lo que el paciente indica: nunca calcula ni sugiere una dosis.
- Respuesta: `id`, `insulin_product_id`, `kind`, `units`, `administered_at`, `injection_site`, `injection_spot`, `treatment_plan_id` (el plan activo, si existe), `simulated`.
- Errores: C1, C3, C4 (unidades fuera de límites responde `422 VALIDATION_ERROR`).

#### `GET /insulin-doses`
- Operación: `list_insulin_doses` · Permiso: `records.read_own` · Ruta: P · Trazabilidad: HU-17, HU-22 · Patrón: - · Éxito: 200
- Solicitud: `from`, `to`, `limit`, `cursor`.
- Respuesta: dosis propias.
- Errores: C1, C3, C4.

#### `GET /patients/own/injection-sites`
- Operación: `get_own_injection_sites` · Permiso: `records.read_own` · Ruta: P · Trazabilidad: HU-57, RF-101 · Patrón: P19 · Éxito: 200
- Solicitud: `kind` (`BASAL`, `BOLUS`, `CORRECTION` o `MIXED`).
- Respuesta: `kind`, `suggestion` (`site`, `spot` de 1 a 4, `reason_codes`, `needle_note`, `pinch_up`), `sites` (por cada uno de los 8 sitios: `site`, `state` `SUGGESTED`, `ALLOWED`, `RECENT` o `AVOID`, `reason_code`, `last_used_at`, `last_spot`) y `rules_version`. Sitios: `ABDOMEN_RIGHT`, `ABDOMEN_LEFT`, `THIGH_RIGHT`, `THIGH_LEFT`, `ARM_RIGHT`, `ARM_LEFT`, `BUTTOCK_RIGHT`, `BUTTOCK_LEFT` (derecha e izquierda del paciente). Es una regla determinista, no una IA: candidatos = sitios del ítem del plan (nulo = todos); se excluyen los sitios con lipohipertrofia reportada en 90 días, el centro del abdomen en embarazo y brazos y muslos para un bolo con IMC bajo (menos de 20, o menos de 22 en hombres) salvo que el plan los pida; el bolo prefiere el abdomen y la basal el muslo y luego el glúteo; se evita el último sitio, se alterna el lado y se avanza el punto. Los criterios son técnica general de inyección y los valida el equipo clínico; el médico los restringe en el plan. **Nunca contiene unidades de insulina.**
- Errores: C1, C3, C4.

#### `POST /meals`
- Operación: `record_meal` · Permiso: `records.write_own` · Ruta: P · Trazabilidad: HU-18, RF-35 · Patrón: - · Éxito: 201
- Solicitud: `meal_type` (valores por definir, G8), `eaten_at`, `carbs_g` (carbohidratos estimados, dentro del límite de `FieldLimits`).
- Respuesta: `id`, `meal_type`, `eaten_at`, `carbs_g`, `simulated`.
- Errores: C1, C3, C4 (carbohidratos negativos o fuera de límites responde `422` con el campo en `detail.errors`).

#### `GET /meals`
- Operación: `list_meals` · Permiso: `records.read_own` · Ruta: P · Trazabilidad: HU-18, HU-22 · Patrón: - · Éxito: 200
- Solicitud: `from`, `to`, `limit`, `cursor`.
- Respuesta: comidas propias.
- Errores: C1, C3, C4.

#### `POST /activities`
- Operación: `record_activity` · Permiso: `records.write_own` · Ruta: P · Trazabilidad: HU-18, RF-36 · Patrón: - · Éxito: 201
- Solicitud: `activity_type` y `intensity` (valores por definir, G8), `duration_minutes` (dentro de límites), `started_at`.
- Respuesta: `id`, `activity_type`, `intensity`, `duration_minutes`, `started_at`, `simulated`. Se usa como contexto en los patrones.
- Errores: C1, C3, C4.

#### `GET /activities`
- Operación: `list_activities` · Permiso: `records.read_own` · Ruta: P · Trazabilidad: HU-18, HU-22 · Patrón: - · Éxito: 200
- Solicitud: `from`, `to`, `limit`, `cursor`.
- Respuesta: actividades propias.
- Errores: C1, C3, C4.

#### `POST /symptoms`
- Operación: `record_symptoms` · Permiso: `records.write_own` · Ruta: P · Trazabilidad: HU-19, RF-37 · Patrón: P17 · Éxito: 201
- Solicitud: `symptoms` (códigos de una lista, por ejemplo sed, mareo, sudoración, visión borrosa; G10), `occurred_at`, `note` (texto libre acotado por `FieldLimits`).
- Respuesta: `id`, `symptoms`, `occurred_at`, `alarm_detected` (propuesto: `true` si algún síntoma es de alarma; la app muestra "contacta a tu equipo o a urgencias" y se crea una alerta para el equipo), `simulated`.
- Errores: C1, C3, C4 (nota más larga que el límite responde `422`).

#### `GET /symptoms`
- Operación: `list_symptoms` · Permiso: `records.read_own` · Ruta: P · Trazabilidad: HU-19, HU-22 · Patrón: - · Éxito: 200
- Solicitud: `from`, `to`, `limit`, `cursor`.
- Respuesta: síntomas propios.
- Errores: C1, C3, C4.

#### `POST /lab-results`
- Operación: `record_own_lab_result` · Permiso: `labs.write_own` · Ruta: P · Trazabilidad: HU-20, RF-38 · Patrón: - · Éxito: 201
- Solicitud: `value`, `unit` (`%` o `mmol/mol`; mmol/mol se convierte con la ecuación IFCC-NGSP), `measured_on` (fecha del examen). El origen queda `PATIENT_REPORTED`.
- Respuesta: `id`, `value_percent`, `measured_on`, `origin: PATIENT_REPORTED`, `simulated`.
- Errores: C1, C3, C4 (valor de HbA1c fuera de rango responde `422 VALIDATION_ERROR`).

#### `POST /patients/{patient_id}/lab-results`
- Operación: `record_patient_lab_result` · Permiso: `labs.write_assigned` · Ruta: P · Trazabilidad: HU-20, RF-38 · Patrón: P11, P09 · Éxito: 201
- Solicitud: `value`, `unit`, `measured_on`. El origen queda `LAB` y reemplaza al autorreporte en las gráficas de tendencia.
- Respuesta: igual que `POST /lab-results` con `origin: LAB`.
- Errores: C1, C2, C4, C5.

#### `GET /lab-results`
- Operación: `list_lab_results` · Permiso: `records.read_own` · Ruta: P · Trazabilidad: HU-20 · Patrón: - · Éxito: 200
- Solicitud: `from`, `to`, `limit`, `cursor`.
- Respuesta: resultados propios con su origen.
- Errores: C1, C3, C4.

#### `GET /patients/{patient_id}/lab-results`
- Operación: `list_patient_lab_results` · Permiso: `patients.read_assigned` · Ruta: P · Trazabilidad: HU-20, HU-46, RF-38, RF-80 · Patrón: P11, P09 · Éxito: 200
- Solicitud: `from`, `to`, `limit`, `cursor`.
- Respuesta: resultados del paciente asignado, con origen. Escribe una fila `LAB_RESULTS` en `audit.data_access_log`.
- Errores: C1, C2, C4, C5.

#### `POST /records/{record_type}/{record_id}/corrections`
- Operación: `correct_record` · Permiso: `records.correct_own` · Ruta: P · Trazabilidad: HU-21, RF-39, RNF-20 · Patrón: P12 · Éxito: 201
- Solicitud: `record_type` en la ruta (`readings`, `insulin-doses`, `meals`, `activities` o `symptoms`), `reason` (10 a 500 caracteres) y `correction` (los campos del mismo tipo de registro). Crea un registro nuevo que apunta al original (`supersedes_id`); el original queda visible como corregido.
- Respuesta: el registro nuevo. Si es una lectura, pasa de nuevo por la validación en cadena.
- Errores: C1, C3, C4, C5 (registro ajeno responde `404`); `409 INVALID_STATE_TRANSITION` (el registro ya fue corregido o anulado), `422 REASON_REQUIRED`, `422 GLUCOSE_OUT_OF_RANGE` (para lecturas).

#### `POST /records/{record_type}/{record_id}/annulments`
- Operación: `annul_record` · Permiso: `records.correct_own` · Ruta: P · Trazabilidad: HU-21, RF-39, RNF-20 · Patrón: - · Éxito: 201
- Solicitud: `record_type` como en la corrección y `reason` (10 a 500 caracteres). Anula sin borrar: agrega una fila de anulación que apunta al original.
- Respuesta: el registro de anulación con `supersedes_id`.
- Errores: C1, C3, C4, C5; `409 INVALID_STATE_TRANSITION`, `422 REASON_REQUIRED`.

#### `GET /timeline`
- Operación: `get_own_timeline` · Permiso: `records.read_own` · Ruta: P · Trazabilidad: HU-22, RF-40 · Patrón: P21 · Éxito: 200
- Solicitud: `from`, `to`, `event_types` (lista), `limit`, `cursor`.
- Respuesta: eventos propios de glucosa, dosis, comidas, actividad y síntomas ordenados por hora, cada uno con `event_type`, `occurred_at`, `status` y los datos propios de su tipo. La misma colección alimenta la vista, el CSV y el FHIR (`ClinicalEventVisitor`).
- Errores: C1, C3, C4.

#### `GET /patients/{patient_id}/timeline`
- Operación: `get_patient_timeline` · Permiso: `patients.read_assigned` · Ruta: P · Trazabilidad: HU-46, HU-22, RF-40, RF-80 · Patrón: P21, P11, P09 · Éxito: 200
- Solicitud: `from`, `to`, `event_types`, `limit`, `cursor`.
- Respuesta: igual que `GET /timeline`, del paciente asignado. Escribe una fila `PATIENT_TIMELINE` en `audit.data_access_log`.
- Errores: C1, C2, C4, C5.

#### `GET /timeline/export`
- Operación: `export_own_timeline` · Permiso: `records.read_own` · Ruta: P · Trazabilidad: RF-40, RNF-13 · Patrón: P21 · Éxito: 200
- Solicitud: `format` (`csv` o `fhir`), `from`, `to`. Cuenta para el límite de reportes y exportaciones (20 por hora).
- Respuesta: archivo `text/csv` (con prefijo `'` en celdas que empiezan con `=`, `+`, `-`, `@`) o Bundle `application/fhir+json`. El contenido FHIR exacto está por definir (G25).
- Errores: C1, C3, C4.

#### `GET /patients/{patient_id}/timeline/export`
- Operación: `export_patient_timeline` · Permiso: `patients.read_assigned` · Ruta: P · Trazabilidad: RF-40, RNF-13 · Patrón: P21, P11, P09 · Éxito: 200
- Solicitud: `format` (`csv` o `fhir`), `from`, `to`.
- Respuesta: igual que `GET /timeline/export`. Escribe una fila con `action = EXPORT` en `audit.data_access_log`.
- Errores: C1, C2, C4, C5.

#### `GET /patients/own`
- Operación: `get_own_patient_profile` · Permiso: `patients.read_own` · Ruta: P · Trazabilidad: HU-22, RF-42, RF-50 · Patrón: P11 · Éxito: 200
- Solicitud: sin parámetros. Se declara antes que `GET /patients/{patient_id}` para que `me` no se lea como un id.
- Respuesta: `id`, `account_status`, `clinic` (`name`, `simulated`), `target_profile` (`id`, `code`, `version`) y `simulated`.
- Errores: C1, C3.

#### `GET /patients/own/overview`
- Operación: `get_own_overview` · Permiso: `patients.read_own` · Ruta: P · Trazabilidad: HU-22, HU-29, RF-42 · Patrón: P10, P11 · Éxito: 200
- Solicitud: `window` (`24h`, `7d`, `14d` o `30d`, por defecto `14d`).
- Respuesta: el inicio del paciente: lecturas recientes con su rango objetivo, métricas propias de la ventana en lenguaje simple, plan activo y alertas abiertas propias. No llama a la IA.
- Errores: C1, C3, C4.

#### `GET /patients/{patient_id}/overview`
- Operación: `get_patient_overview` · Permiso: `patients.read_assigned` · Ruta: F · Trazabilidad: HU-46, HU-14, RF-80, RF-30, RNF-07 · Patrón: P10, P11, P09 · Éxito: 200
- Solicitud: `window` (`24h`, `7d`, `14d` o `30d`, por defecto `14d`).
- Respuesta: `PatientOverviewResponse`: últimas lecturas, métricas de la ventana, plan activo, alertas abiertas, recomendaciones pendientes y el último pronóstico guardado. **Leer el expediente no llama a la IA.** Las glucosas salen en mg/dL. Incluye `simulated` y, en una clínica demo, `data_source: "SIMULATED"` (G6). `PatientOverviewFacade` abre una unidad de trabajo, usa el puerto envuelto por el decorador de auditoría y el proxy de asignación; la fila de auditoría se escribe en la misma transacción.
- Errores: C1, C2, C4, C5 (el `CLINIC_ADMIN` recibe `403 FORBIDDEN`: no tiene el permiso).

### 8.7 Plan de tratamiento, metas y recordatorios (M6)

Estados del plan: `DRAFT`, `ACTIVE` y `SUPERSEDED`. Un paciente tiene un solo plan activo. Cada cambio crea una versión nueva copiada de la anterior. El paciente solo ve el plan activo y no puede editar dosis. Las metas, las duraciones y los umbrales son datos de la base de datos (`care.target_profiles`, `care.protocol_templates`, `care.reminder_schedules`): ninguno vive en el código.

#### `POST /protocol-templates`
- Operación: `create_protocol_template` · Permiso: `protocol_templates.manage` · Ruta: P · Trazabilidad: HU-24, RF-43 · Patrón: P04 · Éxito: 201
- Solicitud: `name` (por ejemplo "Basal-bolo adulto DM1") y `content` (estructura de insulinas, horarios y metas por defecto; cada ítem de insulina admite `injection_sites`, la lista de sitios permitidos; su forma interna está por definir, G16).
- Respuesta: `id`, `name`, `version` (1), `status` (`ACTIVE`), `content`, `simulated`. Queda versionada y disponible para los médicos de su clínica.
- Errores: C1, C2, C4; `409 CONFLICT` (nombre repetido).

#### `GET /protocol-templates`
- Operación: `list_protocol_templates` · Permiso: `protocol_templates.read` · Ruta: P · Trazabilidad: HU-24, HU-25, RF-43, RF-44 · Patrón: - · Éxito: 200
- Solicitud: `status` (`ACTIVE` o `RETIRED`), `limit`, `cursor`.
- Respuesta: plantillas de la clínica con su última versión.
- Errores: C1, C2, C4.

#### `GET /protocol-templates/{template_id}`
- Operación: `get_protocol_template` · Permiso: `protocol_templates.read` · Ruta: P · Trazabilidad: HU-24, HU-25 · Patrón: - · Éxito: 200
- Solicitud: `template_id` en la ruta.
- Respuesta: la plantilla con su contenido y sus versiones.
- Errores: C1, C2, C4, C5.

#### `POST /protocol-templates/{template_id}/versions`
- Operación: `create_protocol_template_version` · Permiso: `protocol_templates.manage` · Ruta: P · Trazabilidad: HU-24, RF-43 · Patrón: P05 · Éxito: 201
- Solicitud: `content` (la estructura nueva). La versión anterior se conserva.
- Respuesta: la plantilla con `version` incrementada. Los planes ya creados no cambian.
- Errores: C1, C2, C4, C5; `409 INVALID_STATE_TRANSITION` (plantilla retirada).

#### `POST /protocol-templates/{template_id}/retire`
- Operación: `retire_protocol_template` · Permiso: `protocol_templates.manage` · Ruta: P · Trazabilidad: HU-24, RF-43 · Patrón: P18 · Éxito: 200
- Solicitud: sin cuerpo. Una plantilla retirada no se puede clonar, pero los planes que ya la usan no cambian.
- Respuesta: la plantilla con `status: RETIRED`.
- Errores: C1, C2, C4, C5; `409 INVALID_STATE_TRANSITION` (ya retirada).

#### `POST /treatment-plans`
- Operación: `create_treatment_plan` · Permiso: `treatment_plans.manage` · Ruta: P · Trazabilidad: HU-25, RF-44, RF-45 · Patrón: P05, P04, P11 · Éxito: 201
- Solicitud: `patient_id` (paciente asignado), `template_id` (opcional: clona la plantilla con `ProtocolTemplate.clone_for_patient()`) y `content` con las personalizaciones.
- Respuesta: `id`, `patient_id`, `version`, `status: DRAFT`, `content`, `template_id`. La plantilla original no cambia. `TreatmentPlanBuilder` valida las invariantes al activar, no al crear el borrador.
- Errores: C1, C2, C4; `404 NOT_FOUND` (paciente no asignado o plantilla inexistente o de otra clínica).

#### `GET /treatment-plans`
- Operación: `list_treatment_plans` · Permiso: `treatment_plans.manage` · Ruta: P · Trazabilidad: HU-26, RF-46 · Patrón: P11, P09 · Éxito: 200
- Solicitud: `patient_id` (obligatorio), `status`, `limit`, `cursor`.
- Respuesta: planes del paciente asignado con su versión y estado (`DRAFT`, `ACTIVE`, `SUPERSEDED`). Escribe una fila `TREATMENT_PLAN` en `audit.data_access_log`. El permiso de lectura del médico no está separado de `treatment_plans.manage` (G15).
- Errores: C1, C2, C4; `404 NOT_FOUND` (paciente no asignado).

#### `GET /treatment-plans/{plan_id}`
- Operación: `get_treatment_plan` · Permiso: `treatment_plans.manage` · Ruta: P · Trazabilidad: HU-25, HU-26 · Patrón: P11, P09 · Éxito: 200
- Solicitud: `plan_id` en la ruta.
- Respuesta: el plan con su contenido.
- Errores: C1, C2, C4, C5.

#### `PATCH /treatment-plans/{plan_id}`
- Operación: `update_treatment_plan` · Permiso: `treatment_plans.manage` · Ruta: P · Trazabilidad: HU-25, RF-45, RF-47 · Patrón: P16, P04 · Éxito: 200
- Solicitud: `content` (solo en un plan `DRAFT`). Antes de cada cambio se guarda una foto jsonb del plan (`TreatmentPlanMemento`).
- Respuesta: el borrador actualizado.
- Errores: C1, C2, C4, C5; `409 INVALID_STATE_TRANSITION` (un plan `ACTIVE` no se edita: se crea una versión nueva).

#### `POST /treatment-plans/{plan_id}/activate`
- Operación: `activate_treatment_plan` · Permiso: `treatment_plans.manage` · Ruta: P · Trazabilidad: HU-25, HU-26, RF-45, RF-46 · Patrón: P13, P04, P18, P09 · Éxito: 200
- Solicitud: sin cuerpo. `ActivateTreatmentPlanCommand` valida las invariantes (dosis dentro de límites, horarios sin solapes, metas coherentes), pasa el plan a `ACTIVE` y el anterior a `SUPERSEDED`.
- Respuesta: el plan activo. El paciente ve el plan nuevo.
- Errores: C1, C2, C4, C5; `409 INVALID_STATE_TRANSITION` (no es un borrador), `422 VALIDATION_ERROR` con la lista de invariantes incumplidas en `detail.errors` (G16).

#### `POST /treatment-plans/{plan_id}/versions`
- Operación: `create_treatment_plan_version` · Permiso: `treatment_plans.manage` · Ruta: P · Trazabilidad: HU-26, RF-46 · Patrón: P05, P16 · Éxito: 201
- Solicitud: sin cuerpo. Copia profunda del plan en `DRAFT` (`copy_for_new_version()`); el plan activo no cambia hasta activar la nueva.
- Respuesta: el borrador nuevo con la versión siguiente.
- Errores: C1, C2, C4, C5; `409 INVALID_STATE_TRANSITION` (solo un plan `ACTIVE` genera una versión nueva).

#### `GET /treatment-plans/{plan_id}/snapshots`
- Operación: `list_treatment_plan_snapshots` · Permiso: `treatment_plans.manage` · Ruta: P · Trazabilidad: HU-26, RF-47 · Patrón: P16, P11, P09 · Éxito: 200
- Solicitud: `limit`, `cursor`.
- Respuesta: fotos del plan (`id`, `version`, `created_at`, `created_by`) para elegir cuál restaurar.
- Errores: C1, C2, C4, C5.

#### `POST /treatment-plans/{plan_id}/restore`
- Operación: `restore_treatment_plan` · Permiso: `treatment_plans.manage` · Ruta: P · Trazabilidad: HU-26, RF-47 · Patrón: P16, P05, P09 · Éxito: 201
- Solicitud: `snapshot_id`. Restaurar crea una versión nueva en `DRAFT` con el contenido de la foto; el historial no se pierde.
- Respuesta: el borrador nuevo.
- Errores: C1, C2, C4, C5 (foto de otro plan responde `404`).

#### `GET /patients/own/treatment-plan`
- Operación: `get_own_treatment_plan` · Permiso: `treatment_plans.read_own` · Ruta: P · Trazabilidad: HU-28, RF-50 · Patrón: P11 · Éxito: 200
- Solicitud: sin parámetros.
- Respuesta: el plan `ACTIVE` en lenguaje claro (insulinas, horarios y metas) y sus recordatorios. Cada ítem de insulina lleva `insulin_kind` e `injection_sites` (lista de sitios permitidos por el médico; nula si no restringe). Sin opciones de edición. No existe plan en `DRAFT` visible para el paciente ni recomendaciones con dosis hasta que se apliquen.
- Errores: C1, C3; `404 NOT_FOUND` (no hay plan activo).

#### `POST /target-profiles`
- Operación: `create_target_profile` · Permiso: `target_profiles.manage` · Ruta: P · Trazabilidad: HU-27, RF-48 · Patrón: P19 · Éxito: 201
- Solicitud: `code`, `label`, `population`, `is_default`, `range_low_mg_dl`, `range_high_mg_dl`, `very_low_mg_dl`, `very_high_mg_dl`, `tir_min_pct`, `tbr_l1_max_pct`, `tbr_l2_max_pct`, `tar_l1_max_pct`, `tar_l2_max_pct`, `cv_max_pct`, `min_data_sufficiency_pct`, `min_days`, `hba1c_goal_pct`, `fasting_low_mg_dl`, `fasting_high_mg_dl`, `postprandial_max_mg_dl`, `night_start`, `night_end` (los nombres de [`Metricas-clinicas.md`](Metricas-clinicas.md), sección 7.5).
- Respuesta: el perfil con `id` y `version` (1). Los valores de los perfiles semilla (`ADULT_STANDARD`, `OLDER_OR_HIGH_RISK`, `PREGNANCY_T1D`, `PREGNANCY_T2D_GDM`) se cargan por la base de datos, no por esta API.
- Errores: C1, C2, C4; `409 CONFLICT` (código repetido).

#### `GET /target-profiles`
- Operación: `list_target_profiles` · Permiso: `target_profiles.manage` o `target_profiles.assign` · Ruta: P · Trazabilidad: HU-27, RF-48 · Patrón: - · Éxito: 200
- Solicitud: `population`, `limit`, `cursor`.
- Respuesta: perfiles vigentes de la clínica con su versión.
- Errores: C1, C2, C4.

#### `GET /target-profiles/{profile_id}`
- Operación: `get_target_profile` · Permiso: `target_profiles.manage` o `target_profiles.assign` · Ruta: P · Trazabilidad: HU-27, RF-48 · Patrón: - · Éxito: 200
- Solicitud: `profile_id` en la ruta.
- Respuesta: el perfil con todos sus campos y su historial de versiones.
- Errores: C1, C2, C4, C5.

#### `POST /target-profiles/{profile_id}/versions`
- Operación: `create_target_profile_version` · Permiso: `target_profiles.manage` · Ruta: P · Trazabilidad: HU-27, RF-48 · Patrón: P05 · Éxito: 201
- Solicitud: los campos del perfil que cambian. Se crea una versión nueva; las métricas pasadas conservan la versión con la que se calcularon.
- Respuesta: el perfil con la versión siguiente.
- Errores: C1, C2, C4, C5.

#### `PUT /patients/{patient_id}/target-profile`
- Operación: `assign_target_profile` · Permiso: `target_profiles.assign` · Ruta: P · Trazabilidad: HU-27, RF-48 · Patrón: P11, P19, P09 · Éxito: 200
- Solicitud: `target_profile_id` (un perfil vigente). Las métricas del paciente se comparan desde entonces con ese perfil.
- Respuesta: `patient_id` y el perfil asignado con su versión.
- Errores: C1, C2, C4, C5 (paciente no asignado o perfil de otra clínica).

#### `POST /patients/{patient_id}/reminders`
- Operación: `create_reminder` · Permiso: `reminders.manage_assigned` · Ruta: P · Trazabilidad: HU-28, RF-49 · Patrón: P11, P07 · Éxito: 201
- Solicitud: `reminder_type` (medición, dosis o control; valores por definir, G8), `schedule` (hora local y días; forma por definir) y `is_active`.
- Respuesta: el recordatorio. Se envía a su hora por los canales elegidos y respeta el horario de silencio del paciente.
- Errores: C1, C2, C4, C5.

#### `GET /patients/{patient_id}/reminders`
- Operación: `list_patient_reminders` · Permiso: `reminders.manage_assigned` · Ruta: P · Trazabilidad: HU-28, RF-49 · Patrón: P11 · Éxito: 200
- Solicitud: `limit`, `cursor`.
- Respuesta: recordatorios del paciente asignado.
- Errores: C1, C2, C4, C5.

#### `PATCH /patients/{patient_id}/reminders/{reminder_id}`
- Operación: `update_patient_reminder` · Permiso: `reminders.manage_assigned` · Ruta: P · Trazabilidad: HU-28, RF-49 · Patrón: P11 · Éxito: 200
- Solicitud: `schedule`, `is_active`.
- Respuesta: el recordatorio actualizado.
- Errores: C1, C2, C4, C5.

#### `GET /reminders`
- Operación: `list_own_reminders` · Permiso: `reminders.manage_own` · Ruta: P · Trazabilidad: HU-28, RF-49, RF-50 · Patrón: - · Éxito: 200
- Solicitud: `limit`, `cursor`.
- Respuesta: recordatorios propios con lo que el plan permite ajustar.
- Errores: C1, C3, C4.

#### `PATCH /reminders/{reminder_id}`
- Operación: `update_own_reminder` · Permiso: `reminders.manage_own` · Ruta: P · Trazabilidad: HU-28, RF-49 · Patrón: - · Éxito: 200
- Solicitud: `schedule`, `is_active`, solo dentro de lo que permite el plan.
- Respuesta: el recordatorio actualizado.
- Errores: C1, C3, C4, C5; `403 FORBIDDEN` (el ajuste excede lo que permite el plan).

### 8.8 Métricas glucémicas y pronóstico (M7, M9)

Las métricas y los pronósticos se calculan con el perfil de metas asignado al paciente (nunca con valores del código). Los días y las noches se calculan en la zona de la clínica. `window` acepta `24h`, `7d`, `14d` y `30d`. Con datos insuficientes la respuesta lo dice y no muestra un porcentaje engañoso.

#### `GET /patients/{patient_id}/metrics`
- Operación: `get_patient_metrics` · Permiso: `metrics.read_assigned` · Ruta: F · Trazabilidad: HU-29, RF-51, RF-52, RF-54, RF-55 · Patrón: P14, P19, P11, P09 · Éxito: 200
- Solicitud: `window` (por defecto `14d`), `compare_previous` (booleano, por defecto `true`).
- Respuesta: `window`, `period_from`, `period_to`, `timezone`, `target_profile` (`id`, `code`, `version`), `data_sufficiency_pct`, `is_sufficient` y `confidence` (`NORMAL` o `LOW_CONFIDENCE`); `metrics` con `tir_pct`, `tbr_l1_pct`, `tbr_l2_pct`, `tbr_pct`, `tar_l1_pct`, `tar_l2_pct`, `tar_pct`, `mean_glucose_mg_dl`, `gmi_pct`, `cv_pct` y `hypo_events_count`; y, si se pide, `previous` (mismas métricas de la ventana anterior del mismo tamaño) y `tir_delta_pct` (puntos porcentuales, con signo). Para un paciente con SMBG no hay AGP, CV ni GMI: se devuelven las métricas de glucometría (nombres por definir). Escribe una fila `GLYCEMIC_METRICS` en `audit.data_access_log`.
- Errores: C1, C2, C4, C5.

#### `GET /patients/{patient_id}/metrics/agp`
- Operación: `get_patient_agp` · Permiso: `metrics.read_assigned` · Ruta: P · Trazabilidad: HU-30, RF-53, RF-55 · Patrón: P14, P11, P09 · Éxito: 200
- Solicitud: `days` (por defecto 14), `resolution` (`hour` o `15min`).
- Respuesta: `bins` (por franja del día local: `p5`, `p25`, `p50`, `p75` y `p95` en mg/dL), `target_range` (`low` y `high` del perfil), `data_sufficiency_pct` e `is_sufficient`. Con datos insuficientes `bins` va vacío y `is_sufficient` es `false` (aviso "datos insuficientes").
- Errores: C1, C2, C4, C5.

#### `GET /patients/own/metrics`
- Operación: `get_own_metrics` · Permiso: `metrics.read_own` · Ruta: P · Trazabilidad: HU-29, RF-51, RF-55 · Patrón: P14, P19 · Éxito: 200
- Solicitud: `window`, `compare_previous`.
- Respuesta: las métricas propias con la forma de `GET /patients/{patient_id}/metrics`. Solo las del paciente autenticado.
- Errores: C1, C3, C4.

#### `GET /patients/{patient_id}/forecast`
- Operación: `get_patient_forecast` · Permiso: `ai.forecasts.read_assigned` · Ruta: F · Trazabilidad: HU-36, HU-40, RF-66, RF-75, RF-76 · Patrón: P11, P18, P06 · Éxito: 200
- Solicitud: `mode` (`SHORT_TERM` u `OVERNIGHT`, por defecto `SHORT_TERM`).
- Respuesta: `mode`, `generated_at`, `model_name`, `model_version`, `is_fallback`, `fallback_reason`, `trend` (`FALLING`, `STABLE` o `RISING`), `points` (`horizon_minutes`, `timestamp`, `p10`, `p50`, `p90`), `risk` (`hypo_probability` y `hyper_probability` por horizonte) y `explanation` (`summary`, `factors`, `data_refs`). `RemoteAiServiceProxy` llama al servicio con un seudónimo, con tiempo máximo de 3 s; si hay timeout, error o circuito abierto responde el respaldo lineal con `is_fallback: true` (la interfaz muestra "Respaldo por reglas"). La salida se guarda en `ai.glucose_forecasts`. Con datos insuficientes (por ejemplo un paciente con SMBG): `points` vacío, `is_fallback: true` y `fallback_reason: INSUFFICIENT_DATA`. Si la IA y el respaldo fallan no hay `5xx`: la API responde `200` con el respaldo.
- Errores: C1, C2, C4, C5. La IA caída **no** es un error (G33).

#### `GET /patients/own/forecast`
- Operación: `get_own_forecast` · Permiso: `ai.forecasts.read_own` · Ruta: P · Trazabilidad: HU-36, RF-64, RF-66 · Patrón: P11, P18 · Éxito: 200
- Solicitud: `mode`.
- Respuesta: tendencia y banda `p10` a `p90` por horizonte con `is_fallback`. **Nunca contiene una dosis de insulina.**
- Errores: C1, C3, C4.

### 8.9 Alertas, reglas y notificaciones (M8)

Estados de la alerta: `OPEN`, `ACKNOWLEDGED`, `RESOLVED`, `ESCALATED` (`OPEN → ACKNOWLEDGED → RESOLVED` y `OPEN → ESCALATED → ACKNOWLEDGED`). Las alertas las crea el sistema (evaluación de reglas, planificador, síntomas de alarma, pronóstico); no hay endpoint para crearlas. El escalamiento por la cadena paciente, médico principal, equipo y administrador lo corre el sistema (`AlertEscalationHandler`, P12) y no tiene endpoint propio: reconocer la alerta lo detiene. Las notificaciones por correo y Web Push dicen solo "Tienes una alerta nueva en Insumap", sin valores clínicos.

#### `POST /alert-rules`
- Operación: `create_alert_rule` · Permiso: `alert_rules.manage` · Ruta: P · Trazabilidad: HU-31, RF-56, RF-57, RF-58 · Patrón: P08, P09 · Éxito: 201
- Solicitud: `name`, `alert_type`, `priority`, `condition` (árbol de condiciones: nodos de umbral, duración y tasa de cambio, combinados con `ALL_OF` y `ANY_OF`; campos de cada nodo por definir, G16) y `escalation` (tiempos por eslabón de la cadena). Los umbrales y las duraciones son datos de la regla, no del código.
- Respuesta: `id`, `version` (1), `status`, `name`, `alert_type`, `priority`, `condition`, `escalation`.
- Errores: C1, C2, C4.

#### `GET /alert-rules`
- Operación: `list_alert_rules` · Permiso: `alert_rules.read` · Ruta: P · Trazabilidad: HU-31, RF-56 · Patrón: - · Éxito: 200
- Solicitud: `alert_type`, `limit`, `cursor`.
- Respuesta: reglas vigentes de la clínica.
- Errores: C1, C2, C4.

#### `GET /alert-rules/{rule_id}`
- Operación: `get_alert_rule` · Permiso: `alert_rules.read` · Ruta: P · Trazabilidad: HU-31, RF-56 · Patrón: P08 · Éxito: 200
- Solicitud: `rule_id` en la ruta.
- Respuesta: la regla con su árbol y su historial de versiones.
- Errores: C1, C2, C4, C5.

#### `POST /alert-rules/{rule_id}/versions`
- Operación: `create_alert_rule_version` · Permiso: `alert_rules.manage` · Ruta: P · Trazabilidad: HU-31, RF-56 · Patrón: P08, P09 · Éxito: 201
- Solicitud: los campos de la regla que cambian. Una regla activa no se edita: se versiona y la anterior queda para el historial.
- Respuesta: la regla con la versión siguiente.
- Errores: C1, C2, C4, C5.

#### `GET /alerts`
- Operación: `list_alerts` · Permiso: `alerts.read_assigned` o `alerts.read_own` · Ruta: P · Trazabilidad: HU-33, HU-32, RF-65 · Patrón: P11, P09 · Éxito: 200
- Solicitud: `status`, `type`, `from`, `to`, `patient_id` (solo médico), `limit`, `cursor`. El médico ve las alertas de sus pacientes asignados; el paciente, las propias.
- Respuesta: alertas con `id`, `patient_id`, `type` (`HYPOGLYCEMIA`, `HYPERGLYCEMIA`, `ADHERENCE`, `PREDICTIVE`), `level` (1, 2 o 3 en hipoglucemia), `priority`, `status`, `opened_at`, `rule_id`, `is_fallback` (alerta predictiva por tendencia lineal: "Respaldo por reglas") y `simulated`. Para el médico escribe una fila `ALERTS` en `audit.data_access_log`.
- Errores: C1, C2, C3, C4; `404 NOT_FOUND` (un `patient_id` no asignado o ajeno).

#### `GET /alerts/summary`
- Operación: `get_alert_summary` · Permiso: `alerts.read_summary` · Ruta: P · Trazabilidad: HU-34, RF-60, RF-83 · Patrón: P10 · Éxito: 200
- Solicitud: sin parámetros. Se declara antes que `GET /alerts/{alert_id}`.
- Respuesta: conteos agregados (`open_count`, `escalated_count`) y `by_care_team` (médico principal y cantidad sin atender). Nunca glucosa ni valores; los conteos pequeños se agrupan.
- Errores: C1, C2.

#### `GET /alerts/{alert_id}`
- Operación: `get_alert` · Permiso: `alerts.read_assigned` o `alerts.read_own` · Ruta: P · Trazabilidad: HU-33, RF-59, RF-65 · Patrón: P18, P11, P09 · Éxito: 200
- Solicitud: `alert_id` en la ruta.
- Respuesta: la alerta con su `history` (cadena de estados: quién, cuándo y nota) y a quién se notificó. El historial es append-only.
- Errores: C1, C2, C3, C4, C5.

#### `POST /alerts/{alert_id}/acknowledge`
- Operación: `acknowledge_alert` · Permiso: `alerts.acknowledge` o `alerts.acknowledge_own` · Ruta: P · Trazabilidad: HU-33, HU-34, RF-59, RF-60 · Patrón: P18, P12, P11 · Éxito: 200
- Solicitud: `note` (opcional). El médico reconoce la de un paciente asignado; el paciente, la suya (primer paso de la cadena).
- Respuesta: la alerta con `status: ACKNOWLEDGED`, quién y cuándo. Detiene el escalamiento.
- Errores: C1, C2, C3, C4, C5; `409 INVALID_STATE_TRANSITION` (por ejemplo, una alerta `RESOLVED`).

#### `POST /alerts/{alert_id}/resolve`
- Operación: `resolve_alert` · Permiso: `alerts.resolve` · Ruta: P · Trazabilidad: HU-33, RF-59 · Patrón: P18, P11 · Éxito: 200
- Solicitud: `note` (obligatoria, con límite de `FieldLimits`).
- Respuesta: la alerta con `status: RESOLVED` y la nota en su historial.
- Errores: C1, C2, C4, C5; `409 INVALID_STATE_TRANSITION` (solo una alerta `ACKNOWLEDGED` se resuelve).

#### `GET /notifications`
- Operación: `list_notifications` · Permiso: `notifications.read_own` · Ruta: P · Trazabilidad: HU-32, HU-35, RF-61 · Patrón: P07 · Éxito: 200
- Solicitud: `unread_only` (booleano), `limit`, `cursor`. La pueden llamar los cuatro roles.
- Respuesta: notificaciones in-app propias con `id`, `type`, `title`, `body`, `created_at`, `read_at` y la referencia del recurso (por ejemplo la alerta). No incluye contenido que el rol no pueda ver.
- Errores: C1, C2, C3, C4 (según el rol de quien llama).

#### `POST /notifications/{notification_id}/read`
- Operación: `mark_notification_read` · Permiso: `notifications.read_own` · Ruta: P · Trazabilidad: HU-35, RF-61 · Patrón: - · Éxito: 204
- Solicitud: sin cuerpo.
- Respuesta: sin cuerpo.
- Errores: C1, C2, C3, C4, C5.

#### `GET /notification-preferences`
- Operación: `get_notification_preferences` · Permiso: `notification_preferences.manage_own` · Ruta: P · Trazabilidad: HU-35, RF-61, RF-62 · Patrón: P07 · Éxito: 200
- Solicitud: sin parámetros.
- Respuesta: `channels` (`EMAIL`, `WEB_PUSH`, `IN_APP`, cada uno habilitado o no) y `quiet_hours` (`start`, `end` en hora local).
- Errores: C1, C2, C3.

#### `PUT /notification-preferences`
- Operación: `update_notification_preferences` · Permiso: `notification_preferences.manage_own` · Ruta: P · Trazabilidad: HU-35, RF-61, RF-62 · Patrón: P07 · Éxito: 200
- Solicitud: `channels` y `quiet_hours`. Las notificaciones críticas (hipoglucemia nivel 2 y 3) no se silencian.
- Respuesta: las preferencias guardadas.
- Errores: C1, C2, C3, C4.

#### `PUT /notification-preferences/web-push-subscription`
- Operación: `register_web_push_subscription` · Permiso: `notification_preferences.manage_own` · Ruta: P · Trazabilidad: HU-35, RF-61 · Patrón: P07 · Éxito: 204
- Solicitud: `endpoint` (solo `https`, host en `PUSH_ENDPOINT_ALLOWED_HOSTS`, sin IP literal) y `keys` (`p256dh`, `auth`). El endpoint lo envía el navegador y se trata como dato no confiable.
- Respuesta: sin cuerpo.
- Errores: C1, C2, C3, C4 (un endpoint rechazado responde `422` y registra `PUSH_ENDPOINT_REJECTED`).

#### `DELETE /notification-preferences/web-push-subscription`
- Operación: `remove_web_push_subscription` · Permiso: `notification_preferences.manage_own` · Ruta: P · Trazabilidad: HU-35, RF-61 · Patrón: P07 · Éxito: 204
- Solicitud: sin cuerpo.
- Respuesta: sin cuerpo. No es un registro clínico: se puede borrar.
- Errores: C1, C2, C3.

### 8.10 IA y soporte a decisiones (M9)

La IA solo apoya al médico: nunca aplica un cambio ni da una dosis al paciente. Toda salida trae `model_version`, `is_fallback` y `fallback_reason` (`AI_TIMEOUT`, `CIRCUIT_OPEN`, `AI_ERROR` o `INSUFFICIENT_DATA`) y se guarda en el esquema `ai` con su explicación. Al servicio de IA solo llega un seudónimo (`subject_ref`), nunca nombres, documento, MRN ni contacto. Una IA caída responde `200` con el respaldo por reglas (la interfaz muestra "Respaldo por reglas"), nunca un error. Los estados de la recomendación son `PROPOSED`, `APPROVED`, `APPROVED_WITH_CHANGES`, `REJECTED`, `APPLIED` y `EXPIRED`.

#### `GET /recommendations`
- Operación: `list_recommendations` · Permiso: `recommendations.read_assigned` · Ruta: P · Trazabilidad: HU-39, HU-40, RF-69, RF-71 · Patrón: P18, P11, P09 · Éxito: 200
- Solicitud: `patient_id`, `status`, `limit`, `cursor`. Solo pacientes asignados.
- Respuesta: por recomendación `id`, `patient_id`, `status`, `proposal` (`action` `INCREASE` o `DECREASE`, dosis actual, dosis propuesta, `delta_units`, `requires_doctor_approval: true`), `explanation` (`summary`, `factors`, `data_refs`), `model_version`, `is_fallback`, `expires_at`, `created_at` y `simulated`. Si el servicio de IA no responde no se genera ninguna sugerencia de ajuste y la respuesta trae `unavailable_reason` (propuesto, G19). Una recomendación nace en `PROPOSED` y no cambia el plan por sí sola.
- Errores: C1, C2, C4; `404 NOT_FOUND` (un `patient_id` no asignado).

#### `GET /recommendations/{recommendation_id}`
- Operación: `get_recommendation` · Permiso: `recommendations.read_assigned` · Ruta: P · Trazabilidad: HU-39, RF-69, RF-75 · Patrón: P18, P11, P09 · Éxito: 200
- Solicitud: `recommendation_id` en la ruta.
- Respuesta: la recomendación con su historial de decisiones (`actor`, hora, motivo y, si cambió, el valor original y el modificado).
- Errores: C1, C2, C4, C5.

#### `POST /recommendations/{recommendation_id}/approve`
- Operación: `approve_recommendation` · Permiso: `recommendations.decide` · Ruta: P · Trazabilidad: HU-39, RF-70, RF-71 · Patrón: P13, P18, P05, P17, P09 · Éxito: 200
- Solicitud: sin cuerpo. `ApproveRecommendationCommand` pasa la recomendación a `APPROVED`, crea una versión `DRAFT` del plan para que el médico la active, publica `RecommendationApproved` después del commit y audita la decisión.
- Respuesta: la recomendación con `status`, quién y cuándo, `draft_plan_id` y la versión del modelo.
- Errores: C1, C2, C4, C5; `409 INVALID_STATE_TRANSITION` (ya decidida o `EXPIRED`: una recomendación vencida no se puede decidir).

#### `POST /recommendations/{recommendation_id}/modify`
- Operación: `modify_recommendation` · Permiso: `recommendations.decide` · Ruta: P · Trazabilidad: HU-39, RF-70, RF-71 · Patrón: P13, P18, P05, P09 · Éxito: 200
- Solicitud: `modified_proposal` (la propuesta con el cambio del médico) y `reason` (10 a 500 caracteres). Se guardan el texto original, el modificado y el motivo.
- Respuesta: la recomendación con `status: APPROVED_WITH_CHANGES` y `draft_plan_id`.
- Errores: C1, C2, C4, C5; `409 INVALID_STATE_TRANSITION`, `422 REASON_REQUIRED`.

#### `POST /recommendations/{recommendation_id}/reject`
- Operación: `reject_recommendation` · Permiso: `recommendations.decide` · Ruta: P · Trazabilidad: HU-39, RF-70 · Patrón: P13, P18, P09 · Éxito: 200
- Solicitud: `reason` (10 a 500 caracteres; y, si existe, un código del catálogo de motivos, G10).
- Respuesta: la recomendación con `status: REJECTED` y el motivo guardado.
- Errores: C1, C2, C4, C5; `409 INVALID_STATE_TRANSITION`, `422 REASON_REQUIRED`.

#### `GET /patients/{patient_id}/risk`
- Operación: `get_patient_risk` · Permiso: `ai.risk.read_assigned` · Ruta: P · Trazabilidad: HU-37, RF-67, RF-76 · Patrón: P19, P11, P18, P09 · Éxito: 200
- Solicitud: `window_days` (por defecto 14).
- Respuesta: `assessment_type: DETERIORATION`, `risk_probability` (0 a 1), `risk_tier` (`LOW`, `MEDIUM`, `HIGH` o `CRITICAL`), `calibrated`, `explanation` con al menos un factor legible, `model_version`, `is_fallback` y `fallback_reason`. Con la IA caída usa reglas tipo TIDE (`RuleBasedRiskStrategy`) y lo indica.
- Errores: C1, C2, C4, C5.

#### `GET /patients/{patient_id}/pattern-findings`
- Operación: `list_pattern_findings` · Permiso: `ai.risk.read_assigned` · Ruta: P · Trazabilidad: HU-38, RF-68 · Patrón: P11, P09 · Éxito: 200
- Solicitud: `status` (nuevo o descartado; valores por definir), `limit`, `cursor`.
- Respuesta: hallazgos con `id`, `pattern_type` (`NOCTURNAL_HYPOGLYCEMIA`, `DAWN_PHENOMENON`, `POSTPRANDIAL_SPIKE`, `MISSED_DOSE`, `DUPLICATE_DOSE`, `ADHERENCE_DROP`, `IMPLAUSIBLE_READING`), ventana de fechas, `confidence`, evidencia, `is_fallback`.
- Errores: C1, C2, C4, C5.

#### `POST /patients/{patient_id}/pattern-findings/{finding_id}/dismiss`
- Operación: `dismiss_pattern_finding` · Permiso: `ai.risk.read_assigned` · Ruta: P · Trazabilidad: HU-38, RF-68 · Patrón: P11, P09 · Éxito: 200
- Solicitud: `note` (obligatoria). El hallazgo queda registrado como descartado y no se vuelve a mostrar como nuevo. Ningún permiso del catálogo nombra esta acción (G15).
- Respuesta: el hallazgo descartado.
- Errores: C1, C2, C4, C5; `409 INVALID_STATE_TRANSITION` (ya descartado).

#### `POST /patients/{patient_id}/clinical-summaries`
- Operación: `create_clinical_summary` · Permiso: `clinical_summaries.generate` · Ruta: P · Trazabilidad: HU-41, RF-72 (Post-MVP) · Patrón: P11, P09, P04 · Éxito: 201
- Solicitud: `period_days` (por defecto 14). Los datos viajan seudonimizados; el LLM no calcula métricas. Un LLM no disponible o una clínica no demo con `LLM_REAL_DATA_ALLOWED=false` usan la plantilla determinista.
- Respuesta: `id`, `summary_text`, `sections` (resumen del periodo, eventos, adherencia y cambios del plan), `references` (cada afirmación apunta a un dato), `model_version`, `is_fallback` y la marca "Generado con IA como apoyo; verifica con los datos".
- Errores: C1, C2, C4, C5; `429` (30 por hora por médico).

#### `GET /patients/{patient_id}/clinical-summaries/{summary_id}`
- Operación: `get_clinical_summary` · Permiso: `clinical_summaries.generate` · Ruta: P · Trazabilidad: HU-41, RF-72 (Post-MVP) · Patrón: P11, P09 · Éxito: 200
- Solicitud: `summary_id` en la ruta.
- Respuesta: el resumen ya generado. No vuelve a llamar a la IA.
- Errores: C1, C2, C4, C5.

#### `POST /assistant/messages`
- Operación: `send_assistant_message` · Permiso: `assistant.use` · Ruta: P · Trazabilidad: HU-42, RF-73 (Post-MVP) · Patrón: P11, P12 · Éxito: 200
- Solicitud: `message` (longitud de `FieldLimits`).
- Respuesta: `reply_text` (texto plano), `citations` (material aprobado por la clínica), `escalation` (`NONE`, `CONTACT_DOCTOR` o `EMERGENCY`) e `is_fallback`. El asistente no da dosis ni diagnósticos; ante síntomas de alarma muestra el aviso de urgencia y avisa al equipo. Sin el consentimiento `ai_external_processing` o con el LLM caído responde con respuestas predefinidas del material de la clínica.
- Errores: C1, C3, C4; `429` (20 por hora y 100 por día por paciente).

#### `GET /dropout-risks`
- Operación: `list_dropout_risks` · Permiso: `ai.dropout_risk.read` · Ruta: P · Trazabilidad: HU-43, RF-74 · Patrón: P19, P11, P09 · Éxito: 200
- Solicitud: `risk_tier`, `limit`, `cursor`. El `CLINIC_ADMIN` ve la lista administrativa; el `DOCTOR`, solo sus pacientes asignados.
- Respuesta: por paciente `patient_id`, nombre administrativo, `account_status`, `days_without_record`, `risk_tier`, `explanation` y `is_fallback` (con la IA caída se usa la regla de días sin registros). **Nunca valores clínicos.**
- Errores: C1, C2, C4.

#### `GET /ai-evaluations`
- Operación: `list_ai_evaluations` · Permiso: `ai_evaluations.read` · Ruta: P · Trazabilidad: HU-44, RF-77 (Post-MVP) · Patrón: P19 · Éxito: 200
- Solicitud: `use_case` (`IA1` a `IA7`), `model_version`, `limit`, `cursor`.
- Respuesta: por caso y versión, la métrica de la IA frente al respaldo (MAE, RMSE y Clarke Error Grid para el pronóstico; AUROC y calibración para el riesgo), el porcentaje servido con respaldo y la marca de que los datos son simulados. Solo métricas agregadas, nunca series de pacientes.
- Errores: C1, C2, C4.

### 8.11 Dashboard médico, notas y reportes (M10)

#### `GET /dashboard/triage`
- Operación: `get_triage_dashboard` · Permiso: `dashboard.read_assigned` · Ruta: P · Trazabilidad: HU-45, HU-37, RF-78, RF-79, RF-67, RF-76, RNF-07 · Patrón: P10, P19, P11, P09 · Éxito: 200
- Solicitud: `window` (`24h`, `7d`, `14d` o `30d`), `status` (filtro de estado; valores por definir), `reviewed` (booleano), `limit`, `cursor`.
- Respuesta: los pacientes asignados ordenados por riesgo. Por paciente: `patient_id`, nombre, `risk_tier` y puntaje, `flags` (cada bandera con su motivo legible), `open_alerts_count`, `pending_recommendations_count`, métricas resumidas de la ventana, `reviewed_at`, `is_fallback` e `simulated`. `DoctorDashboardFacade` escribe una fila de auditoría por paciente listado, en una sola inserción por lotes. Objetivo: 200 pacientes en 2 s.
- Errores: C1, C2, C4.

#### `POST /dashboard/patients/{patient_id}/review`
- Operación: `mark_patient_reviewed` · Permiso: `dashboard.read_assigned` · Ruta: P · Trazabilidad: HU-45, RF-79 · Patrón: P11, P09 · Éxito: 200
- Solicitud: sin cuerpo. Ningún permiso del catálogo nombra esta acción (G15).
- Respuesta: el paciente con `reviewed_at`. Baja de prioridad hasta que cambie su situación.
- Errores: C1, C2, C4, C5.

#### `POST /patients/{patient_id}/clinical-notes`
- Operación: `create_clinical_note` · Permiso: `clinical_notes.manage` · Ruta: P · Trazabilidad: HU-46, RF-81 · Patrón: P11, P09 · Éxito: 201
- Solicitud: `text` (longitud de `FieldLimits`) y `corrects_note_id` (opcional: una nota se corrige con otra). Las notas son append-only y solo las ve el equipo asignado.
- Respuesta: `id`, `text`, `author_id`, `created_at`, `corrects_note_id`, `simulated`.
- Errores: C1, C2, C4, C5.

#### `GET /patients/{patient_id}/clinical-notes`
- Operación: `list_clinical_notes` · Permiso: `clinical_notes.manage` · Ruta: P · Trazabilidad: HU-46, RF-81 · Patrón: P11, P09 · Éxito: 200
- Solicitud: `limit`, `cursor`.
- Respuesta: las notas del paciente asignado. Escribe una fila `CLINICAL_NOTES` en `audit.data_access_log`. El `CLINIC_ADMIN` recibe `403 FORBIDDEN`. El permiso de lectura no está separado del de escritura (G15).
- Errores: C1, C2, C4, C5.

#### `POST /reports/patient`
- Operación: `create_patient_report` · Permiso: `reports.generate_assigned` · Ruta: P · Trazabilidad: HU-47, RF-82 · Patrón: P02, P03, P20, P11, P09 · Éxito: 200
- Solicitud: `patient_id`, `format` (`pdf` o `html`) y el periodo (`from`, `to`; forma por definir, G16).
- Respuesta: el documento (`application/pdf` o `text/html`) con AGP, métricas, eventos y plan, con la fecha y el periodo; ambos formatos muestran la misma información. Un paciente de la clínica demo lleva la marca "Datos simulados". Las plantillas usan autoescape y el motor de PDF no descarga recursos remotos. Cuenta para el límite de 20 reportes por hora.
- Errores: C1, C2, C4, C5.

#### `POST /reports/own`
- Operación: `create_own_report` · Permiso: `reports.generate_own` · Ruta: P · Trazabilidad: HU-47, RF-82 · Patrón: P02, P03, P20 · Éxito: 200
- Solicitud: `format` y el periodo.
- Respuesta: el reporte propio para compartir con el equipo; solo contiene datos del paciente autenticado.
- Errores: C1, C3, C4.

#### `POST /reports/clinic`
- Operación: `create_clinic_report` · Permiso: `reports.generate_clinic` · Ruta: P · Trazabilidad: HU-48, RF-83 · Patrón: P02, P03, P20 · Éxito: 200
- Solicitud: `format` y el periodo.
- Respuesta: reporte agregado de la clínica (`ClinicReportCreator`), sin datos clínicos individuales.
- Errores: C1, C2, C4.

#### `GET /clinic-kpis`
- Operación: `get_clinic_kpis` · Permiso: `clinic_kpis.read` · Ruta: P · Trazabilidad: HU-48, RF-83 · Patrón: P10 · Éxito: 200
- Solicitud: `from`, `to` (periodo; por definir).
- Respuesta: pacientes por estado de cuenta, tasa de activación, adherencia y alertas abiertas. Ningún indicador identifica la glucosa o las dosis de un paciente; los conteos pequeños (propuesta: menos de 5) se agrupan.
- Errores: C1, C2, C4.

### 8.12 Mensajería y seguimiento (M11, Post-MVP)

La mensajería no es un canal de emergencias: toda respuesta del hilo lleva el aviso permanente de que no se usa para emergencias ni dosis urgentes (RF-85). Los mensajes son append-only. Solo los ven el paciente y su equipo asignado: un `CLINIC_ADMIN` recibe `403 FORBIDDEN` porque no tiene el permiso (la regla V8 habla de `404`, G28).

#### `GET /messages`
- Operación: `list_messages` · Permiso: `messages.use_own` o `messages.use_assigned` · Ruta: P · Trazabilidad: HU-49, RF-84, RF-85 · Patrón: P11, P09 · Éxito: 200
- Solicitud: `patient_id` (obligatorio para el médico; el paciente lee su propio hilo), `limit`, `cursor`.
- Respuesta: mensajes del hilo con `id`, `sender_role`, `body`, `sent_at` y `simulated`, más `emergency_notice` (el aviso de no emergencia). Escribe una fila `MESSAGES` en `audit.data_access_log` para el médico.
- Errores: C1, C2, C3, C4, C5 (hilo de un paciente no asignado responde `404`).

#### `POST /messages`
- Operación: `send_message` · Permiso: `messages.use_own` o `messages.use_assigned` · Ruta: P · Trazabilidad: HU-49, RF-84, RF-85 · Patrón: P07, P17 · Éxito: 201
- Solicitud: `body` (longitud de `FieldLimits`) y `patient_id` (solo médico).
- Respuesta: el mensaje y `alarm_keywords_detected` (propuesto): con palabras de alarma la app sugiere llamar a urgencias y el equipo recibe un aviso. El correo y el Web Push del aviso no llevan el texto del mensaje.
- Errores: C1, C2, C3, C4, C5; `429` (30 por minuto por usuario).

#### `POST /follow-ups`
- Operación: `create_follow_up` · Permiso: `follow_ups.manage` · Ruta: P · Trazabilidad: HU-50, RF-86 · Patrón: P11, P09 · Éxito: 201
- Solicitud: `patient_id` (asignado) y `scheduled_at` (fecha futura).
- Respuesta: el control con `id`, `status: SCHEDULED`, `scheduled_at` y `simulated`. El paciente lo ve y recibe un recordatorio antes de la fecha.
- Errores: C1, C2, C4 (una fecha pasada responde `422 VALIDATION_ERROR`), C5.

#### `GET /follow-ups`
- Operación: `list_follow_ups` · Permiso: `follow_ups.manage` o `follow_ups.read_own` · Ruta: P · Trazabilidad: HU-50, RF-86 · Patrón: P11 · Éxito: 200
- Solicitud: `status` (`SCHEDULED`, `DONE` o `MISSED`), `patient_id` (solo médico), `limit`, `cursor`.
- Respuesta: controles del médico (pacientes asignados) o del propio paciente.
- Errores: C1, C2, C3, C4.

#### `POST /follow-ups/{follow_up_id}/close`
- Operación: `close_follow_up` · Permiso: `follow_ups.manage` · Ruta: P · Trazabilidad: HU-50, RF-86, HU-43 · Patrón: P18 · Éxito: 200
- Solicitud: `outcome` (`DONE` o `MISSED`). Un control que pasa su fecha sin cerrarse queda `MISSED` por el planificador; el seguimiento alimenta el riesgo de abandono.
- Respuesta: el control con su estado final.
- Errores: C1, C2, C4, C5; `409 INVALID_STATE_TRANSITION` (ya cerrado).

### 8.13 Auditoría, consentimiento y privacidad (M12)

#### `GET /audit-log`
- Operación: `list_audit_log` · Permiso: `audit.read` · Ruta: P · Trazabilidad: HU-51, RF-88, RF-91 (Post-MVP) · Patrón: P09 · Éxito: 200
- Solicitud: `user_id`, `action`, `from`, `to`, `limit`, `cursor`.
- Respuesta: acciones de la clínica con `id`, `occurred_at`, `actor_user_id`, `actor_role`, `action`, `entity_type`, `entity_id`, `reason` y los **nombres** de los campos cambiados. Nunca valores de glucosa ni textos de notas.
- Errores: C1, C2, C4.

#### `GET /audit-log/data-access`
- Operación: `list_data_access_log` · Permiso: `audit.read` · Ruta: P · Trazabilidad: HU-51, RF-89, RF-91 (Post-MVP) · Patrón: P09 · Éxito: 200
- Solicitud: `user_id`, `patient_id`, `resource_type`, `from`, `to`, `limit`, `cursor`.
- Respuesta: quién accedió, a qué paciente, qué recurso (`resource_type`), con qué resultado (`GRANTED` o `DENIED`) y propósito. Sin contenido clínico. La propia consulta no se audita como lectura clínica.
- Errores: C1, C2, C4.

#### `POST /audit-log/verifications`
- Operación: `verify_audit_chain` · Permiso: `audit.read` · Ruta: P · Trazabilidad: HU-51, RF-92 (Post-MVP) · Patrón: - · Éxito: 200
- Solicitud: sin cuerpo. Recalcula la cadena de hashes de la clínica (`audit.verify_chain`).
- Respuesta: `is_valid` y, si falla, `first_inconsistent_row_id`. Una discrepancia registra `AUDIT_CHAIN_BROKEN` (crítico).
- Errores: C1, C2.

#### `GET /security-events`
- Operación: `list_security_events` · Permiso: `audit.read` o `audit.read_platform` · Ruta: P · Trazabilidad: HU-51, RF-95 · Patrón: - · Éxito: 200
- Solicitud: `type`, `severity`, `from`, `to`, `limit`, `cursor`. `audit.read` ve los de su clínica; `audit.read_platform` ve los de la plataforma.
- Respuesta: `id`, `type`, `severity`, `user_id`, `clinic_id`, `occurred_at` e `ip_truncated` (/24 en IPv4, /48 en IPv6). Nunca secretos ni la IP en claro.
- Errores: C1, C2, C4.

#### `GET /public/privacy-notices/{privacy_notice_version_id}`
- Operación: `get_privacy_notice` · Permiso: público · Ruta: P · Trazabilidad: HU-10, HU-52, RF-24, RF-90 · Patrón: - · Éxito: 200
- Solicitud: `privacy_notice_version_id` en la ruta (el que devuelve `POST /auth/activation/verify` o `GET /auth/current-user`).
- Respuesta: `id`, `version`, `published_at`, `text` (aviso de privacidad versionado y sin datos personales) y los alcances del consentimiento (tratamiento de datos sensibles, obligatorio; `ai_external_processing`, opcional).
- Errores: `404 NOT_FOUND`, `429`, `422`, `500`.

#### `GET /consents/own`
- Operación: `get_own_consent` · Permiso: `consents.manage_own` · Ruta: P · Trazabilidad: HU-52, RF-90 · Patrón: P11 · Éxito: 200
- Solicitud: sin parámetros. No exige consentimiento vigente.
- Respuesta: la versión aceptada, la fecha, los alcances aceptados, `current_version_id` y `consent_required`.
- Errores: C1, C3 sin `CONSENT_REQUIRED` (esta ruta está exenta).

#### `POST /consents/own/acceptances`
- Operación: `accept_consent` · Permiso: `consents.manage_own` · Ruta: P · Trazabilidad: HU-52, RF-90 · Patrón: P09 · Éxito: 201
- Solicitud: `privacy_notice_version_id`, `accepted` (debe ser `true`) y `ai_external_processing`. Se guarda con la versión, la fecha y el alcance.
- Respuesta: el consentimiento vigente. Una versión nueva obliga al paciente a aceptarla antes de seguir registrando.
- Errores: C1, C4; `409 CONSENT_VERSION_OUTDATED` (la versión ya no es la vigente).

#### `POST /consents/own/withdrawals`
- Operación: `withdraw_consent` · Permiso: `consents.manage_own` · Ruta: P · Trazabilidad: HU-52, RF-90 · Patrón: P09, P17 · Éxito: 200
- Solicitud: `scope` (el consentimiento de datos sensibles o solo `ai_external_processing`; valores por definir). Retirar el de datos sensibles detiene los registros nuevos (`403 CONSENT_REQUIRED` después) y la clínica recibe un aviso para tramitar la baja o la retención.
- Respuesta: el consentimiento con su estado.
- Errores: C1, C4.

#### `GET /consents`
- Operación: `list_consent_statuses` · Permiso: `consents.read_status` · Ruta: P · Trazabilidad: HU-52, RF-90 · Patrón: P09 · Éxito: 200
- Solicitud: `status` (valores por definir), `limit`, `cursor`.
- Respuesta: por paciente el estado del consentimiento y la versión aceptada. Sin contenido clínico. Escribe una fila `PATIENT_LIST` en `audit.data_access_log`.
- Errores: C1, C2, C4.

#### `POST /privacy-requests`
- Operación: `create_privacy_request` · Permiso: `privacy_requests.create_own` · Ruta: P · Trazabilidad: HU-53, RF-93 (Post-MVP) · Patrón: P18 · Éxito: 201
- Solicitud: `request_type` (`ACCESS`, `RECTIFICATION` o `ERASURE`) y una descripción opcional.
- Respuesta: `id`, `status` (valores por definir) y `due_at` (el plazo).
- Errores: C1, C3, C4.

#### `GET /privacy-requests`
- Operación: `list_privacy_requests` · Permiso: `privacy_requests.create_own` o `privacy_requests.manage` · Ruta: P · Trazabilidad: HU-53, RF-93 (Post-MVP) · Patrón: - · Éxito: 200
- Solicitud: `status`, `limit`, `cursor`. El paciente ve las suyas; el `CLINIC_ADMIN`, las de su clínica.
- Respuesta: solicitudes con estado y plazo, sin contenido clínico.
- Errores: C1, C2, C3, C4.

#### `POST /privacy-requests/{request_id}/resolve`
- Operación: `resolve_privacy_request` · Permiso: `privacy_requests.manage` · Ruta: P · Trazabilidad: HU-53, RF-93, RF-94 (Post-MVP) · Patrón: P13, P09 · Éxito: 200
- Solicitud: `decision` (aprobar o rechazar; valores por definir) y `note`.
- Respuesta: la solicitud con su estado.
- Errores: C1, C2, C4, C5; `409 INVALID_STATE_TRANSITION`.

#### `GET /privacy-requests/{request_id}/export`
- Operación: `export_privacy_request_data` · Permiso: `privacy_requests.create_own` · Ruta: P · Trazabilidad: HU-53, RF-93 (Post-MVP) · Patrón: P21, P09 · Éxito: 200
- Solicitud: `format` (`json` o `fhir`). Solo para la solicitud aprobada del propio paciente.
- Respuesta: los datos del paciente en JSON o FHIR, con el documento completo descifrado solo en esta exportación. Escribe filas `EXPORT` y `DECRYPT` en `audit.data_access_log`.
- Errores: C1, C3, C4, C5; `409 INVALID_STATE_TRANSITION` (la solicitud no está aprobada).

## 9. Trazabilidad

Todo endpoint del catálogo cita al menos una historia de usuario o un requisito. Todas las historias HU-01 a HU-55, HU-57 y los requisitos RF-01 a RF-101 tienen un endpoint o aparecen en esta sección, salvo los vacíos de la sección 10.

### 9.1 Capacidades que no tienen endpoint propio

Las atiende un proceso del sistema (evento, planificador o regla transversal) o un actor que no es esta API. Se listan para que nadie busque una ruta que no existe.

| Requisitos | Capacidad | Quién la atiende | Dónde se ve en la API |
|---|---|---|---|
| RF-04, RF-07, RF-14, RF-19, RF-21, RF-30, RF-33 | Política de contraseñas, permisos desde la BD, aislamiento por clínica, deduplicación por MRN, documento cifrado, proxy de asignación y validación en cadena | Reglas transversales (`PatientRecordAccessProxy`, RLS, `GlucoseReadingValidationHandler`) | Los códigos `403`, `404`, `409` y `422` de cada endpoint |
| RF-57, RF-58, RF-62, RF-63, RF-64 | Detección de hipoglucemia e hiperglucemia, reducción de la fatiga de alertas, aviso de adherencia y alerta predictiva | Suscriptores de eventos (`GlucoseReadingRecorded`) y planificador | Aparecen como alertas en `GET /alerts` y como notificaciones en `GET /notifications` |
| RF-60 | Escalamiento de una alerta sin reconocer | `AlertEscalationHandler` (P12) | `GET /alerts/{alert_id}` (historial) y `GET /alerts/summary`; reconocer la alerta lo detiene |
| RF-71 | Vencimiento (`EXPIRED`) de una recomendación y aplicación al plan | Planificador y `ApproveRecommendationCommand` | `GET /recommendations` (estado) |
| RF-74 | Cálculo del riesgo de abandono | Planificador y IA7 | `GET /dropout-risks` |
| RF-75, RF-76 | Seudonimización hacia la IA y respaldo determinista | `AiServiceClientAdapter`, `RemoteAiServiceProxy` | `is_fallback` y `fallback_reason` en las salidas de IA |
| RF-88, RF-89, RF-94, RF-95 | Cadena de hashes, auditoría de lecturas, retención y registro de eventos de seguridad | Triggers de la base de datos, `PhiAccessAuditDecorator`, jobs | `GET /audit-log`, `GET /audit-log/data-access` y `GET /security-events` los consultan |
| RF-96, RF-97 | Marca de datos simulados e importación de la clínica demo | Campo `simulated` en las respuestas; el importador real | Sección 1.2 y `POST /imports/fhir` |
| RF-98, HU-56 | Lecturas en vivo del simulador | `insumap-simulator` llama a `POST /readings` con tokens de paciente | `POST /readings` (misma validación y mismos límites que cualquier cliente) |
| RF-99, RF-100 | Escenarios y datasets de entrenamiento | `insumap-simulator` | Ninguna: son del simulador |
| RF-87 | Tareas de contacto por abandono | Sin permiso para el `CLINIC_ADMIN` en el catálogo | Vacío G29 |

### 9.2 Permisos sin endpoint

| Permiso | Motivo |
|---|---|
| `demo_data.manage` | Los documentos dicen que el backend no tiene rutas de simulación ([`Datos-simulados.md`](Datos-simulados.md), sección 11): la clínica demo se crea con `POST /clinics` (`is_demo`) y se llena por el importador real. "Reiniciar" la clínica demo no tiene ruta definida (G12). |

## 10. Vacíos y diferencias entre documentos y código

Cada fila es algo que falta o que no coincide. Esta tabla es la lista de trabajo pendiente de la Fase 0. **Usado aquí** es lo que este archivo asumió mientras no se decida.

| ID | Tema | Qué dicen las fuentes | Usado aquí | Quién lo resuelve |
|---|---|---|---|---|
| G1 | Nombre del `401` | El código define `UNAUTHENTICATED` (`ErrorCode` y la clave `unauthenticated`). `Seguridad.md`, `Actores-y-permisos.md`, las historias y `api-documentation.md` dicen `UNAUTHORIZED`. | `UNAUTHENTICATED` (es lo que ve el frontend generado). Alinear los otros documentos o renombrar el código antes de la fase 3. | Drako Salazar |
| G2 | Estado de `VALIDATION_ERROR` | Las historias de usuario dicen `400`. `Seguridad.md`, `Arquitectura.md`, `AGENTS.md` y el código dicen `422`. | `422` | Documentación de historias |
| G3 | Forma del cuerpo de error | Las historias (convenciones) dicen `{"error": {"code", "message", "details", "request_id"}}`. `AGENTS.md`, `Arquitectura.md` y el código dicen `detail` y el `request_id` solo en la cabecera `X-Request-ID`. | `detail` y cabecera | Documentación de historias |
| G4 | Elemento de `detail.errors` | El código emite `field` y `type`. `api-documentation.md` propone `field` y `message`. `Seguridad.md` (decisión 17) propone agregar `code`. | Se documenta lo que emite el código | Drako Salazar (cambio en `api.errors` y en la guía) |
| G5 | Tamaño del cuerpo | `Seguridad.md` dice 64 KiB (`BODY_MAX_BYTES`), `Arquitectura.md` usa `MAX_JSON_BODY_BYTES` y el código usa `MAX_REQUEST_BODY_BYTES` de 1 MiB. Los límites de importación (hasta 10 MiB) y de lotes superan el global, y `BodySizeLimitMiddleware` hoy los bloquearía. | 1 MiB global y excepción por ruta para importaciones y lotes | Drako Salazar |
| G6 | Marca de datos simulados | `RF-96` y `HU-55`: `simulated: true`. `Arquitectura.md`: `data_source = "SIMULATED"`. `Datos-simulados.md`: `is_demo` y el texto "Datos simulados". | `simulated` en toda respuesta; `is_demo` en la clínica; `data_source` solo se menciona en el expediente. Elegir uno. | Nicolas Diaz |
| G7 | Campos de una lectura de glucosa | `Arquitectura.md` (paso 4) usa `value` y `unit`. El ejemplo de `api-documentation.md` usa `value_mg_dl`. HU-15 exige aceptar mmol/L. | Entrada `value` y `unit`; salida `value_mg_dl` | Nicolas Mora |
| G8 | Enumeraciones sin definir | Contexto de la glucosa (RF-31 lista valores sueltos), tipo de comida, tipo e intensidad de la actividad y tipo de recordatorio. Solo `FASTING` y `POST_MEAL` aparecen en `Metricas-clinicas.md`. | "Por definir" | Nicolas Mora |
| G9 | Idempotencia y `Idempotency-Key` | La política de CORS permite la cabecera `Idempotency-Key`, pero ningún documento define un endpoint que la use. Solo las lecturas de glucosa tienen identificador de cliente (`client_reading_id`). RNF-11 pide registrar sin conexión todo (insulina, comidas, actividad, síntomas) y RNF-20 pide idempotencia por UUID de cliente. El lote offline (RF-32) cubre solo lecturas. | Sin `Idempotency-Key`; lote solo de lecturas; los demás `POST` no son idempotentes | Nicolas Mora |
| G10 | Catálogos | `Actores-y-permisos.md` (3.1) menciona "catálogos" que solo exigen sesión, pero no hay rutas: productos de insulina (P23), lista de síntomas y síntomas de alarma, tipos de comida y de actividad, motivos de rechazo de recomendaciones. | Sin endpoints de catálogo; los valores salen del esquema OpenAPI hasta que se definan | Nicolas Mora |
| G11 | Hoja de activación y entrega | `Seguridad.md` dice que la hoja PDF o HTML sale en la respuesta de la emisión y que la JSON es solo para clínicas demo, pero no dice cómo se pide cada formato ni los valores de `delivery_status`. No dice si en el canal `EMAIL` el código vuelve al administrador. | `PRINT` devuelve el código; `EMAIL` no. Formato por definir. | Drako Salazar |
| G12 | Datos demo y simulador | `demo_data.manage` (crear, reiniciar e importar datos demo) no tiene endpoint, y `Datos-simulados.md` dice que no hay rutas de simulación. HU-56 exige `403` a un token de una clínica no demo, pero ningún documento dice cómo el backend sabe que quien envía es el simulador. | Sin endpoint; `GET /clinics/current` expone `is_demo` | Nicolas Mora y Drako Salazar |
| G13 | Ciclo de vida del personal | No hay requisito para reactivar personal desactivado, reemitir la invitación de personal que venció a los 7 días, cambiar el rol de un usuario ni nada que use `/memberships` (prefijo propuesto en `api-documentation.md`). Seguridad registra `ROLE_CHANGED` y `tv + 1` en un cambio de rol, sin endpoint. La ruta del restablecimiento de MFA tampoco está fijada. | No se agregan esos endpoints. `/memberships` queda sin uso. | Nicolas Diaz |
| G14 | Sesión al restablecer la contraseña | `Seguridad.md` (sección 5) dice que el cambio o el restablecimiento le da al dispositivo actual una sesión nueva. Para el restablecimiento sin sesión previa eso saltaría el MFA del personal. | `password-reset/complete` responde `204` y exige iniciar sesión | Drako Salazar |
| G15 | Permisos que ninguna acción nombra | Descartar un hallazgo de IA (HU-38), marcar un paciente como revisado (RF-79), leer planes y notas del paciente asignado por el médico, leer los resultados de HbA1c propios, listar sedes. Ninguna tiene un código en el catálogo. | Se reutiliza el permiso más cercano (`ai.risk.read_assigned`, `dashboard.read_assigned`, `treatment_plans.manage`, `clinical_notes.manage`, `records.read_own`, `sites.manage`). Agregar los códigos en `Actores-y-permisos.md` y como semilla en `insumap-database`. | Drako Salazar |
| G16 | Contenido interno sin definir | Estructura de plantillas y planes, nodos del árbol de reglas, estados de lote y de fila de importación (solo `SKIPPED_DUPLICATE`), columnas del CSV de pacientes, resultado por paciente en el lote de credenciales, periodo de los reportes, código de error de un Bundle `SIMULATED` en una clínica no demo y de un Bundle sin la marca, y códigos de cada invariante de un plan. | "Por definir" | Drako Salazar |
| G17 | Activación del personal y del simulador | `Seguridad.md` dice que el personal no da fecha de nacimiento; `POST /auth/activation/verify` la pide a los pacientes. `Datos-simulados.md` (8.3) dice que el simulador activa con MRN y código, y `Seguridad.md` (decisión 6) lo cambia a código y fecha de nacimiento. El simulador renueva sesión con la cookie y `X-Requested-With`, que `Datos-simulados.md` no menciona. El frontend necesita saber si pedir el correo (`email_required`, propuesto). | `birth_date` solo para pacientes; ver `Seguridad.md` decisión 6 | Nicolas Mora |
| G18 | Reutilización de un refresh | `HU-03` dice `401 UNAUTHORIZED`; `Seguridad.md` (decisión 3) y `testing-plan.md` dicen `401 SESSION_REVOKED`. | `SESSION_REVOKED` | Documentación de historias |
| G19 | Recomendaciones: `APPLIED` y falta de IA | RF-71 y `Modulo-IA.md` dicen que aprobar crea una versión `DRAFT` y que `APPLIED` ocurre al crearla, mientras HU-39 solo dice `APPROVED`. HU-40 pide informar el motivo cuando la IA no genera sugerencias, sin campo definido. Un vencimiento (`EXPIRED`) decidido responde `409 INVALID_STATE_TRANSITION` por analogía. | `status` de la aprobación más `draft_plan_id`; `unavailable_reason` propuesto | Nicolas Mora |
| G20 | Errores de una lectura | HU-15 llama `VALIDATION_ERROR` a la fecha futura; `Arquitectura.md` usa `READING_IN_FUTURE` y `READING_TOO_OLD`. `api-documentation.md` da `DUPLICATE_READING` como ejemplo de `409`, y `Arquitectura.md` responde `409 CONFLICT`. El mensaje de `GLUCOSE_OUT_OF_RANGE` difiere entre `api-documentation.md` y `Arquitectura.md`. | Códigos de `Arquitectura.md`; mensaje de `Arquitectura.md` | Nicolas Mora |
| G21 | Salud | `Seguridad.md` dice que `/health` devuelve `{"status": "ok"}` sin consultar la base de datos; RNF-18 pide el estado de la BD y la IA. `GET /ready` (código) no está en ningún documento de diseño. | Como el código: `/health` (vida) y `/ready` (disponibilidad con `503`) | Nicolas Diaz |
| G22 | `X-Request-ID` | `Arquitectura.md` y `Contrato-IA.md` escriben `X-Request-Id`; `Seguridad.md` y el código `X-Request-ID`. `Seguridad.md` (sección 11) acepta solo UUID; el código acepta cualquier valor de 1 a 64 caracteres `[A-Za-z0-9._-]`. | Como el código | Drako Salazar |
| G23 | Paginación | Solo `api-documentation.md` define `limit`, `cursor`, `items` y `next_cursor`. No hay convención de orden ni de filtros. | Se aplica a todos los listados; el orden por defecto es el más reciente primero salvo el triage, que va por riesgo | Drako Salazar |
| G24 | Datos insuficientes en métricas | `Metricas-clinicas.md` (2.2) calcula igual y marca `LOW_CONFIDENCE`; RF-55 pide no mostrar un porcentaje engañoso. | La respuesta trae `is_sufficient` y `confidence`; el frontend decide qué mostrar | Drako Salazar |
| G25 | Documentos y campos que faltan | No existen `Modelo-de-datos.md`, `Diccionario-de-datos.md`, `Cumplimiento-y-privacidad.md`, `Plan-de-commits.md`, `Roles-y-planeacion.md`, `.agents/security.md`, `.agents/input-validation.md` ni `.agents/design-patterns.md`, así que no hay nombres de campo de perfil ni longitudes. `FieldLimits` implementa 7 constantes (los límites de notas, nombres y lotes de las políticas aún no están). La forma de `GET /meta/field-limits` y el contenido FHIR de la exportación no están definidos. | Nombres de campo propuestos en `snake_case`; longitudes "de `FieldLimits`" | Drako Salazar |
| G26 | CORS | `Seguridad.md` exige las cabeceras `X-Requested-With` e `Idempotency-Key` y exponer `Retry-After`. El código (`main.py`) permite solo `Authorization`, `Content-Type` y `X-Request-ID` y expone solo `X-Request-ID`. El refresh desde un navegador fallaría en el preflight. | Se documenta lo que exige la política | Drako Salazar |
| G27 | Textos y listas configurables por la clínica | HU-15 (aviso de acción inmediata ante hipoglucemia), RF-37 (síntomas de alarma configurados) y IA6 (material educativo aprobado) hablan de contenido configurado por la clínica, sin permiso ni endpoint para gestionarlo. | No se agregan endpoints | Nicolas Mora |
| G28 | `403` o `404` para mensajes y notas | `Actores-y-permisos.md` (V8) dice `404` para el administrador que lee mensajes o notas; HU-46 y HU-49 dicen `403`; `Seguridad.md` (6.5) decide `403` porque se decide antes de buscar el recurso. | `403 FORBIDDEN` | Documentación de actores |
| G29 | Tareas de contacto | RF-87 y HU-43 piden que la clínica cree tareas de contacto, pero `follow_ups.manage` es solo del médico y el `CLINIC_ADMIN` no tiene permiso para crearlas ni leerlas sin ver datos clínicos. | Sin endpoint | Nicolas Diaz |
| G30 | Lista del médico fuera del triage | El médico solo tiene `GET /dashboard/triage` como lista de sus pacientes. No hay búsqueda por nombre o MRN ni un listado simple de pacientes asignados. | Sin endpoint extra | Nicolas Diaz |
| G31 | Alerta por síntoma de alarma | HU-19 dice que un síntoma de alarma crea una alerta para el equipo, pero ningún documento define su `type`. | `GET /alerts` lista el `type` sin ese valor | Drako Salazar |
| G32 | Mensajes de error propuestos | Solo ocho códigos tienen mensaje en `messages_es.json`. Los de la sección 6.3 marcados "propuesto" son texto de este archivo. | Texto propuesto | Drako Salazar |
| G33 | Pronóstico: lectura o llamada | `Modulo-IA.md` (sección 14) muestra que `GET /patients/{id}/forecast` llama a la IA por el proxy y guarda el resultado. `Arquitectura.md` dice que leer el expediente no llama a la IA y que el pronóstico se refresca como máximo una vez por intervalo tras una lectura. | `GET .../forecast` pasa por `RemoteAiServiceProxy` (con respaldo); `overview` devuelve el último guardado | Nicolas Mora |
