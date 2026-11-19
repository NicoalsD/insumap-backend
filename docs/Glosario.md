# Glosario

Términos clínicos y técnicos usados en la documentación de Insumap, en orden alfabético dentro de cada sección. La columna **En el código** muestra el identificador en inglés que usan el código, la base de datos o la API; si no hay identificador aparece un guion.

> **Aviso:** Insumap es un proyecto académico, no es un dispositivo médico y la IA solo apoya al médico. Las definiciones clínicas son de apoyo para el equipo de desarrollo y no sustituyen la guía de un profesional. Las cifras de referencia (por ejemplo, las metas de TIR) son valores del consenso internacional que se guardan como **perfiles de metas en la base de datos**, no como constantes del código (ver [Metricas-clinicas.md](Metricas-clinicas.md)).

## 1. Términos clínicos

| Término | En el código | Definición |
|---|---|---|
| AGP (perfil ambulatorio de glucosa) | `agp`, `AgpProfile` | Reporte estándar que superpone varios días de glucosa en un solo "día tipo" y muestra los percentiles 5, 25, 50, 75 y 95 por hora. Insumap lo calcula con ventanas de 14 días. |
| Alarma (síntoma de) | `alarm_symptom` | Síntoma configurado como señal de urgencia (por ejemplo, confusión o pérdida de conocimiento). Muestra el aviso "contacta a tu equipo o a urgencias" y crea una alerta. |
| Basal (insulina) | `BASAL` | Insulina de acción prolongada que cubre las necesidades de fondo durante el día y la noche. |
| Bolo (insulina) | `BOLUS` | Dosis de insulina de acción rápida que se aplica con las comidas o para corregir una glucosa alta. |
| CGM (monitoreo continuo de glucosa) | `CGM` | Sensor que mide la glucosa intersticial de forma continua, típicamente cada 5 minutos (hasta 288 lecturas por día). Fuente de lectura `CGM`. |
| Coeficiente de variación (CV) | `cv_percent` | Variabilidad de la glucosa: desviación estándar dividida por la media, en porcentaje. El consenso internacional usa 36 % como referencia de estabilidad. |
| Cobertura de datos | `data_coverage` | Porcentaje del periodo con datos CGM. Se necesita un mínimo para que las métricas sean confiables (ver RF-55). |
| Diabetes gestacional | `GESTATIONAL` | Diabetes que se diagnostica durante el embarazo. Tiene metas glucémicas más estrictas que las del adulto no gestante; Insumap la maneja con un perfil de metas propio. |
| DM1 (diabetes tipo 1) | `T1D` | Diabetes por destrucción autoinmune de las células beta; requiere insulina. Suele usar CGM y esquema basal-bolo. |
| DM2 (diabetes tipo 2) | `T2D` | Diabetes con resistencia a la insulina y déficit relativo; el tratamiento varía (estilo de vida, orales, insulina). Suele medir con glucómetro 1 a 4 veces al día. |
| Fenómeno del alba | `dawn_phenomenon` | Aumento de la glucosa en las primeras horas de la mañana, antes de despertar, por hormonas contrarreguladoras. Es un patrón que la IA3 puede detectar. |
| Glucemia | `glucose` | Concentración de glucosa en sangre. Se almacena siempre en **mg/dL**; el mmol/L se convierte con una constante con nombre (`MG_DL_PER_MMOL_L`). |
| GMI (indicador de gestión de la glucosa) | `gmi_percent` | Estimación de la HbA1c a partir de la glucosa media del CGM: `GMI (%) = 3,31 + 0,02392 × glucosa media (mg/dL)`. Puede diferir de la HbA1c de laboratorio. |
| HbA1c (hemoglobina glicosilada) | `hba1c_percent`, `lab_results` | Examen de laboratorio que refleja el promedio de glucosa de unos 2 a 3 meses. Se registra por el paciente (autorreporte) o por el médico (laboratorio). |
| Hiperglucemia | `HYPERGLYCEMIA` | Glucosa por encima del rango objetivo. El TAR distingue nivel 1 (> 180 mg/dL) y nivel 2 (> 250 mg/dL). |
| Hipoglucemia nivel 1 | `HYPO_L1` | Glucosa < 70 mg/dL y ≥ 54 mg/dL. Alerta de acción. |
| Hipoglucemia nivel 2 | `HYPO_L2` | Glucosa < 54 mg/dL. Hipoglucemia clínicamente importante que requiere acción inmediata. |
| Hipoglucemia nivel 3 | `HYPO_L3` | Evento severo con alteración mental o física que requiere ayuda de otra persona; se registra como evento, sin un umbral de glucosa. |
| ICR (relación insulina-carbohidratos) | `insulin_to_carb_ratio` | Gramos de carbohidratos que cubre una unidad de insulina de acción rápida. Es un parámetro del plan que define el médico; la IA nunca lo comunica al paciente como consejo. |
| ISF (factor de sensibilidad a la insulina) | `insulin_sensitivity_factor` | Cuántos mg/dL baja la glucosa una unidad de insulina de acción rápida. Parámetro del plan definido por el médico. |
| Lipohipertrofia | `lipohypertrophy` | Engrosamiento del tejido graso por inyectar insulina repetidamente en el mismo sitio; altera la absorción y puede explicar una glucosa variable. Es un síntoma que se puede registrar. |
| Rango objetivo | `target_range` | Intervalo de glucosa deseado (por ejemplo, 70 a 180 mg/dL), definido por el perfil de metas. |
| SMBG (automonitoreo de glucosa capilar) | `SMBG` | Medición con glucómetro y gota de sangre. Fuente de lectura `SMBG`. |
| TAR (tiempo por encima del rango) | `tar_above_180`, `tar_above_250` | Porcentaje del tiempo con glucosa > 180 mg/dL y > 250 mg/dL. |
| TBR (tiempo por debajo del rango) | `tbr_below_70`, `tbr_below_54` | Porcentaje del tiempo con glucosa < 70 mg/dL y < 54 mg/dL. |
| TIR (tiempo en rango) | `tir_70_180` | Porcentaje del tiempo con glucosa dentro del rango objetivo (por defecto 70 a 180 mg/dL). Métrica central del Consenso Internacional de Tiempo en Rango (Battelino et al., *Diabetes Care* 2019). |
| Titulación | `titration`, `TitrationStrategy` | Ajuste gradual de la dosis (por ejemplo, de la insulina basal) según la glucosa en ayunas. La IA4 propone y el médico decide. |

## 2. Términos técnicos y de producto

| Término | En el código | Definición |
|---|---|---|
| Access token | `access_token` | Credencial JWT de 15 minutos que se envía en cada petición. |
| Activación | `activation_code` | Proceso en el que el paciente usa un código de un solo uso para definir su contraseña, aceptar el consentimiento y pasar de `INVITED` a `ACTIVE`. El código se guarda como hash. |
| Adapter (P06) | `FhirPatientAdapter`, `CgmCsvAdapter`, `AiServiceClientAdapter` | Traduce una interfaz externa (FHIR, CSV de CGM, servicio de IA) al modelo interno. |
| Alerta | `Alert`, `alerts.alerts` | Aviso generado por una regla. Estados `OPEN`, `ACKNOWLEDGED`, `ESCALATED`, `RESOLVED`. |
| Append-only | `append-only` | Tabla en la que solo se inserta y se consulta; las correcciones son filas nuevas. Así funcionan las lecturas, las notas y la auditoría. |
| Argon2id | `Argon2PasswordHasher` | Función de hash de contraseñas resistente a fuerza bruta. |
| Asignación (equipo de atención) | `care_team_assignments` | Relación vigente entre un médico y un paciente. Define quién puede ver a quién. Un médico es el principal. |
| Auditoría | `audit_log`, `data_access_log` | Registro append-only de quién hizo qué y cuándo, con cadena de hashes. |
| Backfill (modo) | `backfill` | Modo del simulador que genera el Bundle FHIR y el CSV de la clínica demo para el importador real. |
| Bundle FHIR | `Bundle` | Recurso FHIR que agrupa varios recursos (Patient, Observation, etc.); formato de importación de la clínica. |
| Chain of Responsibility (P12) | `GlucoseReadingValidationHandler`, `AlertEscalationHandler` | Cadena de manejadores; aquí valida lecturas y escala alertas. |
| Circuit breaker | `CircuitBreakerState` | Mecanismo que deja de llamar a un servicio que falla repetidamente y usa un respaldo. Estados `CLOSED`, `OPEN`, `HALF_OPEN` (P18 y P11). |
| Clínica (tenant) | `clinic`, `clinic_id` | Organización contratante (hospital o clínica). Cada dato pertenece a una clínica. |
| Clínica demo | `is_demo` | Clínica de prueba, simulada por definición; toda su información se marca "Datos simulados". |
| CLINIC_ADMIN | `CLINIC_ADMIN` | Rol administrativo de la clínica; no ve datos clínicos detallados. |
| Command (P13) | `CommandBus`, `ApproveRecommendationCommand` | Encapsula una acción como objeto para ejecutarla, auditarla y registrarla. |
| Consentimiento | `patient_consents` | Aceptación versionada del tratamiento de datos sensibles de salud. |
| Contrato de IA | `AiServiceClientAdapter` | Esquema de petición y respuesta entre el backend y `insumap-ai` (ver [Contrato-IA.md](Contrato-IA.md)). |
| Credenciales (emisión de) | `credential_invitations` | Invitación con código de activación que emite la clínica. |
| Decorator (P09) | `PhiAccessAuditDecorator` | Añade comportamiento (auditoría) sin cambiar la clase decorada. |
| Deduplicación | `SKIPPED_DUPLICATE` | Evitar crear un segundo paciente con el mismo MRN en una clínica. |
| Denegación por defecto | `deny by default` | Un permiso no otorgado explícitamente en la BD está prohibido. |
| Dominio | `domain/` | Capa de reglas de negocio en Python puro, sin FastAPI ni SQLAlchemy. |
| Evento de dominio | `GlucoseReadingRecorded`, `HypoglycemiaDetected` | Hecho publicado después del commit para desacoplar efectos (Observer, P17). |
| Facade (P10) | `DoctorDashboardFacade` | Interfaz simple sobre varios servicios (dashboard del médico). |
| FHIR R4 | `fhir` | Estándar HL7 de intercambio de datos de salud, versión 4. Recursos usados: Patient, Practitioner, Condition, Observation, MedicationRequest. |
| FieldLimits | `FieldLimits` | Clase única de límites técnicos (longitudes, patrones, tamaños) que alimenta los `Field(...)` de Pydantic y se compara con `information_schema`. |
| Guardrail | `GuardrailHandler` | Control que limita lo que puede responder el asistente de IA (sin dosis ni diagnósticos; escalamiento ante síntomas de alarma). |
| Hexagonal (arquitectura) | `api → application → domain ← infrastructure` | Organización por capas con puertos y adaptadores; el dominio no depende de infraestructura. |
| Human-in-the-loop | `RecommendationState` | La IA propone y una persona (el médico) decide; ninguna recomendación se aplica sola. |
| IA1 a IA7 | `ai.*` | Casos de uso de IA: IA1 pronóstico, IA2 triage, IA3 patrones y anomalías, IA4 sugerencias de ajuste, IA5 resumen previo a la consulta, IA6 asistente educativo, IA7 riesgo de abandono (ver [Modulo-IA.md](Modulo-IA.md)). |
| Idempotencia | `client_uuid` | Propiedad por la que repetir una petición con el mismo UUID de cliente no duplica datos. |
| Importación (lote) | `import_batches`, `import_rows` | Operación que carga pacientes de la clínica con resultado por fila. |
| Interoperabilidad | - | Capacidad de intercambiar datos con otros sistemas (FHIR, CSV). |
| JWT | `access_token` | JSON Web Token firmado que lleva identidad, rol y clínica. |
| LOINC | `loinc_code` | Catálogo internacional de códigos de observaciones de laboratorio y clínicas; se usa en las Observation de FHIR (por ejemplo, glucosa y HbA1c). |
| LLM | `TextGenerator` | Modelo de lenguaje grande de un proveedor compatible con OpenAI; recibe solo datos seudonimizados. |
| MFA (autenticación multifactor) | `mfa_factors` | Segundo factor de acceso (TOTP). Obligatorio para el personal. |
| MRN (número de historia clínica) | `mrn` | Identificador del paciente en la clínica; clave de deduplicación. |
| Notificación | `Notification`, `NotificationChannel` | Mensaje al usuario por correo, Web Push o in-app (Bridge, P07). |
| PATIENT | `PATIENT` | Rol del paciente; solo ve sus propios datos. |
| Permiso | `permissions` | Código `dominio.accion` guardado en la BD y asignado a roles (ver [Actores-y-permisos.md](Actores-y-permisos.md)). |
| PHI | `PhiAccess` | Información de salud protegida (datos clínicos y de identificación del paciente). |
| PLATFORM_ADMIN | `PLATFORM_ADMIN` | Rol mínimo que gestiona clínicas. |
| Plan de tratamiento | `treatment_plans` | Conjunto versionado de insulinas, horarios, metas y recordatorios de un paciente. Estados `DRAFT`, `ACTIVE`, `SUPERSEDED`. |
| Plantilla de protocolo | `protocol_templates` | Plan modelo de la clínica que el médico clona para un paciente (Prototype, P05). |
| Proxy (P11) | `PatientRecordAccessProxy`, `RemoteAiServiceProxy` | Intermediario que controla el acceso (asignación) o protege una llamada remota (circuit breaker y respaldo). |
| PWA | `PWA` | Aplicación web instalable que funciona sin conexión; todas las superficies se diseñan primero para escritorio y la app del paciente sigue usable desde 360 px. |
| RAG | `retrieval` | Recuperación de material aprobado para fundamentar la respuesta del asistente educativo. |
| Rate limiting | `RATE_LIMITED` | Límite de peticiones por ventana para frenar abusos y fuerza bruta. |
| Recomendación | `Recommendation` | Propuesta de la IA para el médico. Estados `PROPOSED`, `APPROVED`, `APPROVED_WITH_CHANGES`, `REJECTED`, `APPLIED`, `EXPIRED`. |
| Refresh token | `refresh_tokens` | Credencial opaca de larga duración que se guarda solo como hash, rota en cada uso y detecta reutilización. |
| Respaldo (fallback) | `fallback` | Cálculo determinista (reglas, tendencia, plantilla) que reemplaza a la IA cuando falla. La UI lo indica. |
| RLS (seguridad a nivel de fila) | `ROW LEVEL SECURITY` | Mecanismo de PostgreSQL que filtra filas por `clinic_id` y usuario, usando el contexto fijado con `SET LOCAL app.clinic_id`. |
| Seudonimización | `pseudonym_id` | Sustituir los datos identificables por un identificador sin significado fuera del sistema, para minimizar lo que ve la IA y el LLM. |
| Simulador | `insumap-simulator` | Repositorio que genera clínica, médicos y pacientes simulados. |
| State (P18) | `AlertState`, `PatientAccountState` | Patrón que modela el comportamiento según el estado. |
| Strategy (P19) | `RiskScoringStrategy`, `TitrationStrategy` | Algoritmos intercambiables (IA o reglas). |
| Tenant | `tenant` | Ver "Clínica". Aislamiento lógico de los datos de cada cliente. |
| TIDE | `TideRiskStrategy` | *Timely Interventions for Diabetes Excellence*: panel de triage de Tidepool basado en banderas de CGM; inspira el respaldo por reglas. |
| Triage | `triage` | Ordenar a los pacientes según la urgencia de atención. |
| TOTP | `totp` | Código temporal de un solo uso del segundo factor. |
| UUID de cliente | `client_uuid` | Identificador generado en el cliente para cada lectura, base de la idempotencia. |
| Versionado | `version` | Cada cambio de reglas, metas, plantillas o planes crea una versión nueva; la activa es inmutable. |

## Documentos relacionados

[Insumap.md](Insumap.md) · [Metricas-clinicas.md](Metricas-clinicas.md) · [Modulo-IA.md](Modulo-IA.md) · [Actores-y-permisos.md](Actores-y-permisos.md) · [Seguridad.md](Seguridad.md) · [Patrones-de-diseno.md](Patrones-de-diseno.md)
