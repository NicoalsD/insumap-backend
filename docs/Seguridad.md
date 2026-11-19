# Seguridad

Esta es la política global de seguridad de Insumap. Aplica a los cinco repositorios: [`insumap-backend`](https://github.com/NicoalsD/insumap-backend), [`insumap-database`](https://github.com/NicoalsD/insumap-database), [`insumap-frontend`](https://github.com/NicoalsD/insumap-frontend), [`insumap-ai`](https://github.com/NicoalsD/insumap-ai) e [`insumap-simulator`](https://github.com/NicoalsD/insumap-simulator). Cuando una regla es específica de un repositorio, se indica.

Responsables:
- **Drako Salazar (`Drako2305`):** líder de seguridad. Responde por el backend y la base de datos.
- **Nicolas Diaz (`NicoalsD`):** responde por el frontend, la CI, el despliegue y los secretos de las plataformas.
- **Nicolas Mora (`nicomora70`):** responde por `insumap-ai`, el canal hacia el LLM y el simulador.

Las cifras de este documento son canónicas. Lo que no aparece aquí está marcado como "por definir", "verificar" o "propuesta", y nadie lo implementa con un valor inventado.

Documentos relacionados:
- El marco legal (Ley 1581 de 2012, Decreto 1377 de 2013, historia clínica e interoperabilidad) vive en [`Cumplimiento-y-privacidad.md`](Cumplimiento-y-privacidad.md). Este documento lo enlaza y no lo repite.
- Los permisos y la matriz por rol están en [`Actores-y-permisos.md`](Actores-y-permisos.md).
- La implementación en Python está en [`.agents/security.md`](../.agents/security.md) y la tabla de entradas en [`.agents/input-validation.md`](../.agents/input-validation.md).

> **Aviso:** Insumap es un proyecto académico. No es un dispositivo médico y la IA solo apoya al médico. Todos los pacientes son simulados. Aun así, los controles se diseñan como si los datos fueran reales, porque los datos de salud son **datos sensibles**.

## 1. Modelo de amenazas

### 1.1 Activos

| Activo | Por qué importa | Clase (sección 1.2) |
|---|---|---|
| Registros clínicos: glucosa, insulina, comidas, actividad, síntomas y HbA1c | Datos sensibles de salud. Su fuga o alteración daña al paciente | H |
| Planes de tratamiento, notas clínicas, alertas y mensajes médico-paciente | Decisiones clínicas y comunicación privada | H |
| Salidas de la IA y decisiones del médico sobre ellas | Trazabilidad de cada decisión clínica apoyada por IA | H |
| Identidad del paciente: nombres, documento, número de historia (MRN), fecha de nacimiento, correo y teléfono | Datos personales que reidentifican los datos clínicos | C (documento cifrado: H) |
| Cuentas del personal (`CLINIC_ADMIN`, `DOCTOR`, `PLATFORM_ADMIN`) | Un médico ve a todos sus pacientes. Un admin emite credenciales | S (hashes) |
| Códigos de activación, refresh tokens, secretos TOTP y códigos de respaldo | Dan acceso directo a una cuenta | S |
| Auditoría (`audit.audit_log`, `audit.data_access_log`) e `iam.security_events` | Prueban quién vio o cambió qué y cuándo | C e I |
| Llaves y secretos de la plataforma (JWT, AES, HMAC, token de la IA, credenciales de BD, SMTP, VAPID, LLM) | Su filtración rompe todos los demás controles | S |
| Aislamiento entre clínicas (*tenants*) | Una clínica nunca ve los datos de otra | I |

### 1.2 Clasificación de datos

| Clase | Significado | Ejemplos |
|---|---|---|
| P (pública) | Se puede ver sin iniciar sesión | `GET /api/v1/meta/field-limits`, textos legales publicados, nombre de la clínica en la pantalla de activación |
| I (interna) | Configuración y datos operativos sin datos personales | Catálogos, perfiles de metas, reglas de alerta, versiones de modelos |
| C (personal) | Dato personal que no es de salud | `given_name`, `family_name`, `email`, `phone`, `mrn`, `birth_date`, `document_last4`, `ip_truncated`, `ip_hmac` |
| H (salud, sensible) | Dato de salud o que revela una condición de salud | Todas las tablas de `monitoring`, `care` y `ai` con `patient_id`, `alerts.alerts`, `messaging.messages`, diagnósticos importados, `document_ciphertext` |
| S (secreta) | Material de credenciales o llaves. Nunca se lee salvo para verificar | `password_hash`, `token_hash`, `code_hash`, `secret_ciphertext` de MFA, llaves en variables de entorno |

Reglas que dependen de la clase:

1. **S** nunca aparece en logs, respuestas, `detail` de errores, exportaciones ni para `insumap_readonly`.
2. **H** solo lo lee el propio paciente o un médico de su equipo de atención (sección 6.3). Cada lectura queda en `audit.data_access_log` (sección 7.1). Nunca sale hacia `insumap-ai` con identificadores directos (sección 9) ni aparece en logs, correos o notificaciones push.
3. **C** lo ve el personal de la clínica que lo necesita (sección 6.4). Nunca sale hacia `insumap-ai` ni hacia el LLM.
4. Toda columna nueva se clasifica en el [diccionario de datos](Diccionario-de-datos.md). Una columna sin clase no se integra.

### 1.3 Actores maliciosos

| Actor | Motivación | Capacidad |
|---|---|---|
| Atacante externo anónimo | Robar datos de salud, extorsión, vandalismo | Internet, la API pública, listas de contraseñas filtradas |
| Paciente curioso o malicioso | Ver datos de otro paciente o alterar los propios para engañar al médico | Credenciales propias y herramientas del navegador |
| Médico fuera del equipo de atención | Ver pacientes que no le asignaron | Credenciales válidas de `DOCTOR` en la misma clínica |
| Admin de clínica | Leer detalle clínico que no le corresponde | Credenciales de `CLINIC_ADMIN` y conocimiento de los pacientes |
| Usuario de otra clínica | Cruzar datos entre *tenants* | Credenciales válidas en su clínica |
| Quien obtiene una hoja de activación | Activar la cuenta de otro paciente | La hoja impresa o el correo de invitación |
| Proveedor del LLM o atacante en ese canal | Entrenar con los datos o reidentificar pacientes | Todo lo que el backend le envíe al servicio de IA |
| Atacante con acceso a la BD o a un respaldo | Leer datos sin pasar por la aplicación | Credenciales de BD filtradas o un volcado |
| Atacante en la cadena de suministro | Insertar código o robar secretos | Dependencias, GitHub Actions y repositorios públicos |

### 1.4 Superficies

| Superficie | Repositorio | Quién llega |
|---|---|---|
| Autenticación, activación y MFA (`/api/v1/auth/*`) | backend, frontend | Cualquiera en internet |
| API autenticada (`/api/v1/*`) | backend, frontend, simulador (modo `live`) | Usuarios con JWT |
| Importación FHIR y CSV | backend | `CLINIC_ADMIN` |
| Servicio de IA | `insumap-ai` | Solo el backend, con token de servicio |
| Proveedor del LLM | `insumap-ai` | Solo `insumap-ai`, con datos minimizados |
| Notificaciones (SMTP, Web Push e in-app) | backend | El backend envía; el navegador registra endpoints de push |
| Base de datos (Neon, PostgreSQL 18) | database, backend | `insumap_app`, `insumap_migrator` e `insumap_readonly` |
| PWA y almacenamiento local del navegador | frontend | El dispositivo del paciente |
| CI, dependencias y secretos | los cinco | El equipo y GitHub Actions |

### 1.5 STRIDE

S: suplantación, T: alteración, R: repudio, I: divulgación, D: denegación de servicio, E: elevación de privilegios.

| Componente | STRIDE | Amenaza | Control principal | Sección |
|---|---|---|---|---|
| Datos de salud | S | Robo de la cuenta de un paciente o un médico | Argon2id, bloqueo por cuenta e IP, MFA del personal, refresh rotativo con detección de reutilización | 2, 4 |
| Datos de salud | T | Alterar lecturas o planes de otro, o borrar historia | Permisos desde BD, proxy de equipo de atención, tablas append-only con correcciones y auditoría | 6, 7 |
| Datos de salud | R | Un médico niega haber visto o aprobado algo | `audit.data_access_log` por cada lectura y `audit.audit_log` con cadena de hashes; las decisiones guardan motivo | 7 |
| Datos de salud | I | Fuga por logs, caché del navegador o de proxies, o notificaciones en la pantalla bloqueada | Filtro de redacción, `Cache-Control: no-store`, el service worker no cachea `/api`, push y correo sin valores clínicos | 11, 13 |
| Datos de salud | I | Robo de la BD o de un respaldo | Documento cifrado con AES-256-GCM, credenciales solo como hash, llaves fuera de la BD | 8, 16 |
| Datos de salud | D | Cuerpos enormes, JSON profundo o abuso del costo de Argon2id | Límites de cuerpo y profundidad, límites de tasa, concurrencia acotada del hash | 2.1, 12, 13.3 |
| Datos de salud | E | El admin de clínica lee detalle clínico | El rol no tiene permisos clínicos; el proxy solo le da la vista administrativa; RLS por rol en los esquemas clínicos (propuesta) | 6.4 |
| Multi-tenant | S | Petición con un `clinic_id` manipulado | El `clinic_id` sale solo del JWT firmado, nunca de la ruta, el cuerpo ni una cabecera | 6.2 |
| Multi-tenant | T | Insertar o mover filas a otra clínica | RLS con `USING` y `WITH CHECK`, `FORCE ROW LEVEL SECURITY` | 6.2 |
| Multi-tenant | I | Enumerar pacientes de otra clínica por UUID | RLS y respuesta `404`, igual que un recurso inexistente | 6.5 |
| Multi-tenant | I | Cruzar personas entre clínicas por el hash del documento | El HMAC del documento incluye el `clinic_id` | 8.1 |
| Multi-tenant | E | Una conexión del pool conserva el contexto de la petición anterior | `set_config(..., true)` (equivale a `SET LOCAL`) dentro de cada transacción; sin contexto no hay filas | 6.2 |
| Multi-tenant | E | Un médico no asignado abre un expediente | `PatientRecordAccessProxy` (P11) y respuesta `404` | 6.3 |
| Multi-tenant | D | Una clínica agota recursos con importaciones o emisiones masivas | Límites de tasa por clínica | 12 |
| Activación | S | Activar la cuenta de otro con una hoja robada o un código adivinado | Código de 80 bits, fecha de nacimiento como segundo dato, intentos limitados, expiración de 7 días | 3 |
| Activación | I | Oráculo que distingue un código vencido, usado o incorrecto | Un solo error genérico, `410 INVITATION_INVALID` | 3.5 |
| Activación | I | El código queda en logs, en el historial o en el `Referer` | El código viaja en el fragmento de la URL (`#`), con `no-store`, y nunca se registra | 3.3 |
| Importación | T | Archivo FHIR o CSV malicioso (XXE, profundidad, fórmulas, tamaño) | Solo JSON y CSV en UTF-8, sin XML, límites de bytes, filas y profundidad; cada fila pasa la misma validación que la API | 13.3 |
| Canal IA y LLM | I | El proveedor del LLM recibe identificadores o entrena con los datos | `subject_ref` seudónimo, sin nombres, documentos ni contacto; la capa gratuita solo recibe datos simulados o seudonimizados | 9 |
| Canal IA y LLM | T | Inyección de prompt en el texto del paciente, incluido texto invisible (caracteres *tag* Unicode) | Rechazo de caracteres de formato, redacción, guardrails; el LLM no tiene herramientas ni acceso a la BD | 9 |
| Canal IA y LLM | I | Exfiltración por imágenes o enlaces Markdown en la salida del LLM | La salida se muestra como texto plano, sin imágenes ni enlaces externos | 9 |
| Canal IA y LLM | S | Un tercero llama al servicio de IA | Token de servicio de 32 bytes o más, comparado en tiempo constante | 10 |
| Canal IA y LLM | T | Respuesta falsa o malformada del servicio de IA | Validación estricta de la respuesta, circuit breaker y respaldo determinista | 10 |
| Canal IA y LLM | E | La IA entrega una dosis al paciente | La IA nunca da dosis; IA4 es solo una propuesta que el médico aprueba; guardrails en IA6 | 9 |
| Canal IA y LLM | R | Una recomendación sin trazabilidad | Versión del modelo, explicación y decisión del médico guardadas en `ai` | 7 |
| Notificaciones | I | SSRF a través del endpoint de Web Push que registra el navegador | Lista de hosts permitidos, solo HTTPS, sin IP literales ni redirecciones | 13.4 |
| Cadena de suministro | T | Dependencia o Action maliciosa | `uv.lock`, `pip-audit`, Dependabot, CodeQL, Actions fijadas a SHA | 15 |
| Cadena de suministro | I | Secretos en git | Gitleaks, secret scanning con push protection, `.env.example` con marcadores | 14, 15 |

## 2. Autenticación

### 2.1 Contraseñas

| Parámetro | Valor canónico | Variable o constante |
|---|---|---|
| Algoritmo | Argon2id con `argon2-cffi` (`PasswordHasher`, `Type.ID`) | No aplica |
| Memoria (`memory_cost`) | 19.456 KiB (19 MiB) | `ARGON2_MEMORY_KIB` |
| Iteraciones (`time_cost`) | 2 | `ARGON2_TIME_COST` |
| Paralelismo (`parallelism`) | 1 | `ARGON2_PARALLELISM` |
| Sal | 16 bytes aleatorios | No configurable |
| Hash | 32 bytes, en formato PHC (`$argon2id$v=19$m=19456,t=2,p=1$...`) en `iam.users.password_hash` | No configurable |
| Rehash | Al iniciar sesión, si `check_needs_rehash` indica que los parámetros cambiaron | No aplica |
| Concurrencia | 4 hashes simultáneos como máximo por proceso (19 MiB × 4 = 76 MiB de pico) | `PASSWORD_HASH_MAX_CONCURRENCY` |
| Longitud | 12 a 128 puntos de código Unicode después de normalizar con NFKC | `FieldLimits.PASSWORD_MIN_LENGTH`, `PASSWORD_MAX_LENGTH` |
| Composición | Sin reglas de mayúsculas, números ni símbolos | No aplica |
| Rechazadas | Las de la lista local de contraseñas comunes; las que contienen la parte local del correo, el nombre, el apellido o el número de documento (fragmentos de 4 caracteres o más) | No aplica |
| Historial | Las últimas 5 no se pueden reutilizar (`iam.password_history`) | `PASSWORD_HISTORY_SIZE` |
| Contraseñas temporales | No existen. Toda cuenta nace con un código de activación (sección 3) | No aplica |

Decisiones:

- **Parámetros.** `m=19456, t=2, p=1` es la configuración mínima que recomienda la OWASP Password Storage Cheat Sheet para Argon2id. No se usa el perfil por defecto de `argon2-cffi` (64 MiB y `p=4`) porque el plan gratuito de Render tiene poca memoria y varios logins simultáneos la agotarían. La cota de concurrencia evita que una ráfaga de logins se convierta en una denegación de servicio por memoria. El hash corre en un hilo aparte (`anyio.to_thread.run_sync` con `CapacityLimiter`), nunca en el *event loop*. En el perfil de pruebas se usan parámetros bajos ([`testing-plan.md`](../.agents/testing-plan.md)).
- **Lista de comunes.** Son 100.000 contraseñas de una lista pública con licencia compatible. La propuesta es SecLists (MIT); hay que verificar el archivo exacto y la licencia al integrarla. Se comparan después de NFKC y `casefold()`. El archivo vive en el paquete, no se descarga en tiempo de ejecución.
- **Hash, no cifrado.** Un hash es de una sola vía: nadie puede recuperar la contraseña, ni siquiera el equipo. Si alguien la olvida, recibe un enlace o código de restablecimiento de un solo uso (sección 3.6). En cambio, el secreto TOTP sí se cifra (sección 4), porque el sistema necesita leerlo.
- **Errores.** Una contraseña nueva que no cumple la política responde `422 VALIDATION_ERROR`, con el motivo en `detail.errors[].code`: `PASSWORD_TOO_SHORT`, `PASSWORD_TOO_LONG`, `PASSWORD_TOO_COMMON`, `PASSWORD_CONTAINS_PERSONAL_DATA` o `PASSWORD_REUSED`. En el login, una contraseña de más de 128 caracteres se rechaza con `422` antes de calcular el hash.
- Las contraseñas nunca aparecen en logs, respuestas, URLs ni `detail`.

### 2.2 Login, enumeración y bloqueo

1. **Identificador:** el correo (`iam.users.email`, único en toda la plataforma). Se normaliza con NFKC, se recorta y se pasa a minúsculas.
2. **Mensaje genérico:** un correo o una contraseña incorrectos responden `401 INVALID_CREDENTIALS` con el mensaje "Usuario o contraseña incorrectos". El mensaje no revela si el correo existe ni qué campo falló.
3. **Tiempo constante:** si el correo no existe, la contraseña se verifica contra un hash señuelo (`DecoyPasswordHash`), calculado al arrancar con los mismos parámetros. Siempre se calcula exactamente un Argon2id por intento.
4. **Cuenta o clínica inactiva:** solo después de verificar una contraseña correcta se informa el motivo:
   - Cuenta `SUSPENDED` o `DEACTIVATED`, o personal con `is_active = false`: `403 ACCOUNT_NOT_ACTIVE`.
   - Clínica suspendida: `403 CLINIC_SUSPENDED`.

   Revelarlo ahí no filtra nada, porque quien pregunta ya probó conocer la contraseña. Una cuenta `IMPORTED` o `INVITED` no tiene contraseña, así que responde `INVALID_CREDENTIALS`.
5. **Bloqueo por pareja (correo, IP):** 5 fallos consecutivos de la misma pareja en 15 minutos la bloquean 15 minutos. Cada nivel duplica el bloqueo, hasta 24 horas. Un ingreso exitoso reinicia el contador y el nivel.
6. **Bloqueo global del correo:** 20 fallos en 60 minutos desde cualquier IP bloquean el correo 60 minutos.
   - Se registra `ACCOUNT_LOCKED` (severidad alta).
   - Si la cuenta existe y su correo está verificado, el titular recibe un aviso.
   - Un `CLINIC_ADMIN` puede desbloquear antes (`POST /api/v1/users/{user_id}/unlock`, auditado).
7. **Respuesta durante un bloqueo:** `429 RATE_LIMITED` con la cabecera `Retry-After`, sin verificar la contraseña. Los contadores se guardan por HMAC del correo normalizado, **exista o no la cuenta**. Así el `429` aparece igual para un correo inexistente y no sirve para enumerar.
8. **Por qué dos niveles:** en un hospital, decenas de personas salen a internet por la misma IP (NAT), y un bloqueo solo por IP las bloquearía a todas. El bloqueo por pareja frena al atacante sin bloquear a la víctima desde sus otras redes. El bloqueo global frena los ataques distribuidos. Así un atacante tampoco puede dejar sin acceso a un médico desde una sola IP.
9. **Registro:** cada intento queda en `iam.login_attempts`, con `user_id` (si existe), `ip_hmac` (nunca la IP en claro), resultado y motivo (`INVALID_CREDENTIALS`, `LOCKED`, `NOT_ACTIVE`, `RATE_LIMITED`, `MFA_FAILED`). Esa escritura va en una transacción propia, que se confirma aunque la petición falle.

| Parámetro | Valor | Variable |
|---|---|---|
| Fallos por pareja (correo, IP) | 5 en 15 minutos | `LOGIN_PAIR_MAX_FAILURES`, `LOGIN_FAILURE_WINDOW_MINUTES` |
| Bloqueo base de la pareja | 15 minutos, ×2 por nivel, tope de 24 horas | `LOGIN_LOCK_BASE_MINUTES`, `LOGIN_LOCK_MAX_HOURS` |
| Fallos globales por correo | 20 en 60 minutos | `LOGIN_ACCOUNT_MAX_FAILURES`, `LOGIN_ACCOUNT_WINDOW_MINUTES` |
| Bloqueo global del correo | 60 minutos | `LOGIN_ACCOUNT_LOCK_MINUTES` |
| Tasa de login por IP | Sección 12 | `RATE_LIMIT_LOGIN_PER_IP_PER_MINUTE` |

### 2.3 Access token (JWT)

| Aspecto | Valor canónico |
|---|---|
| Algoritmo | HS256, con PyJWT. Al validar se pasa `algorithms=["HS256"]`; se rechazan `none` y cualquier otro |
| Llave | `JWT_SECRET`: 32 bytes o más después de decodificar. Una llave más corta impide el arranque |
| Rotación | La cabecera `kid` lleva la huella de la llave (sección 8.3). Durante una rotación, `JWT_SECRET_PREVIOUS` solo verifica, nunca firma |
| Duración | 15 minutos (`JWT_ACCESS_MINUTES=15`) |
| Tolerancia de reloj | 30 segundos para `exp`, `nbf` e `iat` (`JWT_LEEWAY_SECONDS`) |
| Claims obligatorios | `iss` (`JWT_ISSUER`), `aud` (`JWT_AUDIENCE`), `sub` (UUID del usuario), `role`, `clinic_id` (UUID; `null` solo para `PLATFORM_ADMIN`), `tv` (token_version), `sid` (id de la familia de refresh; `null` en la sesión de enrolamiento), `amr`, `jti`, `iat`, `nbf`, `exp` |
| `amr` | `["pwd"]` para pacientes y para el personal que aún no enroló MFA; `["pwd", "otp"]` para el personal con MFA verificado |
| Personal sin `"otp"` | Solo puede llamar a `/auth/mfa/enrollment*`, `GET /auth/current-user` y `/auth/logout`. Cualquier otra ruta responde `403 MFA_REQUIRED` |
| Verificación por petición | En la misma transacción de la petición: `iam.users.status = 'ACTIVE'` (o `is_active` para el personal), `token_version = tv` y clínica activa. Si no se cumple: `401 SESSION_REVOKED` (o `403 CLINIC_SUSPENDED` si la clínica está suspendida) |
| Token inválido | Ausente, mal formado, firma o `alg` incorrectos, `iss` o `aud` ajenos, vencido: `401 UNAUTHORIZED` |
| Cabecera | `Authorization: Bearer <jwt>`. Si mide más de 2.048 bytes (`FieldLimits.AUTH_HEADER_MAX_BYTES`), se rechaza antes de decodificar |
| Almacenamiento en el cliente | Solo en memoria del frontend. Nunca en `localStorage`, `sessionStorage`, IndexedDB ni cookies |

Los permisos **no** van en el token: se leen de la BD (sección 6.1) y `GET /api/v1/auth/current-user` los devuelve al frontend. La consulta de `tv` en cada petición es una lectura por clave primaria. Se acepta su costo porque permite cortar de inmediato una sesión robada o una cuenta suspendida.

### 2.4 Refresh token y cookie

- **Formato:** opaco, de 256 bits aleatorios (`secrets.token_urlsafe(32)`, 43 caracteres base64url).
- **Almacenamiento:** la BD guarda solo su SHA-256 en hexadecimal (`iam.refresh_tokens.token_hash`). Como el token tiene 256 bits, SHA-256 basta; no hace falta un hash lento ni una llave.
- **Familia:** cada login crea una familia (`family_id`, que viaja como `sid` en el JWT). Cada uso del refresh emite uno nuevo en la misma familia, revoca el anterior (`revoked_reason = 'ROTATED'`) y enlaza `replaced_by_id`.
- **Reutilización:** si llega un token ya revocado:
  - Se revoca toda la familia (`REUSE_DETECTED`).
  - Se incrementa `token_version`, así que los access tokens vigentes mueren.
  - Se registra `REFRESH_TOKEN_REUSE_DETECTED` con severidad alta.
  - Se responde `401 SESSION_REVOKED`.

  Las demás sesiones legítimas del usuario se recuperan solas con su propio refresh.
- **Token desconocido o vencido:** `401 UNAUTHORIZED`, sin más detalle.
- **Sin ventana de gracia:** el servidor es estricto. El frontend serializa el refresh entre pestañas con la Web Locks API (`navigator.locks.request("insumap-refresh", ...)`), para no disparar una falsa detección de reutilización.
- **Rotación atómica:** el token se marca como rotado con un `UPDATE ... WHERE revoked_at IS NULL RETURNING`. Dos peticiones simultáneas no pueden rotar el mismo token (algoritmo en [`.agents/security.md`](../.agents/security.md), sección 5).

| Población | Vida de cada refresh token (inactividad máxima) | Vida absoluta de la familia | Variables |
|---|---|---|---|
| `PATIENT` | **30 días** | 90 días | `REFRESH_TOKEN_DAYS=30`, `REFRESH_FAMILY_MAX_DAYS=90` |
| Personal (`CLINIC_ADMIN`, `DOCTOR`, `PLATFORM_ADMIN`) | 12 horas | 12 horas (un turno), luego login con MFA | `REFRESH_TOKEN_STAFF_HOURS=12` |

`REFRESH_TOKEN_DAYS`, la variable que [`.agents/configuration.md`](../.agents/configuration.md) dejó pendiente, vale **30**.

Cookie del refresh:

```text
Set-Cookie: __Secure-insumap_rt=<token>; HttpOnly; Secure; SameSite=Strict; Path=/api/v1/auth; Max-Age=<vida del token en segundos>
```

- Sin atributo `Domain`. El prefijo `__Secure-` obliga al navegador a exigir `Secure`. No se usa `__Host-` porque ese prefijo exige `Path=/`.
- `SameSite` viene de `REFRESH_COOKIE_SAMESITE` (por defecto `Strict`). Solo vale `Strict`, salvo la excepción documentada en la sección 2.5.
- En desarrollo local (`http://localhost`), verificar que el navegador acepte cookies `Secure` en `localhost` ([`deployment.md`](../.agents/deployment.md)).

### 2.5 Despliegue en el mismo sitio y CSRF

**Requisito (propuesta para [`Arquitectura.md`](Arquitectura.md) y [`deployment.md`](../.agents/deployment.md)):** el frontend y la API deben quedar en el **mismo sitio** (*same-site*). Hay dos formas válidas:

1. Una regla `rewrites` de Vercel envía `/api/:path*` al backend en Render, y el frontend llama a rutas relativas `/api/v1/...`.
2. Un dominio propio con subdominios del mismo dominio registrable (`app.<dominio>` y `api.<dominio>`).

Por qué: `vercel.app` y `onrender.com` están en la Public Suffix List, así que dos subdominios suyos son **sitios distintos**. Una cookie entre sitios exige `SameSite=None`, y Safari (ITP) bloquea por defecto las cookies de terceros: el refresh fallaría en los iPhone de los pacientes. En el mismo sitio, la cookie es `SameSite=Strict` y funciona en todos los navegadores.

Defensas adicionales en `POST /api/v1/auth/refresh`, `/logout` y `/logout-all`, los únicos endpoints que usan la cookie:

- La cabecera `X-Requested-With: insumap-web` es obligatoria. Un formulario HTML de otro sitio no puede enviarla.
- Si `Origin` está presente, debe estar en `CORS_ORIGINS`. Si `Sec-Fetch-Site` vale `cross-site`, se rechaza.
- Si falla: `403 FORBIDDEN` y el evento `CSRF_CHECK_FAILED`.
- El access token nunca va en cookie. Por eso el resto de la API no es vulnerable a CSRF.

Excepción documentada: si algún entorno no puede cumplir el requisito, se usa `REFRESH_COOKIE_SAMESITE=None` con las defensas anteriores, y se acepta que Safari no renovará la sesión (riesgo en la sección 20).

### 2.6 Endpoints y códigos de error de autenticación

Las rutas exactas las publica [`API.md`](API.md). Las de abajo son las que fija esta política (propuesta).

| Endpoint | Uso | Acceso |
|---|---|---|
| `POST /api/v1/auth/login` | Correo y contraseña. Responde `status`: `AUTHENTICATED` (sesión completa), `MFA_CHALLENGE` (devuelve `challenge_token`) o `MFA_ENROLLMENT_REQUIRED` (access token de enrolamiento, sin refresh) | Público |
| `POST /api/v1/auth/mfa/verify` | `challenge_token` más TOTP o código de respaldo. Devuelve la sesión completa | Público (con `challenge_token`) |
| `POST /api/v1/auth/mfa/enrollment` | Devuelve una sola vez el secreto y el URI `otpauth://` | Token de enrolamiento |
| `POST /api/v1/auth/mfa/enrollment/confirm` | Confirma con un TOTP. Devuelve una sola vez los códigos de respaldo y la sesión completa | Token de enrolamiento |
| `POST /api/v1/auth/mfa/recovery-codes` | Regenera los códigos de respaldo (exige un TOTP vigente) | Sesión completa |
| `GET /api/v1/auth/current-user` | Usuario, rol, clínica, permisos, `mfa_enabled` y `consent_required` (RF-08) | Autenticado |
| `POST /api/v1/auth/refresh` | Rota el refresh de la cookie | Cookie y CSRF (sección 2.5) |
| `POST /api/v1/auth/logout` y `/logout-all` | Cierre de sesión (sección 5) | Cookie y JWT |
| `POST /api/v1/auth/password/change` | Cambio de contraseña con la actual | Autenticado |
| `POST /api/v1/auth/password-reset/request` | Siempre `202`, exista o no el correo | Público |
| `POST /api/v1/auth/password-reset/complete` | Token de un solo uso y contraseña nueva | Público |
| `POST /api/v1/auth/email-verification/confirm` | Verifica el correo con un token de un solo uso | Público |
| `POST /api/v1/auth/activation/verify` | Código de activación y fecha de nacimiento (sección 3.4) | Público |
| `POST /api/v1/auth/activation/complete` | Contraseña, correo si falta y consentimiento | Público (con `activation_token`) |
| `GET /api/v1/meta/field-limits` | Límites de `FieldLimits` para el frontend (sin datos personales) | Público |
| `GET /health` | Salud mínima `{"status": "ok"}`, sin detalle de componentes ni consulta a la BD ([`deployment.md`](../.agents/deployment.md)) | Público |

| Código | HTTP | Cuándo |
|---|---|---|
| `UNAUTHORIZED` | 401 | Token ausente, mal formado, vencido o no verificable; refresh desconocido o vencido; `challenge_token` vencido, usado o agotado. El frontend intenta un refresh una vez, o vuelve al login |
| `SESSION_REVOKED` | 401 | `tv` no coincide, la cuenta dejó de estar activa o se reutilizó un refresh revocado. El frontend vuelve al login |
| `INVALID_CREDENTIALS` | 401 | Correo o contraseña incorrectos, cuenta sin contraseña, TOTP o código de respaldo incorrecto o ya usado (mensaje genérico) |
| `ACCOUNT_NOT_ACTIVE` | 403 | Contraseña correcta, pero la cuenta está `SUSPENDED` o `DEACTIVATED`, o el personal tiene `is_active = false` |
| `CLINIC_SUSPENDED` | 403 | Contraseña correcta, pero la clínica está suspendida (RF-10) |
| `MFA_REQUIRED` | 403 | Personal sin `"otp"` en `amr` que llama a una ruta distinta del enrolamiento |
| `CONSENT_REQUIRED` | 403 | Activación sin aceptar el consentimiento, o consentimiento retirado o vencido por versión nueva |
| `FORBIDDEN` | 403 | El rol no tiene el permiso (sección 6.5) o falló la verificación CSRF |
| `NOT_FOUND` | 404 | El recurso no existe, es de otra clínica o el paciente no está asignado (sección 6.5) |
| `EMAIL_UNAVAILABLE` | 409 | En la activación, el correo ya pertenece a otra cuenta |
| `CONSENT_VERSION_OUTDATED` | 409 | La versión del aviso de privacidad aceptada ya no es la vigente |
| `INVALID_STATE_TRANSITION` | 409 | Transición de estado de la cuenta no permitida ([`Actores-y-permisos.md`](Actores-y-permisos.md), sección 5) |
| `INVITATION_INVALID` | 410 | Cualquier fallo de activación, de restablecimiento o de verificación de correo: código o token mal formado, inexistente, vencido, usado, reemplazado, revocado o bloqueado, o fecha de nacimiento incorrecta (sección 3.5) |
| `VALIDATION_ERROR` | 422 | Entrada inválida, incluida una contraseña que no cumple la política ([validación](../.agents/input-validation.md)) |
| `REASON_REQUIRED` | 422 | Falta el motivo al suspender o desactivar una cuenta |
| `RATE_LIMITED` | 429 | Se excedió un límite o hay un bloqueo de login (secciones 2.2 y 12). Incluye la cabecera `Retry-After` |

Todos usan el formato canónico `{"error": {"code": "...", "message": "...", "detail": {}}}`. El `detail` nunca incluye un secreto ni el valor enviado en un campo secreto.

## 3. Credenciales para pacientes importados

### 3.1 Estados de la cuenta y de la invitación

La cuenta del paciente sigue `PatientAccountState` (P18): `IMPORTED → INVITED → ACTIVE → SUSPENDED → DEACTIVATED`. Las transiciones y quién las dispara están en [`Actores-y-permisos.md`](Actores-y-permisos.md), sección 5. Las que afectan a la seguridad son estas:

| Transición | Efecto de seguridad |
|---|---|
| `IMPORTED → INVITED` | Se crea una invitación `PENDING` con su código |
| `INVITED → INVITED` (reenvío) | La invitación anterior pasa a `REVOKED` y se emite un código nuevo |
| `INVITED → IMPORTED` (revocación o vencimiento) | La invitación pasa a `REVOKED` o `EXPIRED`. Un job periódico detecta las vencidas y devuelve la cuenta a `IMPORTED` |
| `INVITED → ACTIVE` | La invitación pasa a `USED`, se guarda el hash de la contraseña y el consentimiento |
| `ACTIVE → SUSPENDED` | `tv + 1` y se revocan todas las familias de refresh |
| `→ DEACTIVATED` | `tv + 1`, se revocan las familias y la invitación pendiente. Es terminal; los datos clínicos se conservan según [Cumplimiento](Cumplimiento-y-privacidad.md) |

Estados de la invitación (`iam.credential_invitations.status`): `PENDING`, `VERIFIED` (pasó el paso 1 de la sección 3.4), `USED`, `EXPIRED`, `REVOKED` y `LOCKED`. Cada paciente tiene como máximo una invitación `PENDING` o `VERIFIED` (índice único parcial, propuesta).

Propósito de la invitación (`purpose`): `PATIENT_ACTIVATION`, `STAFF_ACTIVATION` y `PASSWORD_RESET`.

### 3.2 Código de activación

| Parámetro | Valor canónico | Variable o constante |
|---|---|---|
| Alfabeto | Crockford base32: `0123456789ABCDEFGHJKMNPQRSTVWXYZ` (sin I, L, O ni U) | No aplica |
| Longitud | 16 caracteres = 80 bits de entropía | `FieldLimits.ACTIVATION_CODE_LENGTH` |
| Presentación | `XXXX-XXXX-XXXX-XXXX` | No aplica |
| Generación | `secrets.choice` sobre el alfabeto, carácter por carácter. Nunca `random` | No aplica |
| Normalización de la entrada | Recorte, mayúsculas, sin espacios ni guiones; `O` pasa a `0`; `I` y `L` pasan a `1` | No aplica |
| Almacenamiento | `HMAC-SHA256(k_activation, código_normalizado)` en hexadecimal en `iam.credential_invitations.code_hash` (único), más `code_key_id` | `CODE_HMAC_KEY` (sección 8.3) |
| Llave del HMAC | `k_activation = HKDF-SHA256(CODE_HMAC_KEY, info="insumap/activation-code/v1")` | No aplica |
| Expiración | 7 días desde la emisión | `ACTIVATION_CODE_TTL_HOURS=168` |
| Intentos | 5 fallos de fecha de nacimiento con un código válido bloquean la invitación (`LOCKED`) | `ACTIVATION_MAX_ATTEMPTS` |
| Sesión de activación | Token opaco de 256 bits, 15 minutos, de un solo uso (`iam.auth_challenges`, propósito `ACTIVATION`) | `ACTIVATION_SESSION_TTL_MINUTES` |

Por qué HMAC con llave y no SHA-256 solo: el código tiene menos entropía que un token, porque una persona debe poder teclearlo. Con un HMAC con llave, quien robe la tabla sin la llave no puede probar códigos fuera de línea. Además, el HMAC es determinista, así que permite buscar la invitación por el código sin otro identificador.

### 3.3 Hoja de activación y canal de correo

- **Emisión:** `POST /api/v1/patients/{patient_id}/credential-invitations`, con `{"channel": "PRINT" | "EMAIL"}`.
  - Exige el permiso `credentials.issue`.
  - Queda en `audit.audit_log` mediante `IssueCredentialsCommand` (P13) y `AuditingCommandHandler` (P09).
  - En lote: `POST /api/v1/credential-invitations/batch`, con un máximo de 100 pacientes por petición (`FieldLimits.CREDENTIAL_BATCH_MAX_ITEMS`).
  - Revocación: `POST /api/v1/credential-invitations/{invitation_id}/revoke`, con `credentials.revoke`.
- **Se muestra una sola vez:** el código en claro existe solo en la respuesta de la emisión, con `Cache-Control: no-store`. La API nunca lo vuelve a devolver ni lo guarda. Para reimprimir se emite una invitación nueva, que revoca la anterior.
- **Hoja imprimible (PDF o HTML):** se genera en la respuesta de la emisión y no se guarda en ningún lado. Contiene el nombre de la clínica, el nombre del paciente, el código, la fecha de expiración, la URL de activación e instrucciones. No contiene el documento, la fecha de nacimiento, diagnósticos ni datos clínicos. Se entrega en mano.
- **Hoja en JSON (solo clínicas demo):** si `clinic.clinics.is_demo = true`, la emisión puede devolver también la hoja en JSON para el simulador, con el formato de [`Datos-simulados.md`](Datos-simulados.md), sección 8.2. Una clínica no demo nunca recibe esa versión.
- **Correo:** contiene un enlace `https://<frontend>/activar#code=<código>`. El código va en el **fragmento**, que el navegador no envía al servidor ni pone en el `Referer`. El correo no incluye datos clínicos ni el documento. La activación igual exige la fecha de nacimiento.
- **Envío fallido:** queda registrado. Reintentar significa emitir de nuevo (código nuevo), porque el código en claro no se guarda en ningún lado.
- El código nunca se registra en logs, en `security_events` ni en `audit_log`. Allí solo queda el `invitation_id`.

### 3.4 Flujo de activación

1. **Verificación:** `POST /api/v1/auth/activation/verify` con `{"activation_code", "birth_date"}`.
   1. Se normaliza el código. Si no cumple el formato, se responde `INVITATION_INVALID`, y el intento cuenta para la tasa por IP.
   2. Se busca `code_hash` con una función `SECURITY DEFINER` que devuelve solo las columnas mínimas (`iam.lookup_invitation_by_code_hash`, propuesta). Esta consulta corre antes de conocer la clínica.
   3. Si no existe, o el estado no es `PENDING`, o venció: `INVITATION_INVALID`.
   4. Desde aquí se fija `app.clinic_id` de la invitación en la transacción.
   5. Se compara la fecha de nacimiento con la del paciente. Si no coincide: `failed_attempts + 1`. Al llegar a 5, la invitación pasa a `LOCKED` y se registra `ACTIVATION_LOCKED`. La respuesta es `INVITATION_INVALID`.
   6. Si coincide: la invitación pasa a `VERIFIED` y se emite un `activation_token` de 15 minutos. La respuesta incluye el nombre de la clínica y la versión vigente del aviso de privacidad. **No** incluye el nombre del paciente ni otros datos personales.
2. **Lectura del aviso:** el frontend muestra el aviso de privacidad vigente de la clínica (texto versionado; base legal en [Cumplimiento](Cumplimiento-y-privacidad.md)).
3. **Finalización:** `POST /api/v1/auth/activation/complete` con `{"activation_token", "new_password", "email"?, "consent": {"privacy_notice_version_id", "accepted": true, "ai_external_processing": bool}}`.
   1. `new_password` cumple la política de la sección 2.1. Se fija en ese momento: no hay contraseña temporal ni cambio obligatorio posterior.
   2. `email` es obligatorio si la importación no lo traía. Si ya pertenece a otra cuenta: `409 EMAIL_UNAVAILABLE`. Un correo nuevo queda sin verificar y se envía un enlace de verificación de 24 horas (`EMAIL_VERIFICATION_TTL_HOURS`).
   3. Sin `accepted: true`: `403 CONSENT_REQUIRED`, y la cuenta sigue `INVITED` (HU-10). Si la versión no es la vigente: `409 CONSENT_VERSION_OUTDATED`.
   4. El consentimiento se guarda en `clinic.patient_consents` con la versión, la fecha, `ip_hmac` y el alcance. `ai_external_processing` es un consentimiento aparte y opcional para el asistente con LLM externo (sección 9).
   5. En una sola transacción ocurre todo esto:
      - La invitación pasa a `USED` y la cuenta a `ACTIVE`.
      - Se guarda el hash de la contraseña.
      - Se escriben el consentimiento y `audit_log` (`PATIENT_ACTIVATED`).
      - Se emiten el access token y el refresh.

      El evento `PatientActivated` (P17) se publica después del commit.
4. **Simulador:** en la clínica demo, el simulador activa por este mismo flujo, sin rutas especiales. Del JSON de la hoja toma el código. La fecha de nacimiento la busca por MRN en sus propios datos generados, porque el MRN no viaja en la activación (cambio propuesto a [`Datos-simulados.md`](Datos-simulados.md), sección 21).

Diagrama: `docs/images/secuencia-activacion.png` (propuesta; lo dibuja el agente de diagramas).

### 3.5 Intentos, bloqueo, límites y oráculos

- **Un solo error:** todo fallo responde `410 INVITATION_INVALID`, con el mensaje "El código no es válido o venció. Pide uno nuevo a tu clínica". Esto incluye:
  - un código mal formado, inexistente, vencido, usado, reemplazado, revocado o bloqueado;
  - una fecha de nacimiento incorrecta;
  - un `activation_token` inválido.

  El tiempo de respuesta no depende del motivo.
- **Por qué la fecha de nacimiento:** si alguien roba la hoja, el código solo no basta. Un código inventado no se puede atribuir a ninguna invitación, así que esos fallos solo cuentan por IP. Los fallos de fecha con un código real sí cuentan por invitación (5 intentos).
- **Fuerza bruta:** 80 bits a 10 intentos por minuto por IP hacen inviable adivinar un código. El límite de tasa existe sobre todo contra la denegación de servicio y contra quien ya tiene un código y prueba fechas.
- **Tasa:** activación, 10 por minuto y 50 por hora por IP (sección 12). Al excederla: `429 RATE_LIMITED` (HU-10). Un `ACTIVATION_LOCKED` o una ráfaga de `ACTIVATION_FAILED` desde la misma IP generan un evento de severidad media.
- **Desbloqueo:** una invitación `LOCKED` no se desbloquea. El admin emite una nueva, previa verificación de la identidad del paciente en la clínica.

### 3.6 Reemisión y restablecimiento de contraseña

- **Reemisión:** una invitación nueva revoca la anterior (`REVOKED`). Un paciente `ACTIVE` no recibe `PATIENT_ACTIVATION`, sino `PASSWORD_RESET`.
- **Olvido de la contraseña con correo verificado:** `password-reset/request` responde siempre `202`. Si la cuenta existe, está activa y su correo está verificado, se envía un enlace con un token de 256 bits en el fragmento (`#token=`). El token se guarda como SHA-256, dura 30 minutos (`PASSWORD_RESET_TTL_MINUTES`) y es de un solo uso. Un enlace usado o vencido responde `410 INVITATION_INVALID` (HU-03).
- **Paciente sin correo verificado:** el admin emite una invitación `PASSWORD_RESET` por el canal `PRINT`, con el mismo mecanismo de las secciones 3.2 a 3.5.
- **Al restablecer:** se incrementa `tv`, se revocan todas las familias (`PASSWORD_CHANGED`) y, si el correo está verificado, el titular recibe un aviso.

### 3.7 Personal y `PLATFORM_ADMIN`

- **Personal:** el `CLINIC_ADMIN` crea al médico o al otro admin (`users.manage`). El sistema envía una invitación `STAFF_ACTIVATION`, solo por correo, con el mismo código. En la activación no se pide fecha de nacimiento, porque la posesión del correo es el segundo factor. Después de fijar la contraseña, el usuario recibe solo un token de enrolamiento y debe enrolar MFA antes de usar la API (sección 4).
- **Primer `CLINIC_ADMIN`:** lo crea el `PLATFORM_ADMIN` (`clinic_admins.manage`, RF-11), con la misma invitación.
- **`PLATFORM_ADMIN`:** no tiene endpoint de registro. El primero se crea con un comando de la aplicación (`insumap create-platform-admin`, propuesta), que imprime una invitación en la terminal del operador.

## 4. MFA del personal

| Parámetro | Valor canónico | Variable |
|---|---|---|
| Obligatorio para | `CLINIC_ADMIN`, `DOCTOR` y `PLATFORM_ADMIN` (todo rol distinto de `PATIENT`) | No aplica |
| Algoritmo | TOTP (RFC 6238): HMAC-SHA1, 6 dígitos, paso de 30 segundos, por compatibilidad con las apps de autenticación | No aplica |
| Ventana | ±1 paso (deriva de reloj) | `MFA_TOTP_VALID_WINDOW` |
| Secreto | 20 bytes aleatorios (160 bits, 32 caracteres base32) | No aplica |
| Cifrado del secreto | AES-256-GCM con `MFA_ENCRYPTION_KEY`. AAD = `iam.mfa_factors.secret|<factor_id>|<user_id>`. Se guardan `secret_ciphertext` y `key_id` | `MFA_ENCRYPTION_KEY`, `MFA_ENCRYPTION_KEY_PREVIOUS` |
| Anti-repetición | `last_used_step`: se rechaza un paso menor o igual al último aceptado | No aplica |
| Reto de login | Token opaco de 256 bits en `iam.auth_challenges` (propósito `MFA`), 5 minutos y 5 intentos | `MFA_CHALLENGE_TTL_SECONDS`, `MFA_CHALLENGE_MAX_ATTEMPTS` |
| Códigos de respaldo | 10 códigos de 10 caracteres Crockford (50 bits), presentados como `XXXXX-XXXXX`, de un solo uso | `MFA_RECOVERY_CODE_COUNT` |
| Almacenamiento de los códigos | `HMAC-SHA256(HKDF(CODE_HMAC_KEY, "insumap/recovery-code/v1"), código)`, con `key_id` y `used_at` | `CODE_HMAC_KEY` |

Reglas:

1. **Primer ingreso sin MFA** (HU-02): el login responde `MFA_ENROLLMENT_REQUIRED` con un access token de 15 minutos con `amr: ["pwd"]` y sin refresh. Ese token solo sirve para enrolar, para `GET /auth/current-user` y para cerrar sesión; cualquier otra ruta responde `403 MFA_REQUIRED`.
2. **Enrolamiento:**
   - El URI `otpauth://totp/Insumap:<correo>?secret=...&issuer=Insumap` y el secreto se devuelven una sola vez, con `no-store`.
   - El QR se dibuja en el navegador, no en el servidor.
   - El factor queda activo solo después de confirmar un TOTP válido. La confirmación devuelve la sesión completa (`amr: ["pwd", "otp"]` y refresh).
3. **Códigos de respaldo:** se muestran una sola vez, al confirmar el enrolamiento o al regenerarlos. Regenerarlos invalida los anteriores.
4. **Fallos:** un TOTP o código de respaldo incorrecto o repetido responde `401 INVALID_CREDENTIALS` (HU-02), registra `MFA_FAILED` y cuenta para el bloqueo de la sección 2.2.
5. **Uso de un código de respaldo:** registra `MFA_RECOVERY_CODE_USED` (severidad media) y avisa al titular. Si quedan 2 o menos, la UI pide regenerarlos.
6. **Restablecer el MFA de alguien** (teléfono perdido):
   - Lo hace un `CLINIC_ADMIN` para el personal de su clínica (`users.manage`), o un `PLATFORM_ADMIN` para un `CLINIC_ADMIN` (`clinic_admins.manage`).
   - Exige motivo y queda en `audit_log`.
   - Incrementa `tv`, revoca las familias (`MFA_RESET`), registra `MFA_RESET` (severidad alta) y avisa al titular.
   - En el siguiente login, el usuario enrola de nuevo.
   - Nadie restablece su propio MFA.
7. **MFA para pacientes:** fuera del alcance del MVP (sección 20).

## 5. Sesiones

| Acción | Efecto | Motivo en `revoked_reason` |
|---|---|---|
| `POST /auth/logout` | Revoca la familia de la cookie. El frontend descarta el access token de memoria (vence en 15 minutos o menos) | `LOGOUT` |
| `POST /auth/logout-all` | Revoca todas las familias del usuario y hace `tv + 1` | `LOGOUT_ALL` |
| Cambio o restablecimiento de contraseña | `tv + 1`; revoca todas las familias; el dispositivo actual recibe una sesión nueva | `PASSWORD_CHANGED` |
| Cambio de rol o de membresía | `tv + 1`; revoca todas las familias | `ROLE_CHANGED` |
| Suspensión o desactivación de la cuenta | `tv + 1`; revoca todas las familias | `ACCOUNT_SUSPENDED`, `ACCOUNT_DEACTIVATED` |
| Suspensión de la clínica | Se revocan las familias de todos sus usuarios. El chequeo por petición rechaza con `403 CLINIC_SUSPENDED` | `CLINIC_SUSPENDED` |
| Restablecimiento de MFA | `tv + 1`; revoca todas las familias | `MFA_RESET` |
| Reutilización de un refresh | Revoca la familia; `tv + 1` | `REUSE_DETECTED` |
| Acción de un administrador sobre una cuenta | `tv + 1`; revoca todas las familias | `ADMIN` |

- Un usuario pertenece a una sola clínica: el JWT lleva un solo `clinic_id` ([`Actores-y-permisos.md`](Actores-y-permisos.md), sección 1.3).
- La lista de sesiones activas con revocación individual queda como propuesta futura (sección 20).

## 6. Autorización

### 6.1 Permisos desde la BD y denegación por defecto

- **Denegación por defecto:** todo endpoint exige autenticación y un permiso, salvo los públicos y las acciones sobre la propia cuenta de la sección 2.6. Una prueba recorre todas las rutas de FastAPI y falla si una ruta no declara su permiso o su excepción ([`.agents/security.md`](../.agents/security.md), sección 10).
- **RBAC desde la BD:** los roles, los permisos y su matriz viven en `iam.roles`, `iam.permissions` e `iam.role_permissions`. El código solo verifica códigos de permiso, nunca nombres de rol. Cambiar la matriz no exige un despliegue.
- **Códigos:** usan la convención `dominio.accion` o `dominio.accion_alcance` de [`Actores-y-permisos.md`](Actores-y-permisos.md), sección 3. Por ejemplo, `credentials.issue`, `patients.read_assigned` o `glucose.write_own`. Ese documento tiene el catálogo y la matriz canónicos.
- **Caché:** los permisos por rol se cachean 60 segundos (`PERMISSION_CACHE_TTL_SECONDS`). Un cambio de la matriz surte efecto en 60 segundos o menos. Un cambio que afecta a un usuario concreto (rol o membresía) incrementa su `tv` y surte efecto de inmediato.
- Un `403 FORBIDDEN` registra `PERMISSION_DENIED` en `iam.security_events`.

### 6.2 Aislamiento por clínica (RLS)

1. El `clinic_id`, el `user_id` y el rol salen **solo** del JWT validado. Nunca de la ruta, el cuerpo, la consulta ni una cabecera.
2. La unidad de trabajo, justo después de abrir cada transacción, ejecuta:

   ```sql
   SELECT set_config('app.clinic_id', :clinic_id, true),
          set_config('app.user_id',   :user_id,   true),
          set_config('app.role',      :role,      true);
   ```

   El tercer parámetro `true` equivale a `SET LOCAL`: el valor dura hasta el `COMMIT` o el `ROLLBACK` y no se filtra entre peticiones que comparten una conexión del pool. Además, es compatible con el *pooler* de Neon en modo transacción. Nunca se fija a nivel de sesión.
3. **`app.role`** es una tercera variable (propuesta). La necesitan la política que deja al paciente ver solo sus filas (V3 de [`Actores-y-permisos.md`](Actores-y-permisos.md)) y la de los esquemas clínicos que excluye a `CLINIC_ADMIN`.
4. **Fallo cerrado:** si la transacción no fija el valor, `current_setting('app.clinic_id', true)` devuelve `NULL` y la política no devuelve filas.
5. **Políticas:** toda tabla con `clinic_id` tiene `ENABLE` y `FORCE ROW LEVEL SECURITY`, con políticas `USING` y `WITH CHECK`. Las políticas exactas, sus pruebas y la matriz de privilegios viven en `insumap-database`.
6. **Roles:**
   - La API se conecta como `insumap_app`, sin `BYPASSRLS` ni DDL.
   - `insumap_migrator` solo corre migraciones.
   - `insumap_readonly` no ve columnas S.
   - En Neon, el login dueño (`neondb_owner`) salta la RLS por diseño de la plataforma (verificado en CAUDAL el 2026-10-09; hay que verificarlo de nuevo en el proyecto nuevo). Por eso la aplicación nunca usa ese login.
7. **`PLATFORM_ADMIN`:** no tiene `clinic_id`. Solo una política de `clinic.clinics` lo deja gestionar las clínicas. Las tablas de `clinic.patients`, `monitoring`, `care`, `alerts`, `ai`, `messaging` y `audit` no tienen rama para `PLATFORM_ADMIN`.
8. **Consultas antes del contexto:** el login, la activación y el refresh leen antes de conocer la clínica. Lo hacen con funciones `SECURITY DEFINER` de `search_path` fijo, que devuelven solo las columnas mínimas: `iam.lookup_login_identity(email)`, `iam.lookup_invitation_by_code_hash(hash)` e `iam.lookup_refresh_token(hash)` (propuesta para `insumap-database`).

### 6.3 Equipo de atención: `PatientRecordAccessProxy` (P11)

Todo acceso a datos de un paciente pasa por el proxy, que envuelve al puerto `PatientRecordPort`. Reglas:

| Rol del actor | Acceso concedido |
|---|---|
| `PATIENT` | Solo si `patient.user_id = actor.user_id` (permisos `*_own`) |
| `DOCTOR` | Solo si existe una asignación vigente en `clinic.care_team_assignments` para ese paciente y ese médico (sin `ended_at`, o con `ended_at` en el futuro) (permisos `*_assigned`) |
| `CLINIC_ADMIN` | Solo la vista administrativa (`PatientAdministrativeView`, permiso `patients.read_roster`): nombre, MRN, `document_last4`, estado de la cuenta, médicos asignados y estado de la invitación. Nunca datos H |
| `PLATFORM_ADMIN` | Ninguno |

- Si se niega, el proxy lanza `PatientNotFoundError` (respuesta `404`). `PhiAccessAuditDecorator` registra la fila `DENIED` en `data_access_log` y se emite `PHI_ACCESS_DENIED`.
- No existe acceso de emergencia (*break-glass*) en el MVP: un médico no asignado pide la asignación al admin (sección 20).

### 6.4 Qué datos ve cada rol

| Datos | `PATIENT` | `DOCTOR` (asignado) | `CLINIC_ADMIN` | `PLATFORM_ADMIN` |
|---|---|---|---|---|
| Registros, métricas, plan, alertas, notas, mensajes y salidas de IA (H) | Los propios | Sí | No | No |
| Identidad del paciente (C) | La propia | Sí | Sí, la vista administrativa | No |
| Documento completo (descifrado) | En la exportación de sus datos | No (solo `document_last4`) | No (solo `document_last4`) | No |
| KPIs de la clínica | No | No | Solo agregados; los conteos pequeños se agrupan (RF-83; propuesta: celdas con menos de 5 pacientes) | No |
| Auditoría y eventos de seguridad | No | No | Los de su clínica (`audit.read`) | Los de plataforma (`audit.read_platform`) |

Tres barreras impiden que el admin lea detalle clínico:

1. El rol no tiene permisos clínicos ([`Actores-y-permisos.md`](Actores-y-permisos.md), sección 3.3).
2. El proxy le da solo la vista administrativa.
3. Propuesta para `insumap-database`: las políticas de `monitoring`, `care`, `ai`, `alerts.alerts` y `messaging` exigen `current_setting('app.role', true) IN ('DOCTOR', 'PATIENT')`. Los KPIs del admin salen de funciones `SECURITY DEFINER` que devuelven solo agregados.

### 6.5 `404` frente a `403`

| Situación | Respuesta |
|---|---|
| El recurso no existe | `404 NOT_FOUND` |
| El recurso es de otra clínica (la RLS no lo devuelve) | `404 NOT_FOUND`, idéntico al anterior |
| `DOCTOR` y paciente no asignado, o `PATIENT` y otro paciente | `404 NOT_FOUND`, idéntico al anterior |
| El rol no tiene el permiso del endpoint (por ejemplo, `CLINIC_ADMIN` en un endpoint clínico) | `403 FORBIDDEN`. No revela existencia, porque se decide antes de buscar el recurso |
| Sin token o con token inválido | `401 UNAUTHORIZED` (sección 2.6) |

El cuerpo, las cabeceras y el tiempo de un `404` por aislamiento no se distinguen de los de un `404` real.

## 7. Auditoría

### 7.1 Acceso a datos clínicos: `audit.data_access_log`

- **Qué se registra:** cada lectura de datos H. El proxy envuelto por `PhiAccessAuditDecorator` (P09) escribe una fila por petición y por paciente. El triage del dashboard (`DoctorDashboardFacade`) escribe una fila por paciente listado, en una sola inserción por lotes.
- **Fallo cerrado:** la fila se escribe en la misma transacción de la lectura y antes de responder. Si la escritura falla, la lectura falla (V5 de [`Actores-y-permisos.md`](Actores-y-permisos.md)).
- También se registran las denegaciones (`outcome = 'DENIED'`), el descifrado del documento (`action = 'DECRYPT'`), las exportaciones (`EXPORT`) y cada envío de datos de un paciente a `insumap-ai` (actor `SYSTEM`, propósito `AI_PROCESSING`).
- **Datos administrativos:** las vistas del admin con identidad del paciente registran una fila por petición con `resource_type = 'PATIENT_LIST'` o `PATIENT_DEMOGRAPHICS`, sin una fila por paciente listado.

| Columna (propuesta para el modelo de datos) | Contenido |
|---|---|
| `id`, `occurred_at` | Identidad y hora en UTC |
| `clinic_id`, `patient_id` | Clínica y paciente |
| `actor_user_id`, `actor_role`, `actor_type` | Quién (`USER` o `SYSTEM`) |
| `resource_type` | `GLUCOSE_READINGS`, `INSULIN_DOSES`, `MEALS`, `PHYSICAL_ACTIVITIES`, `SYMPTOMS`, `LAB_RESULTS`, `GLYCEMIC_METRICS`, `TREATMENT_PLAN`, `CLINICAL_NOTES`, `ALERTS`, `AI_OUTPUTS`, `MESSAGES`, `PATIENT_TIMELINE`, `REPORT`, `TRIAGE_LIST`, `PATIENT_DEMOGRAPHICS`, `PATIENT_LIST`, `PATIENT_DOCUMENT` |
| `action`, `outcome`, `purpose` | `READ`, `EXPORT` o `DECRYPT`; `GRANTED` o `DENIED`; `CARE`, `SELF`, `ADMINISTRATION` o `AI_PROCESSING` |
| `request_id`, `ip_hmac` | Correlación con los logs; la IP nunca en claro |

`data_access_log` es append-only: un trigger rechaza `UPDATE` y `DELETE`, y solo la función de purga con retención borra (sección 16). No lleva cadena de hashes, por su volumen.

### 7.2 Acciones: `audit.audit_log` con cadena de hashes

- **Qué se registra:** cada acción que cambia datos de seguridad o decisiones clínicas. Ejemplos: importación, emisión y revocación de credenciales, activación, cambios de rol, membresía o equipo de atención, consentimiento, MFA y desbloqueos, suspensión, activación de planes, decisiones sobre recomendaciones, cambios de metas y reglas, cambios de retención y purgas. Lo escribe `AuditingCommandHandler` (P09) en la **misma transacción** de la acción: si la acción falla, no hay fila.
- **Minimización:** `audit_log` no copia valores clínicos. Guarda `entity_type`, `entity_id`, la versión, el motivo y los **nombres** de los campos cambiados. Los valores viven en las tablas versionadas (por ejemplo, `care.treatment_plan_snapshots`).
- **Cadena por clínica:** `row_hash = sha256(prev_hash || contenido_canónico)`, en hexadecimal de 64 caracteres.
  - La primera fila usa 64 ceros como génesis.
  - Lo calcula un trigger `BEFORE INSERT` con `pg_advisory_xact_lock` por clínica, para que dos transacciones no tomen el mismo `prev_hash`.
  - La fórmula exacta y el contenido canónico los fija `insumap-database`, a partir del diseño de CAUDAL.
- **Verificación:** `audit.verify_chain(p_clinic_id)` (propuesta) recalcula la cadena. Corre en un job diario. Una discrepancia registra `AUDIT_CHAIN_BROKEN` (crítico).
- Append-only: un trigger rechaza `UPDATE` y `DELETE` para todos los roles.

### 7.3 Eventos de seguridad: `iam.security_events`

| Evento | Severidad |
|---|---|
| `AUDIT_CHAIN_BROKEN` | CRITICAL |
| `REFRESH_TOKEN_REUSE_DETECTED`, `ACCOUNT_LOCKED`, `MFA_RESET`, `LLM_DATA_POLICY_BLOCKED` | HIGH |
| `MFA_FAILED`, `MFA_RECOVERY_CODE_USED`, `PERMISSION_DENIED`, `PHI_ACCESS_DENIED`, `ACTIVATION_LOCKED`, `PUSH_ENDPOINT_REJECTED`, `CSRF_CHECK_FAILED` | MEDIUM |
| `LOGIN_FAILED`, `ACCOUNT_UNLOCKED`, `ACTIVATION_FAILED`, `ACCOUNT_ACTIVATED`, `ROLE_CHANGED`, `RATE_LIMITED` (uno por clave y ventana), `PASSWORD_CHANGED`, `PASSWORD_RESET_REQUESTED`, `SESSIONS_REVOKED`, `IMPORT_REJECTED`, `SECRET_ROTATED` | LOW |

- Cada evento guarda tipo, severidad, usuario (si existe), clínica (si existe), hora, `ip_truncated` e `ip_hmac` (RF-95). `ip_truncated` es la IP truncada (/24 en IPv4 y /48 en IPv6), que la consola de la plataforma muestra; `ip_hmac` sirve para correlacionar.
- Los `details` se escriben ya redactados (sección 11).
- `SECRET_ROTATED` lo registra quien rota un secreto, con un comando de la aplicación (propuesta). Incluye la rotación del token de servicio que pide [`Contrato-IA.md`](Contrato-IA.md), sección 2.2.
- Los eventos sin clínica (por ejemplo, un login fallido con un correo inexistente) van aquí con `clinic_id` nulo y nunca a `audit_log`.

## 8. Columnas sensibles y gestión de llaves

### 8.1 Número de documento

| Columna (`clinic.patients`) | Contenido |
|---|---|
| `document_type` | Enum (ver [validación](../.agents/input-validation.md), sección 6.1) |
| `document_hash` | `HMAC-SHA256(LOOKUP_HMAC_KEY, clinic_id ‖ 0x1F ‖ document_type ‖ 0x1F ‖ número_normalizado)` en hexadecimal. Único por `(clinic_id, document_hash)`. Sirve para buscar y deduplicar |
| `document_hash_key_id` | Huella de la `LOOKUP_HMAC_KEY` usada (sección 8.3) |
| `document_ciphertext` | AES-256-GCM: `nonce (12 bytes) ‖ texto cifrado ‖ tag (16 bytes)`, en `bytea` |
| `document_key_id` | Huella de la `FIELD_ENCRYPTION_KEY` con la que se cifró |
| `document_last4` | Últimos 4 caracteres, para mostrar `******1234` sin descifrar (clase C) |

- **AAD de GCM:** `clinic.patients.document|<patient_id>|<clinic_id>`. Ata el texto cifrado a su fila: copiarlo a otra fila hace fallar el descifrado.
- **Nonce aleatorio:** 96 bits por cifrado. El límite práctico de cifrados con nonce aleatorio por llave (del orden de 2^32) está muy por encima del uso de Insumap.
- **El `clinic_id` en el HMAC** impide correlacionar a la misma persona entre clínicas con solo comparar hashes.
- **Descifrado:** solo para exportar los datos del propio paciente o devolverlos a la clínica. Cada descifrado queda en `data_access_log` (`DECRYPT`). Ninguna respuesta de la API incluye el documento completo.
- **Deduplicación:** la importación deduplica por MRN de la clínica (RF-19). `document_hash` es una segunda comprobación.

### 8.2 Material de credenciales en la BD

| Dato | Cómo se guarda | Por qué |
|---|---|---|
| Contraseña | Argon2id (sección 2.1) | Baja entropía: exige un hash lento |
| Refresh token, `challenge_token`, `activation_token`, token de restablecimiento y token de verificación de correo | SHA-256 en hexadecimal | 256 bits de entropía: un hash rápido basta |
| Código de activación y código de respaldo de MFA | HMAC-SHA256 con subllave HKDF de `CODE_HMAC_KEY` y `key_id` | Entropía media (80 y 50 bits): la llave impide la fuerza bruta fuera de línea |
| Secreto TOTP | AES-256-GCM con `MFA_ENCRYPTION_KEY` | El sistema necesita leerlo para calcular el código |
| IP | HMAC-SHA256 con la subllave `ip` de `APP_HMAC_KEY` (`ip_hmac`), más `ip_truncated` en `security_events` | Permite contar intentos sin guardar la IP completa |

Toda comparación de un secreto presentado contra uno esperado usa `hmac.compare_digest`. Nunca `==`.

### 8.3 Inventario de llaves, formato y rotación

- **Formato:** cada llave son 32 bytes aleatorios en base64, estándar o url-safe; el cargador acepta ambos y exige exactamente 32 bytes decodificados. Se generan con `openssl rand -base64 32` o con `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
- **Rotación sin corte:** toda llave que cifra, firma o hashea datos guardados sigue el patrón **actual y anterior** (`<NOMBRE>` y `<NOMBRE>_PREVIOUS`), igual que el token de servicio de la IA. La actual firma o cifra. Las dos verifican o descifran.
- **Huella (`key_id`):** cada fila guarda la huella de la llave con la que se protegió: los primeros 16 caracteres hexadecimales de `SHA-256("insumap-key-id|" ‖ llave)`. La huella identifica la llave sin revelarla, y no exige variables `*_ID`. El JWT la lleva en `kid`.
- **Arranque:** se valida que cada llave decodifique a 32 bytes. Si una falta o no cumple, la API no arranca.

| Llave | Uso | Efecto de rotarla | Procedimiento |
|---|---|---|---|
| `JWT_SECRET` (+ `_PREVIOUS`) | Firma HS256 de los access tokens | Ninguno si se usa la anterior | Mover la actual a `JWT_SECRET_PREVIOUS` y poner la nueva. Retirar la anterior después de 15 minutos más la tolerancia. Sin la anterior, rotar cierra todas las sesiones ([`deployment.md`](../.agents/deployment.md), sección 10) |
| `FIELD_ENCRYPTION_KEY` (+ `_PREVIOUS`) | AES-256-GCM de columnas (documento) | Ninguno | Poner la nueva y la anterior, correr el job de recifrado y retirar la anterior cuando ninguna fila tenga su huella |
| `MFA_ENCRYPTION_KEY` (+ `_PREVIOUS`) | AES-256-GCM de secretos TOTP | Ninguno | Igual que la anterior |
| `CODE_HMAC_KEY` (+ `_PREVIOUS`) | HMAC de códigos de activación y de respaldo | Ninguno mientras la anterior siga configurada | Poner la nueva y la anterior. Retirar la anterior cuando no queden invitaciones vigentes con su huella (7 días). Los códigos de respaldo con esa huella se invalidan, y la UI pide regenerarlos |
| `LOOKUP_HMAC_KEY` | HMAC de búsqueda del documento | Hay que recalcular todos los `document_hash` | Solo ante sospecha: un job descifra, recalcula con la llave nueva y actualiza `document_hash_key_id` |
| `APP_HMAC_KEY` | Subllaves HKDF `ip`, `subject-ref` y `cursor` | Los `ip_hmac` dejan de ser comparables, los cursores vencen y los `subject_ref` cambian | Rotar solo ante sospecha y documentar la discontinuidad |
| `AI_SERVICE_TOKEN` | Backend hacia `insumap-ai` | Ninguno | [`Contrato-IA.md`](Contrato-IA.md), sección 2.2 |
| `DATABASE_URL` (credencial de `insumap_app`) | Conexión de la API | Reinicio | [`deployment.md`](../.agents/deployment.md), sección 10 |
| `SMTP_PASSWORD`, `VAPID_PRIVATE_KEY` | Correo y Web Push | VAPID: las suscripciones de push se rehacen | Cambiar en el proveedor y en Render |
| `LLM_API_KEY` (solo en `insumap-ai`) | Proveedor del LLM | Ninguno | Cambiar en el proveedor y en Render |

- Frecuencia: cada 12 meses o ante sospecha. Antes de `v1.0.0` se generan todas de nuevo.
- Las llaves de desarrollo nunca se reutilizan en producción.
- Las llaves no se guardan en la BD ni en los respaldos. Un volcado sin las variables de entorno no permite descifrar ni validar códigos.

## 9. Minimización hacia `insumap-ai` y el LLM

**Principio:** `insumap-ai` es un servicio sin estado. Recibe lo mínimo para calcular y nunca recibe identificadores directos. El contrato detallado está en [`Contrato-IA.md`](Contrato-IA.md) y los casos IA1 a IA7 en [`Modulo-IA.md`](Modulo-IA.md).

| Se envía | Nunca se envía |
|---|---|
| `subject_ref` = `"sub_"` + los primeros 32 caracteres hexadecimales de `HMAC-SHA256(subllave "subject-ref" de APP_HMAC_KEY, patient_id)` (patrón `^sub_[0-9a-f]{32}$` del contrato) | Nombres, documento, MRN, correo, teléfono, dirección, `patient_id` y `user_id` reales |
| Datos clínicos estructurados que pide cada endpoint del contrato: series en mg/dL, dosis, carbohidratos, actividad, códigos de síntomas, métricas, metas y `clinic_timezone` | Fecha de nacimiento, notas clínicas y mensajes en texto libre (salvo los campos redactados del punto 2) |
| Marcas de tiempo ISO-8601 con offset (contrato v1) | Nombre de la clínica, de los médicos y del personal; IP y datos de sesión |

Reglas para el LLM (IA5 e IA6):

1. **Texto libre redactado dos veces.** Antes de enviar `detail`, `description` o el mensaje del paciente (IA6):
   - El backend reemplaza con marcadores los identificadores conocidos del paciente (nombres, apellidos, documento, MRN, correo y teléfono).
   - Después, `insumap-ai` aplica `PhiRedactingTextGenerator` con patrones genéricos.
   - La validación de entrada ya rechazó los caracteres de formato, incluidos los *tag* Unicode (U+E0000 a U+E007F), que sirven para ocultar instrucciones (*ASCII smuggling*).
2. **Capa gratuita = solo datos simulados o seudonimizados.**
   - El backend no envía datos de una clínica con `is_demo = false` a los endpoints que usan el LLM (IA5 e IA6) mientras `LLM_REAL_DATA_ALLOWED=false`, el valor por defecto. En su lugar usa el respaldo determinista y registra `LLM_DATA_POLICY_BLOCKED`.
   - La variable solo se activa con un proveedor que excluya por contrato el entrenamiento con los datos, y con la base legal de transferencia de [Cumplimiento](Cumplimiento-y-privacidad.md).
   - Propuesta para la próxima versión del contrato: enviar `data_origin` (`SIMULATED` o `REAL`) para que `insumap-ai` aplique la misma regla como segunda barrera.
3. **Consentimiento.** IA6 con LLM externo exige el consentimiento `ai_external_processing` del paciente (sección 3.4). Sin él, el asistente usa respuestas predefinidas. El texto y la base legal del consentimiento están en [Cumplimiento](Cumplimiento-y-privacidad.md).
4. **Sin herramientas.** El LLM no tiene herramientas, ni acceso a la BD, ni capacidad de actuar. Una inyección de prompt solo puede alterar el texto de la respuesta, que además pasa por la validación del punto 5.
5. **Salida como dato no confiable.**
   - El backend valida cada respuesta con un modelo Pydantic, números finitos, cuantiles ordenados (p10 ≤ p50 ≤ p90) y longitudes máximas. Ignora los campos desconocidos de la respuesta, como fija el contrato.
   - El texto del LLM se muestra como **texto plano**: sin HTML, sin imágenes y sin enlaces externos, para evitar la exfiltración por URLs de imágenes Markdown.
6. **La IA nunca da dosis al paciente.** IA4 produce una propuesta que el médico aprueba, modifica o rechaza con motivo (P13). En IA6, `GuardrailHandler` bloquea dosis y diagnósticos y escala los síntomas de alarma.
7. **Sin persistencia en `insumap-ai`.** El servicio no guarda las cargas útiles ni las registra en logs. Solo el backend guarda las salidas, en el esquema `ai`, con la versión del modelo, la explicación y la decisión del médico.
8. **Propuesta para una versión futura del contrato:** días relativos ("día -3") en lugar de fechas de calendario en IA5, para reducir aún más la reidentificación.

## 10. Token de servicio de `insumap-ai`

Lo define [`Contrato-IA.md`](Contrato-IA.md), sección 2. Esta política lo resume y agrega lo que le toca al backend:

| Aspecto | Valor canónico |
|---|---|
| Token | 32 bytes aleatorios o más (`secrets.token_urlsafe(32)`). `AI_SERVICE_TOKEN`, sin valor por defecto en ninguno de los dos servicios |
| Transporte | `Authorization: Bearer <token>`, solo por HTTPS. `X-Request-Id` para correlacionar |
| Validación en `insumap-ai` | `hmac.compare_digest` contra el actual **y** el anterior (`AI_SERVICE_TOKEN_PREVIOUS`), siempre los dos, sin cortocircuito. Un token configurado de menos de 32 bytes impide el arranque |
| Fallo | `401 INVALID_SERVICE_TOKEN` con `WWW-Authenticate: Bearer`. El backend lo trata como `AI_ERROR`, usa el respaldo y emite una alerta operativa |
| Rotación sin corte | 1) Nuevo como actual y viejo como anterior en `insumap-ai`. 2) Nuevo en el backend. 3) Retirar el anterior de `insumap-ai`. Cada rotación registra `SECRET_ROTATED` |
| Red | En el plan gratuito de Render el servicio es público, así que el token es la barrera principal. `insumap-ai` también limita el tamaño de las peticiones (contrato, sección 3.3). Un servicio privado de Render es una mejora futura (verificar el plan) |
| Llamadas | Solo desde el backend. `insumap-ai` no habilita CORS: el navegador nunca lo llama |
| Timeouts y circuit breaker | Los del contrato (secciones 3.2 y 5), en variables `AI_TIMEOUT_*_SECONDS`, `AI_CIRCUIT_FAILURE_THRESHOLD` y `AI_CIRCUIT_OPEN_SECONDS`. `RemoteAiServiceProxy` (P11) y `CircuitBreakerState` (P18) los aplican |

## 11. Logs

1. **Formato:** JSON, con `timestamp` en UTC, `level`, `logger`, `message`, `request_id`, `method`, `route` (la **plantilla**, por ejemplo `/api/v1/patients/{patient_id}/readings`), `status`, `duration_ms`, `user_id`, `clinic_id` y `role`.
2. **`request_id`:** se acepta el `X-Request-ID` entrante solo si es un UUID válido; si no, se genera uno. Siempre se devuelve en la cabecera `X-Request-ID` de la respuesta y se reenvía a `insumap-ai`. El cuerpo de error mantiene su formato canónico, sin `request_id`.
3. **Nunca se registra:**
   - Cuerpos de petición ni de respuesta, ni la cadena de consulta.
   - Las cabeceras `Authorization`, `Cookie` y `Set-Cookie`.
   - Contraseñas, códigos, tokens, secretos ni llaves.
   - Datos C o H: nombres, documento, correo, teléfono, fecha de nacimiento, valores clínicos junto a un paciente, notas, mensajes, ni los prompts y respuestas del LLM.
   - IP en claro.
4. **Filtro de redacción** (`RedactionFilter`, en todos los handlers):
   - Reemplaza por `[REDACTED]` el valor de toda clave que contenga `password`, `passwd`, `secret`, `token`, `authorization`, `cookie`, `code`, `otp`, `api_key`, `document`, `email`, `phone` o `birth`. La comparación ignora mayúsculas.
   - Además, enmascara por patrón los JWT (`eyJ...`), `Bearer ...`, correos, códigos Crockford con guiones y secuencias de 6 dígitos o más.
5. **Access log propio:** el *access log* de uvicorn se desactiva, porque registra la ruta completa con la consulta. Lo reemplaza un middleware propio que registra la plantilla de la ruta.
6. **SQLAlchemy:** `echo=False` y `hide_parameters=True` en el engine. Así los parámetros de las consultas, que pueden traer datos H, no salen en logs ni en mensajes de excepción.
7. **Errores de validación:** el manejador global quita `input` y `ctx` de cada error ([`api-documentation.md`](../.agents/api-documentation.md), sección 5), y nunca se registran con esos campos. El manejador por defecto de FastAPI sí devuelve `input`: además de filtrar datos, falla con `500` ante un `NaN`, porque no lo puede serializar (verificado con FastAPI 0.163 y Pydantic 2.14).
8. **Excepciones:** la traza completa va al log con el `request_id`. La respuesta es `500 INTERNAL_ERROR`, sin traza ni nombre de clase. Las excepciones de dominio no incluyen valores de entrada en su mensaje.
9. **Retención:** la que ofrezca el plan de Render (verificar). Los eventos que deben perdurar van a `iam.security_events` y `audit`, no a los logs.

## 12. Límites de tasa

**Decisión:** un esquema híbrido.

- **PostgreSQL para lo crítico.** Las familias críticas para la seguridad usan **contadores de ventana fija en PostgreSQL** (`iam.rate_limit_buckets`, tabla nueva, propuesta para `insumap-database`). Son: autenticación, MFA, activación, restablecimiento, refresh, emisión de credenciales, importación, IA y reportes.
  - Un solo `INSERT ... ON CONFLICT DO UPDATE ... RETURNING` es atómico.
  - Los contadores se comparten entre instancias y sobreviven a un reinicio: un atacante no los borra tumbando el proceso.
  - Corren en una transacción propia, que se confirma aunque la petición falle.
- **Memoria para el resto.** El resto de la API autenticada usa un **token bucket en memoria** por proceso. Es barato y no agrega una escritura a la BD por petición, algo que importa en Neon. Se acepta que el límite se multiplique por el número de instancias (hoy es una) y que se reinicie con el proceso: para estas familias, el límite amortigua el abuso, no es una barrera de seguridad.
- **IP del cliente:** `request.client.host`, que uvicorn calcula con `--proxy-headers` y `FORWARDED_ALLOW_IPS` ([`deployment.md`](../.agents/deployment.md)). En el despliegue hay que verificar que un `X-Forwarded-For` falso enviado por el cliente no cambia la IP resultante, también a través de la regla de reescritura de Vercel. Si la cambia, `ClientIpResolver` toma la IP que agrega el último proxy de confianza contando desde la derecha (propuesta).

| Familia | Endpoints | Clave | Límite | Almacenamiento | Variable |
|---|---|---|---|---|---|
| Login | `POST /auth/login` | IP | 20 por minuto, más los bloqueos de la sección 2.2 | PostgreSQL | `RATE_LIMIT_LOGIN_PER_IP_PER_MINUTE` |
| MFA | `POST /auth/mfa/verify`, `/mfa/enrollment/confirm` | IP | 20 por minuto, más 5 intentos por reto | PostgreSQL | `RATE_LIMIT_MFA_PER_IP_PER_MINUTE` |
| Activación | `POST /auth/activation/verify`, `/activation/complete` | IP | 10 por minuto y 50 por hora | PostgreSQL | `RATE_LIMIT_ACTIVATION_PER_IP_PER_MINUTE`, `RATE_LIMIT_ACTIVATION_PER_IP_PER_HOUR` |
| Solicitud de restablecimiento | `POST /auth/password-reset/request` | IP; correo | 5 por hora por IP; 3 por hora por correo (los excesos se ignoran en silencio y se responde `202`) | PostgreSQL | `RATE_LIMIT_RESET_REQUEST_PER_IP_PER_HOUR`, `RATE_LIMIT_RESET_REQUEST_PER_ACCOUNT_PER_HOUR` |
| Restablecimiento y verificación de correo | `POST /auth/password-reset/complete`, `/email-verification/confirm` | IP | 10 por minuto | PostgreSQL | `RATE_LIMIT_RESET_COMPLETE_PER_IP_PER_MINUTE` |
| Refresh | `POST /auth/refresh` | Usuario | 30 por minuto | PostgreSQL | `RATE_LIMIT_REFRESH_PER_USER_PER_MINUTE` |
| Emisión de credenciales | `POST /patients/{id}/credential-invitations`; lote | Clínica | 300 por hora; lote: 10 por hora | PostgreSQL | `RATE_LIMIT_CREDENTIAL_ISSUE_PER_CLINIC_PER_HOUR`, `RATE_LIMIT_CREDENTIAL_BATCH_PER_CLINIC_PER_HOUR` |
| Importación | FHIR y CSV | Clínica | 10 por hora | PostgreSQL | `RATE_LIMIT_IMPORT_PER_CLINIC_PER_HOUR` |
| Asistente (IA6) | Mensajes al asistente | Paciente | 20 por hora y 100 por día | PostgreSQL | `RATE_LIMIT_ASSISTANT_PER_PATIENT_PER_HOUR`, `RATE_LIMIT_ASSISTANT_PER_PATIENT_PER_DAY` |
| Resumen clínico (IA5) | Generar resumen previo a la consulta | Médico | 30 por hora | PostgreSQL | `RATE_LIMIT_AI_SUMMARY_PER_DOCTOR_PER_HOUR` |
| Reportes y exportaciones | Reportes PDF y HTML, exportaciones | Usuario | 20 por hora | PostgreSQL | `RATE_LIMIT_REPORTS_PER_USER_PER_HOUR` |
| Registros del paciente | Glucosa, insulina, comidas, actividad, síntomas y lotes | Usuario | 120 por minuto | Memoria | `RATE_LIMIT_RECORDS_PER_USER_PER_MINUTE` |
| Mensajes | Envío de mensajes | Usuario | 30 por minuto | Memoria | `RATE_LIMIT_MESSAGES_PER_USER_PER_MINUTE` |
| API general autenticada | Todo lo demás | Usuario | 300 por minuto | Memoria | `RATE_LIMIT_API_PER_USER_PER_MINUTE` |
| Públicos sin sesión | `GET /meta/field-limits` | IP | 60 por minuto | Memoria | `RATE_LIMIT_PUBLIC_PER_IP_PER_MINUTE` |

- Al exceder un límite: `429 RATE_LIMITED`, con la cabecera `Retry-After` en segundos. Se registra `RATE_LIMITED` una vez por clave y ventana, para no inundar la tabla.
- La ventana fija permite hasta el doble del límite en el borde entre dos ventanas. Se acepta, porque los bloqueos de la sección 2.2 cubren los ataques sostenidos.
- La clave de los contadores en PostgreSQL es un HMAC (`APP_HMAC_KEY`) de `familia:valor`, para no guardar IPs ni correos en claro.
- El modo `live` del simulador respeta estos límites, como cualquier cliente ([`Datos-simulados.md`](Datos-simulados.md)).

## 13. Superficie HTTP

### 13.1 Cabeceras

| Cabecera | API (backend) | Frontend (Vercel; detalle en `insumap-frontend`) |
|---|---|---|
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` (sin `preload`) | Igual |
| `Content-Security-Policy` | `default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'` | `default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; worker-src 'self'; manifest-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'` |
| CSP en `/docs` (Swagger) | Swagger de FastAPI carga sus recursos desde `cdn.jsdelivr.net` y usa un script en línea. Propuesta: servir los recursos desde la propia API con un *nonce*. Mientras tanto, CSP relajada solo en `/docs` (verificar) | No aplica |
| `X-Content-Type-Options` | `nosniff` | `nosniff` |
| `Referrer-Policy` | `no-referrer` | `no-referrer` |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=(), payment=(), usb=()` | Igual (si la foto de comida llega a existir, se habilita `camera=(self)`) |
| `Cross-Origin-Resource-Policy` | `same-site` | No aplica |
| `Cache-Control` | `no-store` en toda respuesta de `/api/v1`, salvo `GET /meta/field-limits` (`public, max-age=300`) | Recursos estáticos con *hash*: caché larga; `index.html`: `no-cache` |
| `Server`, `X-Powered-By` | No se envían (uvicorn con `--no-server-header`) | No aplica |

Reglas del frontend con impacto en seguridad:
- El service worker de la PWA **nunca** guarda respuestas de `/api/` en la Cache Storage: solo guarda recursos estáticos.
- La cola offline en IndexedDB guarda registros pendientes (datos H), nunca tokens. Se borra al cerrar sesión, y la app avisa antes si hay pendientes.

### 13.2 CORS, hosts y transporte

- `CORSMiddleware` con `allow_origins` = `CORS_ORIGINS`, una lista explícita. Si contiene `*`, la API no arranca.
- `allow_credentials=True` solo para esa lista. Métodos: `GET`, `POST`, `PUT`, `PATCH` y `DELETE`. Cabeceras: `Authorization`, `Content-Type`, `X-Requested-With`, `X-Request-ID` e `Idempotency-Key`. Se exponen `X-Request-ID` y `Retry-After`. `max_age=600`.
- Con el despliegue en el mismo sitio (sección 2.5), en producción la lista solo tiene el origen del frontend. En desarrollo: `http://localhost:5173`.
- `TrustedHostMiddleware` con `ALLOWED_HOSTS`.
- TLS 1.2 o superior en tránsito (RNF-05). La conexión a Neon usa TLS con verificación del certificado (`sslmode=verify-full`; verificar que la imagen tenga los certificados raíz).

### 13.3 Tamaño de petición e importación

| Límite | Valor | Constante (`FieldLimits`) |
|---|---|---|
| Cuerpo JSON general | 64 KiB | `BODY_MAX_BYTES` |
| Lote de registros offline | 512 KiB y 500 elementos | `RECORDS_BATCH_BODY_MAX_BYTES`, `RECORDS_BATCH_MAX_ITEMS` |
| Bundle FHIR R4 | 10 MiB, 5.000 entradas y 32 niveles de profundidad | `IMPORT_FHIR_MAX_BYTES`, `IMPORT_FHIR_MAX_ENTRIES`, `IMPORT_FHIR_MAX_DEPTH` |
| CSV de pacientes | 2 MiB, 5.000 filas, 40 columnas y 1.000 caracteres por celda | `IMPORT_CSV_MAX_BYTES`, `IMPORT_CSV_MAX_ROWS`, `IMPORT_CSV_MAX_COLUMNS`, `IMPORT_CSV_CELL_MAX_LENGTH` |
| CSV de CGM | 10 MiB y 100.000 filas | `IMPORT_CGM_CSV_MAX_BYTES`, `IMPORT_CGM_CSV_MAX_ROWS` |
| Cabecera `Authorization` | 2 KiB | `AUTH_HEADER_MAX_BYTES` |

Reglas de importación:

1. **Cuerpo crudo, no multipart.** Se acepta `Content-Type: application/fhir+json` para FHIR y `text/csv` para CSV. Se lee el *stream* contando bytes y se corta con `413 PAYLOAD_TOO_LARGE` al pasar el límite, aunque falte `Content-Length` o mienta.
2. **Solo JSON y CSV en UTF-8.** FHIR XML no se acepta (`415 UNSUPPORTED_MEDIA_TYPE`): sin parser XML no hay XXE. Tampoco se aceptan archivos comprimidos, así que no hay bombas de descompresión.
3. **Lista blanca de recursos:** FHIR solo admite `Patient`, `Practitioner`, `Condition`, `Observation` y `MedicationRequest` (RF-16). Otros tipos quedan como incidencia de fila, sin detener el lote.
4. **CSV:** separador `,` o `;`, detectado solo en la línea de encabezado. Se elimina el BOM.
5. **Cada fila pasa la misma validación que la API** (`FieldLimits`, `ImportValidator`). Una fila inválida no crea nada y queda en `clinic.import_rows` con sus códigos de incidencia.
6. **El archivo original no se guarda:** `import_rows` guarda el número de fila, el estado, los códigos y el `patient_id` creado, no la fila cruda.
7. **Campo exigido:** la importación exige `birth_date` en cada paciente, porque la activación lo usa como segundo dato (sección 3.4).
8. **Origen de los datos:** un Bundle marcado `SIMULATED` solo entra en una clínica demo ([`Datos-simulados.md`](Datos-simulados.md), sección 11).

### 13.4 Salidas: errores, CSV, PDF, correo y push

- **Errores:** solo el formato canónico, sin `input`, `ctx`, trazas, SQL ni configuración (sección 11).
- **CSV exportado:** una celda que empieza con `=`, `+`, `-`, `@`, tabulador o retorno de carro se prefija con `'`, para evitar la inyección de fórmulas.
- **Reportes PDF y HTML** (`ReportDocumentFactory`, y también la hoja de activación): plantillas con autoescape. El motor HTML a PDF no descarga recursos remotos (un `url_fetcher` que solo admite recursos empaquetados), para evitar SSRF y lectura de archivos.
- **Correo:**
  - Plantillas Jinja2 con `autoescape=True`.
  - Ningún encabezado se arma con datos del usuario (`email.message.EmailMessage`).
  - El asunto y el cuerpo no llevan valores clínicos, diagnósticos ni documento: dicen que hay una alerta o un mensaje nuevo, y el detalle se ve en la app después de iniciar sesión.
- **Web Push:** la carga visible no lleva valores clínicos ("Tienes una alerta nueva en Insumap"), porque se muestra en la pantalla bloqueada.
- **Endpoint de push** (lo envía el navegador, es dato no confiable):
  - Solo `https`.
  - Host en `PUSH_ENDPOINT_ALLOWED_HOSTS`. Propuesta: `fcm.googleapis.com`, `updates.push.services.mozilla.com`, `web.push.apple.com` y `*.notify.windows.com` (verificar la lista vigente).
  - Sin IP literales, sin seguir redirecciones y con timeout de 5 segundos.
  - Un rechazo registra `PUSH_ENDPOINT_REJECTED`.

## 14. Secretos y `.env.example`

1. **Ningún secreto en git.** `.env` y `.env.*` están en `.gitignore`, salvo `.env.example`.
2. **`.env.example`** lista cada variable con el marcador `cambia-esto-...` ([`configuration.md`](../.agents/configuration.md), sección 6) y, en un comentario, el comando para generarla. Nunca lleva un valor real.
3. **Configuración:** `Settings` (pydantic-settings), con `SecretStr` para cada secreto. Los secretos **no tienen valor por defecto**: si faltan o no cumplen su longitud, la API no arranca. `repr()` y los logs nunca muestran un `SecretStr`.
4. **Dónde viven los secretos:**
   - En variables de entorno de Render (backend e IA), declaradas con `sync: false` en `render.yaml`.
   - En variables de Vercel, solo las públicas `VITE_*`, que nunca son secretos.
   - En los secretos de GitHub Actions, solo si la CI los necesita. Las pruebas con Testcontainers no los necesitan.
5. **Imagen Docker:** nunca contiene secretos. `.dockerignore` excluye `.env*`. El contenedor corre con un usuario sin privilegios.
6. **Secreto nuevo:** se agrega en el mismo PR a `.env.example`, a la tabla 6.1 de [`configuration.md`](../.agents/configuration.md) y, si es una llave, a la tabla de la sección 8.3.
7. **Variables que esta política agrega a la tabla 6.1 de `configuration.md`:**
   - **Secretos:** `JWT_SECRET_PREVIOUS`, `FIELD_ENCRYPTION_KEY_PREVIOUS`, `MFA_ENCRYPTION_KEY` y `MFA_ENCRYPTION_KEY_PREVIOUS`, `CODE_HMAC_KEY` y `CODE_HMAC_KEY_PREVIOUS`, `APP_HMAC_KEY`.
   - **No secretas:** `JWT_ISSUER`, `JWT_AUDIENCE` y `JWT_LEEWAY_SECONDS`; `REFRESH_TOKEN_DAYS=30`, `REFRESH_FAMILY_MAX_DAYS=90`, `REFRESH_TOKEN_STAFF_HOURS=12` y `REFRESH_COOKIE_SAMESITE`; `ALLOWED_HOSTS`; `LLM_REAL_DATA_ALLOWED`; `PUSH_ENDPOINT_ALLOWED_HOSTS`.
   - **Parámetros:** los de Argon2id, bloqueo, activación, MFA, restablecimiento, caché de permisos y límites de tasa (secciones 2 a 6 y 12). [`.agents/security.md`](../.agents/security.md), sección 2, lista sus valores por defecto.
8. **Filtración:** se rota de inmediato, se revoca lo que dependa de él y se abre un incidente (sección 17).

## 15. Cadena de suministro y CI

| Control | Repos | Cuándo | Bloquea el merge |
|---|---|---|---|
| Gitleaks | Los cinco | Cada PR y cada push | Sí |
| Secret scanning y push protection de GitHub | Los cinco (públicos) | Siempre | Sí |
| CodeQL (`python` y `actions`; `javascript-typescript` en el frontend) | Los cinco | Cada PR y semanal | Hallazgos altos y críticos |
| `pip-audit` sobre `uv export --frozen --format requirements-txt` (con `--disable-pip`; verificar las opciones al montar la CI) | backend, ai, simulator | Cada PR y semanal | Sí, salvo excepciones con `--ignore-vuln <id>`, motivo escrito y fecha de revisión |
| `npm audit` (altas y críticas) | frontend | Cada PR | Sí |
| Dependabot: alertas y actualizaciones (`uv`, verificar el soporte del ecosistema, o `pip`; `npm`; `github-actions`) | Los cinco | Semanal, agrupado | No; se atiende por prioridad |
| Ruff con las reglas `S` (flake8-bandit, incluida `S608`) y `PLR2004` | Repos Python | Cada PR | Sí |
| `commit-lint` | Los cinco | Cada PR | Sí |

Reglas adicionales:
- **Dependencias fijadas:** `uv.lock` y `package-lock.json` se versionan, y la CI instala con `uv sync --frozen` y `npm ci`.
- **GitHub Actions fijadas a SHA:** cada Action se fija al SHA de un commit, no a una etiqueta móvil.
- **Permisos de los workflows:** `permissions: contents: read` por defecto. Nada de `pull_request_target` con checkout del código del PR.
- **Imagen base:** `python:3.13-slim` fijada por *digest*.
- **SBOM:** generar un SBOM con CycloneDX en cada release (propuesta).

## 16. Respaldos y retención

- **Neon:** ofrece recuperación a un punto en el tiempo (PITR). La ventana depende del plan y **no está fijada**: hay que verificarla en el proyecto nuevo antes de depender de ella.
- **Prueba de restauración:** antes de cada `release/<versión>`, se restaura en una rama de Neon y se corre `audit.verify_chain` (propuesta).
- **RPO y RTO (propuesta, objetivos académicos):** RPO de 24 horas o menos y RTO de 4 horas o menos.
- **Los respaldos contienen datos H y S**, y su acceso se trata como el de producción. Las llaves no están en los respaldos (sección 8.3).
- **En local** (Docker Compose) no hay PITR ni datos reales.

Retención: cada plazo es un parámetro de `audit.retention_policies` (en la BD, no en el código). Valores iniciales propuestos para las tablas técnicas:

| Tabla | Retención inicial |
|---|---|
| `iam.login_attempts` | 90 días |
| `iam.security_events` | 365 días |
| `iam.refresh_tokens` | 30 días después de vencer o de ser revocado |
| `iam.credential_invitations` | 90 días después de un estado terminal |
| `iam.auth_challenges`, `iam.rate_limit_buckets` | 1 día |
| Datos clínicos, `audit.audit_log`, `audit.data_access_log` y consentimientos | Según la normativa de historia clínica y protección de datos de [Cumplimiento](Cumplimiento-y-privacidad.md). Aquí no se fija ninguna cifra legal |

- Ninguna purga borra sin escribir antes un `PURGE` en `audit.audit_log`. Un cambio de retención queda como `RETENTION_POLICY_CHANGED`.
- Desactivar a un paciente no borra su historia clínica (RF-94).

## 17. Respuesta a incidentes y notificación de brechas

| Severidad | Ejemplos | Objetivo interno |
|---|---|---|
| SEV1 | Exposición de datos H o S, fuga entre clínicas, llave filtrada, cadena de auditoría rota | Contener en 4 horas o menos desde la detección |
| SEV2 | Una cuenta comprometida, reutilización de refresh confirmada, vulnerabilidad explotable sin evidencia de abuso | Contener en 24 horas o menos |
| SEV3 | Ataques bloqueados, picos de `RATE_LIMITED`, hallazgos de dependencias sin explotación conocida | Revisar en la siguiente sesión de trabajo |

1. **Detectar.** Fuentes: eventos `CRITICAL` o `HIGH` en `iam.security_events`, el job de `verify_chain`, alertas de GitHub (Dependabot, CodeQL, secret scanning), alertas de Render o Neon, o un reporte por el canal de `SECURITY.md` (pendiente, sección 21).
2. **Contener.** Según el caso:
   - Revocar sesiones (`logout-all` o `tv + 1`).
   - Suspender cuentas o la clínica.
   - Revocar invitaciones.
   - Rotar los secretos afectados (sección 8.3).
   - Desactivar el envío al LLM (`LLM_REAL_DATA_ALLOWED=false`), o la IA completa con `AI_ENABLED=false`.
   - Apagar la superficie afectada.
3. **Evaluar.** Qué pasó, desde cuándo, qué clínicas, qué pacientes y qué clases de datos (P, I, C, H, S). `audit.data_access_log` dice exactamente qué expedientes se leyeron y quién los leyó: es la fuente principal para delimitar una brecha.
4. **Preservar evidencia.**
   - Copiar `iam.security_events`, `audit.audit_log` (verificado con `verify_chain`), `audit.data_access_log` y los logs con su `request_id`.
   - No borrar nada.
5. **Erradicar.** Corregir la causa con una prueba que la reproduzca, y buscar el mismo patrón en otros módulos.
6. **Notificar.**
   - En el modelo B2B2C, la clínica es la responsable del tratamiento e Insumap el encargado (base y matices en [Cumplimiento](Cumplimiento-y-privacidad.md)).
   - Insumap avisa a la clínica afectada sin demora indebida, con un objetivo interno de 24 horas desde la confirmación.
   - La notificación a la Superintendencia de Industria y Comercio y a los titulares sigue el procedimiento, los plazos y el canal de [Cumplimiento](Cumplimiento-y-privacidad.md). Este documento no fija plazos legales.
7. **Recuperar.** Restaurar el servicio. Si hace falta restaurar datos, usar PITR (sección 16) y verificar la cadena de auditoría antes de reabrir.
8. **Aprender.** Escribir un informe sin culpables en `docs/incidentes/AAAA-MM-DD-titulo.md` (propuesta), con causa raíz, acciones y responsables. Las acciones entran a la lista de la sección 19.

Responsables:
- **Drako Salazar:** coordina lo técnico de backend y BD.
- **Nicolas Diaz:** coordina la comunicación, la CI y los secretos de las plataformas.
- **Nicolas Mora:** coordina el canal de IA y el LLM.

## 18. Pruebas de seguridad

Cada control tiene al menos una prueba que falla si el control se rompe. Las pruebas de integración usan Testcontainers con PostgreSQL 18, las migraciones de la etiqueta de `db-schema.lock` y sesiones con `insumap_app`, nunca con un superusuario ([`testing-plan.md`](../.agents/testing-plan.md), sección 4.2). Cómo escribirlas: [`.agents/security.md`](../.agents/security.md), sección 19. Esta tabla amplía la sección 6 de `testing-plan.md`.

| Control | Pruebas mínimas |
|---|---|
| Argon2id | El hash en formato PHC tiene `m=19456,t=2,p=1` con los parámetros de producción (se verifica una sola vez); se hace rehash cuando cambian los parámetros |
| Política de contraseña | 11 caracteres falla, 12 pasa, 129 falla; NFKC de ancho completo equivale a ASCII; lista de comunes; datos personales; historial de 5; cada caso responde `422 VALIDATION_ERROR` con su código de detalle |
| Login genérico y tiempo | Correo inexistente y contraseña incorrecta devuelven el mismo cuerpo y código; siempre se calcula un hash (contador del hasher) |
| Bloqueos | La pareja (correo, IP) se bloquea con 5 fallos y escala ×2 hasta 24 h; el correo se bloquea con 20 fallos desde IPs distintas; otra IP no queda bloqueada por la primera pareja; un correo inexistente también recibe `429` |
| Cuenta o clínica inactiva | `SUSPENDED` con contraseña correcta da `403 ACCOUNT_NOT_ACTIVE`; clínica suspendida da `403 CLINIC_SUSPENDED` |
| JWT | `alg: none` y `HS512` rechazados; `iss`, `aud`, `exp`, `nbf` y claims obligatorios validados; tolerancia de 30 s; llave de menos de 32 bytes impide el arranque; la llave anterior verifica pero no firma; cabecera de 2.049 bytes rechazada antes de decodificar |
| MFA obligatorio | Personal sin `"otp"` en `amr` recibe `403 MFA_REQUIRED` en toda ruta salvo el enrolamiento, `GET /auth/current-user` y el logout |
| `token_version` | Cambio de contraseña, de rol, suspensión, restablecimiento de MFA y `logout-all` invalidan el access token vigente (`401 SESSION_REVOKED`) |
| Refresh | El token nuevo funciona y el anterior no; la BD no contiene el token en claro; dos rotaciones simultáneas del mismo token: solo una gana |
| Reutilización | Reutilizar un token revoca la familia, hace `tv + 1`, responde `401 SESSION_REVOKED` y registra `REFRESH_TOKEN_REUSE_DETECTED` |
| Cookie y CSRF | `HttpOnly`, `Secure`, `SameSite=Strict`, `Path=/api/v1/auth` y prefijo `__Secure-`; sin `X-Requested-With`, con `Origin` ajeno o con `Sec-Fetch-Site: cross-site` responde `403 FORBIDDEN` |
| Activación | Código válido más fecha correcta activa; cada causa de fallo devuelve el mismo `410 INVITATION_INVALID`; 5 fechas incorrectas dan `LOCKED`; código vencido; reemisión revoca la anterior; vencimiento devuelve la cuenta a `IMPORTED`; el código no aparece en logs ni en la BD en claro; el `activation_token` es de un solo uso; la hoja JSON solo existe para clínicas demo |
| Consentimiento | Sin `accepted: true` responde `403 CONSENT_REQUIRED` y la cuenta sigue `INVITED`; una versión vieja da `409 CONSENT_VERSION_OUTDATED`; queda la fila en `patient_consents` |
| MFA | TOTP del mismo paso repetido rechazado; ventana ±1; secreto cifrado y descifrable solo con su AAD; código de respaldo de un solo uso (`401 INVALID_CREDENTIALS` al reusarlo); reto que vence a los 5 minutos o con 5 intentos |
| Permisos | Cada ruta de `app.routes` aparece en la matriz de autorización ([`testing-plan.md`](../.agents/testing-plan.md), sección 6); un rol sin el permiso recibe `403 FORBIDDEN`; un cambio en `iam.role_permissions` surte efecto tras la caché |
| RLS | Sin `app.clinic_id` no hay filas; un recurso de otra clínica da `404`; un `INSERT` con otro `clinic_id` falla por `WITH CHECK`; el contexto no se filtra entre transacciones de la misma conexión |
| Proxy (P11) | El médico asignado ve; el no asignado recibe `404` y queda la fila `DENIED`; el admin recibe solo la vista administrativa; el paciente solo ve lo propio; una asignación terminada deja de dar acceso |
| Auditoría (P09) | Cada lectura H deja una fila en `data_access_log`; si la escritura de auditoría falla, la lectura falla; cada acción sensible deja fila en `audit_log` y no la deja si la acción falla; `verify_chain` detecta una fila alterada |
| Columnas cifradas | El mismo documento produce ciphertexts distintos; descifrar con otra AAD falla; el mismo documento en dos clínicas da hashes distintos; la rotación de llave con recifrado funciona |
| Minimización IA | El cuerpo enviado a `insumap-ai` no contiene nombres, documento, MRN, correo, teléfono, fecha de nacimiento ni UUID reales (fixture con valores centinela); `subject_ref` cumple `^sub_[0-9a-f]{32}$`; una clínica no demo con `LLM_REAL_DATA_ALLOWED=false` usa el respaldo; la salida del LLM con HTML o Markdown de imagen se muestra como texto |
| Token de servicio | En `insumap-ai`: el token actual pasa; el anterior pasa durante la rotación; un token de 31 bytes impide el arranque; uno incorrecto da `401 INVALID_SERVICE_TOKEN` |
| Logs | `Authorization`, `Cookie`, contraseña, código, token, correo y documento salen como `[REDACTED]`; un error de validación no registra `input`; `hide_parameters=True` en el engine |
| Límites de tasa | Cada fila de la sección 12 devuelve `429 RATE_LIMITED` con `Retry-After` al exceder; los contadores en PostgreSQL se comparten entre dos instancias de la app; un `X-Forwarded-For` falso no cambia la IP contada |
| Cabeceras y CORS | Están las cabeceras de la sección 13.1; `no-store` en las respuestas autenticadas; un origen fuera de `CORS_ORIGINS` no recibe cabeceras CORS; `*` en la lista impide el arranque |
| Tamaño e importación | 64 KiB pasa y 64 KiB + 1 da `413`; FHIR XML da `415`; un CSV con 5.001 filas se rechaza; una fila inválida no crea paciente; un Bundle `SIMULATED` en una clínica real se rechaza |
| Salidas | Una celda CSV `=HYPERLINK(...)` se exporta con `'`; el PDF no descarga recursos remotos; un endpoint de push fuera de la lista se rechaza |
| Errores | Formato canónico sin trazas, `input` ni `ctx`; un error no esperado da `500 INTERNAL_ERROR`; un cuerpo con `NaN` da `422` y no `500` |

Las pruebas de entradas maliciosas están en [validación](../.agents/input-validation.md), sección 9.

## 19. Lista de verificación de seguridad para cada PR

- [ ] No hay secretos, tokens ni contraseñas en el diff. Gitleaks pasa.
- [ ] Todo endpoint nuevo exige autenticación y `require_permission("dominio.accion")`, con el permiso del catálogo de [`Actores-y-permisos.md`](Actores-y-permisos.md) sembrado en `insumap-database`.
- [ ] Ningún endpoint nuevo es público sin revisión de seguridad (y entonces se agrega a la sección 2.6).
- [ ] Los accesos a datos de un paciente pasan por `PatientRecordAccessProxy` y `PhiAccessAuditDecorator`.
- [ ] Las acciones sensibles pasan por un comando con `AuditingCommandHandler`.
- [ ] Las entradas nuevas están en [`.agents/input-validation.md`](../.agents/input-validation.md) con su constante de `FieldLimits`.
- [ ] Solo hay consultas parametrizadas: nada de SQL concatenado ni `text()` con f-strings.
- [ ] Los errores usan el formato canónico, sin trazas, `input` ni `ctx`.
- [ ] Los logs no tienen datos C, H ni S.
- [ ] Si hay una tabla nueva con `clinic_id`, tiene RLS con `FORCE` y prueba de aislamiento (en `insumap-database`).
- [ ] Si hay una columna nueva, está clasificada (P, I, C, H o S). Si es S o del documento, tiene hash o cifrado y privilegios por columna.
- [ ] Si hay datos nuevos hacia `insumap-ai`, cumplen la sección 9 y tienen su prueba de minimización.
- [ ] Las dependencias nuevas están fijadas y sin alertas de `pip-audit` o Dependabot.
- [ ] Existe la prueba del control de la sección 18 y falla sin el cambio.
- [ ] Ningún valor clínico o de negocio está escrito en el código.

## 20. Riesgos aceptados y fuera de alcance

| Riesgo o exclusión | Por qué se acepta | Revisión |
|---|---|---|
| Sin MFA para pacientes | Fricción alta para pacientes mayores. El riesgo se reduce con la política de contraseñas, los bloqueos y el refresh rotativo | Después del MVP |
| Sin acceso de emergencia (*break-glass*) para médicos no asignados | Requiere un flujo de justificación y revisión que no cabe en el MVP | Antes de un uso real |
| Refresh de 30 días para pacientes | La PWA se usa a diario; pedir el login seguido reduce la adherencia | Tras las pruebas de usabilidad |
| Límites en memoria por proceso para la API general | Hoy corre una sola instancia; la seguridad crítica usa PostgreSQL | Si se escala a más instancias |
| Servicio de IA público protegido solo por token | Plan gratuito de Render | Fase 12 |
| `SameSite=None` si no se logra el mismo sitio | Safari no renovaría la sesión | Fase 12 (requisito de la sección 2.5) |
| Lista de sesiones activas con revocación individual | No es imprescindible: existe `logout-all` | Después del MVP |
| Cuentas de pacientes menores de edad y representación legal | Lo define [Cumplimiento](Cumplimiento-y-privacidad.md) | Antes de importar pacientes pediátricos reales |
| Swagger activo en todos los entornos | No expone datos y toda ruta no pública exige autenticación | Antes de `v1.0.0` |

## 21. Decisiones que fijan otros documentos y pendientes de `insumap-database`

Todas son **propuestas** de esta política. El documento dueño las confirma o las corrige, y si cambia algo se actualiza también este documento.

| # | Decisión | Documento o repo dueño |
|---|---|---|
| 1 | Rutas de autenticación, activación y MFA de la sección 2.6. Emisión con `POST /api/v1/patients/{patient_id}/credential-invitations`, `/credential-invitations/batch` y `/credential-invitations/{invitation_id}/revoke`. Estados de login `AUTHENTICATED`, `MFA_CHALLENGE` y `MFA_ENROLLMENT_REQUIRED` | [`API.md`](API.md) |
| 2 | Códigos de error de la sección 2.6 que no estaban en otros documentos: `EMAIL_UNAVAILABLE` y `CONSENT_VERSION_OUTDATED`. Los demás (`UNAUTHORIZED`, `SESSION_REVOKED`, `FORBIDDEN`, `MFA_REQUIRED`, `ACCOUNT_NOT_ACTIVE`, `CLINIC_SUSPENDED`, `CONSENT_REQUIRED`, `INVITATION_INVALID`, `INVALID_STATE_TRANSITION`, `REASON_REQUIRED`) se alinean con [`Requerimientos.md`](Requerimientos.md), [`Historias-de-usuario.md`](Historias-de-usuario.md) y [`Actores-y-permisos.md`](Actores-y-permisos.md) | [`API.md`](API.md), `ErrorCode` |
| 3 | La reutilización de un refresh responde `401 SESSION_REVOKED`, como [`testing-plan.md`](../.agents/testing-plan.md). La HU-03 dice `401 UNAUTHORIZED` y hay que ajustarla | [`Historias-de-usuario.md`](Historias-de-usuario.md) (HU-03) |
| 4 | El correo es el identificador de login y es obligatorio para activar. Si la importación no lo trae, se pide en la activación | [`Requerimientos.md`](Requerimientos.md) (M1, M3) |
| 5 | `birth_date` es obligatorio en la importación, porque es el segundo dato de la activación | [`Requerimientos.md`](Requerimientos.md) (RF-16, RF-17), [`Modelo-de-datos.md`](Modelo-de-datos.md) |
| 6 | El simulador activa con `activation_code` y `birth_date`, que busca por MRN en sus datos. El MRN no viaja en la activación. Esto cambia la sección 8.2, punto 3, de `Datos-simulados.md` | [`Datos-simulados.md`](Datos-simulados.md) |
| 7 | Tercera variable de sesión `app.role`, además de `app.clinic_id` y `app.user_id` | [`Arquitectura.md`](Arquitectura.md), `insumap-database` |
| 8 | Tablas nuevas `iam.rate_limit_buckets` e `iam.auth_challenges`. Los códigos de respaldo van en `iam.mfa_factors` (tipo `RECOVERY_CODE`) o en una tabla propia | [`Modelo-de-datos.md`](Modelo-de-datos.md), `insumap-database` |
| 9 | Columnas nuevas, todas en el modelo de datos:<br>• Documento: `document_hash`, `document_hash_key_id`, `document_ciphertext`, `document_key_id` y `document_last4`.<br>• `credential_invitations`: `purpose`, `channel`, `code_hash`, `code_key_id`, `status`, `failed_attempts` y `expires_at`.<br>• `security_events`: `ip_truncated` e `ip_hmac`.<br>• `data_access_log`: las de la sección 7.1 | [`Modelo-de-datos.md`](Modelo-de-datos.md), [`Diccionario-de-datos.md`](Diccionario-de-datos.md) |
| 10 | Funciones `SECURITY DEFINER` para las consultas antes del contexto: `iam.lookup_login_identity`, `iam.lookup_invitation_by_code_hash` e `iam.lookup_refresh_token` | `insumap-database` |
| 11 | RLS por rol en los esquemas clínicos (`app.role IN ('DOCTOR','PATIENT')`). KPIs del admin con funciones que devuelven solo agregados y suprimen las celdas pequeñas | `insumap-database` |
| 12 | Alcances de consentimiento: tratamiento de datos sensibles (obligatorio) y `ai_external_processing` (opcional) | [`Cumplimiento-y-privacidad.md`](Cumplimiento-y-privacidad.md) |
| 13 | Frontend y API en el mismo sitio (regla de reescritura de Vercel o dominio propio), cookie `SameSite=Strict` y refresh serializado con Web Locks | [`Arquitectura.md`](Arquitectura.md), [`deployment.md`](../.agents/deployment.md), `insumap-frontend` |
| 14 | `REFRESH_TOKEN_DAYS=30` y las variables nuevas de la sección 14, punto 7. Las llaves rotan con el patrón actual y anterior (`*_PREVIOUS`) | [`configuration.md`](../.agents/configuration.md) (tabla 6.1) |
| 15 | Con `JWT_SECRET_PREVIOUS`, rotar `JWT_SECRET` no cierra las sesiones. Hay que actualizar la sección 10 de `deployment.md` | [`deployment.md`](../.agents/deployment.md) |
| 16 | Contrato backend-IA, versión siguiente: campo `data_origin` y días relativos en IA5. Mientras tanto, el bloqueo de datos reales lo aplica el backend con `LLM_REAL_DATA_ALLOWED` | [`Contrato-IA.md`](Contrato-IA.md) |
| 17 | Cada error de `detail.errors[]` lleva `code` (por ejemplo, `FIELD_TOO_LONG`), además de `field` y `message` | [`api-documentation.md`](../.agents/api-documentation.md) |
| 18 | Endpoint público `GET /api/v1/meta/field-limits` | [`API.md`](API.md) |
| 19 | Agregar `SECURITY.md` con el canal de reporte de vulnerabilidades | Este repo (Fase 1) |

Relacionados: [`Cumplimiento-y-privacidad.md`](Cumplimiento-y-privacidad.md), [`Actores-y-permisos.md`](Actores-y-permisos.md), [`Requerimientos.md`](Requerimientos.md), [`Arquitectura.md`](Arquitectura.md), [`Modelo-de-datos.md`](Modelo-de-datos.md), [`Contrato-IA.md`](Contrato-IA.md), [`Datos-simulados.md`](Datos-simulados.md), [`../.agents/security.md`](../.agents/security.md), [`../.agents/input-validation.md`](../.agents/input-validation.md), [`../.agents/configuration.md`](../.agents/configuration.md), [`../.agents/testing-plan.md`](../.agents/testing-plan.md)
