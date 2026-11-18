# Diccionario de datos

Este documento lista, tabla por tabla, las columnas de la base de datos de Insumap: tipo, nulabilidad, valor por defecto, restricción y descripción. Complementa el [Modelo de datos](Modelo-de-datos.md), que explica los esquemas, la RLS, los índices, la retención y los casos de uso. La definición ejecutable vive en `insumap-database` (migraciones de Alembic con SQL escrito a mano).

> **Aviso:** Insumap es un proyecto académico, no es un dispositivo médico y todos los pacientes son simulados.

## 1. Convenciones

- **Tipos:** `uuid` (claves; `DEFAULT uuidv7()`), `varchar(n)` para todo texto limitado, `char(64)` para SHA-256 y HMAC en hexadecimal, `char(16)` para huellas de llave (`*_key_id`), `text` solo para contenido largo sin límite de entrada (aviso de privacidad, material educativo), `timestamptz` (UTC), `date`, `time` (hora local de la clínica), `numeric(p,s)`, `smallint`, `integer`, `bigint`, `boolean`, `jsonb`, `bytea` y `cidr`. Los arreglos se escriben `tipo[]`.
- **Nulo:** `No` es `NOT NULL`; `Sí` admite nulo.
- **Restricción:** `PK`, `FK esquema.tabla(columna)` (siempre `ON DELETE RESTRICT`), `UNIQUE`, `CHECK ...` y la referencia a `FieldLimits` cuando el límite de la columna debe coincidir con la constante. Un `CHECK` nunca contiene un valor clínico.
- **Columna S:** secreto, hash o texto cifrado (clase S de [Seguridad.md](Seguridad.md) 1.2). `insumap_readonly` no la ve.
- **Glucosa:** siempre mg/dL. **Fechas:** `timestamptz` en UTC.
- **Parámetros clínicos:** viven en tablas (`care.target_profiles`, `alerts.alert_rules`, `care.protocol_templates`, `care.reminder_schedules`, `care.reading_validation_settings`, `clinic.clinic_settings`); ninguna columna tiene un número clínico como `DEFAULT` o `CHECK`. Los ejemplos de valores aparecen solo en las semillas de `insumap-database`.
- **(propuesta):** la tabla no está en la lista base de `insumap-database/AGENTS.md`; ver la sección 14 del Modelo.
- **Columnas comunes:** `created_at` y `updated_at` son `timestamptz NOT NULL DEFAULT now()`. `lock_version` es el contador del bloqueo optimista.
- **Correcciones:** las tablas de `monitoring` repiten `entry_type`, `supersedes_id` y `correction_reason` con la misma regla: un original no tiene `supersedes_id` ni motivo; una corrección o anulación sí (`CHECK ((entry_type = 'ORIGINAL') = (supersedes_id IS NULL AND correction_reason IS NULL))`).

## 2. Límites y `FieldLimits`

La prueba de deriva (`tests/integration/test_field_limits_drift.py`) compara cada constante de `FieldLimits` con `information_schema.columns.character_maximum_length` del esquema fijado en `db-schema.lock`. Por eso toda columna con límite de entrada es `varchar(n)`.

**Constantes que existen hoy** en `src/insumap/shared/field_limits.py` y se reflejan en columnas:

| Constante | Valor | Columnas |
|---|---|---|
| `FieldLimits.EMAIL_MAX_LENGTH` | 254 | `clinic.patients.contact_email`, `iam.users.email_normalized`, `iam.users.email` |
| `FieldLimits.REQUEST_ID_MAX_LENGTH` | 64 | `audit.audit_log.request_id`, `audit.data_access_log.request_id`, `iam.login_attempts.request_id`, `iam.security_events.request_id` |

Las demás constantes de `FieldLimits` (`REQUEST_ID_PATTERN`, `PASSWORD_MIN_LENGTH`, `PASSWORD_MAX_LENGTH`, `MAX_REQUEST_BODY_BYTES`, `PAGE_SIZE_DEFAULT` y `PAGE_SIZE_MAX`) no corresponden a columnas: la contraseña se guarda como hash y los tamaños de cuerpo y de página no son del esquema.

**Constantes propuestas** (por fijar en `FieldLimits`, cada una con su prueba de deriva). El valor es el de la longitud `varchar(n)` propuesta; donde `.agents/configuration.md` da un ejemplo, se anota. Mientras no existan en `FieldLimits`, no son canónicas.

| Constante propuesta | Valor propuesto | Columnas | Nota |
|---|---|---|---|
| `FieldLimits.REASON_MIN_LENGTH` | 10 | `ai.recommendation_decisions.reason`, `alerts.alert_rules.change_reason`, `alerts.alert_status_history.note`, `alerts.alerts.resolution_note`, `audit.audit_log.reason`, `care.follow_ups.result_note` y 14 más | Mínimo de un motivo (RF-70: 10 a 500 caracteres). Se generaliza a todo motivo. |
| `FieldLimits.REASON_MAX_LENGTH` | 500 | `ai.recommendation_decisions.reason`, `alerts.alert_rules.change_reason`, `alerts.alert_status_history.note`, `alerts.alerts.resolution_note`, `audit.audit_log.reason`, `care.follow_ups.result_note` y 15 más | Máximo de un motivo (RF-70). |
| `FieldLimits.CLINIC_NAME_MAX_LENGTH` | 120 | `clinic.clinics.name` | Nombre de clínica. |
| `FieldLimits.TAX_ID_MAX_LENGTH` | 32 | `clinic.clinics.tax_id` | Identificación fiscal. |
| `FieldLimits.TIMEZONE_MAX_LENGTH` | 64 | `clinic.clinics.timezone` | Nombre de zona IANA. |
| `FieldLimits.SITE_NAME_MAX_LENGTH` | 120 | `clinic.sites.name` | Nombre de sede. |
| `FieldLimits.STAFF_FULL_NAME_MAX_LENGTH` | 120 | `clinic.staff_profiles.full_name` | Nombre del personal. |
| `FieldLimits.PROFESSIONAL_LICENSE_MAX_LENGTH` | 40 | `clinic.staff_profiles.professional_license` | Registro profesional. |
| `FieldLimits.SPECIALTY_MAX_LENGTH` | 80 | `clinic.staff_profiles.specialty` | Especialidad. |
| `FieldLimits.MRN_MAX_LENGTH` | 40 | `clinic.import_rows.mrn`, `clinic.patients.mrn` | Número de historia (`DEMO-000001` cabe de sobra). |
| `FieldLimits.PATIENT_FULL_NAME_MAX_LENGTH` | 120 | `clinic.patients.full_name` | Nombre del paciente (valor de ejemplo de `configuration.md`). |
| `FieldLimits.PHONE_MAX_LENGTH` | 32 | `clinic.patients.contact_phone` | Teléfono. |
| `FieldLimits.PRIVACY_VERSION_MAX_LENGTH` | 20 | `clinic.privacy_notice_versions.version` | Etiqueta de versión del aviso de privacidad. |
| `FieldLimits.SIMULATOR_VERSION_MAX_LENGTH` | 40 | `ai.model_versions.simulator_version`, `clinic.import_batches.simulator_version` | Versión del simulador. |
| `FieldLimits.PROFILE_LABEL_MAX_LENGTH` | 120 | `care.target_profiles.label` | Etiqueta de un perfil de metas. |
| `FieldLimits.SOURCE_REFERENCE_MAX_LENGTH` | 300 | `care.target_profiles.source_reference` | Cita de la fuente de una semilla clínica. |
| `FieldLimits.TEMPLATE_NAME_MAX_LENGTH` | 120 | `care.protocol_templates.name` | Nombre de plantilla de protocolo. |
| `FieldLimits.INSTRUCTIONS_MAX_LENGTH` | 500 | `care.protocol_templates.description`, `care.treatment_plan_items.instructions` | Descripción o indicaciones de plantillas e ítems del plan. |
| `FieldLimits.PLAN_NOTES_MAX_LENGTH` | 1000 | `care.treatment_plans.notes` | Notas de un plan. |
| `FieldLimits.PLAN_ITEM_NAME_MAX_LENGTH` | 120 | `care.treatment_plan_items.name` | Nombre de un ítem del plan. |
| `FieldLimits.FOLLOW_UP_TITLE_MAX_LENGTH` | 120 | `care.follow_ups.title` | Título de un control o tarea de contacto. |
| `FieldLimits.CLINICAL_NOTE_MAX_LENGTH` | 2000 | `care.clinical_notes.body` | Texto de una nota clínica. |
| `FieldLimits.SYMPTOM_LABEL_MAX_LENGTH` | 80 | `care.symptom_catalog.label_es` | Etiqueta de un síntoma. |
| `FieldLimits.GLUCOSE_NOTE_MAX_LENGTH` | 500 | `monitoring.glucose_readings.note` | Nota de una lectura de glucosa (valor de ejemplo de `configuration.md`). |
| `FieldLimits.RECORD_NOTE_MAX_LENGTH` | 500 | `monitoring.insulin_doses.note`, `monitoring.meals.note`, `monitoring.physical_activities.note`, `monitoring.symptoms.note` | Nota de insulina, comida, actividad y síntoma. |
| `FieldLimits.INSULIN_PRODUCT_NAME_MAX_LENGTH` | 80 | `monitoring.insulin_doses.product_name` | Producto de insulina. |
| `FieldLimits.ACTIVITY_TYPE_MAX_LENGTH` | 40 | `monitoring.physical_activities.activity_type` | Tipo de actividad física. |
| `FieldLimits.ALERT_NAME_MAX_LENGTH` | 120 | `alerts.alert_rules.name` | Nombre de una regla de alerta. |
| `FieldLimits.PATIENT_NOTICE_MAX_LENGTH` | 300 | `alerts.alert_rules.patient_notice` | Aviso al paciente de una regla. |
| `FieldLimits.PUSH_ENDPOINT_MAX_LENGTH` | 2048 | `alerts.push_subscriptions.endpoint` | URL de un endpoint Web Push. |
| `FieldLimits.MODEL_NAME_MAX_LENGTH` | 80 | `ai.ai_evaluations.baseline_name`, `ai.ai_evaluations.model_name`, `ai.assistant_messages.model_name`, `ai.clinical_summaries.model_name`, `ai.glucose_forecasts.model_name`, `ai.model_versions.model_name` y 3 más | Nombre de modelo de IA. |
| `FieldLimits.MODEL_VERSION_MAX_LENGTH` | 80 | `ai.ai_evaluations.model_version`, `ai.assistant_messages.model_version`, `ai.clinical_summaries.model_version`, `ai.glucose_forecasts.model_version`, `ai.model_versions.model_version`, `ai.pattern_findings.model_version` y 3 más | Versión de modelo de IA. |
| `FieldLimits.ASSISTANT_MESSAGE_MAX_LENGTH` | 1000 | `ai.assistant_messages.content` | Mensaje del asistente educativo. |
| `FieldLimits.KNOWLEDGE_TITLE_MAX_LENGTH` | 160 | `ai.knowledge_documents.title` | Título de material educativo. |
| `FieldLimits.MESSAGE_BODY_MAX_LENGTH` | 1000 | `messaging.messages.body` | Mensaje entre paciente y equipo. |

Columnas con longitud técnica que no responden a una entrada de la API y no se comparan con `FieldLimits`: `password_hash` y `password_history.password_hash` (`varchar(255)`, formato PHC), los tipos `varchar` de enumeraciones (calculados por el valor más largo del `CHECK`), `code` de catálogos (`varchar(32)` o `varchar(40)`), `message_key` (`varchar(60)`), `issue_codes`, `guardrails_triggered`, `changed_fields` y los `*_error_code`.

Límites que `Seguridad.md` fija para cuerpos, importaciones y encabezados (`BODY_MAX_BYTES`, `IMPORT_*`, `AUTH_HEADER_MAX_BYTES`, `CREDENTIAL_BATCH_MAX_ITEMS`) son de la API y no de la base.

## 3. Valores de las enumeraciones

Los valores válidos de cada enumeración están en el `CHECK` de la columna. Resumen de las que más se reutilizan:

| Enumeración | Valores | Columnas |
|---|---|---|
| Rol (`role`) | `PLATFORM_ADMIN`, `CLINIC_ADMIN`, `DOCTOR`, `PATIENT` (y `SYSTEM` solo como `app.role` y como actor) | `iam.roles.code`, `audit.*.actor_role` |
| Estado de la cuenta | `IMPORTED`, `INVITED`, `ACTIVE`, `SUSPENDED`, `DEACTIVATED` | `iam.users.status` |
| Estado de la invitación | `PENDING`, `VERIFIED`, `USED`, `EXPIRED`, `REVOKED`, `LOCKED` | `iam.credential_invitations.status` |
| Fuente de glucosa | `CGM`, `SMBG`, `MANUAL` | `monitoring.glucose_readings.source` |
| Contexto de glucosa | `FASTING`, `PRE_MEAL`, `POST_MEAL`, `BEDTIME`, `EXERCISE`, `OTHER` | `monitoring.glucose_readings.context` |
| Estado de la lectura | `ACCEPTED`, `FLAGGED` | `monitoring.glucose_readings.status` |
| Estado de una alerta | `OPEN`, `ACKNOWLEDGED`, `ESCALATED`, `RESOLVED` | `alerts.alerts.status` |
| Estado de una recomendación | `PROPOSED`, `APPROVED`, `APPROVED_WITH_CHANGES`, `REJECTED`, `APPLIED`, `EXPIRED` | `ai.recommendations.status` |
| Estado de un plan | `DRAFT`, `ACTIVE`, `SUPERSEDED`, `DISCARDED` | `care.treatment_plans.status` |
| Estado de una versión (perfil, plantilla, regla, parámetros) | `DRAFT`, `ACTIVE`, `RETIRED` | `care.target_profiles`, `care.protocol_templates`, `alerts.alert_rules`, `care.reading_validation_settings` |
| Motivo de respaldo de IA | `AI_TIMEOUT`, `CIRCUIT_OPEN`, `AI_ERROR`, `INSUFFICIENT_DATA` | `ai.*.fallback_reason` |


## 4. Esquema `iam`: Identidad y acceso

### `iam.roles`

Catálogo de roles del sistema (RBAC). Semilla de `insumap-database`; el código verifica permisos, nunca nombres de rol.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `code` | `varchar(32)` | No |  | UNIQUE; CHECK IN ('PLATFORM_ADMIN','CLINIC_ADMIN','DOCTOR','PATIENT') | Código del rol (inglés, mayúsculas). |
| `name_es` | `varchar(80)` | No |  |  | Nombre visible en español. |
| `description` | `varchar(300)` | No |  |  | Descripción del rol. |
| `requires_mfa` | `boolean` | No |  |  | Verdadero para todo rol distinto de `PATIENT` (MFA TOTP obligatorio). |
| `created_at` | `timestamptz` | No | `now()` |  | Fecha de creación (UTC). |

Unicidad y reglas entre columnas: `code`.

### `iam.permissions`

Catálogo de códigos de permiso (`dominio.accion` o `dominio.accion_alcance`). Semilla con el catálogo de `Actores-y-permisos.md`.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `code` | `varchar(64)` | No |  | UNIQUE; CHECK ~ '^[a-z][a-z_]*(\.[a-z][a-z_]*)+$' | Código del permiso, por ejemplo `glucose.write_own`. |
| `description` | `varchar(300)` | No |  |  | Qué permite el permiso. |
| `module` | `varchar(3)` | No |  | CHECK ~ '^M(1[0-3]\|[1-9])$' | Módulo funcional (`M1` a `M13`). |
| `created_at` | `timestamptz` | No | `now()` |  | Fecha de creación (UTC). |

Unicidad y reglas entre columnas: `code`.

### `iam.role_permissions`

Matriz rol por permiso. La presencia de la fila concede el permiso; lo que no está, está denegado. Cambiarla no exige despliegue (caché de 60 s).

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `role_id` | `uuid` | No |  | PK; FK iam.roles(id) | Rol. |
| `permission_id` | `uuid` | No |  | PK; FK iam.permissions(id) | Permiso concedido. |
| `created_at` | `timestamptz` | No | `now()` |  | Fecha de creación (UTC). |

Unicidad y reglas entre columnas: PK compuesta (`role_id`, `permission_id`).

### `iam.users`

Identidad y credenciales de toda persona con cuenta: personal y pacientes (la cuenta `IMPORTED` ya tiene fila, sin contraseña ni correo). El estado de la cuenta del paciente (`PatientAccountState`, P18) vive aquí.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `email` | `varchar(254)` | Sí |  | FieldLimits.EMAIL_MAX_LENGTH | Correo de login tal como lo escribió la persona. Nulo hasta la activación del paciente importado. |
| `email_normalized` | `varchar(254)` | Sí |  | UNIQUE parcial (WHERE NOT NULL); FieldLimits.EMAIL_MAX_LENGTH; CHECK (email IS NULL) = (email_normalized IS NULL) | Correo normalizado (NFKC, recortado, minúsculas). Es el identificador de login. |
| `email_verified_at` | `timestamptz` | Sí |  |  | Momento de la verificación del correo. Nulo si no está verificado. |
| `password_hash` | `varchar(255)` | Sí |  |  | Hash Argon2id en formato PHC. Nulo en cuentas `IMPORTED` e `INVITED`. Columna S. |
| `password_changed_at` | `timestamptz` | Sí |  |  | Último cambio de contraseña. |
| `token_version` | `integer` | No | `0` | CHECK >= 0 | `tv` del JWT. Se incrementa para cortar de inmediato todos los access tokens. |
| `status` | `varchar(16)` | No | `'IMPORTED'` | CHECK IN ('IMPORTED','INVITED','ACTIVE','SUSPENDED','DEACTIVATED') | Estado de la cuenta. Para el personal, `is_active` equivale a `status = 'ACTIVE'`. |
| `status_reason` | `varchar(500)` | Sí |  | CHECK char_length BETWEEN REASON_MIN_LENGTH AND REASON_MAX_LENGTH | Motivo del último cambio a `SUSPENDED` o `DEACTIVATED` (obligatorio en esos estados). |
| `status_changed_at` | `timestamptz` | No | `now()` |  | Fecha del último cambio de estado. |
| `last_login_at` | `timestamptz` | Sí |  |  | Último inicio de sesión completo. |
| `is_system` | `boolean` | No | `false` |  | Verdadero solo para el usuario de sistema que siembra la BD (jobs). Sin contraseña ni membresía. |
| `created_at` | `timestamptz` | No | `now()` |  | Fecha de creación (UTC). |
| `updated_at` | `timestamptz` | No | `now()` |  | Fecha de la última modificación (UTC). |
| `lock_version` | `integer` | No | `0` | CHECK >= 0 | Versión para el bloqueo optimista (`409` si no coincide). |

Unicidad y reglas entre columnas: `email_normalized` (índice único parcial `WHERE email_normalized IS NOT NULL`).

### `iam.memberships`

Vínculo de una persona con una clínica y un rol. En el MVP cada usuario tiene una sola membresía (`user_id` único): un usuario pertenece a una clínica. El `PLATFORM_ADMIN` tiene una membresía sin clínica.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `user_id` | `uuid` | No |  | FK iam.users(id); UNIQUE | Usuario. La unicidad impone una clínica por usuario (relajable en una versión futura). |
| `clinic_id` | `uuid` | Sí |  | FK clinic.clinics(id) | Clínica. Nulo solo para `PLATFORM_ADMIN` (lo valida un trigger contra el rol). |
| `role_id` | `uuid` | No |  | FK iam.roles(id) | Rol del usuario en esa clínica. |
| `is_active` | `boolean` | No | `true` |  | Falso si la membresía terminó. |
| `ended_at` | `timestamptz` | Sí |  | CHECK (ended_at IS NULL) = (NOT is_active) | Momento en que terminó la membresía. |
| `ended_reason` | `varchar(500)` | Sí |  | CHECK char_length BETWEEN REASON_MIN_LENGTH AND REASON_MAX_LENGTH | Motivo de la baja. |
| `created_at` | `timestamptz` | No | `now()` |  | Fecha de creación (UTC). |
| `updated_at` | `timestamptz` | No | `now()` |  | Fecha de la última modificación (UTC). |

Unicidad y reglas entre columnas: `user_id` (una membresía por usuario).

### `iam.credential_invitations`

Invitaciones de un solo uso: activación de paciente, activación de personal y restablecimiento entregado en papel. El código nunca se guarda en claro.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `clinic_id` | `uuid` | No |  | FK clinic.clinics(id) | Clínica dueña de la fila (tenant). La RLS filtra por esta columna. |
| `user_id` | `uuid` | No |  | FK iam.users(id) | Cuenta invitada. |
| `patient_id` | `uuid` | Sí |  | FK clinic.patients(id) | Paciente invitado. Nulo para invitaciones de personal. |
| `purpose` | `varchar(20)` | No |  | CHECK IN ('PATIENT_ACTIVATION','STAFF_ACTIVATION','PASSWORD_RESET') | Propósito de la invitación. |
| `channel` | `varchar(5)` | No |  | CHECK IN ('PRINT','EMAIL') | Canal de entrega (`STAFF_ACTIVATION` solo usa `EMAIL`). |
| `status` | `varchar(8)` | No | `'PENDING'` | CHECK IN ('PENDING','VERIFIED','USED','EXPIRED','REVOKED','LOCKED') | Estado de la invitación. |
| `code_hash` | `char(64)` | No |  | UNIQUE | HMAC-SHA256 hexadecimal del código normalizado, con subllave HKDF de `CODE_HMAC_KEY`. Columna S. |
| `code_key_id` | `char(16)` | No |  |  | Huella de la llave con que se calculó `code_hash`. |
| `failed_attempts` | `smallint` | No | `0` | CHECK >= 0 | Fallos de fecha de nacimiento con un código válido. Al llegar a `ACTIVATION_MAX_ATTEMPTS` pasa a `LOCKED`. |
| `expires_at` | `timestamptz` | No |  | CHECK expires_at > issued_at | Vencimiento (7 días desde la emisión, `ACTIVATION_CODE_TTL_HOURS`). |
| `issued_by` | `uuid` | No |  | FK iam.users(id) | Quien emitió la invitación (`credentials.issue`). |
| `issued_at` | `timestamptz` | No | `now()` |  | Momento de la emisión. |
| `verified_at` | `timestamptz` | Sí |  |  | Paso 1 de la activación superado. |
| `used_at` | `timestamptz` | Sí |  |  | Invitación consumida. |
| `revoked_at` | `timestamptz` | Sí |  |  | Invitación revocada o reemplazada. |
| `revoked_by` | `uuid` | Sí |  | FK iam.users(id) | Quien la revocó. Nulo si la reemplazó el sistema. |
| `replaced_by_id` | `uuid` | Sí |  | FK iam.credential_invitations(id) | Invitación nueva que la reemplazó. |
| `delivery_status` | `varchar(14)` | No | `'NOT_APPLICABLE'` | CHECK IN ('NOT_APPLICABLE','PENDING','SENT','FAILED') | Resultado del envío por correo. `FAILED` queda registrado; reintentar es emitir de nuevo. |
| `delivery_error_code` | `varchar(40)` | Sí |  |  | Código del fallo de envío, sin datos personales. |
| `created_at` | `timestamptz` | No | `now()` |  | Fecha de creación (UTC). |

Unicidad y reglas entre columnas: `code_hash`; Una invitación vigente por cuenta y propósito: único parcial (`user_id`, `purpose`) `WHERE status IN ('PENDING','VERIFIED')` (equivale a una por paciente).

### `iam.auth_challenges` (propuesta)

Retos y tokens de vida corta y un solo uso: sesión de activación, reto de MFA, restablecimiento de contraseña por enlace y verificación de correo (propuesta, Seguridad 21 #8). Solo guarda el SHA-256 del token.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `purpose` | `varchar(18)` | No |  | CHECK IN ('ACTIVATION','MFA','PASSWORD_RESET','EMAIL_VERIFICATION') | Para qué sirve el token. |
| `token_hash` | `char(64)` | No |  | UNIQUE | SHA-256 hexadecimal del token opaco de 256 bits. Columna S. |
| `user_id` | `uuid` | No |  | FK iam.users(id) | Cuenta a la que pertenece el reto. |
| `clinic_id` | `uuid` | Sí |  | FK clinic.clinics(id) | Clínica de la cuenta, si la tiene (informativa, sin RLS). |
| `invitation_id` | `uuid` | Sí |  | FK iam.credential_invitations(id) | Invitación que origina una sesión de activación. |
| `attempts` | `smallint` | No | `0` | CHECK >= 0 | Intentos fallidos sobre este reto. |
| `max_attempts` | `smallint` | No |  | CHECK > 0 | Máximo de intentos (`MFA_CHALLENGE_MAX_ATTEMPTS` para el reto MFA). |
| `expires_at` | `timestamptz` | No |  |  | Vencimiento: 15 min (activación), 5 min (MFA), 30 min (restablecimiento) o 24 h (correo). |
| `consumed_at` | `timestamptz` | Sí |  |  | Momento de uso. Un token usado no sirve de nuevo. |
| `ip_hmac` | `char(64)` | Sí |  |  | HMAC-SHA256 de la IP (nunca la IP en claro). |
| `created_at` | `timestamptz` | No | `now()` |  | Fecha de creación (UTC). |

Unicidad y reglas entre columnas: `token_hash`.

### `iam.refresh_tokens`

Refresh tokens opacos con rotación y detección de reutilización. Se guarda solo el SHA-256; una familia (`family_id`) viaja como `sid` en el JWT.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `user_id` | `uuid` | No |  | FK iam.users(id) | Dueño del token. |
| `clinic_id` | `uuid` | Sí |  | FK clinic.clinics(id) | Clínica del usuario (nulo para `PLATFORM_ADMIN`). Permite revocar por clínica suspendida. |
| `family_id` | `uuid` | No |  |  | Familia de rotación creada en cada login. |
| `token_hash` | `char(64)` | No |  | UNIQUE | SHA-256 hexadecimal del token. Columna S. |
| `issued_at` | `timestamptz` | No | `now()` |  | Emisión. |
| `expires_at` | `timestamptz` | No |  |  | Vence a los 30 días de inactividad (paciente) o a las 12 horas (personal). |
| `family_expires_at` | `timestamptz` | No |  |  | Vida absoluta de la familia: 90 días (paciente) o 12 horas (personal). |
| `revoked_at` | `timestamptz` | Sí |  |  | Momento de la revocación. |
| `revoked_reason` | `varchar(20)` | Sí |  | CHECK IN ('ROTATED','LOGOUT','LOGOUT_ALL','PASSWORD_CHANGED','ROLE_CHANGED','ACCOUNT_SUSPENDED','ACCOUNT_DEACTIVATED','CLINIC_SUSPENDED','MFA_RESET','REUSE_DETECTED','ADMIN'); CHECK (revoked_at IS NULL) = (revoked_reason IS NULL) | Motivo de la revocación. |
| `replaced_by_id` | `uuid` | Sí |  | FK iam.refresh_tokens(id) | Token que lo reemplazó al rotar. |
| `ip_hmac` | `char(64)` | Sí |  |  | HMAC-SHA256 de la IP de emisión. |
| `created_at` | `timestamptz` | No | `now()` |  | Fecha de creación (UTC). |

Unicidad y reglas entre columnas: `token_hash`.

### `iam.mfa_factors`

Segundo factor del personal: secreto TOTP cifrado y códigos de respaldo de un solo uso. Los códigos de respaldo van aquí con `factor_type = 'RECOVERY_CODE'` (una fila por código).

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `user_id` | `uuid` | No |  | FK iam.users(id) | Dueño del factor. |
| `factor_type` | `varchar(13)` | No |  | CHECK IN ('TOTP','RECOVERY_CODE') | Tipo de factor. |
| `secret_ciphertext` | `bytea` | Sí |  | CHECK (factor_type = 'TOTP') = (secret_ciphertext IS NOT NULL) | Secreto TOTP cifrado con AES-256-GCM (`MFA_ENCRYPTION_KEY`; AAD `iam.mfa_factors.secret\|<factor_id>\|<user_id>`). Columna S. |
| `code_hash` | `char(64)` | Sí |  | UNIQUE parcial; CHECK (factor_type = 'RECOVERY_CODE') = (code_hash IS NOT NULL) | HMAC-SHA256 del código de respaldo (subllave HKDF de `CODE_HMAC_KEY`). Columna S. |
| `key_id` | `char(16)` | No |  |  | Huella de la llave de cifrado o de HMAC usada. |
| `last_used_step` | `bigint` | Sí |  |  | Último paso TOTP aceptado (anti-repetición): se rechaza un paso menor o igual. |
| `confirmed_at` | `timestamptz` | Sí |  |  | El factor TOTP queda activo al confirmar un código válido. Nulo mientras está en enrolamiento. |
| `used_at` | `timestamptz` | Sí |  |  | Uso de un código de respaldo. |
| `revoked_at` | `timestamptz` | Sí |  |  | Factor invalidado (restablecimiento de MFA o regeneración de códigos). |
| `created_at` | `timestamptz` | No | `now()` |  | Fecha de creación (UTC). |

Unicidad y reglas entre columnas: Un TOTP activo por usuario: único parcial (`user_id`) `WHERE factor_type = 'TOTP' AND revoked_at IS NULL`; `code_hash` (único parcial `WHERE code_hash IS NOT NULL`).

### `iam.login_attempts`

Registro de cada intento de login, exista o no la cuenta. Se escribe en una transacción propia que se confirma aunque la petición falle.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `occurred_at` | `timestamptz` | No | `now()` |  | Momento del intento. |
| `user_id` | `uuid` | Sí |  | FK iam.users(id) | Cuenta, si el correo existe. |
| `email_hmac` | `char(64)` | No |  |  | HMAC-SHA256 (`APP_HMAC_KEY`) del correo normalizado. Nunca el correo en claro. |
| `ip_hmac` | `char(64)` | No |  |  | HMAC-SHA256 de la IP. Nunca la IP en claro. |
| `outcome` | `varchar(7)` | No |  | CHECK IN ('SUCCESS','FAILURE') | Resultado. |
| `reason` | `varchar(20)` | Sí |  | CHECK IN ('INVALID_CREDENTIALS','LOCKED','NOT_ACTIVE','RATE_LIMITED','MFA_FAILED'); CHECK (outcome = 'SUCCESS') = (reason IS NULL) | Motivo del fallo. |
| `request_id` | `varchar(64)` | Sí |  | FieldLimits.REQUEST_ID_MAX_LENGTH | Correlación con los logs. |

### `iam.login_lockouts` (propuesta)

Estado del bloqueo escalonado: nivel y fin del bloqueo por pareja (correo, IP) y global por correo. Guarda el nivel que Seguridad 2.2 exige recordar entre bloqueos (propuesta).

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `scope` | `varchar(7)` | No |  | CHECK IN ('PAIR','ACCOUNT') | Bloqueo por pareja (correo, IP) o global del correo. |
| `key_hmac` | `char(64)` | No |  |  | HMAC de `scope:valor` (correo, o correo con IP). Nunca datos en claro. |
| `level` | `smallint` | No | `0` | CHECK >= 0 | Nivel de escalamiento; cada nivel duplica el bloqueo hasta el tope. |
| `locked_until` | `timestamptz` | Sí |  |  | Fin del bloqueo vigente. Nulo si no hay bloqueo. |
| `last_failure_at` | `timestamptz` | Sí |  |  | Último fallo contado. |
| `reset_at` | `timestamptz` | Sí |  |  | Último reinicio por ingreso exitoso o desbloqueo. |
| `updated_at` | `timestamptz` | No | `now()` |  | Fecha de la última modificación (UTC). |

Unicidad y reglas entre columnas: (`scope`, `key_hmac`).

### `iam.password_history`

Hashes de las últimas contraseñas para impedir su reutilización (`PASSWORD_HISTORY_SIZE` = 5).

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `user_id` | `uuid` | No |  | FK iam.users(id) | Dueño de la contraseña. |
| `password_hash` | `varchar(255)` | No |  |  | Hash Argon2id anterior. Columna S. |
| `created_at` | `timestamptz` | No | `now()` |  | Fecha de creación (UTC). |

### `iam.security_events`

Eventos de seguridad (reutilización de refresh, bloqueos, MFA, activaciones, cambios de rol, límites de tasa). Los eventos sin clínica van aquí y nunca a `audit.audit_log`.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `occurred_at` | `timestamptz` | No | `now()` |  | Momento del evento. |
| `event_type` | `varchar(40)` | No |  | CHECK IN (catálogo de la sección 7.3 de Seguridad) | Tipo: `AUDIT_CHAIN_BROKEN`, `REFRESH_TOKEN_REUSE_DETECTED`, `ACCOUNT_LOCKED`, `MFA_RESET`, `LLM_DATA_POLICY_BLOCKED`, `MFA_FAILED`, `MFA_RECOVERY_CODE_USED`, `PERMISSION_DENIED`, `PHI_ACCESS_DENIED`, `ACTIVATION_LOCKED`, `PUSH_ENDPOINT_REJECTED`, `CSRF_CHECK_FAILED`, `LOGIN_FAILED`, `ACCOUNT_UNLOCKED`, `ACTIVATION_FAILED`, `ACCOUNT_ACTIVATED`, `ROLE_CHANGED`, `RATE_LIMITED`, `PASSWORD_CHANGED`, `PASSWORD_RESET_REQUESTED`, `SESSIONS_REVOKED`, `IMPORT_REJECTED`, `SECRET_ROTATED`. |
| `severity` | `varchar(8)` | No |  | CHECK IN ('LOW','MEDIUM','HIGH','CRITICAL') | Severidad según Seguridad 7.3. |
| `user_id` | `uuid` | Sí |  | FK iam.users(id) | Usuario involucrado, si existe. |
| `clinic_id` | `uuid` | Sí |  | FK clinic.clinics(id) | Clínica, si existe. Nulo en eventos previos al contexto (por ejemplo, login con correo inexistente). |
| `ip_truncated` | `cidr` | Sí |  |  | IP truncada (/24 en IPv4, /48 en IPv6). La consola de plataforma la muestra. |
| `ip_hmac` | `char(64)` | Sí |  |  | HMAC-SHA256 de la IP completa, para correlacionar. |
| `request_id` | `varchar(64)` | Sí |  | FieldLimits.REQUEST_ID_MAX_LENGTH | Correlación con los logs. |
| `details` | `jsonb` | No | `'{}'::jsonb` | CHECK jsonb_typeof = 'object' | Detalle ya redactado: sin secretos, códigos, correos, nombres ni valores clínicos. |

### `iam.rate_limit_buckets` (propuesta)

Contadores de ventana fija para los límites de tasa críticos (login, MFA, activación, restablecimiento, refresh, emisión, importación, IA, reportes). Un `INSERT ... ON CONFLICT DO UPDATE ... RETURNING` es atómico y compartido entre instancias (propuesta, Seguridad 12).

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `family` | `varchar(40)` | No |  | PK | Familia del límite (por ejemplo `LOGIN_IP`). |
| `key_hmac` | `char(64)` | No |  | PK | HMAC (`APP_HMAC_KEY`) de `familia:valor`. No guarda IPs ni correos en claro. |
| `window_start` | `timestamptz` | No |  | PK | Inicio de la ventana fija. |
| `hits` | `integer` | No | `1` | CHECK > 0 | Peticiones contadas en la ventana. |
| `limit_event_logged` | `boolean` | No | `false` |  | Evita registrar `RATE_LIMITED` más de una vez por clave y ventana. |

Unicidad y reglas entre columnas: PK compuesta (`family`, `key_hmac`, `window_start`).

## 5. Esquema `clinic`: Clínicas, personas y onboarding

### `clinic.clinics`

Clínica contratante (tenant). La bandera `is_demo` marca la clínica de "Datos simulados". Es la raíz de todo `clinic_id`.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `name` | `varchar(120)` | No |  | UNIQUE (`lower(name)`); FieldLimits.CLINIC_NAME_MAX_LENGTH (propuesta) | Nombre de la clínica. Repetido responde `409 CONFLICT`. |
| `tax_id` | `varchar(32)` | No |  | FieldLimits.TAX_ID_MAX_LENGTH (propuesta) | Identificación fiscal. |
| `timezone` | `varchar(64)` | No |  | FieldLimits.TIMEZONE_MAX_LENGTH (propuesta); validada contra `pg_timezone_names` | Zona IANA de la clínica (por ejemplo `America/Bogota`). Base de los cálculos por día y de la noche. |
| `status` | `varchar(9)` | No | `'ACTIVE'` | CHECK IN ('ACTIVE','SUSPENDED') | Estado de la clínica. |
| `suspended_at` | `timestamptz` | Sí |  | CHECK (status = 'SUSPENDED') = (suspended_at IS NOT NULL) | Momento de la suspensión. |
| `suspended_reason` | `varchar(500)` | Sí |  | CHECK char_length BETWEEN REASON_MIN_LENGTH AND REASON_MAX_LENGTH | Motivo de la suspensión. |
| `is_demo` | `boolean` | No | `false` |  | Verdadero para la clínica de datos simulados. Solo ahí se aceptan Bundles `SIMULATED` y se envía a la IA con LLM. |
| `created_at` | `timestamptz` | No | `now()` |  | Fecha de creación (UTC). |
| `updated_at` | `timestamptz` | No | `now()` |  | Fecha de la última modificación (UTC). |
| `lock_version` | `integer` | No | `0` | CHECK >= 0 | Versión para el bloqueo optimista (`409` si no coincide). |

Unicidad y reglas entre columnas: `lower(name)` (índice único funcional).

### `clinic.sites`

Sedes de una clínica (Post-MVP, RF-15).

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `clinic_id` | `uuid` | No |  | FK clinic.clinics(id) | Clínica dueña de la fila (tenant). La RLS filtra por esta columna. |
| `name` | `varchar(120)` | No |  | FieldLimits.SITE_NAME_MAX_LENGTH (propuesta) | Nombre de la sede. |
| `is_active` | `boolean` | No | `true` |  | Falso si la sede se cerró. |
| `created_at` | `timestamptz` | No | `now()` |  | Fecha de creación (UTC). |
| `updated_at` | `timestamptz` | No | `now()` |  | Fecha de la última modificación (UTC). |

Unicidad y reglas entre columnas: (`clinic_id`, `lower(name)`).

### `clinic.staff_profiles`

Perfil profesional del personal (médicos y administradores). Relación 1:1 con `iam.users`.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `user_id` | `uuid` | No |  | PK; FK iam.users(id) | Usuario del personal. |
| `clinic_id` | `uuid` | No |  | FK clinic.clinics(id) | Clínica dueña de la fila (tenant). La RLS filtra por esta columna. |
| `full_name` | `varchar(120)` | No |  | FieldLimits.STAFF_FULL_NAME_MAX_LENGTH (propuesta) | Nombre completo (clase C). |
| `professional_license` | `varchar(40)` | Sí |  | FieldLimits.PROFESSIONAL_LICENSE_MAX_LENGTH (propuesta) | Registro profesional. Obligatorio para `DOCTOR` (lo valida la aplicación). |
| `specialty` | `varchar(80)` | Sí |  | FieldLimits.SPECIALTY_MAX_LENGTH (propuesta) | Especialidad. |
| `created_at` | `timestamptz` | No | `now()` |  | Fecha de creación (UTC). |
| `updated_at` | `timestamptz` | No | `now()` |  | Fecha de la última modificación (UTC). |

Unicidad y reglas entre columnas: PK (`user_id`); (`clinic_id`, `professional_license`) único parcial `WHERE professional_license IS NOT NULL`.

### `clinic.staff_sites` (propuesta)

Asociación muchos a muchos entre personal y sedes (Post-MVP, RF-15). Un médico puede pertenecer a varias sedes de su clínica.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `user_id` | `uuid` | No |  | PK; FK clinic.staff_profiles(user_id) | Personal. |
| `site_id` | `uuid` | No |  | PK; FK clinic.sites(id) | Sede. |
| `clinic_id` | `uuid` | No |  | FK clinic.clinics(id) | Clínica dueña de la fila (tenant). La RLS filtra por esta columna. |
| `created_at` | `timestamptz` | No | `now()` |  | Fecha de creación (UTC). |

Unicidad y reglas entre columnas: PK compuesta (`user_id`, `site_id`).

### `clinic.patients`

Paciente de una clínica: identidad (clase C), documento cifrado y con hash para búsqueda, y vínculo con su cuenta de `iam.users`. Los datos clínicos viven en `monitoring`, `care`, `alerts` y `ai`.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `clinic_id` | `uuid` | No |  | FK clinic.clinics(id) | Clínica dueña de la fila (tenant). La RLS filtra por esta columna. |
| `user_id` | `uuid` | No |  | FK iam.users(id); UNIQUE | Cuenta del paciente (se crea `IMPORTED` al importar). |
| `mrn` | `varchar(40)` | No |  | FieldLimits.MRN_MAX_LENGTH (propuesta) | Número de historia de la clínica. Clave de deduplicación (RF-19). |
| `full_name` | `varchar(120)` | No |  | FieldLimits.PATIENT_FULL_NAME_MAX_LENGTH (propuesta; ejemplo de `configuration.md`) | Nombre completo (clase C). |
| `birth_date` | `date` | No |  |  | Fecha de nacimiento. Obligatoria en la importación: es el segundo dato de la activación. |
| `sex` | `varchar(7)` | No | `'UNKNOWN'` | CHECK IN ('FEMALE','MALE','OTHER','UNKNOWN') | Sexo administrativo (FHIR `Patient.gender`). |
| `diabetes_type` | `varchar(5)` | No | `'OTHER'` | CHECK IN ('T1D','T2D','GDM','OTHER') | Tipo de diabetes (de `Condition` FHIR o del CSV). Selecciona la población del perfil de metas por defecto. |
| `diagnosis_date` | `date` | Sí |  |  | Fecha de diagnóstico, si se conoce. |
| `contact_email` | `varchar(254)` | Sí |  | FieldLimits.EMAIL_MAX_LENGTH | Correo de contacto traído de la importación (sin verificar, no único). El correo de login se fija al activar en `iam.users.email`. |
| `contact_phone` | `varchar(32)` | Sí |  | FieldLimits.PHONE_MAX_LENGTH (propuesta) | Teléfono de contacto (clase C). |
| `document_type` | `varchar(3)` | No |  | CHECK IN ('CC','TI','RC','CE','PA','PEP','PPT') (propuesta, a confirmar con `input-validation.md`) | Tipo de documento de identidad. |
| `document_hash` | `char(64)` | No |  | UNIQUE con `clinic_id` | HMAC-SHA256 (`LOOKUP_HMAC_KEY`) de `clinic_id`, tipo y número normalizado. Búsqueda y deduplicación. Columna S. |
| `document_hash_key_id` | `char(16)` | No |  |  | Huella de `LOOKUP_HMAC_KEY`. |
| `document_ciphertext` | `bytea` | No |  |  | Número de documento cifrado con AES-256-GCM: nonce (12 bytes), texto cifrado y tag (16 bytes). AAD `clinic.patients.document\|<patient_id>\|<clinic_id>`. Columna S. |
| `document_key_id` | `char(16)` | No |  |  | Huella de `FIELD_ENCRYPTION_KEY`. |
| `document_last4` | `varchar(4)` | No |  |  | Últimos 4 caracteres para mostrar `******1234` sin descifrar (clase C). |
| `import_batch_id` | `uuid` | Sí |  | FK clinic.import_batches(id) | Lote que lo creó. |
| `created_at` | `timestamptz` | No | `now()` |  | Fecha de creación (UTC). |
| `updated_at` | `timestamptz` | No | `now()` |  | Fecha de la última modificación (UTC). |
| `lock_version` | `integer` | No | `0` | CHECK >= 0 | Versión para el bloqueo optimista (`409` si no coincide). |

Unicidad y reglas entre columnas: (`clinic_id`, `mrn`); (`clinic_id`, `document_hash`); `user_id`.

### `clinic.care_team_assignments`

Asignación médico-paciente con historial. Es la fuente de `PatientRecordAccessProxy` (P11). Un paciente puede tener varios médicos y exactamente un principal vigente.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `clinic_id` | `uuid` | No |  | FK clinic.clinics(id) | Clínica dueña de la fila (tenant). La RLS filtra por esta columna. |
| `patient_id` | `uuid` | No |  | FK clinic.patients(id) | Paciente al que pertenece la fila. |
| `doctor_user_id` | `uuid` | No |  | FK clinic.staff_profiles(user_id) | Médico asignado (misma clínica). |
| `is_primary` | `boolean` | No | `false` |  | Médico principal vigente. |
| `assigned_by` | `uuid` | No |  | FK iam.users(id) | Administrador que asignó. |
| `assigned_at` | `timestamptz` | No | `now()` |  | Inicio de la asignación. |
| `ended_at` | `timestamptz` | Sí |  | CHECK ended_at >= assigned_at | Fin de la asignación. Vigente: `ended_at IS NULL` o en el futuro. El MVP solo escribe `now()` al retirar. |
| `ended_by` | `uuid` | Sí |  | FK iam.users(id) | Quien retiró la asignación. |
| `end_reason` | `varchar(500)` | Sí |  | CHECK char_length BETWEEN REASON_MIN_LENGTH AND REASON_MAX_LENGTH; CHECK (ended_at IS NULL) = (end_reason IS NULL) | Motivo del retiro o reasignación. |
| `created_at` | `timestamptz` | No | `now()` |  | Fecha de creación (UTC). |

Unicidad y reglas entre columnas: Un principal vigente por paciente: único parcial (`patient_id`) `WHERE is_primary AND ended_at IS NULL`; Una asignación abierta por (`patient_id`, `doctor_user_id`) `WHERE ended_at IS NULL`.

### `clinic.privacy_notice_versions` (propuesta)

Versiones del aviso de privacidad y del consentimiento de cada clínica (propuesta, Seguridad 3.4 y RF-90). El texto es versionado e inmutable.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `clinic_id` | `uuid` | No |  | FK clinic.clinics(id) | Clínica dueña de la fila (tenant). La RLS filtra por esta columna. |
| `version` | `varchar(20)` | No |  | FieldLimits.PRIVACY_VERSION_MAX_LENGTH (propuesta) | Etiqueta de la versión (por ejemplo `2026-11-01`). |
| `content` | `text` | No |  |  | Texto del aviso en español. |
| `content_sha256` | `char(64)` | No |  |  | SHA-256 del texto, para probar que no cambió. |
| `effective_from` | `timestamptz` | No |  |  | Desde cuándo rige. |
| `is_current` | `boolean` | No | `false` |  | Versión vigente. |
| `published_by` | `uuid` | No |  | FK iam.users(id) | Quien publicó la versión. |
| `created_at` | `timestamptz` | No | `now()` |  | Fecha de creación (UTC). |

Unicidad y reglas entre columnas: (`clinic_id`, `version`); Una vigente por clínica: único parcial (`clinic_id`) `WHERE is_current`.

### `clinic.patient_consents`

Historial de consentimientos del paciente por versión y alcance. Cada aceptación o retiro es una fila nueva; el consentimiento vigente es la última fila por paciente y alcance.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `clinic_id` | `uuid` | No |  | FK clinic.clinics(id) | Clínica dueña de la fila (tenant). La RLS filtra por esta columna. |
| `patient_id` | `uuid` | No |  | FK clinic.patients(id) | Paciente al que pertenece la fila. |
| `privacy_notice_version_id` | `uuid` | No |  | FK clinic.privacy_notice_versions(id) | Versión aceptada o retirada. |
| `scope` | `varchar(26)` | No |  | CHECK IN ('SENSITIVE_DATA_PROCESSING','AI_EXTERNAL_PROCESSING') | Alcance: tratamiento de datos sensibles (obligatorio) o procesamiento externo con IA (opcional). |
| `action` | `varchar(9)` | No |  | CHECK IN ('ACCEPTED','WITHDRAWN') | Aceptación o retiro. |
| `occurred_at` | `timestamptz` | No | `now()` |  | Momento del acto. |
| `ip_hmac` | `char(64)` | Sí |  |  | HMAC-SHA256 de la IP. |
| `recorded_by` | `uuid` | No |  | FK iam.users(id) | Cuenta que registró el acto (el paciente). |

### `clinic.privacy_requests` (propuesta)

Solicitudes de acceso, rectificación, supresión o retiro del paciente, con estado y plazo (Post-MVP, RF-93). Propuesta.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `clinic_id` | `uuid` | No |  | FK clinic.clinics(id) | Clínica dueña de la fila (tenant). La RLS filtra por esta columna. |
| `patient_id` | `uuid` | No |  | FK clinic.patients(id) | Paciente al que pertenece la fila. |
| `request_type` | `varchar(18)` | No |  | CHECK IN ('ACCESS','RECTIFICATION','ERASURE','CONSENT_WITHDRAWAL') | Tipo de solicitud. |
| `status` | `varchar(11)` | No | `'OPEN'` | CHECK IN ('OPEN','IN_PROGRESS','APPROVED','REJECTED','COMPLETED') | Estado de la solicitud. |
| `description` | `varchar(500)` | Sí |  | FieldLimits.REASON_MAX_LENGTH (propuesta) | Detalle que escribe el paciente. |
| `requested_at` | `timestamptz` | No | `now()` |  | Fecha de la solicitud. |
| `due_at` | `timestamptz` | No |  | CHECK due_at > requested_at | Plazo para responder (lo fija la normativa; por definir). |
| `resolved_at` | `timestamptz` | Sí |  |  | Cierre. |
| `resolved_by` | `uuid` | Sí |  | FK iam.users(id) | Quien tramitó. |
| `resolution_note` | `varchar(500)` | Sí |  | CHECK char_length BETWEEN REASON_MIN_LENGTH AND REASON_MAX_LENGTH | Resolución motivada. |
| `created_at` | `timestamptz` | No | `now()` |  | Fecha de creación (UTC). |
| `updated_at` | `timestamptz` | No | `now()` |  | Fecha de la última modificación (UTC). |

### `clinic.import_batches`

Lote de importación de pacientes (FHIR R4 o CSV) con totales, origen y autor. El archivo original no se guarda; se conserva su huella.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `clinic_id` | `uuid` | No |  | FK clinic.clinics(id) | Clínica dueña de la fila (tenant). La RLS filtra por esta columna. |
| `source_format` | `varchar(4)` | No |  | CHECK IN ('FHIR','CSV') | Formato del archivo. |
| `data_origin` | `varchar(9)` | No | `'REAL'` | CHECK IN ('REAL','SIMULATED') | Origen declarado. `SIMULATED` solo entra en clínicas con `is_demo = true`. |
| `status` | `varchar(10)` | No | `'PREVIEWED'` | CHECK IN ('PREVIEWED','COMPLETED','REJECTED','FAILED') | Estado: previsualizado, completado, rechazado (por ejemplo, simulados en clínica real) o fallido. |
| `file_sha256` | `char(64)` | No |  |  | SHA-256 del archivo, para reconocer una reimportación del mismo contenido. |
| `file_size_bytes` | `integer` | No |  | CHECK > 0 | Tamaño leído del cuerpo. |
| `simulator_version` | `varchar(40)` | Sí |  | FieldLimits.SIMULATOR_VERSION_MAX_LENGTH (propuesta) | Versión del simulador que consta en `Bundle.meta.source`. |
| `total_rows` | `integer` | No | `0` | CHECK >= 0 | Filas o entradas leídas. |
| `valid_rows` | `integer` | No | `0` | CHECK >= 0 | Filas válidas. |
| `warning_rows` | `integer` | No | `0` | CHECK >= 0 | Filas con advertencia. |
| `error_rows` | `integer` | No | `0` | CHECK >= 0 | Filas con error. |
| `created_rows` | `integer` | No | `0` | CHECK >= 0 | Pacientes creados. |
| `skipped_rows` | `integer` | No | `0` | CHECK >= 0 | Filas omitidas por duplicado (`SKIPPED_DUPLICATE`). |
| `created_by` | `uuid` | No |  | FK iam.users(id) | Administrador que importó. |
| `created_at` | `timestamptz` | No | `now()` |  | Fecha de creación (UTC). |
| `finished_at` | `timestamptz` | Sí |  |  | Cierre del lote. |

### `clinic.import_rows`

Resultado por fila de un lote: estado y códigos de incidencia. No guarda la fila cruda.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `clinic_id` | `uuid` | No |  | FK clinic.clinics(id) | Clínica dueña de la fila (tenant). La RLS filtra por esta columna. |
| `batch_id` | `uuid` | No |  | FK clinic.import_batches(id) | Lote. |
| `row_number` | `integer` | No |  | CHECK > 0 | Número de fila (CSV) o de entrada (FHIR). |
| `resource_type` | `varchar(24)` | Sí |  | CHECK IN ('Patient','Practitioner','Condition','Observation','MedicationRequest') | Tipo de recurso FHIR. Nulo en CSV. |
| `status` | `varchar(17)` | No |  | CHECK IN ('CREATED','UPDATED','SKIPPED_DUPLICATE','REJECTED','WARNING','UNSUPPORTED') | Resultado de la fila. |
| `issue_codes` | `varchar(40)[]` | No | `'{}'` |  | Códigos de incidencia (por ejemplo `MISSING_BIRTH_DATE`), sin datos personales. |
| `mrn` | `varchar(40)` | Sí |  | FieldLimits.MRN_MAX_LENGTH (propuesta) | MRN de la fila, para reportar duplicados. |
| `patient_id` | `uuid` | Sí |  | FK clinic.patients(id) | Paciente creado o actualizado. |
| `created_at` | `timestamptz` | No | `now()` |  | Fecha de creación (UTC). |

Unicidad y reglas entre columnas: (`batch_id`, `row_number`, `resource_type`) con `NULLS NOT DISTINCT`.

### `clinic.clinic_settings` (propuesta)

Parámetros operativos de negocio de la clínica, una fila por clínica (propuesta). Son datos configurables, nunca constantes del código.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `clinic_id` | `uuid` | No |  | PK; FK clinic.clinics(id) | Clínica. |
| `recommendation_expiry_hours` | `integer` | No |  | CHECK > 0 | Plazo para decidir una recomendación antes de `EXPIRED`. |
| `forecast_refresh_minutes` | `integer` | No |  | CHECK > 0 | Intervalo mínimo entre pronósticos de IA1 por paciente. |
| `dropout_inactivity_days` | `integer` | No |  | CHECK > 0 | Días sin registros para el respaldo por reglas de IA7 y la alerta de adherencia. |
| `kpi_min_cell_size` | `integer` | No |  | CHECK > 0 | Tamaño mínimo de celda en los KPI del administrador; las menores se agrupan. |
| `updated_by` | `uuid` | No |  | FK iam.users(id) | Último administrador que cambió los valores. |
| `updated_at` | `timestamptz` | No | `now()` |  | Fecha de la última modificación (UTC). |
| `lock_version` | `integer` | No | `0` | CHECK >= 0 | Versión para el bloqueo optimista (`409` si no coincide). |

Unicidad y reglas entre columnas: PK (`clinic_id`).

## 6. Esquema `care`: Plan de tratamiento, metas y seguimiento

### `care.target_profiles`

Perfiles de metas glucémicas versionados (TIR, TBR, TAR, CV, ayunas, posprandial, noche). Las semillas (`ADULT_STANDARD`, `OLDER_OR_HIGH_RISK`, `PREGNANCY_T1D`, `PREGNANCY_T2D_GDM`) traen `clinic_id` nulo; el `CLINIC_ADMIN` crea versiones propias. Ningún valor clínico es `DEFAULT` ni `CHECK`.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `clinic_id` | `uuid` | Sí |  | FK clinic.clinics(id) | Clínica dueña de la versión. Nulo en las semillas globales de solo lectura. |
| `code` | `varchar(40)` | No |  | CHECK ~ '^[A-Z][A-Z0-9_]*$' | Código del perfil (inglés). |
| `label` | `varchar(120)` | No |  | FieldLimits.PROFILE_LABEL_MAX_LENGTH (propuesta) | Etiqueta visible en español. |
| `population` | `varchar(20)` | No |  | CHECK IN ('ADULT','OLDER_OR_HIGH_RISK','PREGNANCY_T1D','PREGNANCY_T2D_GDM') | Población a la que aplica. |
| `version` | `integer` | No |  | CHECK > 0 | Número de versión por (`clinic_id`, `code`). |
| `status` | `varchar(7)` | No | `'DRAFT'` | CHECK IN ('DRAFT','ACTIVE','RETIRED') | Estado de la versión. Una `ACTIVE` es inmutable (trigger). |
| `is_default` | `boolean` | No | `false` |  | Perfil por defecto de su población. |
| `range_low_mg_dl` | `numeric(5,1)` | No |  | CHECK > 0 | Límite inferior del rango objetivo. |
| `range_high_mg_dl` | `numeric(5,1)` | No |  | CHECK > range_low_mg_dl | Límite superior del rango objetivo. |
| `very_low_mg_dl` | `numeric(5,1)` | No |  | CHECK > 0 AND < range_low_mg_dl | Umbral de nivel 2 de hipoglucemia. |
| `very_high_mg_dl` | `numeric(5,1)` | No |  | CHECK > range_high_mg_dl | Umbral de nivel 2 de hiperglucemia. |
| `tir_min_pct` | `numeric(5,2)` | No |  | CHECK BETWEEN 0 AND 100 | Meta mínima de tiempo en rango. |
| `tbr_l1_max_pct` | `numeric(5,2)` | No |  | CHECK BETWEEN 0 AND 100 | Máximo de tiempo bajo el rango (total bajo `range_low_mg_dl`). |
| `tbr_l2_max_pct` | `numeric(5,2)` | No |  | CHECK BETWEEN 0 AND 100 | Máximo de tiempo bajo `very_low_mg_dl`. |
| `tar_l1_max_pct` | `numeric(5,2)` | No |  | CHECK BETWEEN 0 AND 100 | Máximo de tiempo sobre el rango (total sobre `range_high_mg_dl`). |
| `tar_l2_max_pct` | `numeric(5,2)` | No |  | CHECK BETWEEN 0 AND 100 | Máximo de tiempo sobre `very_high_mg_dl`. |
| `cv_max_pct` | `numeric(5,2)` | No |  | CHECK BETWEEN 0 AND 100 | Máximo del coeficiente de variación. |
| `min_data_sufficiency_pct` | `numeric(5,2)` | No |  | CHECK BETWEEN 0 AND 100 | Suficiencia mínima de datos para reportar métricas. |
| `min_days` | `smallint` | No |  | CHECK > 0 | Días del periodo de referencia (por ejemplo, el AGP). |
| `max_gap_minutes` | `smallint` | No |  | CHECK > 0 | Máximo de minutos que una lectura representa antes de contar como hueco (`Δ_max`). |
| `hypo_episode_min_minutes` | `smallint` | No |  | CHECK > 0 | Minutos consecutivos bajo el umbral para contar un episodio de hipoglucemia. |
| `min_readings_for_cv` | `integer` | No |  | CHECK > 0 | Lecturas mínimas para calcular el CV con CGM. |
| `min_readings_for_cv_smbg` | `integer` | No |  | CHECK > 0 | Lecturas mínimas para estimar el CV con glucometría. |
| `hba1c_goal_pct` | `numeric(4,1)` | Sí |  | CHECK > 0 | Meta de HbA1c. |
| `fasting_low_mg_dl` | `numeric(5,1)` | Sí |  | CHECK > 0 | Meta de glucosa en ayunas, mínimo. |
| `fasting_high_mg_dl` | `numeric(5,1)` | Sí |  | CHECK >= fasting_low_mg_dl | Meta de glucosa en ayunas, máximo. |
| `postprandial_max_mg_dl` | `numeric(5,1)` | Sí |  | CHECK > 0 | Pico posprandial máximo. |
| `postprandial_1h_max_mg_dl` | `numeric(5,1)` | Sí |  | CHECK > 0 | Máximo a 1 hora posprandial (embarazo). |
| `postprandial_2h_max_mg_dl` | `numeric(5,1)` | Sí |  | CHECK > 0 | Máximo a 2 horas posprandial (embarazo). |
| `night_start` | `time` | No |  |  | Inicio de la ventana nocturna (hora local de la clínica). |
| `night_end` | `time` | No |  |  | Fin de la ventana nocturna (hora local). |
| `source_reference` | `varchar(300)` | No |  | FieldLimits.SOURCE_REFERENCE_MAX_LENGTH (propuesta) | Fuente de los valores (por ejemplo, Consenso 2019, Tabla 3; ADA 2026, Tabla 6.2). |
| `change_reason` | `varchar(500)` | Sí |  | CHECK char_length BETWEEN REASON_MIN_LENGTH AND REASON_MAX_LENGTH | Motivo de la versión nueva (obligatorio al activar una versión de clínica). |
| `created_by` | `uuid` | Sí |  | FK iam.users(id) | Autor. Nulo en las semillas. |
| `activated_at` | `timestamptz` | Sí |  |  | Momento de la activación. |
| `created_at` | `timestamptz` | No | `now()` |  | Fecha de creación (UTC). |

Unicidad y reglas entre columnas: (`clinic_id`, `code`, `version`) con `NULLS NOT DISTINCT`; Una `ACTIVE` por (`clinic_id`, `code`): único parcial `WHERE status = 'ACTIVE'` con `NULLS NOT DISTINCT`.

### `care.patient_target_assignments` (propuesta)

Historial del perfil de metas asignado a cada paciente (propuesta). Sin asignación vigente aplica el perfil por defecto de su población.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `clinic_id` | `uuid` | No |  | FK clinic.clinics(id) | Clínica dueña de la fila (tenant). La RLS filtra por esta columna. |
| `patient_id` | `uuid` | No |  | FK clinic.patients(id) | Paciente al que pertenece la fila. |
| `target_profile_id` | `uuid` | No |  | FK care.target_profiles(id) | Versión del perfil asignada. |
| `assigned_by` | `uuid` | No |  | FK iam.users(id) | Médico que asignó (`target_profiles.assign`). |
| `assigned_at` | `timestamptz` | No | `now()` |  | Inicio. |
| `ended_at` | `timestamptz` | Sí |  | CHECK ended_at >= assigned_at | Fin de la asignación. |
| `reason` | `varchar(500)` | Sí |  | CHECK char_length BETWEEN REASON_MIN_LENGTH AND REASON_MAX_LENGTH | Motivo del cambio. |

Unicidad y reglas entre columnas: Una vigente por paciente: único parcial (`patient_id`) `WHERE ended_at IS NULL`.

### `care.protocol_templates`

Plantillas de protocolo versionadas (prototipo P05 del contenido del plan). Las semillas traen `clinic_id` nulo; el `CLINIC_ADMIN` crea versiones propias.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `clinic_id` | `uuid` | Sí |  | FK clinic.clinics(id) | Clínica dueña. Nulo en las semillas globales. |
| `code` | `varchar(40)` | No |  | CHECK ~ '^[A-Z][A-Z0-9_]*$' | Código de la plantilla (inglés). |
| `name` | `varchar(120)` | No |  | FieldLimits.TEMPLATE_NAME_MAX_LENGTH (propuesta) | Nombre visible en español (dato de catálogo), por ejemplo "Basal-bolo adulto DM1". |
| `description` | `varchar(500)` | Sí |  | FieldLimits.INSTRUCTIONS_MAX_LENGTH (propuesta) | Descripción. |
| `diabetes_type` | `varchar(5)` | Sí |  | CHECK IN ('T1D','T2D','GDM','OTHER') | Tipo de diabetes al que apunta. |
| `version` | `integer` | No |  | CHECK > 0 | Versión por (`clinic_id`, `code`). |
| `status` | `varchar(7)` | No | `'DRAFT'` | CHECK IN ('DRAFT','ACTIVE','RETIRED') | Una `RETIRED` no se puede clonar pero no altera planes ya creados. |
| `default_target_profile_id` | `uuid` | Sí |  | FK care.target_profiles(id) | Perfil de metas por defecto del contenido. |
| `content` | `jsonb` | No |  | CHECK jsonb_typeof = 'object' | Estructura: ítems (insulinas, horarios), recordatorios por defecto y reglas de titulación (`step_units`, `max_change_units`, `min_days_between_adjustments`). Se copia en profundidad al plan. |
| `created_by` | `uuid` | Sí |  | FK iam.users(id) | Autor. Nulo en las semillas. |
| `activated_at` | `timestamptz` | Sí |  |  | Activación. |
| `created_at` | `timestamptz` | No | `now()` |  | Fecha de creación (UTC). |

Unicidad y reglas entre columnas: (`clinic_id`, `code`, `version`) con `NULLS NOT DISTINCT`.

### `care.treatment_plans`

Plan de tratamiento versionado de un paciente. Un paciente tiene un solo plan `ACTIVE`; cada cambio crea una versión nueva copiada de la anterior (P05).

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `clinic_id` | `uuid` | No |  | FK clinic.clinics(id) | Clínica dueña de la fila (tenant). La RLS filtra por esta columna. |
| `patient_id` | `uuid` | No |  | FK clinic.patients(id) | Paciente al que pertenece la fila. |
| `version` | `integer` | No |  | CHECK > 0 | Número de versión por paciente. |
| `status` | `varchar(10)` | No | `'DRAFT'` | CHECK IN ('DRAFT','ACTIVE','SUPERSEDED','DISCARDED') | Estado del plan. |
| `template_id` | `uuid` | Sí |  | FK care.protocol_templates(id) | Plantilla de origen. |
| `previous_plan_id` | `uuid` | Sí |  | FK care.treatment_plans(id) | Versión de la que se copió. |
| `source_recommendation_id` | `uuid` | Sí |  | FK ai.recommendations(id) | Recomendación aprobada que originó la versión (RF-71). |
| `target_profile_id` | `uuid` | No |  | FK care.target_profiles(id) | Versión del perfil de metas con que se construyó. |
| `titration_rules` | `jsonb` | Sí |  | CHECK jsonb_typeof = 'object' | Reglas de titulación copiadas de la plantilla (`step_units`, `max_change_units`, `min_days_between_adjustments`). |
| `notes` | `varchar(1000)` | Sí |  | FieldLimits.PLAN_NOTES_MAX_LENGTH (propuesta) | Notas del médico sobre el plan. |
| `created_by` | `uuid` | No |  | FK iam.users(id) | Médico que lo creó. |
| `activated_by` | `uuid` | Sí |  | FK iam.users(id) | Médico que lo activó. |
| `activated_at` | `timestamptz` | Sí |  |  | Activación. |
| `superseded_at` | `timestamptz` | Sí |  |  | Momento en que otra versión lo reemplazó. |
| `created_at` | `timestamptz` | No | `now()` |  | Fecha de creación (UTC). |
| `updated_at` | `timestamptz` | No | `now()` |  | Fecha de la última modificación (UTC). |
| `lock_version` | `integer` | No | `0` | CHECK >= 0 | Versión para el bloqueo optimista (`409` si no coincide). |

Unicidad y reglas entre columnas: (`patient_id`, `version`); Un plan activo por paciente: único parcial (`patient_id`) `WHERE status = 'ACTIVE'`.

### `care.treatment_plan_items`

Ítems del plan: insulinas, medicamentos y mediciones con su horario. Solo se editan mientras el plan está en `DRAFT`.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `clinic_id` | `uuid` | No |  | FK clinic.clinics(id) | Clínica dueña de la fila (tenant). La RLS filtra por esta columna. |
| `plan_id` | `uuid` | No |  | FK care.treatment_plans(id) | Plan. |
| `item_type` | `varchar(10)` | No |  | CHECK IN ('INSULIN','MEDICATION','MEASURE') | Tipo de ítem. |
| `insulin_kind` | `varchar(10)` | Sí |  | CHECK IN ('BASAL','BOLUS','CORRECTION','MIXED'); CHECK (item_type = 'INSULIN') = (insulin_kind IS NOT NULL) | Clase de insulina. |
| `name` | `varchar(120)` | No |  | FieldLimits.PLAN_ITEM_NAME_MAX_LENGTH (propuesta) | Producto o medicamento. |
| `dose_units` | `numeric(6,2)` | Sí |  | CHECK > 0 | Dosis en unidades (o cantidad). Los límites técnicos los valida `FieldLimits`; los clínicos, el protocolo. |
| `time_of_day` | `time` | Sí |  |  | Hora local de la toma o medición. |
| `days_of_week` | `smallint[]` | Sí |  | CHECK <@ ARRAY[1,2,3,4,5,6,7] | Días de la semana (1 lunes a 7 domingo). Nulo es todos los días. |
| `instructions` | `varchar(500)` | Sí |  | FieldLimits.INSTRUCTIONS_MAX_LENGTH (propuesta) | Indicaciones en lenguaje claro. |
| `sort_order` | `smallint` | No | `0` | CHECK >= 0 | Orden de presentación. |

### `care.treatment_plan_snapshots`

Foto jsonb del plan antes de cada cambio (`TreatmentPlanMemento`, P16). Permite restaurar una versión anterior como `DRAFT`.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `clinic_id` | `uuid` | No |  | FK clinic.clinics(id) | Clínica dueña de la fila (tenant). La RLS filtra por esta columna. |
| `plan_id` | `uuid` | No |  | FK care.treatment_plans(id) | Plan fotografiado. |
| `snapshot_no` | `integer` | No |  | CHECK > 0 | Número de foto por plan. |
| `snapshot` | `jsonb` | No |  | CHECK jsonb_typeof = 'object' | Contenido completo del plan (solo datos primitivos). |
| `taken_by` | `uuid` | No |  | FK iam.users(id) | Quien disparó el cambio. |
| `taken_at` | `timestamptz` | No | `now()` |  | Momento de la foto. |
| `reason` | `varchar(500)` | Sí |  | CHECK char_length BETWEEN REASON_MIN_LENGTH AND REASON_MAX_LENGTH | Motivo del cambio. |

Unicidad y reglas entre columnas: (`plan_id`, `snapshot_no`).

### `care.reminder_schedules`

Recordatorios programados (medición, dosis, control, registro) con hora local y días. El job `send_due_reminders` los evalúa cada minuto.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `clinic_id` | `uuid` | No |  | FK clinic.clinics(id) | Clínica dueña de la fila (tenant). La RLS filtra por esta columna. |
| `patient_id` | `uuid` | No |  | FK clinic.patients(id) | Paciente al que pertenece la fila. |
| `plan_id` | `uuid` | Sí |  | FK care.treatment_plans(id) | Plan que los origina. |
| `reminder_type` | `varchar(12)` | No |  | CHECK IN ('MEASUREMENT','INSULIN_DOSE','CONTROL','REGISTRATION') | Tipo de recordatorio. |
| `local_time` | `time` | No |  |  | Hora local de la clínica. |
| `days_of_week` | `smallint[]` | Sí |  | CHECK <@ ARRAY[1,2,3,4,5,6,7] | Días de la semana. Nulo es todos los días. |
| `message_key` | `varchar(60)` | No |  |  | Clave del texto en `messages_es` (sin datos clínicos). |
| `is_active` | `boolean` | No | `true` |  | Activo. |
| `set_by` | `uuid` | No |  | FK iam.users(id) | Médico (`reminders.manage_assigned`) o paciente (`reminders.manage_own`) que lo programó. |
| `last_sent_at` | `timestamptz` | Sí |  |  | Último envío, para la idempotencia del job. |
| `created_at` | `timestamptz` | No | `now()` |  | Fecha de creación (UTC). |
| `updated_at` | `timestamptz` | No | `now()` |  | Fecha de la última modificación (UTC). |

### `care.follow_ups`

Controles de seguimiento (citas) y tareas de contacto por riesgo de abandono (Post-MVP, RF-86 y RF-87).

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `clinic_id` | `uuid` | No |  | FK clinic.clinics(id) | Clínica dueña de la fila (tenant). La RLS filtra por esta columna. |
| `patient_id` | `uuid` | No |  | FK clinic.patients(id) | Paciente al que pertenece la fila. |
| `kind` | `varchar(8)` | No |  | CHECK IN ('CONTROL','OUTREACH') | Control programado por el médico o tarea de contacto de la clínica. |
| `status` | `varchar(9)` | No | `'SCHEDULED'` | CHECK IN ('SCHEDULED','OPEN','DONE','MISSED','CANCELLED','DISMISSED') | Controles: `SCHEDULED`, `DONE`, `MISSED`, `CANCELLED`. Tareas de contacto: `OPEN`, `DONE`, `DISMISSED`. |
| `scheduled_for` | `timestamptz` | Sí |  |  | Fecha del control. Nula en tareas de contacto. |
| `assigned_to` | `uuid` | Sí |  | FK iam.users(id) | Quien lo atiende. |
| `source` | `varchar(10)` | No | `'MANUAL'` | CHECK IN ('MANUAL','AI_DROPOUT','RULE') | Origen: manual, riesgo de abandono de IA7 o regla de inactividad. |
| `risk_assessment_id` | `uuid` | Sí |  | FK ai.risk_assessments(id) | Evaluación de IA7 que lo sugirió. |
| `title` | `varchar(120)` | No |  | FieldLimits.FOLLOW_UP_TITLE_MAX_LENGTH (propuesta) | Título breve, sin datos clínicos. |
| `result_note` | `varchar(500)` | Sí |  | CHECK char_length BETWEEN REASON_MIN_LENGTH AND REASON_MAX_LENGTH | Resultado registrado al cerrar. |
| `created_by` | `uuid` | No |  | FK iam.users(id) | Autor. |
| `closed_at` | `timestamptz` | Sí |  |  | Cierre. |
| `created_at` | `timestamptz` | No | `now()` |  | Fecha de creación (UTC). |
| `updated_at` | `timestamptz` | No | `now()` |  | Fecha de la última modificación (UTC). |

### `care.clinical_notes`

Notas clínicas del médico, append-only: una nota equivocada se corrige con otra que la referencia.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `clinic_id` | `uuid` | No |  | FK clinic.clinics(id) | Clínica dueña de la fila (tenant). La RLS filtra por esta columna. |
| `patient_id` | `uuid` | No |  | FK clinic.patients(id) | Paciente al que pertenece la fila. |
| `author_user_id` | `uuid` | No |  | FK iam.users(id) | Médico autor. |
| `body` | `varchar(2000)` | No |  | FieldLimits.CLINICAL_NOTE_MAX_LENGTH (propuesta); CHECK char_length > 0 | Texto de la nota (clase H). |
| `supersedes_id` | `uuid` | Sí |  | FK care.clinical_notes(id) | Nota que esta corrige. |
| `created_at` | `timestamptz` | No | `now()` |  | Fecha de la nota. |

### `care.triage_reviews` (propuesta)

Marcas de "revisado" del dashboard de triage (RF-79). Un paciente revisado baja de prioridad hasta que cambie su situación. Propuesta.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `clinic_id` | `uuid` | No |  | FK clinic.clinics(id) | Clínica dueña de la fila (tenant). La RLS filtra por esta columna. |
| `patient_id` | `uuid` | No |  | FK clinic.patients(id) | Paciente al que pertenece la fila. |
| `reviewed_by` | `uuid` | No |  | FK iam.users(id) | Médico que revisó. |
| `risk_assessment_id` | `uuid` | Sí |  | FK ai.risk_assessments(id) | Evaluación vigente al revisar; si cambia, el paciente sube de nuevo. |
| `window_days` | `smallint` | No |  | CHECK > 0 | Ventana del triage al revisar (1, 7, 14 o 30 días). |
| `reviewed_at` | `timestamptz` | No | `now()` |  | Momento de la revisión. |

### `care.reading_validation_settings` (propuesta)

Parámetros de validación de lecturas de glucosa por clínica (rango medible, retraso máximo, ventana de duplicado, tasa de cambio, razón de unidades). Versionados y sembrados; ningún umbral vive en el código (propuesta).

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `clinic_id` | `uuid` | Sí |  | FK clinic.clinics(id) | Clínica. Nulo en la semilla global. |
| `version` | `integer` | No |  | CHECK > 0 | Versión por clínica. |
| `status` | `varchar(7)` | No | `'DRAFT'` | CHECK IN ('DRAFT','ACTIVE','RETIRED') | Estado de la versión. |
| `min_measurable_mg_dl` | `numeric(5,1)` | No |  | CHECK > 0 | Límite inferior medible; menos responde `422 GLUCOSE_OUT_OF_RANGE`. |
| `max_measurable_mg_dl` | `numeric(5,1)` | No |  | CHECK > min_measurable_mg_dl | Límite superior medible. |
| `future_tolerance_seconds` | `integer` | No |  | CHECK >= 0 | Tolerancia de marcas de tiempo futuras (`READING_IN_FUTURE`). |
| `max_reading_age_hours` | `integer` | No |  | CHECK > 0 | Retraso máximo de una lectura (`READING_TOO_OLD`). |
| `duplicate_window_seconds` | `integer` | No |  | CHECK > 0 | Ventana de duplicado sospechoso (`DUPLICATE_SUSPECTED`). |
| `max_rate_mg_dl_per_min` | `numeric(5,2)` | No |  | CHECK > 0 | Tasa de cambio máxima plausible (`IMPLAUSIBLE_RATE_OF_CHANGE`). |
| `unit_mismatch_ratio` | `numeric(5,2)` | No |  | CHECK > 1 | Razón con el historial que sugiere confusión mg/dL y mmol/L (`UNIT_MISMATCH_SUSPECTED`). |
| `created_by` | `uuid` | Sí |  | FK iam.users(id) | Autor. Nulo en la semilla. |
| `activated_at` | `timestamptz` | Sí |  |  | Activación. |
| `created_at` | `timestamptz` | No | `now()` |  | Fecha de creación (UTC). |

Unicidad y reglas entre columnas: (`clinic_id`, `version`) con `NULLS NOT DISTINCT`; Una `ACTIVE` por clínica: único parcial `WHERE status = 'ACTIVE'` con `NULLS NOT DISTINCT`.

### `care.symptom_catalog` (propuesta)

Catálogo de síntomas que el paciente puede registrar, con la marca de síntoma de alarma (propuesta). Incluye el evento de hipoglucemia nivel 3 reportado.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `clinic_id` | `uuid` | Sí |  | FK clinic.clinics(id) | Clínica. Nulo en la semilla global. |
| `code` | `varchar(32)` | No |  | CHECK ~ '^[A-Z][A-Z0-9_]*$' | Código en inglés (por ejemplo `THIRST`, `CONFUSION`, `SEVERE_HYPOGLYCEMIA`). |
| `label_es` | `varchar(80)` | No |  | FieldLimits.SYMPTOM_LABEL_MAX_LENGTH (propuesta) | Etiqueta visible en español (dato de catálogo). |
| `is_alarm` | `boolean` | No | `false` |  | Síntoma de alarma: muestra el aviso "contacta a tu equipo o a urgencias" y crea una alerta. |
| `is_active` | `boolean` | No | `true` |  | Disponible para registrar. |
| `created_at` | `timestamptz` | No | `now()` |  | Fecha de creación (UTC). |

Unicidad y reglas entre columnas: (`clinic_id`, `code`) con `NULLS NOT DISTINCT`.

### `care.glycemic_metric_snapshots` (propuesta)

Métricas glucémicas calculadas por ventana, con la versión del perfil de metas con que se calcularon (propuesta, Metricas 1). Las llena el triage nocturno y el cálculo bajo demanda.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `clinic_id` | `uuid` | No |  | FK clinic.clinics(id) | Clínica dueña de la fila (tenant). La RLS filtra por esta columna. |
| `patient_id` | `uuid` | No |  | FK clinic.patients(id) | Paciente al que pertenece la fila. |
| `target_profile_id` | `uuid` | No |  | FK care.target_profiles(id) | Versión del perfil usada en el cálculo. |
| `window_days` | `smallint` | No |  | CHECK > 0 | Ventana: 1, 7, 14 o 30 días (el número lo define la solicitud, no el código). |
| `window_start` | `timestamptz` | No |  |  | Inicio de la ventana (UTC; límites de día en la zona de la clínica). |
| `window_end` | `timestamptz` | No |  | CHECK window_end > window_start | Fin de la ventana. |
| `computed_at` | `timestamptz` | No | `now()` |  | Momento del cálculo. |
| `signal` | `varchar(4)` | No |  | CHECK IN ('CGM','SMBG') | Tipo de señal que admite la métrica. |
| `data_sufficiency_pct` | `numeric(5,1)` | No |  | CHECK BETWEEN 0 AND 100 | Suficiencia de datos. |
| `confidence` | `varchar(14)` | No |  | CHECK IN ('OK','LOW_CONFIDENCE') | `LOW_CONFIDENCE` si no alcanza el mínimo del perfil. |
| `mean_glucose_mg_dl` | `numeric(5,1)` | Sí |  |  | Glucosa media. |
| `tir_pct` | `numeric(5,2)` | Sí |  | CHECK BETWEEN 0 AND 100 | Tiempo en rango. |
| `tbr_l1_pct` | `numeric(5,2)` | Sí |  | CHECK BETWEEN 0 AND 100 | Tiempo en nivel 1 de hipoglucemia. |
| `tbr_l2_pct` | `numeric(5,2)` | Sí |  | CHECK BETWEEN 0 AND 100 | Tiempo en nivel 2 de hipoglucemia. |
| `tar_l1_pct` | `numeric(5,2)` | Sí |  | CHECK BETWEEN 0 AND 100 | Tiempo en nivel 1 de hiperglucemia. |
| `tar_l2_pct` | `numeric(5,2)` | Sí |  | CHECK BETWEEN 0 AND 100 | Tiempo en nivel 2 de hiperglucemia. |
| `gmi_pct` | `numeric(5,2)` | Sí |  |  | Indicador de gestión de glucosa (solo CGM). |
| `cv_pct` | `numeric(5,2)` | Sí |  |  | Coeficiente de variación. |
| `hypo_events_count` | `smallint` | Sí |  | CHECK >= 0 | Episodios de hipoglucemia de la ventana. |
| `hypo_events_night_count` | `smallint` | Sí |  | CHECK >= 0 | Episodios nocturnos. |
| `tir_delta_vs_prior_pp` | `numeric(5,2)` | Sí |  |  | Cambio de TIR frente al periodo anterior, en puntos porcentuales. |
| `agp` | `jsonb` | Sí |  | CHECK jsonb_typeof = 'object' | Percentiles 5, 25, 50, 75 y 95 por intervalo (solo ventana de referencia). |

## 7. Esquema `monitoring`: Registros del paciente (append-only)

### `monitoring.sync_batches`

Lote de registros enviado por el paciente (cola sin conexión, CSV de CGM o simulador `live`). Se escribe una sola vez con los conteos finales, en la misma transacción que sus registros.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `clinic_id` | `uuid` | No |  | FK clinic.clinics(id) | Clínica dueña de la fila (tenant). La RLS filtra por esta columna. |
| `patient_id` | `uuid` | No |  | FK clinic.patients(id) | Paciente al que pertenece la fila. |
| `source` | `varchar(13)` | No |  | CHECK IN ('OFFLINE_QUEUE','CGM_CSV','SIMULATOR') | Origen del lote. |
| `submitted_by` | `uuid` | No |  | FK iam.users(id) | Cuenta que envió el lote (el paciente). |
| `total_items` | `integer` | No |  | CHECK >= 0 | Elementos recibidos. |
| `created_count` | `integer` | No |  | CHECK >= 0 | Resultado `CREATED`. |
| `duplicate_count` | `integer` | No |  | CHECK >= 0 | Resultado `DUPLICATE` (idempotencia). |
| `rejected_count` | `integer` | No |  | CHECK >= 0 AND created_count + duplicate_count + rejected_count = total_items | Resultado `REJECTED`. |
| `file_sha256` | `char(64)` | Sí |  |  | SHA-256 del CSV de CGM, si aplica. |
| `received_at` | `timestamptz` | No | `now()` |  | Momento de recepción. |

### `monitoring.glucose_readings`

Lecturas de glucosa en mg/dL (CGM, glucómetro o manual). Append-only con correcciones; ninguna lectura sospechosa se oculta, se marca.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `clinic_id` | `uuid` | No |  | FK clinic.clinics(id) | Clínica dueña de la fila (tenant). La RLS filtra por esta columna. |
| `patient_id` | `uuid` | No |  | FK clinic.patients(id) | Paciente al que pertenece la fila. |
| `client_reading_id` | `uuid` | No |  |  | UUID generado por el cliente; hace idempotente el envío. |
| `measured_at` | `timestamptz` | No |  |  | Momento de la medición (UTC). |
| `received_at` | `timestamptz` | No | `now()` |  | Momento de recepción en el servidor. |
| `value_mg_dl` | `numeric(5,1)` | No |  | CHECK > 0 | Valor siempre en mg/dL. El rango medible lo valida la cadena con `care.reading_validation_settings`; ningún límite clínico vive aquí. |
| `source` | `varchar(6)` | No |  | CHECK IN ('CGM','SMBG','MANUAL') | Fuente de la lectura. |
| `context` | `varchar(10)` | Sí |  | CHECK IN ('FASTING','PRE_MEAL','POST_MEAL','BEDTIME','EXERCISE','OTHER') | Contexto de la medición. |
| `note` | `varchar(500)` | Sí |  | FieldLimits.GLUCOSE_NOTE_MAX_LENGTH (propuesta; ejemplo de `configuration.md`) | Nota breve del paciente (clase H). |
| `status` | `varchar(8)` | No | `'ACCEPTED'` | CHECK IN ('ACCEPTED','FLAGGED') | `FLAGGED` si la cadena de validación dejó incidencias en `reading_issues`. |
| `recorded_by` | `uuid` | No |  | FK iam.users(id) | Cuenta que registró (el paciente). |
| `sync_batch_id` | `uuid` | Sí |  | FK monitoring.sync_batches(id) DEFERRABLE INITIALLY DEFERRED | Lote de origen, si llegó por lote. |
| `entry_type` | `varchar(10)` | No | `'ORIGINAL'` | CHECK IN ('ORIGINAL','CORRECTION','VOID') | Registro original, corrección (fila nueva) o anulación (fila nueva). |
| `supersedes_id` | `uuid` | Sí |  | FK monitoring.glucose_readings(id) | Fila original que esta fila corrige o anula. Nulo en un original. |
| `correction_reason` | `varchar(500)` | Sí |  | CHECK char_length BETWEEN REASON_MIN_LENGTH AND REASON_MAX_LENGTH | Motivo de la corrección o anulación. Nulo en un original. |

Unicidad y reglas entre columnas: (`patient_id`, `client_reading_id`); CHECK ((entry_type = 'ORIGINAL') = (supersedes_id IS NULL AND correction_reason IS NULL)).

### `monitoring.reading_issues`

Incidencias que la cadena de validación (P12) dejó sobre una lectura. Una fila por bandera.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `clinic_id` | `uuid` | No |  | FK clinic.clinics(id) | Clínica dueña de la fila (tenant). La RLS filtra por esta columna. |
| `reading_id` | `uuid` | No |  | FK monitoring.glucose_readings(id) | Lectura marcada. |
| `issue_code` | `varchar(32)` | No |  | CHECK IN ('DUPLICATE_SUSPECTED','IMPLAUSIBLE_RATE_OF_CHANGE','UNIT_MISMATCH_SUSPECTED') | Código de la incidencia. |
| `detail` | `jsonb` | No | `'{}'::jsonb` | CHECK jsonb_typeof = 'object' | Datos técnicos de la comprobación (sin texto libre del paciente). |
| `created_at` | `timestamptz` | No | `now()` |  | Fecha de creación (UTC). |

Unicidad y reglas entre columnas: (`reading_id`, `issue_code`).

### `monitoring.insulin_doses`

Dosis de insulina registradas por el paciente (nunca sugeridas por la app). Append-only con correcciones.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `clinic_id` | `uuid` | No |  | FK clinic.clinics(id) | Clínica dueña de la fila (tenant). La RLS filtra por esta columna. |
| `patient_id` | `uuid` | No |  | FK clinic.patients(id) | Paciente al que pertenece la fila. |
| `client_record_id` | `uuid` | No |  |  | UUID del cliente para idempotencia. |
| `administered_at` | `timestamptz` | No |  |  | Momento de la dosis (UTC). |
| `insulin_kind` | `varchar(10)` | No |  | CHECK IN ('BASAL','BOLUS','CORRECTION','MIXED') | Clase de insulina (la unión de RF-34 y del simulador). |
| `product_name` | `varchar(80)` | No |  | FieldLimits.INSULIN_PRODUCT_NAME_MAX_LENGTH (propuesta) | Producto. |
| `units` | `numeric(6,2)` | No |  | CHECK > 0 | Unidades de insulina. El límite técnico lo valida `FieldLimits`. |
| `plan_id` | `uuid` | Sí |  | FK care.treatment_plans(id) | Plan activo al registrar, si existe. |
| `source` | `varchar(6)` | No | `'MANUAL'` | CHECK IN ('MANUAL','IMPORT') | Origen. |
| `note` | `varchar(500)` | Sí |  | FieldLimits.RECORD_NOTE_MAX_LENGTH (propuesta) | Nota breve. |
| `recorded_by` | `uuid` | No |  | FK iam.users(id) | Cuenta que registró. |
| `sync_batch_id` | `uuid` | Sí |  | FK monitoring.sync_batches(id) DEFERRABLE INITIALLY DEFERRED | Lote de origen. |
| `received_at` | `timestamptz` | No | `now()` |  | Recepción. |
| `entry_type` | `varchar(10)` | No | `'ORIGINAL'` | CHECK IN ('ORIGINAL','CORRECTION','VOID') | Registro original, corrección (fila nueva) o anulación (fila nueva). |
| `supersedes_id` | `uuid` | Sí |  | FK monitoring.insulin_doses(id) | Fila original que esta fila corrige o anula. Nulo en un original. |
| `correction_reason` | `varchar(500)` | Sí |  | CHECK char_length BETWEEN REASON_MIN_LENGTH AND REASON_MAX_LENGTH | Motivo de la corrección o anulación. Nulo en un original. |

Unicidad y reglas entre columnas: (`patient_id`, `client_record_id`); CHECK ((entry_type = 'ORIGINAL') = (supersedes_id IS NULL AND correction_reason IS NULL)).

### `monitoring.meals`

Comidas con carbohidratos estimados. Append-only con correcciones.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `clinic_id` | `uuid` | No |  | FK clinic.clinics(id) | Clínica dueña de la fila (tenant). La RLS filtra por esta columna. |
| `patient_id` | `uuid` | No |  | FK clinic.patients(id) | Paciente al que pertenece la fila. |
| `client_record_id` | `uuid` | No |  |  | UUID del cliente para idempotencia. |
| `eaten_at` | `timestamptz` | No |  |  | Momento de la comida (UTC). |
| `meal_type` | `varchar(9)` | No |  | CHECK IN ('BREAKFAST','LUNCH','DINNER','SNACK') | Tipo de comida. |
| `carbs_g` | `numeric(5,1)` | No |  | CHECK >= 0 | Carbohidratos estimados en gramos. El límite técnico lo valida `FieldLimits`. |
| `note` | `varchar(500)` | Sí |  | FieldLimits.RECORD_NOTE_MAX_LENGTH (propuesta) | Nota breve. |
| `recorded_by` | `uuid` | No |  | FK iam.users(id) | Cuenta que registró. |
| `sync_batch_id` | `uuid` | Sí |  | FK monitoring.sync_batches(id) DEFERRABLE INITIALLY DEFERRED | Lote de origen. |
| `received_at` | `timestamptz` | No | `now()` |  | Recepción. |
| `entry_type` | `varchar(10)` | No | `'ORIGINAL'` | CHECK IN ('ORIGINAL','CORRECTION','VOID') | Registro original, corrección (fila nueva) o anulación (fila nueva). |
| `supersedes_id` | `uuid` | Sí |  | FK monitoring.meals(id) | Fila original que esta fila corrige o anula. Nulo en un original. |
| `correction_reason` | `varchar(500)` | Sí |  | CHECK char_length BETWEEN REASON_MIN_LENGTH AND REASON_MAX_LENGTH | Motivo de la corrección o anulación. Nulo en un original. |

Unicidad y reglas entre columnas: (`patient_id`, `client_record_id`); CHECK ((entry_type = 'ORIGINAL') = (supersedes_id IS NULL AND correction_reason IS NULL)).

### `monitoring.physical_activities`

Actividad física registrada. Append-only con correcciones.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `clinic_id` | `uuid` | No |  | FK clinic.clinics(id) | Clínica dueña de la fila (tenant). La RLS filtra por esta columna. |
| `patient_id` | `uuid` | No |  | FK clinic.patients(id) | Paciente al que pertenece la fila. |
| `client_record_id` | `uuid` | No |  |  | UUID del cliente para idempotencia. |
| `started_at` | `timestamptz` | No |  |  | Inicio de la actividad (UTC). |
| `activity_type` | `varchar(40)` | No |  | FieldLimits.ACTIVITY_TYPE_MAX_LENGTH (propuesta) | Tipo de actividad (por ejemplo, caminata). |
| `duration_min` | `smallint` | No |  | CHECK > 0 | Duración en minutos. El límite técnico lo valida `FieldLimits`. |
| `intensity` | `varchar(8)` | No |  | CHECK IN ('LOW','MODERATE','HIGH') | Intensidad. |
| `note` | `varchar(500)` | Sí |  | FieldLimits.RECORD_NOTE_MAX_LENGTH (propuesta) | Nota breve. |
| `recorded_by` | `uuid` | No |  | FK iam.users(id) | Cuenta que registró. |
| `sync_batch_id` | `uuid` | Sí |  | FK monitoring.sync_batches(id) DEFERRABLE INITIALLY DEFERRED | Lote de origen. |
| `received_at` | `timestamptz` | No | `now()` |  | Recepción. |
| `entry_type` | `varchar(10)` | No | `'ORIGINAL'` | CHECK IN ('ORIGINAL','CORRECTION','VOID') | Registro original, corrección (fila nueva) o anulación (fila nueva). |
| `supersedes_id` | `uuid` | Sí |  | FK monitoring.physical_activities(id) | Fila original que esta fila corrige o anula. Nulo en un original. |
| `correction_reason` | `varchar(500)` | Sí |  | CHECK char_length BETWEEN REASON_MIN_LENGTH AND REASON_MAX_LENGTH | Motivo de la corrección o anulación. Nulo en un original. |

Unicidad y reglas entre columnas: (`patient_id`, `client_record_id`); CHECK ((entry_type = 'ORIGINAL') = (supersedes_id IS NULL AND correction_reason IS NULL)).

### `monitoring.symptoms`

Síntomas registrados desde el catálogo. Append-only con correcciones.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `clinic_id` | `uuid` | No |  | FK clinic.clinics(id) | Clínica dueña de la fila (tenant). La RLS filtra por esta columna. |
| `patient_id` | `uuid` | No |  | FK clinic.patients(id) | Paciente al que pertenece la fila. |
| `client_record_id` | `uuid` | No |  |  | UUID del cliente para idempotencia. |
| `occurred_at` | `timestamptz` | No |  |  | Momento del síntoma (UTC). |
| `symptom_id` | `uuid` | No |  | FK care.symptom_catalog(id) | Síntoma del catálogo. Un evento de hipoglucemia nivel 3 reportado usa su entrada de catálogo. |
| `note` | `varchar(500)` | Sí |  | FieldLimits.RECORD_NOTE_MAX_LENGTH (propuesta) | Texto libre acotado. |
| `recorded_by` | `uuid` | No |  | FK iam.users(id) | Cuenta que registró. |
| `sync_batch_id` | `uuid` | Sí |  | FK monitoring.sync_batches(id) DEFERRABLE INITIALLY DEFERRED | Lote de origen. |
| `received_at` | `timestamptz` | No | `now()` |  | Recepción. |
| `entry_type` | `varchar(10)` | No | `'ORIGINAL'` | CHECK IN ('ORIGINAL','CORRECTION','VOID') | Registro original, corrección (fila nueva) o anulación (fila nueva). |
| `supersedes_id` | `uuid` | Sí |  | FK monitoring.symptoms(id) | Fila original que esta fila corrige o anula. Nulo en un original. |
| `correction_reason` | `varchar(500)` | Sí |  | CHECK char_length BETWEEN REASON_MIN_LENGTH AND REASON_MAX_LENGTH | Motivo de la corrección o anulación. Nulo en un original. |

Unicidad y reglas entre columnas: (`patient_id`, `client_record_id`); CHECK ((entry_type = 'ORIGINAL') = (supersedes_id IS NULL AND correction_reason IS NULL)).

### `monitoring.lab_results`

Resultados de laboratorio (HbA1c, LOINC 4548-4), autorreportados por el paciente o confirmados por el médico. Append-only con correcciones.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `clinic_id` | `uuid` | No |  | FK clinic.clinics(id) | Clínica dueña de la fila (tenant). La RLS filtra por esta columna. |
| `patient_id` | `uuid` | No |  | FK clinic.patients(id) | Paciente al que pertenece la fila. |
| `client_record_id` | `uuid` | No |  |  | UUID del cliente para idempotencia. |
| `test_code` | `varchar(8)` | No | `'HBA1C'` | CHECK IN ('HBA1C') | Prueba. Hoy solo HbA1c. |
| `performed_on` | `date` | No |  |  | Fecha del examen. |
| `value` | `numeric(6,2)` | No |  | CHECK > 0 | Valor tal como lo entrega el laboratorio. |
| `unit` | `varchar(9)` | No |  | CHECK IN ('%','mmol/mol') | Unidad original. |
| `value_pct` | `numeric(4,1)` | No |  | CHECK > 0 | Valor normalizado a % (NGSP; conversión con constante con nombre). |
| `origin` | `varchar(16)` | No |  | CHECK IN ('PATIENT_REPORTED','LAB') | Origen: autorreporte o laboratorio. `LAB` reemplaza al autorreporte en las gráficas de tendencia. |
| `recorded_by` | `uuid` | No |  | FK iam.users(id) | Paciente (`labs.write_own`) o médico (`labs.write_assigned`). |
| `sync_batch_id` | `uuid` | Sí |  | FK monitoring.sync_batches(id) DEFERRABLE INITIALLY DEFERRED | Lote de origen. |
| `received_at` | `timestamptz` | No | `now()` |  | Recepción. |
| `entry_type` | `varchar(10)` | No | `'ORIGINAL'` | CHECK IN ('ORIGINAL','CORRECTION','VOID') | Registro original, corrección (fila nueva) o anulación (fila nueva). |
| `supersedes_id` | `uuid` | Sí |  | FK monitoring.lab_results(id) | Fila original que esta fila corrige o anula. Nulo en un original. |
| `correction_reason` | `varchar(500)` | Sí |  | CHECK char_length BETWEEN REASON_MIN_LENGTH AND REASON_MAX_LENGTH | Motivo de la corrección o anulación. Nulo en un original. |

Unicidad y reglas entre columnas: (`patient_id`, `client_record_id`); CHECK ((entry_type = 'ORIGINAL') = (supersedes_id IS NULL AND correction_reason IS NULL)).

## 8. Esquema `alerts`: Alertas y notificaciones

### `alerts.alert_rules`

Reglas de alerta versionadas como árbol (Composite, P08): hojas de umbral, duración y tasa de cambio, y nodos Y/O. Los umbrales, duraciones y tiempos de escalamiento son datos. Las semillas traen `clinic_id` nulo.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `clinic_id` | `uuid` | Sí |  | FK clinic.clinics(id) | Clínica dueña. Nulo en las semillas globales. |
| `code` | `varchar(40)` | No |  | CHECK ~ '^[A-Z][A-Z0-9_]*$' | Código de la regla (inglés). |
| `name` | `varchar(120)` | No |  | FieldLimits.ALERT_NAME_MAX_LENGTH (propuesta) | Nombre visible en español. |
| `alert_type` | `varchar(14)` | No |  | CHECK IN ('HYPOGLYCEMIA','HYPERGLYCEMIA','RATE_OF_CHANGE','ADHERENCE','PREDICTIVE','SYMPTOM_ALARM') | Tipo de alerta que produce. |
| `level` | `smallint` | Sí |  | CHECK BETWEEN 1 AND 3 | Nivel de hipoglucemia (1, 2 o 3). Nulo en otros tipos. |
| `priority` | `varchar(8)` | No |  | CHECK IN ('LOW','MEDIUM','HIGH','CRITICAL') | Prioridad. |
| `definition` | `jsonb` | No |  | CHECK jsonb_typeof = 'object' | Árbol de la regla: `{"op":"ALL_OF","children":[{"kind":"THRESHOLD",...}]}`. Lo valida el dominio (árbol vacío rechazado). También se puede escribir con el DSL de P22. |
| `escalation` | `jsonb` | No |  | CHECK jsonb_typeof = 'array' | Cadena de escalamiento: nivel, destinatario (paciente, médico principal, equipo, administrador) y espera en minutos. |
| `bypass_quiet_hours` | `boolean` | No | `false` |  | Nunca se silencia (alertas de nivel 2 y 3). |
| `patient_notice` | `varchar(300)` | Sí |  | FieldLimits.PATIENT_NOTICE_MAX_LENGTH (propuesta) | Aviso de acción inmediata que muestra la app al paciente, configurado por la clínica. |
| `version` | `integer` | No |  | CHECK > 0 | Versión por (`clinic_id`, `code`). |
| `status` | `varchar(7)` | No | `'DRAFT'` | CHECK IN ('DRAFT','ACTIVE','RETIRED') | Una regla `ACTIVE` no se edita: se versiona. |
| `change_reason` | `varchar(500)` | Sí |  | CHECK char_length BETWEEN REASON_MIN_LENGTH AND REASON_MAX_LENGTH | Motivo de la versión nueva. |
| `created_by` | `uuid` | Sí |  | FK iam.users(id) | Autor. Nulo en las semillas. |
| `activated_at` | `timestamptz` | Sí |  |  | Activación. |
| `created_at` | `timestamptz` | No | `now()` |  | Fecha de creación (UTC). |

Unicidad y reglas entre columnas: (`clinic_id`, `code`, `version`) con `NULLS NOT DISTINCT`; Una `ACTIVE` por (`clinic_id`, `code`): único parcial `WHERE status = 'ACTIVE'`.

### `alerts.alerts`

Alertas generadas por una regla, un pronóstico o un síntoma de alarma. Estado `OPEN`, `ACKNOWLEDGED`, `ESCALATED`, `RESOLVED` (P18); cada cambio queda en `alert_status_history`.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `clinic_id` | `uuid` | No |  | FK clinic.clinics(id) | Clínica dueña de la fila (tenant). La RLS filtra por esta columna. |
| `patient_id` | `uuid` | No |  | FK clinic.patients(id) | Paciente al que pertenece la fila. |
| `rule_id` | `uuid` | No |  | FK alerts.alert_rules(id) | Versión de la regla que la disparó. |
| `alert_type` | `varchar(14)` | No |  | CHECK IN ('HYPOGLYCEMIA','HYPERGLYCEMIA','RATE_OF_CHANGE','ADHERENCE','PREDICTIVE','SYMPTOM_ALARM') | Tipo (copiado de la regla). |
| `level` | `smallint` | Sí |  | CHECK BETWEEN 1 AND 3 | Nivel de hipoglucemia. |
| `priority` | `varchar(8)` | No |  | CHECK IN ('LOW','MEDIUM','HIGH','CRITICAL') | Prioridad. |
| `status` | `varchar(12)` | No | `'OPEN'` | CHECK IN ('OPEN','ACKNOWLEDGED','ESCALATED','RESOLVED') | Estado actual. |
| `escalation_level` | `smallint` | No | `0` | CHECK >= 0 | Nivel de la cadena de escalamiento alcanzado. |
| `next_escalation_at` | `timestamptz` | Sí |  |  | Cuándo vence el nivel actual; lo lee `escalate_unacknowledged_alerts`. |
| `opened_at` | `timestamptz` | No | `now()` |  | Apertura. |
| `trigger_reading_id` | `uuid` | Sí |  | FK monitoring.glucose_readings(id) | Lectura que la disparó. |
| `forecast_id` | `uuid` | Sí |  | FK ai.glucose_forecasts(id) | Pronóstico que la disparó (`PREDICTIVE`). |
| `evidence` | `jsonb` | No | `'{}'::jsonb` | CHECK jsonb_typeof = 'object' | Evidencia técnica (ventana, valor, duración). Clase H. |
| `is_fallback` | `boolean` | No | `false` |  | Verdadero si se generó con el respaldo por reglas ("Respaldo por reglas"). |
| `acknowledged_by` | `uuid` | Sí |  | FK iam.users(id) | Quien la reconoció. |
| `acknowledged_at` | `timestamptz` | Sí |  |  | Reconocimiento. |
| `resolved_by` | `uuid` | Sí |  | FK iam.users(id) | Quien la resolvió. |
| `resolved_at` | `timestamptz` | Sí |  |  | Resolución. |
| `resolution_note` | `varchar(500)` | Sí |  | CHECK char_length BETWEEN REASON_MIN_LENGTH AND REASON_MAX_LENGTH | Nota de resolución. |
| `updated_at` | `timestamptz` | No | `now()` |  | Fecha de la última modificación (UTC). |
| `lock_version` | `integer` | No | `0` | CHECK >= 0 | Versión para el bloqueo optimista (`409` si no coincide). |

Unicidad y reglas entre columnas: Sin duplicar una alerta abierta: único parcial (`patient_id`, `rule_id`) `WHERE status IN ('OPEN','ESCALATED')`.

### `alerts.alert_status_history`

Historial de transiciones de cada alerta: quién, cuándo y nota. Append-only.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `clinic_id` | `uuid` | No |  | FK clinic.clinics(id) | Clínica dueña de la fila (tenant). La RLS filtra por esta columna. |
| `alert_id` | `uuid` | No |  | FK alerts.alerts(id) | Alerta. |
| `from_status` | `varchar(12)` | Sí |  | CHECK IN ('OPEN','ACKNOWLEDGED','ESCALATED','RESOLVED') | Estado anterior. Nulo en la apertura. |
| `to_status` | `varchar(12)` | No |  | CHECK IN ('OPEN','ACKNOWLEDGED','ESCALATED','RESOLVED') | Estado nuevo. |
| `escalation_level` | `smallint` | No | `0` | CHECK >= 0 | Nivel de escalamiento tras la transición. |
| `actor_user_id` | `uuid` | Sí |  | FK iam.users(id) | Quien la cambió. Nulo si fue el sistema. |
| `actor_type` | `varchar(6)` | No |  | CHECK IN ('USER','SYSTEM') | Persona o sistema. |
| `note` | `varchar(500)` | Sí |  | CHECK char_length BETWEEN REASON_MIN_LENGTH AND REASON_MAX_LENGTH | Nota. |
| `occurred_at` | `timestamptz` | No | `now()` |  | Momento de la transición. |

### `alerts.notifications`

Notificaciones in-app para una persona. El contenido guarda solo una clave de texto y referencias, nunca valores clínicos ni nombres (el correo y el push dicen solo "Tienes una alerta nueva en Insumap").

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `clinic_id` | `uuid` | Sí |  | FK clinic.clinics(id) | Clínica de la persona. Nulo para el `PLATFORM_ADMIN` (la RLS usa `user_id`). |
| `recipient_user_id` | `uuid` | No |  | FK iam.users(id) | Destinatario. |
| `notification_type` | `varchar(10)` | No |  | CHECK IN ('ALERT','REMINDER','ADHERENCE','FOLLOW_UP','MESSAGE','CONSENT') | Tipo de notificación. |
| `message_key` | `varchar(60)` | No |  |  | Clave del texto en `messages_es`. |
| `entity_type` | `varchar(20)` | Sí |  |  | Tipo de la entidad referida (`ALERT`, `FOLLOW_UP`, ...). |
| `entity_id` | `uuid` | Sí |  |  | Identificador de la entidad referida. |
| `alert_id` | `uuid` | Sí |  | FK alerts.alerts(id) | Alerta asociada, si aplica. |
| `params` | `jsonb` | No | `'{}'::jsonb` | CHECK jsonb_typeof = 'object' | Parámetros de interpolación sin datos personales ni clínicos. |
| `read_at` | `timestamptz` | Sí |  |  | Lectura por el destinatario. |
| `created_at` | `timestamptz` | No | `now()` |  | Fecha de creación (UTC). |

### `alerts.notification_deliveries`

Entrega de cada notificación por canal (correo, Web Push, in-app). Un canal caído no bloquea a los demás y el fallo queda registrado.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `clinic_id` | `uuid` | No |  | FK clinic.clinics(id) | Clínica dueña de la fila (tenant). La RLS filtra por esta columna. |
| `notification_id` | `uuid` | No |  | FK alerts.notifications(id) | Notificación. |
| `channel` | `varchar(8)` | No |  | CHECK IN ('EMAIL','WEB_PUSH','IN_APP') | Canal. |
| `status` | `varchar(20)` | No | `'PENDING'` | CHECK IN ('PENDING','SENT','FAILED','SKIPPED_QUIET_HOURS','SKIPPED_DISABLED') | Estado de la entrega. |
| `attempts` | `smallint` | No | `0` | CHECK >= 0 | Intentos. |
| `last_error_code` | `varchar(40)` | Sí |  |  | Código del último error, sin datos personales. |
| `sent_at` | `timestamptz` | Sí |  |  | Envío exitoso. |
| `created_at` | `timestamptz` | No | `now()` |  | Fecha de creación (UTC). |
| `updated_at` | `timestamptz` | No | `now()` |  | Fecha de la última modificación (UTC). |

Unicidad y reglas entre columnas: (`notification_id`, `channel`).

### `alerts.push_subscriptions`

Suscripciones Web Push de un usuario. El endpoint se valida contra una lista de proveedores permitidos (`PUSH_ENDPOINT_REJECTED`).

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `clinic_id` | `uuid` | Sí |  | FK clinic.clinics(id) | Clínica de la persona. Nulo para el `PLATFORM_ADMIN` (la RLS usa `user_id`). |
| `user_id` | `uuid` | No |  | FK iam.users(id) | Dueño de la suscripción. |
| `endpoint` | `varchar(2048)` | No |  | FieldLimits.PUSH_ENDPOINT_MAX_LENGTH (propuesta); CHECK ~ '^https://' | URL del servicio push. |
| `endpoint_hash` | `char(64)` | No |  | UNIQUE | SHA-256 del endpoint, para deduplicar. |
| `p256dh` | `varchar(255)` | No |  |  | Clave pública del navegador. |
| `auth_ciphertext` | `bytea` | No |  |  | Secreto `auth` cifrado con AES-256-GCM (`FIELD_ENCRYPTION_KEY`). Columna S. |
| `key_id` | `char(16)` | No |  |  | Huella de la llave de cifrado. |
| `is_active` | `boolean` | No | `true` |  | Falso si el servicio la rechazó (`410`). |
| `created_at` | `timestamptz` | No | `now()` |  | Fecha de creación (UTC). |
| `last_used_at` | `timestamptz` | Sí |  |  | Último envío exitoso. |

Unicidad y reglas entre columnas: `endpoint_hash`.

### `alerts.notification_preferences` (propuesta)

Canales habilitados y horario de silencio de cada persona (propuesta, HU-35). Las alertas críticas ignoran el silencio.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `user_id` | `uuid` | No |  | PK; FK iam.users(id) | Persona. |
| `clinic_id` | `uuid` | Sí |  | FK clinic.clinics(id) | Clínica de la persona. Nulo para el `PLATFORM_ADMIN` (la RLS usa `user_id`). |
| `email_enabled` | `boolean` | No | `true` |  | Canal de correo. |
| `web_push_enabled` | `boolean` | No | `true` |  | Canal Web Push. |
| `in_app_enabled` | `boolean` | No | `true` |  | Canal in-app. |
| `quiet_start` | `time` | Sí |  | CHECK (quiet_start IS NULL) = (quiet_end IS NULL) | Inicio del horario de silencio (hora local de la clínica). |
| `quiet_end` | `time` | Sí |  |  | Fin del horario de silencio. |
| `updated_at` | `timestamptz` | No | `now()` |  | Fecha de la última modificación (UTC). |

Unicidad y reglas entre columnas: PK (`user_id`).

## 9. Esquema `ai`: IA y soporte a decisiones

### `ai.model_versions`

Registro de cada modelo desplegado: versión, semilla y versión del simulador con que se entrenó, métricas de validación y activación. Catálogo global sin datos de pacientes.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `use_case` | `varchar(3)` | No |  | CHECK IN ('IA1','IA2','IA3','IA4','IA5','IA6','IA7') | Caso de uso de IA. |
| `model_name` | `varchar(80)` | No |  | FieldLimits.MODEL_NAME_MAX_LENGTH (propuesta) | Nombre del modelo. |
| `model_version` | `varchar(80)` | No |  | FieldLimits.MODEL_VERSION_MAX_LENGTH (propuesta) | Versión `<semver>+<huella>`. |
| `simulator_version` | `varchar(40)` | Sí |  | FieldLimits.SIMULATOR_VERSION_MAX_LENGTH (propuesta) | Versión del simulador con que se entrenó. |
| `training_seed` | `integer` | Sí |  |  | Semilla de entrenamiento. |
| `validation_metrics` | `jsonb` | No | `'{}'::jsonb` | CHECK jsonb_typeof = 'object' | Métricas de validación de la ficha del modelo (`model_card.json`). |
| `status` | `varchar(7)` | No | `'SHADOW'` | CHECK IN ('SHADOW','ACTIVE','RETIRED') | Modo sombra, activo o retirado. |
| `activated_at` | `timestamptz` | Sí |  |  | Activación. |
| `created_at` | `timestamptz` | No | `now()` |  | Fecha de creación (UTC). |

Unicidad y reglas entre columnas: (`model_name`, `model_version`).

### `ai.glucose_forecasts`

Pronósticos de glucosa de IA1 con cuantiles p10, p50 y p90 y riesgo de hipo e hiperglucemia, a corto plazo o hasta el fin de la noche.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `clinic_id` | `uuid` | No |  | FK clinic.clinics(id) | Clínica dueña de la fila (tenant). La RLS filtra por esta columna. |
| `patient_id` | `uuid` | No |  | FK clinic.patients(id) | Paciente al que pertenece la fila. |
| `mode` | `varchar(10)` | No |  | CHECK IN ('SHORT_TERM','OVERNIGHT') | Modo de IA1. |
| `based_on_reading_id` | `uuid` | Sí |  | FK monitoring.glucose_readings(id) | Última lectura usada. |
| `points` | `jsonb` | No |  | CHECK jsonb_typeof = 'array' | Puntos `{horizon_minutes, timestamp, p10, p50, p90}` en mg/dL. |
| `hypo_probability` | `jsonb` | No | `'[]'::jsonb` | CHECK jsonb_typeof = 'array' | Probabilidad de hipoglucemia por horizonte. |
| `hyper_probability` | `jsonb` | No | `'[]'::jsonb` | CHECK jsonb_typeof = 'array' | Probabilidad de hiperglucemia por horizonte. |
| `target_profile_id` | `uuid` | No |  | FK care.target_profiles(id) | Perfil cuyos umbrales (`thresholds`) se enviaron. |
| `model_name` | `varchar(80)` | No |  | FieldLimits.MODEL_NAME_MAX_LENGTH (propuesta) | Modelo que produjo la salida (por ejemplo `chronos-bolt`, `fallback-linear`). |
| `model_version` | `varchar(80)` | No |  | FieldLimits.MODEL_VERSION_MAX_LENGTH (propuesta) | Versión `<semver>+<huella>` de la respuesta. Con el respaldo, `fallback-linear@1.0.0`. |
| `input_hash` | `char(64)` | No |  |  | SHA-256 del JSON canónico de la entrada: detecta entradas repetidas y prueba que no se alteró. |
| `explanation` | `jsonb` | No |  | CHECK jsonb_typeof = 'object' | Explicación para el médico: `summary`, `factors[]` y `data_refs[]`. |
| `is_fallback` | `boolean` | No | `false` |  | Verdadero si la produjo un respaldo y no el modelo. |
| `fallback_reason` | `varchar(17)` | Sí |  | CHECK IN ('AI_TIMEOUT','CIRCUIT_OPEN','AI_ERROR','INSUFFICIENT_DATA'); CHECK (is_fallback) = (fallback_reason IS NOT NULL) | Motivo del respaldo. |
| `is_shadow` | `boolean` | No | `false` |  | Salida de un modelo en modo sombra: se guarda pero el sistema no la usa. |
| `generated_at` | `timestamptz` | No |  |  | Momento de la inferencia (respuesta del servicio o del respaldo). |
| `created_at` | `timestamptz` | No | `now()` |  | Fecha de creación (UTC). |

### `ai.risk_assessments`

Evaluaciones de riesgo: deterioro glucémico para el triage (IA2) y riesgo de abandono (IA7).

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `clinic_id` | `uuid` | No |  | FK clinic.clinics(id) | Clínica dueña de la fila (tenant). La RLS filtra por esta columna. |
| `patient_id` | `uuid` | No |  | FK clinic.patients(id) | Paciente al que pertenece la fila. |
| `assessment_type` | `varchar(13)` | No |  | CHECK IN ('DETERIORATION','DROPOUT') | IA2 o IA7. |
| `risk_probability` | `numeric(5,4)` | Sí |  | CHECK BETWEEN 0 AND 1 | Probabilidad calibrada. Nula si `INSUFFICIENT_DATA`. |
| `risk_tier` | `varchar(8)` | Sí |  | CHECK IN ('LOW','MEDIUM','HIGH','CRITICAL') | Nivel de riesgo según los cortes de la ficha del modelo. |
| `calibrated` | `boolean` | No | `true` |  | Falso si el respaldo del servicio no calibra. |
| `window_days` | `smallint` | No |  | CHECK > 0 | Ventana de entrada. |
| `metric_snapshot_id` | `uuid` | Sí |  | FK care.glycemic_metric_snapshots(id) | Métricas usadas como características. |
| `target_profile_id` | `uuid` | No |  | FK care.target_profiles(id) | Perfil de metas aplicado. |
| `model_name` | `varchar(80)` | No |  | FieldLimits.MODEL_NAME_MAX_LENGTH (propuesta) | Modelo que produjo la salida (por ejemplo `chronos-bolt`, `fallback-linear`). |
| `model_version` | `varchar(80)` | No |  | FieldLimits.MODEL_VERSION_MAX_LENGTH (propuesta) | Versión `<semver>+<huella>` de la respuesta. Con el respaldo, `fallback-linear@1.0.0`. |
| `input_hash` | `char(64)` | No |  |  | SHA-256 del JSON canónico de la entrada: detecta entradas repetidas y prueba que no se alteró. |
| `explanation` | `jsonb` | No |  | CHECK jsonb_typeof = 'object' | Explicación para el médico: `summary`, `factors[]` y `data_refs[]`. |
| `is_fallback` | `boolean` | No | `false` |  | Verdadero si la produjo un respaldo y no el modelo. |
| `fallback_reason` | `varchar(17)` | Sí |  | CHECK IN ('AI_TIMEOUT','CIRCUIT_OPEN','AI_ERROR','INSUFFICIENT_DATA'); CHECK (is_fallback) = (fallback_reason IS NOT NULL) | Motivo del respaldo. |
| `is_shadow` | `boolean` | No | `false` |  | Salida de un modelo en modo sombra: se guarda pero el sistema no la usa. |
| `generated_at` | `timestamptz` | No |  |  | Momento de la inferencia (respuesta del servicio o del respaldo). |
| `created_at` | `timestamptz` | No | `now()` |  | Fecha de creación (UTC). |

### `ai.pattern_findings`

Hallazgos de patrones y anomalías de IA3 con ventana, evidencia y confianza.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `clinic_id` | `uuid` | No |  | FK clinic.clinics(id) | Clínica dueña de la fila (tenant). La RLS filtra por esta columna. |
| `patient_id` | `uuid` | No |  | FK clinic.patients(id) | Paciente al que pertenece la fila. |
| `pattern_type` | `varchar(24)` | No |  | CHECK IN ('NOCTURNAL_HYPOGLYCEMIA','DAWN_PHENOMENON','POSTPRANDIAL_SPIKE','MISSED_DOSE','DUPLICATE_DOSE','ADHERENCE_DROP','IMPLAUSIBLE_READING') | Patrón detectado. |
| `window_start` | `timestamptz` | No |  |  | Inicio de la ventana. |
| `window_end` | `timestamptz` | No |  | CHECK window_end > window_start | Fin de la ventana. |
| `confidence` | `numeric(5,4)` | Sí |  | CHECK BETWEEN 0 AND 1 | Confianza del hallazgo. |
| `evidence` | `jsonb` | No |  | CHECK jsonb_typeof = 'object' | Evidencia (episodios, conteos, valores). |
| `model_name` | `varchar(80)` | No |  | FieldLimits.MODEL_NAME_MAX_LENGTH (propuesta) | Modelo que produjo la salida (por ejemplo `chronos-bolt`, `fallback-linear`). |
| `model_version` | `varchar(80)` | No |  | FieldLimits.MODEL_VERSION_MAX_LENGTH (propuesta) | Versión `<semver>+<huella>` de la respuesta. Con el respaldo, `fallback-linear@1.0.0`. |
| `input_hash` | `char(64)` | No |  |  | SHA-256 del JSON canónico de la entrada: detecta entradas repetidas y prueba que no se alteró. |
| `explanation` | `jsonb` | No |  | CHECK jsonb_typeof = 'object' | Explicación para el médico: `summary`, `factors[]` y `data_refs[]`. |
| `is_fallback` | `boolean` | No | `false` |  | Verdadero si la produjo un respaldo y no el modelo. |
| `fallback_reason` | `varchar(17)` | Sí |  | CHECK IN ('AI_TIMEOUT','CIRCUIT_OPEN','AI_ERROR','INSUFFICIENT_DATA'); CHECK (is_fallback) = (fallback_reason IS NOT NULL) | Motivo del respaldo. |
| `is_shadow` | `boolean` | No | `false` |  | Salida de un modelo en modo sombra: se guarda pero el sistema no la usa. |
| `generated_at` | `timestamptz` | No |  |  | Momento de la inferencia (respuesta del servicio o del respaldo). |
| `created_at` | `timestamptz` | No | `now()` |  | Fecha de creación (UTC). |

### `ai.recommendations`

Propuestas de ajuste de tratamiento de IA4. Nacen `PROPOSED`, nunca se aplican solas y el paciente no las ve hasta `APPLIED`.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `clinic_id` | `uuid` | No |  | FK clinic.clinics(id) | Clínica dueña de la fila (tenant). La RLS filtra por esta columna. |
| `patient_id` | `uuid` | No |  | FK clinic.patients(id) | Paciente al que pertenece la fila. |
| `plan_id` | `uuid` | No |  | FK care.treatment_plans(id) | Plan activo sobre el que se propone. |
| `applied_plan_id` | `uuid` | Sí |  | FK care.treatment_plans(id) | Versión `DRAFT` creada al aplicar. |
| `status` | `varchar(21)` | No | `'PROPOSED'` | CHECK IN ('PROPOSED','APPROVED','APPROVED_WITH_CHANGES','REJECTED','APPLIED','EXPIRED') | Estado actual (`RecommendationState`, P18). El historial vive en `recommendation_decisions`. |
| `action` | `varchar(8)` | No |  | CHECK IN ('INCREASE','DECREASE') | Acción propuesta. `MAINTAIN` y `NO_SUGGESTION` no crean recomendación. |
| `suggestion` | `jsonb` | No |  | CHECK jsonb_typeof = 'object' | Propuesta: dosis actual y propuesta, `delta_units`, `rule_id`. |
| `requires_doctor_approval` | `boolean` | No | `true` | CHECK (requires_doctor_approval) | Siempre verdadero. |
| `target_profile_id` | `uuid` | No |  | FK care.target_profiles(id) | Perfil con que se calculó. |
| `proposed_at` | `timestamptz` | No | `now()` |  | Momento de la propuesta. |
| `expires_at` | `timestamptz` | No |  | CHECK expires_at > proposed_at | Plazo para decidir (`clinic_settings.recommendation_expiry_hours`). |
| `model_name` | `varchar(80)` | No |  | FieldLimits.MODEL_NAME_MAX_LENGTH (propuesta) | Modelo que produjo la salida (por ejemplo `chronos-bolt`, `fallback-linear`). |
| `model_version` | `varchar(80)` | No |  | FieldLimits.MODEL_VERSION_MAX_LENGTH (propuesta) | Versión `<semver>+<huella>` de la respuesta. Con el respaldo, `fallback-linear@1.0.0`. |
| `input_hash` | `char(64)` | No |  |  | SHA-256 del JSON canónico de la entrada: detecta entradas repetidas y prueba que no se alteró. |
| `explanation` | `jsonb` | No |  | CHECK jsonb_typeof = 'object' | Explicación para el médico: `summary`, `factors[]` y `data_refs[]`. |
| `is_fallback` | `boolean` | No | `false` |  | Verdadero si la produjo un respaldo y no el modelo. |
| `fallback_reason` | `varchar(17)` | Sí |  | CHECK IN ('AI_TIMEOUT','CIRCUIT_OPEN','AI_ERROR','INSUFFICIENT_DATA'); CHECK (is_fallback) = (fallback_reason IS NOT NULL) | Motivo del respaldo. |
| `is_shadow` | `boolean` | No | `false` |  | Salida de un modelo en modo sombra: se guarda pero el sistema no la usa. |
| `generated_at` | `timestamptz` | No |  |  | Momento de la inferencia (respuesta del servicio o del respaldo). |
| `updated_at` | `timestamptz` | No | `now()` |  | Fecha de la última modificación (UTC). |
| `lock_version` | `integer` | No | `0` | CHECK >= 0 | Versión para el bloqueo optimista (`409` si no coincide). |

Unicidad y reglas entre columnas: Una pendiente por plan y acción: único parcial (`plan_id`, `action`) `WHERE status = 'PROPOSED'`.

### `ai.recommendation_decisions`

Cada transición de una recomendación con quién, cuándo, motivo y valor modificado. Append-only.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `clinic_id` | `uuid` | No |  | FK clinic.clinics(id) | Clínica dueña de la fila (tenant). La RLS filtra por esta columna. |
| `recommendation_id` | `uuid` | No |  | FK ai.recommendations(id) | Recomendación. |
| `decision` | `varchar(21)` | No |  | CHECK IN ('APPROVED','APPROVED_WITH_CHANGES','REJECTED','APPLIED','EXPIRED') | Transición registrada. |
| `decided_by` | `uuid` | Sí |  | FK iam.users(id) | Médico asignado que decidió. Nulo si fue el sistema (`APPLIED`, `EXPIRED`). |
| `decided_at` | `timestamptz` | No |  |  | Hora tomada del `Clock` inyectado. |
| `reason` | `varchar(500)` | Sí |  | CHECK char_length BETWEEN REASON_MIN_LENGTH AND REASON_MAX_LENGTH; CHECK decision NOT IN ('APPROVED_WITH_CHANGES','REJECTED') OR reason IS NOT NULL | Motivo. Obligatorio al modificar o rechazar (`422 REASON_REQUIRED`). |
| `reason_code` | `varchar(40)` | Sí |  |  | Código del catálogo de motivos, si existe. |
| `original_suggestion` | `jsonb` | Sí |  | CHECK jsonb_typeof = 'object' | Propuesta original de la IA. |
| `modified_suggestion` | `jsonb` | Sí |  | CHECK jsonb_typeof = 'object'; CHECK (decision = 'APPROVED_WITH_CHANGES') = (modified_suggestion IS NOT NULL) | Valor cambiado por el médico. |
| `model_version` | `varchar(80)` | No |  | FieldLimits.MODEL_VERSION_MAX_LENGTH (propuesta) | Versión del modelo (copia de la recomendación). |
| `applied_plan_id` | `uuid` | Sí |  | FK care.treatment_plans(id) | Versión del plan creada en `APPLIED`. |

### `ai.clinical_summaries`

Resumen previo a la consulta de IA5 (con LLM o plantilla determinista) con referencias a sus datos.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `clinic_id` | `uuid` | No |  | FK clinic.clinics(id) | Clínica dueña de la fila (tenant). La RLS filtra por esta columna. |
| `patient_id` | `uuid` | No |  | FK clinic.patients(id) | Paciente al que pertenece la fila. |
| `period_start` | `timestamptz` | No |  |  | Inicio del periodo resumido. |
| `period_end` | `timestamptz` | No |  | CHECK period_end > period_start | Fin del periodo. |
| `sections` | `jsonb` | No |  | CHECK jsonb_typeof = 'object' | Secciones del resumen (narrativa del AGP, eventos, adherencia, cambios de plan) como texto plano. |
| `numeric_check_matched` | `boolean` | Sí |  |  | Resultado de la verificación numérica de IA5. |
| `requested_by` | `uuid` | No |  | FK iam.users(id) | Médico que lo pidió (`clinical_summaries.generate`). |
| `model_name` | `varchar(80)` | No |  | FieldLimits.MODEL_NAME_MAX_LENGTH (propuesta) | Modelo que produjo la salida (por ejemplo `chronos-bolt`, `fallback-linear`). |
| `model_version` | `varchar(80)` | No |  | FieldLimits.MODEL_VERSION_MAX_LENGTH (propuesta) | Versión `<semver>+<huella>` de la respuesta. Con el respaldo, `fallback-linear@1.0.0`. |
| `input_hash` | `char(64)` | No |  |  | SHA-256 del JSON canónico de la entrada: detecta entradas repetidas y prueba que no se alteró. |
| `explanation` | `jsonb` | No |  | CHECK jsonb_typeof = 'object' | Explicación para el médico: `summary`, `factors[]` y `data_refs[]`. |
| `is_fallback` | `boolean` | No | `false` |  | Verdadero si la produjo un respaldo y no el modelo. |
| `fallback_reason` | `varchar(17)` | Sí |  | CHECK IN ('AI_TIMEOUT','CIRCUIT_OPEN','AI_ERROR','INSUFFICIENT_DATA'); CHECK (is_fallback) = (fallback_reason IS NOT NULL) | Motivo del respaldo. |
| `is_shadow` | `boolean` | No | `false` |  | Salida de un modelo en modo sombra: se guarda pero el sistema no la usa. |
| `generated_at` | `timestamptz` | No |  |  | Momento de la inferencia (respuesta del servicio o del respaldo). |
| `created_at` | `timestamptz` | No | `now()` |  | Fecha de creación (UTC). |

### `ai.assistant_messages`

Conversación del paciente con el asistente educativo (IA6): sus preguntas y las respuestas. Las respuestas nunca contienen dosis ni diagnósticos (guardrails).

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `clinic_id` | `uuid` | No |  | FK clinic.clinics(id) | Clínica dueña de la fila (tenant). La RLS filtra por esta columna. |
| `patient_id` | `uuid` | No |  | FK clinic.patients(id) | Paciente al que pertenece la fila. |
| `conversation_id` | `uuid` | No |  |  | Agrupa los mensajes de una conversación. |
| `sender` | `varchar(9)` | No |  | CHECK IN ('PATIENT','ASSISTANT') | Quien escribió. |
| `content` | `varchar(1000)` | No |  | FieldLimits.ASSISTANT_MESSAGE_MAX_LENGTH (propuesta) | Texto plano (clase H). El del paciente se guarda como lo escribió; al LLM llega redactado. |
| `escalation_level` | `varchar(14)` | Sí |  | CHECK IN ('NONE','CONTACT_DOCTOR','EMERGENCY') | Escalamiento decidido por los guardrails (solo respuestas). |
| `guardrails_triggered` | `varchar(40)[]` | No | `'{}'` |  | Eslabones de guardrail que actuaron. |
| `context_doc_ids` | `uuid[]` | No | `'{}'` |  | Material aprobado (`ai.knowledge_documents`) usado como contexto. |
| `external_consent_id` | `uuid` | Sí |  | FK clinic.patient_consents(id) | Consentimiento `AI_EXTERNAL_PROCESSING` vigente cuando se usó LLM externo. |
| `model_name` | `varchar(80)` | Sí |  | FieldLimits.MODEL_NAME_MAX_LENGTH (propuesta); nulo si `sender = 'PATIENT'` | Modelo, solo en respuestas. |
| `model_version` | `varchar(80)` | Sí |  | FieldLimits.MODEL_VERSION_MAX_LENGTH (propuesta) | Versión, solo en respuestas. |
| `input_hash` | `char(64)` | Sí |  |  | SHA-256 de la entrada, solo en respuestas. |
| `explanation` | `jsonb` | Sí |  | CHECK jsonb_typeof = 'object' | Explicación de la respuesta, solo en respuestas. |
| `is_fallback` | `boolean` | No | `false` |  | Respuesta predefinida por respaldo o bloqueo. |
| `fallback_reason` | `varchar(17)` | Sí |  | CHECK IN ('AI_TIMEOUT','CIRCUIT_OPEN','AI_ERROR','INSUFFICIENT_DATA') | Motivo del respaldo. |
| `sent_at` | `timestamptz` | No | `now()` |  | Momento del mensaje. |

### `ai.knowledge_documents` (propuesta)

Material educativo aprobado por la clínica que alimenta el RAG sin estado de IA6 (propuesta). Búsqueda por palabras clave o `pg_trgm`.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `clinic_id` | `uuid` | No |  | FK clinic.clinics(id) | Clínica dueña de la fila (tenant). La RLS filtra por esta columna. |
| `title` | `varchar(160)` | No |  | FieldLimits.KNOWLEDGE_TITLE_MAX_LENGTH (propuesta) | Título del documento. |
| `body` | `text` | No |  |  | Texto aprobado. |
| `version` | `integer` | No | `1` | CHECK > 0 | Versión del documento. |
| `status` | `varchar(8)` | No | `'DRAFT'` | CHECK IN ('DRAFT','APPROVED','RETIRED') | Solo `APPROVED` llega al asistente. |
| `approved_by` | `uuid` | Sí |  | FK iam.users(id) | Quien lo aprobó. |
| `approved_at` | `timestamptz` | Sí |  |  | Aprobación. |
| `created_at` | `timestamptz` | No | `now()` |  | Fecha de creación (UTC). |
| `updated_at` | `timestamptz` | No | `now()` |  | Fecha de la última modificación (UTC). |

### `ai.ai_evaluations`

Comparaciones de cada caso de IA contra su respaldo (MAE, RMSE, Clarke, AUROC, calibración, etc.) sobre cohortes simuladas. Sin datos de pacientes.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `clinic_id` | `uuid` | Sí |  | FK clinic.clinics(id) | Clínica evaluada. Nulo en evaluaciones globales. |
| `use_case` | `varchar(3)` | No |  | CHECK IN ('IA1','IA2','IA3','IA4','IA5','IA6','IA7') | Caso de IA. |
| `model_name` | `varchar(80)` | No |  | FieldLimits.MODEL_NAME_MAX_LENGTH (propuesta) | Modelo evaluado. |
| `model_version` | `varchar(80)` | No |  | FieldLimits.MODEL_VERSION_MAX_LENGTH (propuesta) | Versión evaluada. |
| `baseline_name` | `varchar(80)` | No |  | FieldLimits.MODEL_NAME_MAX_LENGTH (propuesta) | Respaldo con que se compara. |
| `cohort_ref` | `varchar(80)` | No |  |  | Referencia de la cohorte simulada de prueba (versión y semilla). |
| `sample_size` | `integer` | No |  | CHECK > 0 | Casos evaluados. |
| `model_metrics` | `jsonb` | No |  | CHECK jsonb_typeof = 'object' | Métricas del modelo. |
| `baseline_metrics` | `jsonb` | No |  | CHECK jsonb_typeof = 'object' | Métricas del respaldo. |
| `fallback_usage_pct` | `numeric(5,2)` | Sí |  | CHECK BETWEEN 0 AND 100 | Porcentaje de salidas servidas con respaldo. |
| `evaluated_at` | `timestamptz` | No | `now()` |  | Momento de la evaluación. |
| `created_at` | `timestamptz` | No | `now()` |  | Fecha de creación (UTC). |

## 10. Esquema `messaging`: Mensajería

### `messaging.threads`

Hilo de mensajes entre el paciente y su equipo de atención asignado. Un hilo por paciente (Post-MVP, RF-84).

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `clinic_id` | `uuid` | No |  | FK clinic.clinics(id) | Clínica dueña de la fila (tenant). La RLS filtra por esta columna. |
| `patient_id` | `uuid` | No |  | FK clinic.patients(id) | Paciente al que pertenece la fila. |
| `last_message_at` | `timestamptz` | Sí |  |  | Fecha del último mensaje, para ordenar. |
| `created_at` | `timestamptz` | No | `now()` |  | Fecha de creación (UTC). |

Unicidad y reglas entre columnas: `patient_id` (un hilo por paciente).

### `messaging.messages`

Mensajes del hilo, append-only. El hilo muestra un aviso permanente de que no es un canal de emergencias.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `clinic_id` | `uuid` | No |  | FK clinic.clinics(id) | Clínica dueña de la fila (tenant). La RLS filtra por esta columna. |
| `thread_id` | `uuid` | No |  | FK messaging.threads(id) | Hilo. |
| `sender_user_id` | `uuid` | No |  | FK iam.users(id) | Remitente (paciente o médico del equipo). |
| `sender_role` | `varchar(7)` | No |  | CHECK IN ('PATIENT','DOCTOR') | Rol del remitente. |
| `body` | `varchar(1000)` | No |  | FieldLimits.MESSAGE_BODY_MAX_LENGTH (propuesta); CHECK char_length > 0 | Texto plano (clase H). |
| `sent_at` | `timestamptz` | No | `now()` |  | Momento del envío. |

### `messaging.thread_reads` (propuesta)

Última lectura de cada participante en un hilo, para el contador de no leídos (propuesta). Mantiene `messages` append-only.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `thread_id` | `uuid` | No |  | PK; FK messaging.threads(id) | Hilo. |
| `user_id` | `uuid` | No |  | PK; FK iam.users(id) | Participante. |
| `clinic_id` | `uuid` | No |  | FK clinic.clinics(id) | Clínica dueña de la fila (tenant). La RLS filtra por esta columna. |
| `last_read_at` | `timestamptz` | No |  |  | Hasta qué momento leyó. |

Unicidad y reglas entre columnas: PK compuesta (`thread_id`, `user_id`).

## 11. Esquema `audit`: Auditoría y retención

### `audit.audit_log`

Auditoría de acciones que cambian datos de seguridad o decisiones clínicas, con cadena de hashes por clínica. Se escribe solo con `audit.append_audit_log(...)` en la misma transacción de la acción; no guarda valores clínicos.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `clinic_id` | `uuid` | No |  | FK clinic.clinics(id) | Clínica de la acción. La cadena es por clínica; las acciones de plataforma usan la clínica afectada y las que no tienen clínica van a `iam.security_events`. |
| `chain_seq` | `bigint` | No |  | CHECK > 0 | Posición en la cadena de la clínica, asignada por el trigger bajo `pg_advisory_xact_lock`. |
| `occurred_at` | `timestamptz` | No | `now()` |  | Momento de la acción (UTC). |
| `actor_user_id` | `uuid` | Sí |  | FK iam.users(id) | Quien actuó. Nulo si fue el sistema. |
| `actor_role` | `varchar(14)` | Sí |  | CHECK IN ('PLATFORM_ADMIN','CLINIC_ADMIN','DOCTOR','PATIENT','SYSTEM') | Rol del actor. |
| `actor_type` | `varchar(6)` | No |  | CHECK IN ('USER','SYSTEM') | Persona o sistema. |
| `action` | `varchar(60)` | No |  | CHECK ~ '^[A-Z][A-Z0-9_]*$' | Acción (por ejemplo `PATIENTS_IMPORTED`, `PATIENT_ACTIVATED`, `TREATMENT_PLAN_ACTIVATED`, `PURGE`, `RETENTION_POLICY_CHANGED`). |
| `entity_type` | `varchar(40)` | No |  |  | Tipo de la entidad afectada. |
| `entity_id` | `uuid` | Sí |  |  | Identificador de la entidad afectada. |
| `entity_version` | `integer` | Sí |  |  | Versión de la entidad, si es versionada. |
| `reason` | `varchar(500)` | Sí |  | CHECK char_length BETWEEN REASON_MIN_LENGTH AND REASON_MAX_LENGTH | Motivo cuando la acción lo exige. |
| `changed_fields` | `varchar(80)[]` | No | `'{}'` |  | Nombres de los campos cambiados (nunca sus valores). |
| `request_id` | `varchar(64)` | Sí |  | FieldLimits.REQUEST_ID_MAX_LENGTH | Correlación con los logs. |
| `ip_hmac` | `char(64)` | Sí |  |  | HMAC-SHA256 de la IP. |
| `prev_hash` | `char(64)` | No |  |  | `row_hash` de la fila anterior de la clínica; 64 ceros en la primera. Lo fija el trigger. |
| `row_hash` | `char(64)` | No |  |  | `sha256(prev_hash \|\| contenido_canónico)` en hexadecimal. Lo calcula el trigger `BEFORE INSERT`. |

Unicidad y reglas entre columnas: (`clinic_id`, `chain_seq`).

### `audit.data_access_log`

Registro de cada lectura de datos clínicos (`PhiAccessAuditDecorator`, P09): quién, a qué paciente, qué recurso, con qué propósito y con qué resultado. Fallo cerrado: si no se escribe, la lectura no responde.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `clinic_id` | `uuid` | No |  | FK clinic.clinics(id) | Clínica dueña de la fila (tenant). La RLS filtra por esta columna. |
| `patient_id` | `uuid` | Sí |  | FK clinic.patients(id) | Paciente leído. Nulo en listados administrativos (`PATIENT_LIST`). |
| `occurred_at` | `timestamptz` | No | `now()` |  | Hora de la lectura (UTC). |
| `actor_user_id` | `uuid` | Sí |  | FK iam.users(id) | Quien leyó. Nulo si el actor es el sistema. |
| `actor_role` | `varchar(14)` | Sí |  | CHECK IN ('PLATFORM_ADMIN','CLINIC_ADMIN','DOCTOR','PATIENT','SYSTEM') | Rol del actor. |
| `actor_type` | `varchar(6)` | No |  | CHECK IN ('USER','SYSTEM') | Persona o sistema. |
| `resource_type` | `varchar(24)` | No |  | CHECK IN ('GLUCOSE_READINGS','INSULIN_DOSES','MEALS','PHYSICAL_ACTIVITIES','SYMPTOMS','LAB_RESULTS','GLYCEMIC_METRICS','TREATMENT_PLAN','CLINICAL_NOTES','ALERTS','AI_OUTPUTS','MESSAGES','PATIENT_TIMELINE','REPORT','TRIAGE_LIST','PATIENT_DEMOGRAPHICS','PATIENT_LIST','PATIENT_DOCUMENT') | Recurso leído. |
| `action` | `varchar(7)` | No | `'READ'` | CHECK IN ('READ','EXPORT','DECRYPT') | Lectura, exportación o descifrado del documento. |
| `outcome` | `varchar(7)` | No |  | CHECK IN ('GRANTED','DENIED') | Acceso concedido o denegado. |
| `purpose` | `varchar(14)` | No |  | CHECK IN ('CARE','SELF','ADMINISTRATION','AI_PROCESSING') | Propósito. `AI_PROCESSING` registra cada envío a `insumap-ai` (actor `SYSTEM`). |
| `request_id` | `varchar(64)` | Sí |  | FieldLimits.REQUEST_ID_MAX_LENGTH | Correlación con los logs. |
| `ip_hmac` | `char(64)` | Sí |  |  | HMAC-SHA256 de la IP (nunca en claro). |

### `audit.retention_policies`

Plazo de retención por tipo de dato. Los plazos son parámetros de la BD, no del código. Los valores legales de los datos clínicos quedan nulos hasta que `Cumplimiento-y-privacidad.md` los fije.

| Columna | Tipo | Nulo | Por defecto | Restricción | Descripción |
|---|---|---|---|---|---|
| `id` | `uuid` | No | `uuidv7()` | PK | Identificador de la fila (UUID v7). |
| `clinic_id` | `uuid` | Sí |  | FK clinic.clinics(id) | Clínica. Nulo es la política global de plataforma. |
| `table_name` | `varchar(80)` | No |  | CHECK ~ '^[a-z_]+\.[a-z_]+$' | Tabla afectada (por ejemplo `iam.login_attempts`). |
| `reference_column` | `varchar(60)` | No |  |  | Columna que fecha el registro (`occurred_at`, `expires_at`, `revoked_at`...). |
| `retention_days` | `integer` | Sí |  | CHECK > 0 | Días de conservación tras la fecha de referencia. Nulo: por definir, sin purga. |
| `action` | `varchar(9)` | No | `'DELETE'` | CHECK IN ('DELETE','ANONYMIZE') | Borrar o anonimizar (RF-94). Las tablas clínicas nunca usan `DELETE`. |
| `is_enabled` | `boolean` | No | `false` |  | Activa. La purga solo corre si `is_enabled` y `retention_days` no es nulo. |
| `basis` | `varchar(300)` | Sí |  |  | Fundamento (norma o decisión técnica). |
| `updated_by` | `uuid` | Sí |  | FK iam.users(id) | Quien cambió el plazo. Nulo en la semilla. |
| `updated_at` | `timestamptz` | No | `now()` |  | Fecha de la última modificación (UTC). |

Unicidad y reglas entre columnas: (`clinic_id`, `table_name`) con `NULLS NOT DISTINCT`.

## Documentos relacionados

[Modelo-de-datos.md](Modelo-de-datos.md) · [Seguridad.md](Seguridad.md) · [Actores-y-permisos.md](Actores-y-permisos.md) · [Metricas-clinicas.md](Metricas-clinicas.md) · [Contrato-IA.md](Contrato-IA.md) · [`.agents/configuration.md`](../.agents/configuration.md)
