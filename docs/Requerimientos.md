# Requerimientos

Este documento lista los requisitos funcionales (RF) y no funcionales (RNF) de Insumap. Cada RF corresponde a una capacidad concreta y se enlaza con una o más historias de [Historias-de-usuario.md](Historias-de-usuario.md). Los RNF aplican a todo el sistema o a varios módulos. Los IDs (`RF-xx`, `RNF-xx`) son estables: otros documentos y el [Plan-de-commits.md](Plan-de-commits.md) los referencian y no se renumeran.

> **Aviso:** Insumap es un proyecto académico, no es un dispositivo médico y la IA solo apoya al médico. Los pacientes son simulados.

## 0. Convenciones

- **Prioridad:** `MVP` = fases 1 a 9 del plan más el modo `backfill` del simulador. `Post-MVP` = fases 10 a 12 (IA generativa, mensajería, consola de auditoría completa, modo `live`, endurecimiento).
- Las metas de rendimiento y usabilidad son **objetivos**, marcados "objetivo, verificar". Se confirman con mediciones en la fase 12.
- Los valores clínicos y de negocio que aparecen aquí (umbrales, metas, duraciones) son **ejemplos de semilla**: viven en la base de datos y los configura el `CLINIC_ADMIN`; nunca se escriben en el código.
- Roles: `PLATFORM_ADMIN`, `CLINIC_ADMIN`, `DOCTOR`, `PATIENT`. Permisos: [Actores-y-permisos.md](Actores-y-permisos.md).
- Repositorios: `B` = `insumap-backend`, `D` = `insumap-database`, `F` = `insumap-frontend`, `IA` = `insumap-ai`, `S` = `insumap-simulator`.
- Módulos: M1 Identidad y acceso, M2 Clínicas y usuarios, M3 Onboarding desde la BD de la clínica y credenciales, M4 Equipo de atención, M5 Registros del paciente, M6 Plan de tratamiento, M7 Métricas glucémicas, M8 Alertas y notificaciones, M9 IA y soporte a decisiones, M10 Dashboard médico y reportes, M11 Mensajería y seguimiento, M12 Auditoría y cumplimiento, M13 Datos simulados.
- Estados canónicos: cuenta del paciente `IMPORTED → INVITED → ACTIVE → SUSPENDED → DEACTIVATED`; recomendación `PROPOSED → APPROVED | APPROVED_WITH_CHANGES | REJECTED`, aprobada `→ APPLIED`, sin atender `→ EXPIRED`; alerta `OPEN → ACKNOWLEDGED → RESOLVED` y `OPEN → ESCALATED → ACKNOWLEDGED`.
- La glucosa se almacena siempre en **mg/dL**; el mmol/L solo se acepta y se muestra mediante conversión con una constante con nombre.

## 1. Requisitos funcionales

### Resumen de rangos

| Módulo | Rango RF | Cantidad |
|---|---|---|
| M1 Identidad y acceso | RF-01 a RF-08 | 8 |
| M2 Clínicas y usuarios | RF-09 a RF-15 | 7 |
| M3 Onboarding y credenciales | RF-16 a RF-26 | 11 |
| M4 Equipo de atención | RF-27 a RF-30 | 4 |
| M5 Registros del paciente | RF-31 a RF-42 | 12 |
| M6 Plan de tratamiento | RF-43 a RF-50 | 8 |
| M7 Métricas glucémicas | RF-51 a RF-55 | 5 |
| M8 Alertas y notificaciones | RF-56 a RF-65 | 10 |
| M9 IA y soporte a decisiones | RF-66 a RF-77 | 12 |
| M10 Dashboard y reportes | RF-78 a RF-83 | 6 |
| M11 Mensajería y seguimiento | RF-84 a RF-87 | 4 |
| M12 Auditoría y cumplimiento | RF-88 a RF-95 | 8 |
| M13 Datos simulados | RF-96 a RF-100 | 5 |
| **Total** | **RF-01 a RF-100** | **100** |

### M1 Identidad y acceso

| ID | Requisito | Prioridad | Criterio de aceptación (resumen) | HU | Repos |
|---|---|---|---|---|---|
| RF-01 | El sistema autentica con correo y contraseña y emite un access token JWT de 15 minutos y un refresh token opaco guardado solo como hash. | MVP | Credenciales válidas devuelven ambos tokens; credenciales inválidas devuelven `401 INVALID_CREDENTIALS` con mensaje genérico. | HU-01 | B, D, F |
| RF-02 | El refresh token rota en cada uso; si se reutiliza uno ya rotado, se revoca toda su familia. El usuario puede cerrar la sesión actual o todas. | MVP | Reusar un refresh rotado devuelve `401` y deja la familia revocada; tras cerrar todas las sesiones ningún token previo sirve. | HU-03 | B, D, F |
| RF-03 | El personal (todo rol distinto de `PATIENT`) activa MFA TOTP con códigos de respaldo de un solo uso; sin MFA no puede usar la API. | MVP | Un `DOCTOR` sin MFA recibe `403 MFA_REQUIRED` salvo para enrolarlo; un código TOTP válido permite el acceso. | HU-02 | B, F |
| RF-04 | Las contraseñas se guardan con Argon2id, cumplen la política de longitud y no se reutilizan (historial). | MVP | Contraseña corta o reutilizada se rechaza con `VALIDATION_ERROR`; nunca aparece en logs ni respuestas. | HU-03 | B, D |
| RF-05 | El sistema bloquea el login tras intentos fallidos repetidos con bloqueo escalonado y limita los intentos por IP y por cuenta. | MVP | Superar el límite devuelve `429 RATE_LIMITED` con `Retry-After`; los intentos quedan en `iam.login_attempts`. | HU-01 | B, D |
| RF-06 | El usuario recupera su contraseña con un enlace de un solo uso con expiración; el cambio revoca todas las sesiones. | MVP | Un enlace usado o vencido se rechaza; tras el cambio los refresh tokens previos dejan de funcionar. | HU-03 | B, F |
| RF-07 | Toda operación se autoriza por permiso leído de la base de datos (`iam.role_permissions`) con denegación por defecto. | MVP | Un rol sin el permiso recibe `403 FORBIDDEN`; no existe ninguna comparación de nombre de rol en el código de negocio. | HU-01 | B, D |
| RF-08 | `GET /auth/me` devuelve el usuario, su rol, su clínica, sus permisos, el estado de MFA y el consentimiento vigente. | MVP | La respuesta incluye la lista de permisos y las banderas `mfa_enabled` y `consent_required`. | HU-01 | B, F |

### M2 Clínicas y usuarios

| ID | Requisito | Prioridad | Criterio de aceptación (resumen) | HU | Repos |
|---|---|---|---|---|---|
| RF-09 | El `PLATFORM_ADMIN` crea una clínica (tenant) con nombre, identificación fiscal y bandera `is_demo`. | MVP | La clínica queda `ACTIVE` y aislada; el nombre repetido devuelve `409 CONFLICT`. | HU-04 | B, D, F |
| RF-10 | El `PLATFORM_ADMIN` edita, suspende y reactiva una clínica; al suspenderla, su personal y pacientes no pueden iniciar sesión. | MVP | Una clínica suspendida rechaza el login con `403 CLINIC_SUSPENDED`; reactivarla restablece el acceso. | HU-04 | B, F |
| RF-11 | El `PLATFORM_ADMIN` crea el primer `CLINIC_ADMIN` de la clínica y puede restablecer su acceso. | MVP | El administrador recibe una invitación y debe enrolar MFA en su primer ingreso. | HU-04 | B, F |
| RF-12 | El `CLINIC_ADMIN` crea y edita personal (médicos y administradores) con perfil profesional y especialidad. | MVP | Cada usuario nuevo recibe credenciales de un solo uso y queda en la clínica del creador. | HU-05 | B, F |
| RF-13 | El `CLINIC_ADMIN` desactiva personal; sus sesiones se revocan y sus pacientes quedan pendientes de reasignar. | MVP | El usuario desactivado no puede iniciar sesión; el administrador ve la lista de pacientes sin médico asignado. | HU-05 | B, F |
| RF-14 | Ningún usuario accede a datos de otra clínica: toda fila lleva `clinic_id`, la transacción fija el contexto y la RLS aplica. | MVP | Pedir un recurso de otra clínica devuelve `404 NOT_FOUND`; una prueba de aislamiento entre dos clínicas pasa en la base de datos. | HU-06, HU-14 | B, D |
| RF-15 | El `CLINIC_ADMIN` administra las sedes de la clínica y asocia personal a una sede. | Post-MVP | Un médico puede pertenecer a varias sedes de la misma clínica. | HU-05 | B, D, F |

### M3 Onboarding desde la BD de la clínica y credenciales

| ID | Requisito | Prioridad | Criterio de aceptación (resumen) | HU | Repos |
|---|---|---|---|---|---|
| RF-16 | El `CLINIC_ADMIN` importa pacientes desde un Bundle FHIR R4 (Patient, Practitioner, Condition, Observation con LOINC, MedicationRequest). | MVP | Un Bundle válido crea pacientes `IMPORTED`; recursos no soportados se reportan sin detener el lote. | HU-06 | B, S |
| RF-17 | El `CLINIC_ADMIN` importa pacientes desde un CSV con plantilla descargable y codificación UTF-8. | MVP | Un CSV con columnas correctas se procesa; columnas faltantes devuelven `422` con el nombre de la columna. | HU-07 | B, F |
| RF-18 | Antes de confirmar, el sistema valida cada fila y muestra una previsualización con aciertos, advertencias y errores por fila; solo se confirma el lote completo. | MVP | Una fila inválida no impide ver las demás y queda con su causa en `import_rows`; confirmar crea solo las filas válidas. | HU-06, HU-07, HU-08 | B, F |
| RF-19 | El sistema deduplica por número de historia (MRN) de la clínica; un MRN repetido actualiza datos administrativos permitidos o se omite, sin crear un segundo paciente. | MVP | Importar dos veces el mismo archivo no duplica pacientes y el reporte indica `SKIPPED_DUPLICATE`. | HU-06, HU-07 | B, D |
| RF-20 | El sistema conserva el historial de lotes de importación con totales, origen, autor y resultado por fila. | MVP | El administrador consulta cada lote y descarga los errores. | HU-08 | B, D, F |
| RF-21 | Al importar se crea una cuenta `IMPORTED`; el documento de identidad se guarda cifrado y con hash, y la cuenta no tiene contraseña ni acceso. | MVP | La consulta directa a la base de datos no muestra el documento en claro; la cuenta no puede iniciar sesión. | HU-06, HU-07 | B, D |
| RF-22 | El `CLINIC_ADMIN` emite credenciales: una invitación con código de activación de un solo uso, guardado como hash y con expiración; la cuenta pasa a `INVITED`. | MVP | El código solo se muestra al emitirlo; sin código vigente no hay activación; la cuenta queda `INVITED`. | HU-09 | B, D |
| RF-23 | El `CLINIC_ADMIN` reenvía una invitación (el código anterior queda inválido) o la revoca (la cuenta vuelve a `IMPORTED`). | MVP | Un código reemplazado o revocado se rechaza con `410 INVITATION_INVALID`. | HU-09 | B, F |
| RF-24 | El paciente activa su cuenta con el código, define su contraseña y acepta el consentimiento de tratamiento de datos sensibles; la cuenta pasa a `ACTIVE`. | MVP | Sin aceptar el consentimiento no se activa; el código se consume y no sirve de nuevo; hay rate limiting en la activación. | HU-10 | B, F |
| RF-25 | La invitación se entrega por correo electrónico o se imprime (hoja de credenciales) a través de canales de notificación intercambiables. | MVP | Ambos canales usan el mismo contenido; el envío fallido queda registrado y se puede reintentar. | HU-09 | B, F |
| RF-26 | El `CLINIC_ADMIN` suspende, reactiva y desactiva cuentas de paciente; suspender revoca sus sesiones y desactivar es terminal. | MVP | Las transiciones no permitidas devuelven `409 INVALID_STATE_TRANSITION`; el motivo es obligatorio. | HU-11 | B, F |

### M4 Equipo de atención

| ID | Requisito | Prioridad | Criterio de aceptación (resumen) | HU | Repos |
|---|---|---|---|---|---|
| RF-27 | El `CLINIC_ADMIN` asigna uno o varios médicos a un paciente. | MVP | Solo se asignan médicos activos de la misma clínica; la asignación queda en la auditoría. | HU-12 | B, D, F |
| RF-28 | Cada paciente con equipo tiene exactamente un médico principal. | MVP | Designar un nuevo principal reemplaza al anterior en la misma operación; no se puede quedar sin principal. | HU-12 | B, D |
| RF-29 | El `CLINIC_ADMIN` reasigna o retira médicos con motivo e historial; al retirar la asignación se pierde el acceso. | MVP | El médico retirado recibe `404` sobre el paciente; el historial muestra fechas y motivo. | HU-13 | B, D, F |
| RF-30 | Un `DOCTOR` solo accede a los pacientes asignados mediante un proxy de protección que verifica la asignación en cada acceso. | MVP | Acceso a un paciente no asignado devuelve `404 NOT_FOUND`; la prueba unitaria del proxy no necesita FastAPI ni base de datos. | HU-14 | B |

### M5 Registros del paciente

| ID | Requisito | Prioridad | Criterio de aceptación (resumen) | HU | Repos |
|---|---|---|---|---|---|
| RF-31 | El paciente registra una lectura de glucosa manual (SMBG) con valor, fecha y hora, y contexto (ayunas, antes o después de comer, al acostarse, ejercicio, otro). | MVP | La lectura se guarda en mg/dL con su fuente `MANUAL` o `SMBG`; sin contexto válido devuelve `VALIDATION_ERROR`. | HU-15 | B, F |
| RF-32 | El cliente envía lecturas pendientes por lotes con un UUID de cliente por lectura; el servidor las procesa de forma idempotente y responde el resultado de cada una. | MVP | Reenviar el mismo lote no duplica lecturas; cada elemento devuelve `CREATED`, `DUPLICATE` o `REJECTED` con causa. | HU-16 | B, F |
| RF-33 | Toda lectura pasa por una cadena de validación (rango, fecha, duplicado, tasa de cambio y unidad) y se convierte a mg/dL. | MVP | Un valor fuera del rango fisiológico configurado devuelve `422 GLUCOSE_OUT_OF_RANGE`; una tasa de cambio inverosímil queda `FLAGGED` sin ocultarse. | HU-15, HU-16 | B |
| RF-34 | El paciente registra dosis de insulina con producto, tipo (basal, bolo, corrección), unidades y hora. | MVP | La dosis queda ligada al plan activo si existe; unidades fuera del límite devuelven `VALIDATION_ERROR`. | HU-17 | B, F |
| RF-35 | El paciente registra comidas con tipo de comida, hora y carbohidratos estimados (g). | MVP | Los gramos están dentro del límite de `FieldLimits`; la comida aparece en la línea de tiempo. | HU-18 | B, F |
| RF-36 | El paciente registra actividad física con tipo, duración e intensidad. | MVP | La actividad aparece en la línea de tiempo y se usa como contexto en los patrones. | HU-18 | B, F |
| RF-37 | El paciente registra síntomas de una lista (por ejemplo sed, mareo, sudoración, visión borrosa) y texto libre acotado. | MVP | Los síntomas de alarma configurados disparan el aviso "contacta a tu equipo o a urgencias". | HU-19 | B, F |
| RF-38 | Se registra HbA1c (paciente como autorreporte o médico con laboratorio), con valor, fecha y origen. | MVP | La HbA1c se muestra en el detalle clínico con su origen; un valor fuera de rango se rechaza. | HU-20 | B, F |
| RF-39 | Una corrección o anulación crea un registro nuevo con motivo que apunta al original; los datos clínicos son append-only. | MVP | El original permanece visible en el historial; la API no ofrece borrado físico. | HU-21 | B, D, F |
| RF-40 | El sistema ofrece una línea de tiempo unificada de glucosa, dosis, comidas, actividad y síntomas ordenada por hora. | MVP | La misma colección se exporta a vista de línea de tiempo, CSV y FHIR sin duplicar lógica. | HU-22 | B, F |
| RF-41 | El paciente importa lecturas de un CGM mediante un CSV de exportación del fabricante. | MVP | El adaptador reconoce los formatos soportados y rechaza los desconocidos con la lista de formatos admitidos. | HU-23 | B, F |
| RF-42 | El paciente ve sus gráficas de glucosa por día, semana y quincena con su rango objetivo. | MVP | La gráfica usa las metas del perfil asignado y es legible en pantallas de 360 px de ancho. | HU-22 | F, B |

### M6 Plan de tratamiento

| ID | Requisito | Prioridad | Criterio de aceptación (resumen) | HU | Repos |
|---|---|---|---|---|---|
| RF-43 | El `CLINIC_ADMIN` administra plantillas de protocolo de la clínica (por ejemplo "Basal-bolo adulto DM1") con versión. | MVP | Una plantilla retirada no se puede clonar pero no altera los planes ya creados. | HU-24 | B, D, F |
| RF-44 | El médico clona una plantilla para un paciente asignado y la personaliza. | MVP | El plan nuevo nace en `DRAFT`; la plantilla original no cambia. | HU-25 | B, F |
| RF-45 | El plan se construye con invariantes validadas (dosis dentro de límites, horarios sin solapes, metas coherentes) antes de poder activarse. | MVP | Un plan inválido devuelve `422` con la lista de invariantes incumplidas. | HU-25 | B |
| RF-46 | El médico activa un plan; un paciente tiene un solo plan activo y cada cambio crea una versión nueva copiada del anterior. | MVP | Activar un plan reemplaza al anterior; la versión previa queda en `SUPERSEDED`. | HU-26 | B, D, F |
| RF-47 | Antes de cada cambio se guarda una foto del plan y el médico puede restaurar una versión anterior. | MVP | Restaurar crea una nueva versión en `DRAFT` con el contenido de la foto; el historial no se pierde. | HU-26 | B, D |
| RF-48 | Los perfiles de metas (TIR, TBR, TAR) se guardan versionados en la base de datos; el administrador los define y el médico asigna uno a cada paciente. | MVP | Ningún umbral aparece en el código; cambiar un perfil no altera cálculos pasados. | HU-27 | B, D, F |
| RF-49 | El médico programa recordatorios (medición, dosis, control) y el sistema los envía al paciente por los canales elegidos. | MVP | Un recordatorio se envía en su hora y respeta el horario de silencio del paciente. | HU-28 | B, F |
| RF-50 | El paciente ve su plan activo y sus recordatorios en lenguaje claro, sin poder modificar las dosis. | MVP | La pantalla muestra el plan vigente; no existe edición de dosis para el paciente. | HU-28 | F, B |

### M7 Métricas glucémicas

| ID | Requisito | Prioridad | Criterio de aceptación (resumen) | HU | Repos |
|---|---|---|---|---|---|
| RF-51 | El sistema calcula TIR, TBR (< 70 y < 54 mg/dL) y TAR (> 180 y > 250 mg/dL) según los rangos del perfil de metas, por ventanas de 24 h, 7, 14 y 30 días. | MVP | Los resultados coinciden con casos de referencia; los rangos salen del perfil, no del código. | HU-29 | B |
| RF-52 | El sistema calcula media, desviación estándar, coeficiente de variación (CV), GMI y cobertura de datos CGM. | MVP | Con datos de referencia el GMI y el CV coinciden dentro de la tolerancia definida; la fórmula usa constantes con nombre. | HU-29 | B |
| RF-53 | El sistema genera el AGP (perfil ambulatorio de glucosa) de 14 días con percentiles 5, 25, 50, 75 y 95 por hora del día. | MVP | La respuesta incluye los percentiles por franja y se dibuja en el dashboard. | HU-30 | B, F |
| RF-54 | El sistema compara cada métrica con el periodo anterior y reporta el cambio (por ejemplo, variación del TIR en puntos porcentuales). | MVP | El cambio se calcula sobre ventanas del mismo tamaño y se muestra con su signo. | HU-29 | B, F |
| RF-55 | Si los datos son insuficientes (cobertura mínima configurable) el sistema lo indica y no muestra métricas engañosas. | MVP | Con cobertura menor al mínimo se muestra "datos insuficientes" y no un porcentaje. | HU-29, HU-30 | B, F |

### M8 Alertas y notificaciones

| ID | Requisito | Prioridad | Criterio de aceptación (resumen) | HU | Repos |
|---|---|---|---|---|---|
| RF-56 | El `CLINIC_ADMIN` configura reglas de alerta versionadas combinando umbral, duración y tasa de cambio con operadores Y/O. | MVP | Una regla compuesta se evalúa como un árbol; una regla activa no se edita sino que se versiona. | HU-31 | B, D, F |
| RF-57 | El sistema detecta hipoglucemia nivel 1 (< 70 mg/dL), nivel 2 (< 54 mg/dL) y nivel 3 (evento severo reportado) y crea una alerta. | MVP | Una lectura de 50 mg/dL crea una alerta nivel 2 en `OPEN` y publica el evento `HypoglycemiaDetected`. | HU-32 | B |
| RF-58 | El sistema detecta hiperglucemia sostenida (valores por encima del umbral durante una duración configurada) y crea una alerta. | MVP | Valores > 250 mg/dL durante la duración de la regla crean una alerta; un pico aislado no la crea. | HU-32 | B |
| RF-59 | Las alertas siguen `OPEN → ACKNOWLEDGED → RESOLVED` (o `OPEN → ESCALATED → ACKNOWLEDGED`) y cada cambio guarda quién, cuándo y nota. | MVP | Una transición inválida devuelve `409 INVALID_STATE_TRANSITION`; el historial es append-only. | HU-33 | B, D, F |
| RF-60 | Una alerta sin reconocer escala por la cadena paciente, médico principal, equipo y administrador, con tiempos configurables por regla. | MVP | Pasado el tiempo sin reconocimiento, la alerta pasa a `ESCALATED` y notifica al siguiente eslabón. | HU-34 | B |
| RF-61 | Las notificaciones se envían por correo, Web Push e in-app, y el canal se elige sin cambiar el tipo de notificación. | MVP | Una alerta de hipoglucemia llega por los canales habilitados del destinatario; un canal caído no bloquea los demás. | HU-32, HU-35 | B, F |
| RF-62 | El sistema reduce la fatiga de alertas: no duplica una alerta abierta del mismo tipo, agrupa alertas de baja prioridad y respeta el horario de silencio, salvo las críticas. | MVP | Dos lecturas bajas consecutivas generan una sola alerta; las de nivel 2 y 3 nunca se silencian. | HU-35 | B |
| RF-63 | El sistema avisa al paciente y al médico cuando no hay registros durante un periodo configurado (adherencia). | MVP | Pasado el periodo sin lecturas se envía un recordatorio al paciente y luego un aviso de adherencia al equipo. | HU-35 | B |
| RF-64 | El sistema genera una alerta preventiva cuando el pronóstico de la IA indica riesgo de hipoglucemia o hiperglucemia en los próximos 30 a 120 minutos. | MVP | Con riesgo alto en el pronóstico se crea una alerta de tipo `PREDICTIVE`; si la IA falla se usa la tendencia lineal. | HU-36 | B, IA |
| RF-65 | El médico y el paciente consultan el historial de alertas con filtros por estado, tipo y fecha. | MVP | El historial muestra la cadena de estados y a quién se notificó. | HU-33 | B, F |

### M9 IA y soporte a decisiones

| ID | Requisito | Prioridad | Criterio de aceptación (resumen) | HU | Repos |
|---|---|---|---|---|---|
| RF-66 | IA1: el sistema pronostica la glucosa a 30 a 120 minutos y para la noche, con cuantiles, y estima el riesgo de hipo e hiperglucemia. | MVP | La respuesta incluye p10, p50 y p90 y la versión del modelo; el pronóstico se compara con el respaldo. | HU-36 | IA, B, F |
| RF-67 | IA2: el sistema estratifica el riesgo de cada paciente y ordena el triage con los factores que explican la posición. | MVP | Cada paciente tiene un puntaje y al menos un factor legible; con IA caída se usan reglas tipo TIDE. | HU-37 | IA, B, F |
| RF-68 | IA3: el sistema detecta patrones y anomalías (hipoglucemias nocturnas, fenómeno del alba, picos posprandiales, dosis omitidas o duplicadas, caída de adherencia, lecturas inverosímiles). | MVP | Cada hallazgo guarda tipo, ventana, evidencia y confianza; los hallazgos se muestran al médico. | HU-38 | IA, B, F |
| RF-69 | IA4: el sistema propone ajustes del tratamiento (por ejemplo, titulación de basal según glucosa en ayunas) como recomendación en `PROPOSED`, nunca aplicada. | MVP | Una recomendación nace en `PROPOSED` con su explicación y datos de apoyo; no cambia el plan por sí sola. | HU-39 | IA, B, F |
| RF-70 | El médico aprueba, aprueba con cambios o rechaza cada recomendación; modificar o rechazar exige motivo (10 a 500 caracteres). | MVP | Sin motivo devuelve `422 REASON_REQUIRED`; la decisión guarda quién, cuándo, versión del modelo y texto original. | HU-39 | B, F |
| RF-71 | Una recomendación aprobada se aplica al plan como nueva versión (`APPLIED`); una no atendida en su plazo pasa a `EXPIRED`. | MVP | Aplicar crea una versión `DRAFT` del plan para activar; una recomendación vencida no se puede decidir. | HU-39 | B, D |
| RF-72 | IA5: el sistema genera un resumen previo a la consulta con narrativa del AGP, eventos, adherencia y cambios de plan, con referencias a los datos. | Post-MVP | El resumen cita sus fuentes y se genera sobre datos seudonimizados; con LLM no disponible se usa una plantilla determinista. | HU-41 | IA, B, F |
| RF-73 | IA6: el paciente conversa con un asistente educativo con guardrails: no da dosis ni diagnósticos y escala ante síntomas de alarma; responde con material aprobado por la clínica. | Post-MVP | Ante "¿cuánta insulina me pongo?" responde que lo defina su médico; ante síntomas de alarma muestra el aviso de urgencia. | HU-42 | IA, B, F |
| RF-74 | IA7: el sistema estima el riesgo de abandono o no adherencia para que la clínica contacte al paciente. | MVP | La clínica ve una lista de pacientes en riesgo sin detalle clínico; con IA caída se usan reglas de inactividad. | HU-43 | IA, B, F |
| RF-75 | Toda salida de IA guarda versión del modelo, entradas seudonimizadas, explicación y decisión humana; al servicio de IA solo llega un seudónimo. | MVP | Ningún nombre, documento, MRN ni contacto sale hacia la IA o el LLM; una prueba verifica la carga útil. | HU-40 | B, IA, D |
| RF-76 | Si la IA falla, tarda o su circuito está abierto, el sistema usa el respaldo determinista y lo indica en la interfaz. | MVP | Con el servicio de IA caído, el triage y las alertas siguen funcionando con reglas y la UI muestra "Respaldo por reglas". | HU-40 | B, IA, F |
| RF-77 | El equipo evalúa la IA contra el respaldo con MAE, RMSE y Clarke Error Grid (pronóstico), AUROC y calibración (riesgo) sobre datos simulados. | Post-MVP | El tablero muestra la comparación por modelo y versión. | HU-44 | IA, B, F |

### M10 Dashboard médico y reportes

| ID | Requisito | Prioridad | Criterio de aceptación (resumen) | HU | Repos |
|---|---|---|---|---|---|
| RF-78 | El dashboard del médico lista a sus pacientes asignados ordenados por riesgo (triage), con banderas explicadas, alertas abiertas y recomendaciones pendientes. | MVP | La lista solo contiene pacientes asignados; cada bandera muestra su motivo. | HU-45 | B, F |
| RF-79 | El médico filtra por ventana (24 h, 7, 14, 30 días) y estado, y marca un paciente como revisado. | MVP | Un paciente revisado baja de prioridad hasta que cambie su situación. | HU-45 | B, F |
| RF-80 | El detalle del paciente muestra AGP, TIR, métricas, línea de tiempo, plan, alertas y recomendaciones. | MVP | Cada apertura queda auditada; el detalle carga en el tiempo objetivo de RNF-07. | HU-46 | B, F |
| RF-81 | El médico escribe notas clínicas sobre el paciente; las notas son append-only y solo las ve el equipo asignado. | MVP | Una nota se corrige con otra; el administrador no la ve. | HU-46 | B, D, F |
| RF-82 | El sistema genera un reporte del paciente en PDF y HTML (AGP, métricas, eventos y plan) para consulta o entrega al paciente. | MVP | Ambos formatos muestran la misma información; el reporte de la clínica demo lleva "Datos simulados". | HU-47 | B, F |
| RF-83 | El `CLINIC_ADMIN` ve KPIs agregados de la clínica (pacientes por estado, activación, adherencia, alertas) sin datos clínicos individuales. | MVP | Ningún KPI identifica glucosa o dosis de un paciente; los conteos pequeños se agrupan. | HU-48 | B, F |

### M11 Mensajería y seguimiento

| ID | Requisito | Prioridad | Criterio de aceptación (resumen) | HU | Repos |
|---|---|---|---|---|---|
| RF-84 | El paciente y su equipo asignado intercambian mensajes en un hilo por paciente. | Post-MVP | Solo el paciente y su equipo ven el hilo; los mensajes son append-only. | HU-49 | B, D, F |
| RF-85 | La mensajería muestra de forma permanente el aviso de que no es un canal de emergencias y no se usa para dosis urgentes. | Post-MVP | El aviso aparece en el hilo; un mensaje con palabras de alarma sugiere llamar a urgencias. | HU-49 | F, B |
| RF-86 | El médico programa controles (citas de seguimiento) y el paciente los ve y recibe recordatorios. | Post-MVP | Un control cumple `SCHEDULED → DONE` o `MISSED` y se recuerda antes de su fecha. | HU-50 | B, F |
| RF-87 | La clínica crea tareas de contacto para pacientes en riesgo de abandono y registra el resultado. | Post-MVP | La tarea queda ligada al paciente y a quien la atendió, sin exponer datos clínicos al administrador. | HU-43 | B, F |

### M12 Auditoría y cumplimiento

| ID | Requisito | Prioridad | Criterio de aceptación (resumen) | HU | Repos |
|---|---|---|---|---|---|
| RF-88 | El sistema guarda una auditoría append-only con cadena de hashes (cada fila incluye el hash de la anterior). | MVP | Un `UPDATE` o `DELETE` sobre `audit.audit_log` falla por el trigger; las filas se encadenan. | HU-51 | D, B |
| RF-89 | Cada lectura de datos clínicos se audita (quién, a qué paciente, qué recurso y cuándo) y cada comando relevante también. | MVP | Abrir un paciente genera una fila en `audit.data_access_log`; si la auditoría falla, la lectura no responde. | HU-51 | B, D |
| RF-90 | El consentimiento de tratamiento de datos es versionado: se acepta al activar, se registra versión y fecha y puede retirarse. | MVP | Una versión nueva obliga a reaceptar; retirar el consentimiento detiene nuevos registros y avisa a la clínica. | HU-10, HU-52 | B, D, F |
| RF-91 | El `CLINIC_ADMIN` consulta la auditoría de su clínica con filtros por usuario, acción y fecha, sin contenido clínico. | Post-MVP | Los resultados nunca incluyen valores de glucosa ni textos de notas. | HU-51 | B, F |
| RF-92 | El sistema verifica la integridad de la cadena de hashes de auditoría bajo demanda. | Post-MVP | Alterar una fila (en un entorno de prueba) hace que la verificación falle y señale la fila. | HU-51 | B, D |
| RF-93 | El paciente solicita acceso, rectificación o supresión de sus datos y la clínica tramita la solicitud con plazo y registro. | Post-MVP | La solicitud tiene estado y plazo; la exportación entrega los datos del paciente en JSON y FHIR. | HU-53 | B, F |
| RF-94 | El sistema aplica políticas de retención: al desactivar un paciente sus datos se conservan según la política o se anonimizan. | Post-MVP | La política por tipo de dato está en `audit.retention_policies`; la anonimización conserva las estadísticas agregadas. | HU-53 | B, D |
| RF-95 | Los eventos de seguridad (login fallido, MFA, reutilización de refresh, activaciones, cambios de rol) se guardan y la plataforma los consulta. | MVP | Cada evento guarda tipo, usuario, IP truncada y hora, sin secretos. | HU-51 | B, D |

### M13 Datos simulados

| ID | Requisito | Prioridad | Criterio de aceptación (resumen) | HU | Repos |
|---|---|---|---|---|---|
| RF-96 | Todo dato de una clínica `is_demo` se marca "Datos simulados" en la UI, los reportes, los mensajes y en la API (`simulated: true`). | MVP | Ninguna pantalla, PDF ni respuesta de la clínica demo omite la marca. | HU-55 | B, F, S |
| RF-97 | El simulador en modo `backfill` genera un Bundle FHIR R4 y un CSV de una clínica demo que entran por el importador real. | MVP | Importar el Bundle crea los pacientes demo sin código especial en el backend. | HU-54 | S, B |
| RF-98 | El simulador en modo `live` envía lecturas periódicas a la API con tokens de paciente. | Post-MVP | Las lecturas pasan por la misma validación en cadena que las del paciente. | HU-56 | S, B |
| RF-99 | El simulador inyecta escenarios (hipoglucemias nocturnas, fenómeno del alba, dosis omitidas, adherencia que mejora o empeora, abandono). | MVP | Cada escenario es reproducible con una semilla y produce el patrón esperado. | HU-54, HU-56 | S |
| RF-100 | El simulador entrega datasets de entrenamiento para `insumap-ai` y arquetipos de pacientes (DM1, DM2 y gestacional) con variación. | MVP | Los datasets no contienen datos reales; documentos y correos son ficticios (`example.test`). | HU-54 | S, IA |

## 2. Requisitos no funcionales

Las cifras marcadas "objetivo, verificar" se confirman con mediciones en la fase 12.

| ID | Categoría | Requisito |
|---|---|---|
| RNF-01 | Seguridad: contraseñas | Argon2id con parámetros documentados; política de longitud mínima; historial de contraseñas; nunca en logs, respuestas ni URLs. |
| RNF-02 | Seguridad: sesiones | JWT de 15 minutos; refresh opaco guardado solo como hash que rota en cada uso y revoca toda la familia si se reutiliza; cierre de sesión global. |
| RNF-03 | Seguridad: MFA y límites | MFA TOTP obligatorio para el personal; rate limiting en login, activación, recuperación y envío de mensajes; bloqueo escalonado. |
| RNF-04 | Seguridad: autorización y aislamiento | Permisos desde la base de datos con denegación por defecto; RLS por `clinic_id`; asignación médico-paciente con `PatientRecordAccessProxy`; recursos ajenos responden `404`. Pruebas de aislamiento entre clínicas en la CI. |
| RNF-05 | Seguridad: datos y transporte | TLS 1.2 o superior en tránsito; datos en reposo cifrados por el proveedor y documento de identidad cifrado a nivel de columna; solo consultas parametrizadas; entradas validadas con Pydantic `extra="forbid"` y límites de `FieldLimits`; tamaño de cuerpo limitado. |
| RNF-06 | Privacidad y minimización | Datos sensibles de salud con consentimiento versionado; al servicio de IA y al LLM solo llega un seudónimo, nunca nombres, documentos, MRN ni contacto; ningún dato personal ni de salud en logs; cumplimiento descrito en [Cumplimiento-y-privacidad.md](Cumplimiento-y-privacidad.md). |
| RNF-07 | Rendimiento | Objetivo, verificar: lecturas simples p95 ≤ 300 ms y escrituras p95 ≤ 500 ms; dashboard de triage de 200 pacientes ≤ 2 s; detalle del paciente (AGP y métricas de 14 días) ≤ 2 s; importación de 1.000 filas ≤ 60 s en segundo plano; detección de hipoglucemia (de la recepción de la lectura a la alerta creada) ≤ 60 s; pronóstico de IA con tiempo máximo de 3 s antes de usar el respaldo. |
| RNF-08 | Disponibilidad y resiliencia | Objetivo, verificar: 99 % mensual en la demo (hosting gratuito); el arranque en frío del backend gratuito se informa al usuario; la caída de la IA, el LLM, el correo o Web Push no detiene el registro ni las alertas (circuit breaker y respaldo). |
| RNF-09 | Usabilidad | Objetivo, verificar: registrar una glucosa en 3 pasos o menos desde la pantalla de inicio; el paciente completa la activación sin ayuda en menos de 5 minutos; mensajes de error en español claro; el médico llega al detalle de un paciente desde el triage en 1 clic. |
| RNF-10 | Accesibilidad | WCAG 2.2 AA en las tres aplicaciones (paciente, médico y administración): contraste, foco visible, navegación por teclado, etiquetas, objetivos táctiles de 24 px o más (recomendado 44 px) y no depender solo del color para el estado glucémico; pruebas automáticas con axe y revisión manual. |
| RNF-11 | PWA mobile-first | La app del paciente se diseña primero para 360 px, se instala como PWA, funciona sin conexión para registrar (cola local) y sincroniza al volver la señal; el dashboard del médico es responsivo. |
| RNF-12 | Auditabilidad | Auditoría append-only con cadena de hashes; auditoría de cada lectura clínica; decisiones de IA con versión del modelo, explicación y decisión humana; reglas, metas, planes y plantillas versionados. |
| RNF-13 | Interoperabilidad | Importación FHIR R4 (Patient, Practitioner, Condition, Observation con LOINC, MedicationRequest) y exportación FHIR y CSV; API REST con OpenAPI como contrato; adaptadores para formatos de CGM. |
| RNF-14 | Mantenibilidad y patrones | Arquitectura hexagonal (`api → application → domain ← infrastructure`) verificada con import-linter; dominio en Python puro; cada patrón del catálogo (P01 a P23) con clase propia, etiqueta `Pattern: Pnn` en el docstring y prueba unitaria; composition root explícito; hora solo por el `Clock` inyectado. |
| RNF-15 | Calidad estática | ruff (incluye `PLR2004`), mypy `--strict`, ESLint y TypeScript estricto sin errores en la CI; nada de valores quemados: parámetros clínicos en la base de datos, límites en `FieldLimits`, entorno en `.env.example`, textos en `messages_es`. |
| RNF-16 | Testabilidad | Cobertura objetivo: dominio ≥ 90 % y global ≥ 80 %; pruebas de integración con Testcontainers contra PostgreSQL 18 con el esquema de `insumap-database`; prueba de deriva de `FieldLimits` contra `information_schema`; pruebas de aislamiento RLS; pruebas E2E con Playwright del recorrido principal. |
| RNF-17 | Internacionalización | Interfaz, mensajes de error y reportes en español (`es-CO`); código, rutas, JSON y códigos de error en inglés; fechas en zona `America/Bogota` para la presentación y UTC en almacenamiento; glucosa en mg/dL (con mmol/L solo como conversión). |
| RNF-18 | Observabilidad | Logs JSON estructurados con `request_id` y redacción de datos personales; endpoint de salud con estado de la BD y la IA; métricas básicas de latencia y errores; trazas de llamadas a la IA sin cargas clínicas. |
| RNF-19 | Seguridad clínica de la IA | Human-in-the-loop: la IA no aplica cambios ni da dosis al paciente; cada salida tiene un respaldo determinista; el asistente educativo tiene guardrails y escalamiento; la UI distingue "propuesta de IA" de "decisión del médico". |
| RNF-20 | Integridad de datos | Los datos clínicos son append-only con correcciones; glucosa siempre en mg/dL; ninguna lectura sospechosa se oculta (se marca); idempotencia por UUID de cliente en el envío de lotes. |
| RNF-21 | Escalabilidad | Objetivo, verificar: soportar 150 pacientes demo con CGM (288 lecturas por día cada uno) y un pico de 1.000 lecturas por minuto en el modo `live`; particionado o índices por `patient_id` y tiempo en la tabla de glucosa; el servicio de IA es sin estado. |
| RNF-22 | Seguridad del repositorio y cadena | Gitleaks y CodeQL en la CI; secretos solo en variables de entorno sin valor por defecto; dependencias fijadas con `uv.lock`; `commit-lint` obligatorio. |
| RNF-23 | Costo y proveedores | Hosting y servicios en capa gratuita; el proveedor de LLM es compatible con OpenAI y configurable por variables de entorno; límite diario de llamadas al LLM y caché; al LLM solo llegan datos simulados o seudonimizados. |
| RNF-24 | Respaldo y retención | Respaldo de la base de datos según el proveedor (objetivo, verificar); políticas de retención por tipo de dato en `audit.retention_policies`. |

## 3. Restricciones

| ID | Restricción | Origen |
|---|---|---|
| RES-01 | El backend es **Python 3.13 + FastAPI**, con POO y patrones de diseño explícitos. | Exigencia académica |
| RES-02 | Cinco repositorios separados (`insumap-backend`, `-database`, `-frontend`, `-ai`, `-simulator`) bajo `NicoalsD`, con `develop` como rama por defecto y Git Flow. | Plan del equipo |
| RES-03 | El esquema de la base de datos vive en `insumap-database` (PostgreSQL 18, Alembic con SQL escrito a mano) y el backend fija la versión en `db-schema.lock`. | Plan del equipo |
| RES-04 | Hosting en capas gratuitas (Render, Vercel, Neon u otros); la arquitectura debe tolerar el arranque en frío y los límites de memoria. | Presupuesto |
| RES-05 | Todo el código en inglés y toda la documentación, commits y UI en español. | Convención del equipo |
| RES-06 | Proyecto académico: no es un dispositivo médico, no maneja datos reales y exige 150 o más commits en el backend. | Exigencia académica |
| RES-07 | La IA es de apoyo a la decisión con aprobación del médico; el LLM es un proveedor gratuito o barato compatible con OpenAI. | Decisión del equipo |
| RES-08 | Los umbrales, metas y reglas clínicas viven en la base de datos, no en el código. | Convención del equipo |
| RES-09 | Sin atribución del trabajo a una IA en commits, PR ni releases. | Convención del equipo |

## 4. Trazabilidad con las historias de usuario

La tabla de cada módulo enlaza RF con HU. El inverso (HU con sus RF) está en [Historias-de-usuario.md](Historias-de-usuario.md). El plan de commits referencia las HU y estos IDs.

## Documentos relacionados

[Insumap.md](Insumap.md) · [Historias-de-usuario.md](Historias-de-usuario.md) · [Actores-y-permisos.md](Actores-y-permisos.md) · [Arquitectura.md](Arquitectura.md) · [Seguridad.md](Seguridad.md) · [Metricas-clinicas.md](Metricas-clinicas.md) · [Patrones-de-diseno.md](Patrones-de-diseno.md)
