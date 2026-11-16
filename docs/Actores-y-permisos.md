# Actores y permisos

Este documento define quién usa Insumap, qué necesita cada actor, en qué contexto trabaja y qué puede hacer. La matriz de permisos es la fuente para el código: los roles y los códigos de permiso se guardan en la base de datos (`iam.roles`, `iam.permissions`, `iam.role_permissions`), la autorización es de **denegación por defecto** y el código solo verifica códigos de permiso, nunca nombres de rol.

> **Aviso:** Insumap es un proyecto académico, no es un dispositivo médico y la IA solo apoya al médico. Los pacientes son simulados.

## 1. Actores

### 1.1 Actores humanos

| Actor | Rol en el sistema | Objetivo | Necesidades | Contexto de uso | Canales |
|---|---|---|---|---|---|
| Administrador de la plataforma | `PLATFORM_ADMIN` | Dar de alta y controlar las clínicas (tenants). Rol mínimo. | Crear y suspender clínicas, crear el primer administrador de cada clínica, gestionar la clínica demo. | Equipo de Insumap, computador. | Consola de administración (web). |
| Administrador de la clínica | `CLINIC_ADMIN` | Que la clínica opere ordenadamente sobre Insumap sin exponer datos clínicos. | Importar pacientes, emitir credenciales, gestionar médicos, asignar equipos de atención, configurar metas, reglas de alerta y plantillas, ver KPIs y auditoría. | Personal administrativo o de sistemas de la clínica, computador, jornada de oficina. No es clínico. | Consola de administración (web). |
| Médico | `DOCTOR` | Vigilar a sus pacientes, decidir y ajustar tratamientos con evidencia. | Saber a quién ver hoy, ver métricas (TIR, AGP), alertas, plan, recomendaciones de IA para aprobar, notas y mensajes. | Consulta y revisión entre pacientes; poco tiempo; computador y a veces tablet o celular. | Dashboard del médico (web, responsivo). |
| Paciente | `PATIENT` | Llevar el control de su diabetes y hablar con su equipo. | Registrar glucosa, insulina, comidas, actividad y síntomas en pocos pasos, ver su tendencia y metas, recibir recordatorios, escribir a su médico, aprender con un asistente. | Celular, en la calle o en casa, a veces sin conexión; edades y habilidades digitales variadas. | PWA mobile-first, notificaciones in-app, Web Push y correo. |

### 1.2 Actores de sistema

| Actor | Rol | Qué hace | Autenticación |
|---|---|---|---|
| Servicio de IA (`insumap-ai`) | Sistema | Calcula pronósticos, riesgo, patrones, resúmenes y respuestas. No guarda estado ni decide; solo recibe seudónimos. | Token de servicio. |
| Simulador (`insumap-simulator`) | Sistema | Entrega Bundles FHIR y CSV al importador y, en modo `live`, envía lecturas con tokens de paciente. | Token de paciente (modo `live`) y sesión de `CLINIC_ADMIN` (backfill). |
| Planificador | Sistema | Dispara recordatorios, evaluación de alertas y el triage nocturno. | Interno, sin API pública. |
| LLM externo | Tercero | Genera texto a partir de datos seudonimizados. | Clave en variables de entorno del servicio de IA. |

### 1.3 Notas

- El paciente **no se registra por su cuenta**: su clínica lo importa y lo invita.
- El `PLATFORM_ADMIN` y el `CLINIC_ADMIN` **no ven datos clínicos detallados** (glucosa, dosis, notas, mensajes, recomendaciones).
- Un usuario pertenece a **una clínica** (membresía). El `PLATFORM_ADMIN` no pertenece a ninguna clínica clínicamente operativa.
- No hay actores anónimos: todo acceso requiere cuenta, salvo el login, la activación con código y la recuperación de contraseña.

## 2. Roles del sistema (RBAC)

| Código | Nombre en español | Descripción | MFA |
|---|---|---|---|
| `PLATFORM_ADMIN` | Administrador de la plataforma | Gestiona clínicas y la clínica demo. Sin acceso clínico. | Obligatorio (personal). |
| `CLINIC_ADMIN` | Administrador de la clínica | Gestiona usuarios, importación, credenciales, equipos, metas, reglas, plantillas, KPIs y auditoría de su clínica. Sin detalle clínico. | Obligatorio (personal). |
| `DOCTOR` | Médico | Atiende solo a sus pacientes asignados: ve su información clínica, gestiona planes, decide recomendaciones y responde alertas. | Obligatorio (personal). |
| `PATIENT` | Paciente | Registra y consulta únicamente sus propios datos. | No. |

MFA TOTP es obligatorio para todo rol distinto de `PATIENT` (ver [Seguridad.md](Seguridad.md)). Duración de sesión: access token de 15 minutos y refresh opaco con rotación y detección de reutilización (ver [Requerimientos.md](Requerimientos.md), RNF-02).

## 3. Permisos

### 3.1 Convenciones

- Los códigos son `dominio.accion` o `dominio.accion_alcance` en inglés y minúsculas (`^[a-z][a-z_]*\.[a-z][a-z_]*$`, tabla `iam.permissions`).
- Sufijos de alcance:
  - `_own`: solo sobre los propios registros del usuario (paciente).
  - `_assigned`: solo sobre los pacientes asignados al médico en `clinic.care_team_assignments`.
  - sin sufijo: sobre la clínica del usuario (o la plataforma para `PLATFORM_ADMIN`).
- Las acciones sobre la propia cuenta (cambiar contraseña, cerrar sesión, administrar MFA y sesiones propias, consultar `GET /auth/me`, catálogos) solo requieren estar autenticado, sin permiso adicional.
- Las acciones previas a la sesión (login, activación con código, recuperación de contraseña) no tienen permiso y se protegen con rate limiting.
- Los permisos del catálogo son canónicos para el código; si un historial o requisito necesita uno nuevo, se agrega aquí primero.

### 3.2 Catálogo de permisos

| Código | Descripción | Módulo |
|---|---|---|
| `clinics.manage` | Crear, editar, suspender y reactivar clínicas, y marcar una clínica como demo. | M2 |
| `clinic_admins.manage` | Crear el primer `CLINIC_ADMIN` de una clínica y restablecer su acceso. | M2 |
| `clinics.read` | Ver los datos y la configuración de la propia clínica. | M2 |
| `sites.manage` | Crear y editar sedes de la clínica. | M2 |
| `users.manage` | Crear, editar y desactivar personal (`DOCTOR`, `CLINIC_ADMIN`) de la clínica. | M2 |
| `users.read` | Listar el personal de la clínica. | M2 |
| `patients.import` | Importar pacientes (FHIR R4 o CSV) y revisar el resultado por fila. | M3 |
| `import_batches.read` | Consultar el historial de lotes de importación. | M3 |
| `patients.read_roster` | Ver el listado administrativo de pacientes (identificación, MRN, estado de cuenta, equipo), sin datos clínicos. | M3 |
| `patients.manage_status` | Suspender, reactivar y desactivar cuentas de pacientes. | M3 |
| `credentials.issue` | Emitir y reenviar invitaciones con código de activación. | M3 |
| `credentials.revoke` | Revocar una invitación pendiente. | M3 |
| `care_team.assign` | Asignar, reasignar y retirar médicos de un paciente y designar al médico principal. | M4 |
| `care_team.read` | Ver las asignaciones del equipo de atención (el médico, solo las propias). | M4 |
| `patients.read_assigned` | Ver el detalle clínico de los pacientes asignados (perfil, registros, línea de tiempo). | M4, M5 |
| `patients.read_own` | Ver el propio perfil y estado. | M5 |
| `glucose.write_own` | Registrar glucosa (manual, lote offline, CSV de CGM) propia. | M5 |
| `glucose.read_own` | Consultar la glucosa propia. | M5 |
| `records.write_own` | Registrar insulina, comidas, actividad y síntomas propios. | M5 |
| `records.read_own` | Consultar insulina, comidas, actividad y síntomas propios. | M5 |
| `records.correct_own` | Corregir o anular un registro propio con motivo (sin borrar el original). | M5 |
| `labs.write_own` | Registrar un resultado de laboratorio propio (HbA1c) como autorreporte. | M5 |
| `labs.write_assigned` | Registrar o confirmar resultados de laboratorio de pacientes asignados. | M5 |
| `protocol_templates.manage` | Crear, versionar y retirar plantillas de protocolo de la clínica. | M6 |
| `protocol_templates.read` | Ver y clonar plantillas de protocolo. | M6 |
| `treatment_plans.manage` | Crear, editar, activar y versionar planes de tratamiento de pacientes asignados y restaurar versiones. | M6 |
| `treatment_plans.read_own` | Ver el plan de tratamiento activo propio. | M6 |
| `target_profiles.manage` | Crear y versionar perfiles de metas glucémicas (TIR, TBR, TAR). | M6 |
| `target_profiles.assign` | Asignar un perfil de metas a un paciente asignado. | M6 |
| `reminders.manage_assigned` | Programar recordatorios de pacientes asignados. | M6 |
| `reminders.manage_own` | Ajustar los recordatorios propios dentro de lo que permite el plan. | M6 |
| `metrics.read_assigned` | Ver TIR, TBR, TAR, GMI, CV y AGP de pacientes asignados. | M7 |
| `metrics.read_own` | Ver las métricas propias. | M7 |
| `alert_rules.manage` | Crear y versionar reglas de alerta de la clínica. | M8 |
| `alert_rules.read` | Ver las reglas de alerta vigentes. | M8 |
| `alerts.read_assigned` | Ver alertas de pacientes asignados. | M8 |
| `alerts.read_own` | Ver alertas propias. | M8 |
| `alerts.acknowledge` | Reconocer una alerta de un paciente asignado. | M8 |
| `alerts.acknowledge_own` | Reconocer una alerta propia (primer paso de la cadena de escalamiento). | M8 |
| `alerts.resolve` | Resolver una alerta de un paciente asignado, con nota. | M8 |
| `alerts.read_summary` | Ver conteos agregados de alertas de la clínica, sin identificar clínicamente al paciente. | M8 |
| `notifications.read_own` | Ver y marcar como leídas las notificaciones propias. | M8 |
| `notification_preferences.manage_own` | Elegir canales y horario de notificaciones propios. | M8 |
| `ai.forecasts.read_assigned` | Ver pronósticos de glucosa de pacientes asignados. | M9 |
| `ai.forecasts.read_own` | Ver el pronóstico propio. | M9 |
| `ai.risk.read_assigned` | Ver el riesgo, los patrones y los factores explicados de pacientes asignados. | M9 |
| `ai.dropout_risk.read` | Ver el riesgo de abandono (médico: pacientes asignados; administrador: lista sin detalle clínico). | M9 |
| `recommendations.read_assigned` | Ver las recomendaciones de la IA de pacientes asignados. | M9 |
| `recommendations.decide` | Aprobar, aprobar con cambios o rechazar una recomendación (motivo obligatorio al modificar o rechazar). | M9 |
| `clinical_summaries.generate` | Generar y leer el resumen previo a la consulta de un paciente asignado. | M9 |
| `assistant.use` | Conversar con el asistente educativo. | M9 |
| `ai_evaluations.read` | Ver la evaluación de la IA frente al respaldo. | M9 |
| `dashboard.read_assigned` | Ver el dashboard de triage con los pacientes asignados. | M10 |
| `clinical_notes.manage` | Crear notas clínicas sobre pacientes asignados. | M10 |
| `reports.generate_assigned` | Generar reportes de un paciente asignado. | M10 |
| `reports.generate_own` | Generar el reporte propio para compartir con su equipo. | M10 |
| `clinic_kpis.read` | Ver KPIs agregados de adopción y de la clínica, sin detalle clínico. | M10 |
| `reports.generate_clinic` | Generar reportes agregados de la clínica. | M10 |
| `messages.use_assigned` | Leer y responder mensajes de pacientes asignados. | M11 |
| `messages.use_own` | Escribir al equipo de atención y leer las respuestas. | M11 |
| `follow_ups.manage` | Programar y cerrar controles de pacientes asignados. | M11 |
| `follow_ups.read_own` | Ver los controles propios. | M11 |
| `audit.read` | Consultar la auditoría de la clínica (acciones y accesos), sin contenido clínico. | M12 |
| `audit.read_platform` | Consultar eventos de seguridad y auditoría de la plataforma. | M12 |
| `consents.manage_own` | Aceptar, consultar y retirar los consentimientos propios. | M12 |
| `consents.read_status` | Ver el estado del consentimiento por paciente, sin contenido clínico. | M12 |
| `privacy_requests.create_own` | Solicitar acceso, rectificación o supresión de los datos propios. | M12 |
| `privacy_requests.manage` | Tramitar solicitudes de privacidad de la clínica. | M12 |
| `demo_data.manage` | Crear, reiniciar e importar datos de la clínica demo. | M13 |

### 3.3 Matriz rol × permiso

Convenciones: **Sí** = el rol tiene el permiso; **-** = no lo tiene (denegación por defecto). El alcance (`_own`, `_assigned` o la clínica) está en el código y se explica en la sección 4.

| Permiso | `PLATFORM_ADMIN` | `CLINIC_ADMIN` | `DOCTOR` | `PATIENT` |
|---|---|---|---|---|
| `clinics.manage` | Sí | - | - | - |
| `clinic_admins.manage` | Sí | - | - | - |
| `clinics.read` | - | Sí | Sí | - |
| `sites.manage` | - | Sí | - | - |
| `users.manage` | - | Sí | - | - |
| `users.read` | - | Sí | - | - |
| `patients.import` | - | Sí | - | - |
| `import_batches.read` | - | Sí | - | - |
| `patients.read_roster` | - | Sí | - | - |
| `patients.manage_status` | - | Sí | - | - |
| `credentials.issue` | - | Sí | - | - |
| `credentials.revoke` | - | Sí | - | - |
| `care_team.assign` | - | Sí | - | - |
| `care_team.read` | - | Sí | Sí | - |
| `patients.read_assigned` | - | - | Sí | - |
| `patients.read_own` | - | - | - | Sí |
| `glucose.write_own` | - | - | - | Sí |
| `glucose.read_own` | - | - | - | Sí |
| `records.write_own` | - | - | - | Sí |
| `records.read_own` | - | - | - | Sí |
| `records.correct_own` | - | - | - | Sí |
| `labs.write_own` | - | - | - | Sí |
| `labs.write_assigned` | - | - | Sí | - |
| `protocol_templates.manage` | - | Sí | - | - |
| `protocol_templates.read` | - | Sí | Sí | - |
| `treatment_plans.manage` | - | - | Sí | - |
| `treatment_plans.read_own` | - | - | - | Sí |
| `target_profiles.manage` | - | Sí | - | - |
| `target_profiles.assign` | - | - | Sí | - |
| `reminders.manage_assigned` | - | - | Sí | - |
| `reminders.manage_own` | - | - | - | Sí |
| `metrics.read_assigned` | - | - | Sí | - |
| `metrics.read_own` | - | - | - | Sí |
| `alert_rules.manage` | - | Sí | - | - |
| `alert_rules.read` | - | Sí | Sí | - |
| `alerts.read_assigned` | - | - | Sí | - |
| `alerts.read_own` | - | - | - | Sí |
| `alerts.acknowledge` | - | - | Sí | - |
| `alerts.acknowledge_own` | - | - | - | Sí |
| `alerts.resolve` | - | - | Sí | - |
| `alerts.read_summary` | - | Sí | - | - |
| `notifications.read_own` | Sí | Sí | Sí | Sí |
| `notification_preferences.manage_own` | Sí | Sí | Sí | Sí |
| `ai.forecasts.read_assigned` | - | - | Sí | - |
| `ai.forecasts.read_own` | - | - | - | Sí |
| `ai.risk.read_assigned` | - | - | Sí | - |
| `ai.dropout_risk.read` | - | Sí | Sí | - |
| `recommendations.read_assigned` | - | - | Sí | - |
| `recommendations.decide` | - | - | Sí | - |
| `clinical_summaries.generate` | - | - | Sí | - |
| `assistant.use` | - | - | - | Sí |
| `ai_evaluations.read` | Sí | Sí | - | - |
| `dashboard.read_assigned` | - | - | Sí | - |
| `clinical_notes.manage` | - | - | Sí | - |
| `reports.generate_assigned` | - | - | Sí | - |
| `reports.generate_own` | - | - | - | Sí |
| `clinic_kpis.read` | - | Sí | - | - |
| `reports.generate_clinic` | - | Sí | - | - |
| `messages.use_assigned` | - | - | Sí | - |
| `messages.use_own` | - | - | - | Sí |
| `follow_ups.manage` | - | - | Sí | - |
| `follow_ups.read_own` | - | - | - | Sí |
| `audit.read` | - | Sí | - | - |
| `audit.read_platform` | Sí | - | - | - |
| `consents.manage_own` | - | - | - | Sí |
| `consents.read_status` | - | Sí | - | - |
| `privacy_requests.create_own` | - | - | - | Sí |
| `privacy_requests.manage` | - | Sí | - | - |
| `demo_data.manage` | Sí | - | - | - |

Notas sobre la matriz:

- **El `CLINIC_ADMIN` no tiene ningún permiso `*_assigned` ni `*_own` de datos clínicos.** Sus permisos de resumen (`alerts.read_summary`, `clinic_kpis.read`, `ai.dropout_risk.read`, `consents.read_status`) devuelven conteos o listas administrativas, nunca series de glucosa, dosis, notas ni mensajes.
- El `PLATFORM_ADMIN` no tiene permiso alguno sobre pacientes ni sobre datos de una clínica distinto de crearla.
- El `DOCTOR` no puede importar pacientes, emitir credenciales ni asignar equipos: eso es administrativo.
- El `DOCTOR` define el plan del paciente, pero no las **metas ni las reglas de la clínica** (las configura el `CLINIC_ADMIN`); sí asigna un perfil de metas a su paciente.
- Un permiso de tipo `_own` sobre la ruta de otro paciente responde `404`.

## 4. Reglas de visibilidad y acceso por objeto

El permiso (RBAC) es la primera barrera. Después se aplican, en este orden, el aislamiento por clínica, la asignación y la propiedad.

| # | Regla | Dónde se aplica | Resultado si falla |
|---|---|---|---|
| V1 | **Aislamiento por clínica (tenant).** Toda fila lleva `clinic_id`. La transacción fija `app.clinic_id` y `app.user_id` con `SET LOCAL`, y la RLS filtra por clínica. | Base de datos (RLS) y repositorios | El recurso no existe: `404 NOT_FOUND`. |
| V2 | **Asignación del equipo de atención.** Un `DOCTOR` solo accede a un paciente si existe una fila vigente en `clinic.care_team_assignments` que los une. | `PatientRecordAccessProxy` (P11) | `404 NOT_FOUND` (no revela que el paciente existe). |
| V3 | **El paciente solo ve lo propio.** Toda ruta `_own` usa el `patient_id` del token, nunca uno recibido por parámetro. Además aplica RLS en la base de datos sobre sus filas. | Casos de uso y RLS | `404 NOT_FOUND`. |
| V4 | **El administrador no ve detalle clínico.** `CLINIC_ADMIN` y `PLATFORM_ADMIN` no tienen permisos de lectura clínica; los endpoints de listado administrativo devuelven solo campos administrativos. | Permisos y esquemas de respuesta | `403 FORBIDDEN` si falta el permiso. |
| V5 | **Cada lectura clínica se audita.** Toda lectura de datos clínicos registra quién, a quién, qué y cuándo. | `PhiAccessAuditDecorator` (P09) | La operación no responde si la auditoría falla. |
| V6 | **Consentimiento vigente.** Sin consentimiento vigente y versión aceptada, el paciente no pasa a `ACTIVE`. Si lo retira, no se guardan nuevos datos y se aplica la política de retención. | Activación y registros | `403 CONSENT_REQUIRED`. |
| V7 | **Minimización hacia la IA.** Al servicio de IA y al LLM solo llega un seudónimo y datos necesarios; nunca nombres, documentos, MRN ni contacto. | `AiServiceClientAdapter` (P06) | La llamada no se envía. |
| V8 | **Mensajes y notas.** Solo los ven el paciente y su equipo asignado. El administrador no los ve. | Casos de uso | `404 NOT_FOUND`. |
| V9 | **Clínica demo.** Todo dato de una clínica `is_demo = true` se marca "Datos simulados". | API, reportes y UI | No aplica (es marcado, no bloqueo). |
| V10 | **Retirar la asignación retira el acceso.** Al terminar la asignación, el médico deja de ver al paciente; sus decisiones previas quedan en la auditoría. | Proxy y auditoría | `404 NOT_FOUND`. |

### 4.1 Códigos de respuesta de autorización

| Situación | Código HTTP | Código de error |
|---|---|---|
| Sin token o token vencido | 401 | `UNAUTHORIZED` |
| Rol sin el permiso requerido | 403 | `FORBIDDEN` |
| Recurso de otra clínica, paciente no asignado o dato ajeno | 404 | `NOT_FOUND` |
| Falta MFA para el personal | 403 | `MFA_REQUIRED` |
| Cuenta no `ACTIVE` | 403 | `ACCOUNT_NOT_ACTIVE` |
| Falta consentimiento vigente | 403 | `CONSENT_REQUIRED` |

## 5. Reglas del estado de cuenta del paciente

Los estados `IMPORTED → INVITED → ACTIVE → SUSPENDED → DEACTIVATED` se modelan con `PatientAccountState` (P18 State).

| Estado | Significado | ¿Puede iniciar sesión? | ¿Se guardan registros? | ¿Qué lo cambia? |
|---|---|---|---|---|
| `IMPORTED` | El paciente fue importado desde la clínica; todavía no tiene credenciales. | No | No | `CLINIC_ADMIN` emite credenciales: pasa a `INVITED`. |
| `INVITED` | Tiene una invitación vigente con código de un solo uso. | Solo para activar con el código. | No | El paciente activa y acepta el consentimiento: pasa a `ACTIVE`. Si el código vence o se revoca: vuelve a `IMPORTED`. Reenviar invalida el código anterior. |
| `ACTIVE` | Cuenta en uso. | Sí | Sí | `CLINIC_ADMIN` suspende: `SUSPENDED`. Desactiva: `DEACTIVATED`. |
| `SUSPENDED` | Bloqueo temporal (administrativo o de seguridad). | No; las sesiones se revocan. | No | `CLINIC_ADMIN` reactiva: `ACTIVE`. Desactiva: `DEACTIVATED`. |
| `DEACTIVATED` | Baja definitiva (terminal). | No | No | No hay regreso. Los datos se conservan según la política de retención o se anonimizan. |

Transiciones permitidas:

| Desde | Hacia | Evento | Quién |
|---|---|---|---|
| `IMPORTED` | `INVITED` | Emitir credenciales | `CLINIC_ADMIN` (`credentials.issue`) |
| `INVITED` | `INVITED` | Reenviar (nuevo código; el anterior queda inválido) | `CLINIC_ADMIN` (`credentials.issue`) |
| `INVITED` | `IMPORTED` | Revocar o vencer la invitación | `CLINIC_ADMIN` (`credentials.revoke`) o el sistema |
| `INVITED` | `ACTIVE` | Activar la cuenta con consentimiento | `PATIENT` (sin sesión previa) |
| `ACTIVE` | `SUSPENDED` | Suspender | `CLINIC_ADMIN` (`patients.manage_status`) |
| `SUSPENDED` | `ACTIVE` | Reactivar | `CLINIC_ADMIN` (`patients.manage_status`) |
| `IMPORTED`, `INVITED`, `ACTIVE`, `SUSPENDED` | `DEACTIVATED` | Dar de baja | `CLINIC_ADMIN` (`patients.manage_status`) |

Toda transición queda en la auditoría con quién, cuándo y el motivo (obligatorio al suspender o desactivar). Una transición no listada responde `409 INVALID_STATE_TRANSITION`.

### 5.1 Cuentas del personal

El personal (`DOCTOR`, `CLINIC_ADMIN`, `PLATFORM_ADMIN`) tiene un indicador `is_active`. Al desactivarlo se revocan todas sus sesiones y refresh tokens, y sus asignaciones de pacientes quedan pendientes de reasignar (el `CLINIC_ADMIN` recibe el aviso). El personal debe activar MFA TOTP en su primer ingreso antes de usar la API.

## 6. Resumen por actor

| Actor | Puede | No puede |
|---|---|---|
| `PLATFORM_ADMIN` | Crear y suspender clínicas, crear el primer administrador, gestionar la clínica demo, ver eventos de seguridad de la plataforma. | Ver pacientes ni datos clínicos de ninguna clínica. |
| `CLINIC_ADMIN` | Importar pacientes, emitir y revocar credenciales, gestionar personal, asignar equipos, configurar metas, reglas y plantillas, ver KPIs y auditoría de su clínica. | Ver glucosa, dosis, notas, mensajes ni recomendaciones; decidir tratamientos. |
| `DOCTOR` | Ver y gestionar a sus pacientes asignados: dashboard, métricas, plan, alertas, recomendaciones (aprobar, modificar o rechazar), notas, mensajes y controles. | Ver pacientes no asignados o de otra clínica; importar pacientes; cambiar reglas de la clínica. |
| `PATIENT` | Registrar y ver sus datos, plan, alertas, recordatorios, mensajes y reporte; usar el asistente; gestionar su consentimiento. | Ver datos de otros pacientes, ver recomendaciones de la IA para el médico, recibir dosis de la IA. |

## Documentos relacionados

[Insumap.md](Insumap.md) · [Requerimientos.md](Requerimientos.md) · [Historias-de-usuario.md](Historias-de-usuario.md) · [Seguridad.md](Seguridad.md) · [Cumplimiento-y-privacidad.md](Cumplimiento-y-privacidad.md) · [Modelo-de-datos.md](Modelo-de-datos.md) · [Glosario.md](Glosario.md)
