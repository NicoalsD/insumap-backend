# Insumap: visión general del producto

> **El control de la diabetes de cada paciente, visible para su equipo de atención.**

Este documento explica qué problema resuelve Insumap, cómo funciona el modelo B2B2C, qué incluye el MVP y qué no. Es la puerta de entrada a la documentación canónica de `docs/`. Los detalles viven en los demás documentos (ver "Documentos relacionados" al final).

> **Aviso:** Insumap es un proyecto académico. **No es un dispositivo médico**, no reemplaza el criterio clínico y la IA solo apoya al médico, que toma todas las decisiones. Todos los pacientes son simulados y se marcan como "Datos simulados".

## 1. Problema

### 1.1 La carga de la diabetes

- **Colombia:** la Cuenta de Alto Costo (CAC) registró 2.541.648 personas con diabetes mellitus entre julio de 2024 y junio de 2025 (prevalencia cruda de 4,81 por 100 habitantes, 9,3 % más que el periodo anterior). Ese mismo informe indica que la proporción de pacientes con diabetes **controlada y monitorizada** bajó de 30,9 % en 2022 a 23,1 % en 2024, por debajo de la meta del 30 %. Fuente: [ConsultorSalud, "Enfermedades endocrinas y metabólicas crecen 72 % en Colombia"](https://consultorsalud.com/enfermedades-endocrinas-colombia/), que cita el informe de la CAC. Las cifras varían según el corte temporal; se citan con su periodo y deben contrastarse con el informe original de la [Cuenta de Alto Costo](https://cuentadealtocosto.org/) antes de cualquier publicación.
- **Latinoamérica:** el [IDF Diabetes Atlas, 11.ª edición (2025)](https://international-diabetes-federation.s3.eu-west-1.amazonaws.com/media/uploads/sites/3/2025/08/IDF_Atlas_11_2025_SACA_Factsheet.pdf) estima 35,4 millones de adultos (20 a 79 años) con diabetes en 2024 en Sudamérica y Centroamérica, con 1 de cada 3 sin diagnóstico (30,4 %). Colombia aparece con unos 3,0 millones, tras Brasil y Argentina. La proyección regional es de unos 52 millones en 2050.
- **Subdiagnóstico:** según la misma estimación de la IDF, cerca del 16,2 % de los adultos con diabetes en Colombia no sabe que la tiene (cifra citada por [ConsultorSalud](https://consultorsalud.com/enfermedades-endocrinas-colombia/)).

### 1.2 El problema en la consulta

La atención de la diabetes ocurre en consultas separadas por meses, mientras la enfermedad se gestiona todos los días. Para hospitales y clínicas esto produce:

- **Visibilidad parcial:** el médico decide con una HbA1c trimestral y la libreta del paciente, sin ver hipoglucemias nocturnas ni la variabilidad diaria.
- **Registros dispersos:** glucosa, insulina, comidas y síntomas viven en papel, en apps de fabricantes o en el celular del paciente, sin llegar a la historia de la clínica.
- **Sin priorización:** con cientos de pacientes por equipo, nadie sabe a quién llamar hoy. Los pacientes que empeoran se descubren en la siguiente cita, o en urgencias.
- **Tratamientos sin seguimiento fino:** los ajustes de insulina se hacen con poca evidencia reciente y sin dejar claro quién decidió qué y por qué.
- **Abandono silencioso:** el paciente deja de registrar y de asistir, y la clínica solo se entera cuando ya hay una complicación.
- **Datos sensibles sin trazabilidad:** los datos de salud circulan por canales informales (WhatsApp, fotos), sin consentimiento ni auditoría.

## 2. Solución

Insumap es una plataforma web que conecta a la clínica, a sus médicos y a sus pacientes alrededor de un mismo registro:

1. La **clínica importa** a sus pacientes desde su propia base de datos (FHIR R4 Bundle o CSV) y les **emite credenciales** de un solo uso.
2. El **paciente** activa su cuenta, acepta el tratamiento de datos y registra glucosa (manual o CGM), insulina, comidas, actividad, síntomas y HbA1c desde una PWA diseñada primero para escritorio, instalable y usable también desde el celular.
3. Uno o varios **médicos asignados** vigilan a sus pacientes desde un dashboard con triage, métricas (TIR, GMI, CV, AGP), alertas y plan de tratamiento.
4. La **IA propone** (pronósticos, riesgo, patrones, ajustes, resúmenes) y **el médico aprueba, modifica o rechaza con motivo**. Toda salida de IA tiene un respaldo determinista.
5. El **administrador de la clínica** gestiona usuarios, equipos de atención, metas, reglas de alerta y plantillas de protocolo, sin ver datos clínicos detallados.
6. Todo acceso a datos clínicos queda **auditado** y el tratamiento de datos requiere **consentimiento versionado**.

## 3. Modelo de negocio B2B2C

| Etapa | Qué ocurre | Quién |
|---|---|---|
| Contrato | La clínica u hospital contrata Insumap y queda creada como *tenant* (clínica) con su primer `CLINIC_ADMIN`. | `PLATFORM_ADMIN` |
| Onboarding | La clínica importa sus pacientes con diabetes desde su sistema (FHIR R4 o CSV). El sistema valida, deduplica por número de historia (MRN) y crea cuentas en `IMPORTED`. | `CLINIC_ADMIN` |
| Credenciales | La clínica emite invitaciones con código de activación de un solo uso (por correo o impreso). El paciente activa su cuenta (`ACTIVE`). | `CLINIC_ADMIN`, `PATIENT` |
| Equipo | La clínica asigna uno o varios médicos a cada paciente; uno es el principal. | `CLINIC_ADMIN` |
| Uso diario | El paciente registra, el médico vigila, la IA propone y el médico decide. | `PATIENT`, `DOCTOR` |
| Medición | La clínica ve KPIs agregados de adopción y de control glucémico sin detalle clínico. | `CLINIC_ADMIN` |

- **Cliente que paga:** la clínica (B2B). **Usuario final:** el paciente y su equipo (B2C dentro del contrato de la clínica). El paciente no se registra por su cuenta: llega por invitación de su clínica.
- **Modelo de ingresos propuesto (por definir, fuera del alcance académico):** suscripción por clínica o por paciente activo. No se implementa facturación.
- **La clínica conserva la propiedad de los datos** y es la responsable del tratamiento; Insumap actúa como encargado (ver [Cumplimiento-y-privacidad.md](Cumplimiento-y-privacidad.md)).

## 4. Valor por actor

| Actor | Rol | Valor que recibe |
|---|---|---|
| Clínica u hospital | cliente B2B | Visión de población, priorización de pacientes, menos consultas evitables, trazabilidad de decisiones y datos de adopción. |
| Administrador de la clínica | `CLINIC_ADMIN` | Alta masiva de pacientes sin captura manual, control de equipos y reglas, auditoría y KPIs, sin exposición a datos clínicos. |
| Médico | `DOCTOR` | Lista de "a quién ver hoy" con motivos, métricas estándar (AGP, TIR), resumen previo a la consulta y propuestas de ajuste que él decide. |
| Paciente | `PATIENT` | Registro simple desde escritorio o celular (también sin conexión), ver su tendencia y metas, recordatorios, mensajes con su equipo y un asistente educativo con límites claros. |
| Administrador de la plataforma | `PLATFORM_ADMIN` | Alta y control de clínicas con un rol mínimo; sin acceso clínico. |
| Equipo de desarrollo | equipo académico | Un caso completo para aplicar patrones de diseño, seguridad y IA con human-in-the-loop. |

## 5. Objetivos

### 5.1 Objetivo general

Permitir que una clínica monitoree de forma continua a sus pacientes con diabetes, con registros del paciente, métricas glucémicas estándar, alertas y recomendaciones de IA que el médico siempre decide, protegiendo los datos de salud con aislamiento por clínica, asignación por equipo y auditoría.

### 5.2 Objetivos específicos

| ID | Objetivo | Medida de verificación |
|---|---|---|
| OE-01 | Incorporar pacientes desde la base de datos de la clínica sin captura manual. | Un Bundle FHIR R4 y un CSV de la clínica demo se importan, con reporte por fila y sin duplicar MRN. |
| OE-02 | Entregar credenciales seguras de un solo uso y activar cuentas con consentimiento. | Un código se usa una vez, expira y se guarda como hash; la cuenta pasa a `ACTIVE` solo con consentimiento aceptado. |
| OE-03 | Asegurar que cada médico vea únicamente a sus pacientes asignados. | Un médico que consulta un paciente no asignado o de otra clínica recibe `404`. |
| OE-04 | Registrar glucosa, insulina, comidas, actividad, síntomas y HbA1c, también sin conexión. | Un lote offline se sincroniza una sola vez y las lecturas inverosímiles se rechazan o se marcan. |
| OE-05 | Calcular métricas del Consenso Internacional (TIR, TBR, TAR, GMI, CV) y el AGP con metas configurables. | Los resultados coinciden con casos de referencia y las metas salen de la base de datos, no del código. |
| OE-06 | Detectar hipoglucemia e hiperglucemia sostenida y escalar a quien corresponde. | Una hipoglucemia de nivel 2 genera una alerta `OPEN` y escala por la cadena definida si nadie la reconoce. |
| OE-07 | Dar a la IA un rol de apoyo con aprobación humana y respaldo determinista. | Ninguna recomendación se aplica sin decisión registrada; si la IA falla, el sistema responde con reglas e indica "respaldo". |
| OE-08 | Priorizar a los pacientes con un triage explicado. | El dashboard ordena por riesgo y muestra los factores de cada bandera. |
| OE-09 | Proteger los datos de salud y dejar trazabilidad. | Cada lectura clínica queda en la auditoría y la cadena de hashes se verifica. |
| OE-10 | Probar todo con datos simulados verosímiles, sin datos reales. | La clínica demo muestra "Datos simulados" en UI, reportes y API. |
| OE-11 | Medir si la IA ayuda frente al respaldo. | Existe una evaluación con MAE, RMSE, Clarke Error Grid, AUROC y calibración sobre datos simulados. |

## 6. Alcance

### 6.1 Incluido en el MVP

El MVP son las fases 1 a 9 del plan más el modo `backfill` del simulador (ver [Roles-y-planeacion.md](Roles-y-planeacion.md) y [Plan-de-commits.md](Plan-de-commits.md)):

| Módulo | Capacidad del MVP |
|---|---|
| M1 Identidad y acceso | Login, JWT de 15 minutos, refresh opaco con rotación, MFA TOTP del personal, permisos desde la base de datos, rate limiting. |
| M2 Clínicas y usuarios | Alta de clínicas, primer administrador y personal médico. |
| M3 Onboarding | Importación FHIR y CSV, validación, deduplicación, emisión y activación de credenciales, estados de cuenta. |
| M4 Equipo de atención | Asignación de médicos, médico principal, acceso solo a pacientes asignados. |
| M5 Registros | Glucosa, insulina, comidas, actividad, síntomas, HbA1c, lotes offline, validación en cadena y línea de tiempo. |
| M6 Plan de tratamiento | Plantillas de protocolo, plan por paciente versionado, metas y recordatorios. |
| M7 Métricas | TIR, TBR, TAR, GMI, CV y AGP por ventanas. |
| M8 Alertas | Reglas configurables, hipo e hiperglucemia, ciclo de vida, escalamiento, notificaciones por correo, Web Push e in-app. |
| M9 IA | Pronóstico (IA1), triage (IA2), patrones (IA3), sugerencias de ajuste (IA4) y riesgo de abandono (IA7), con aprobación y respaldo. |
| M10 Dashboard | Triage, detalle del paciente, notas, reporte y KPIs de la clínica. |
| M12 Auditoría | Registro append-only, auditoría de lecturas clínicas y consentimiento versionado. |
| M13 Datos simulados | Clínica demo, importación `backfill` y marca "Datos simulados". |

### 6.2 Post-MVP (fases 10 a 12)

- IA generativa con guardrails: resumen previo a la consulta (IA5) y asistente educativo del paciente (IA6), con evaluación de la IA.
- Mensajería paciente-equipo y controles programados (M11), consola de auditoría, derechos del titular y modo `live` del simulador.
- Endurecimiento, despliegue (AWS: CloudFront, S3 y EC2) y versión `v1.0.0`.

### 6.3 Fuera de alcance

| Fuera de alcance | Motivo |
|---|---|
| Ser un dispositivo médico o dar diagnóstico | Proyecto académico; sin registro sanitario. |
| Recomendar dosis de insulina al paciente | La IA nunca da dosis al paciente; solo propone al médico. |
| Datos reales de pacientes | Todo viene del simulador o de fixtures de prueba. |
| Integración directa con sensores CGM de fabricantes (APIs propietarias) | Se importa por CSV o FHIR; la integración directa queda como trabajo futuro. |
| Facturación y contratos de la clínica | Se documenta el modelo, no se implementa. |
| Telemedicina por video, e-prescripción, historia clínica completa | Insumap complementa la historia clínica de la clínica, no la reemplaza. |
| Aplicaciones nativas iOS y Android | Se entrega una PWA instalable, con prioridad de diseño en escritorio. |
| Estimación de carbohidratos por foto | Futuro. |
| Dispositivos de insulina de lazo cerrado | Futuro. |

## 7. Referencias de productos similares

Productos existentes que inspiran el diseño. Se verificó su descripción pública; Insumap no copia su código ni su marca.

| Producto | Qué aporta como referencia |
|---|---|
| **Tidepool TIDE** (*Timely Interventions for Diabetes Excellence*) | Herramienta abierta, nacida en una clínica pediátrica de DM1 de Stanford, que analiza datos de CGM de toda la población de la clínica y genera banderas para priorizar a quién contactar. Inspira el triage por reglas de Insumap (Strategy de respaldo). Ver el [artículo en JMIR Diabetes](https://diabetes.jmir.org/2022/2/e27284/PDF). |
| **Glooko Clinic Dashboard** | Panel de población para la clínica con métricas basadas en TIDE, estratificación de riesgo por CGM y métricas de activación y uso. Referencia para el panel de KPIs de la clínica. Ver [Glooko](https://glooko.com/glooko-release-diabetes-management-clinic-dashboard/). |
| **LibreView (Abbott)** | Sistema en la nube para que pacientes y profesionales analicen datos de glucosa de dispositivos FreeStyle Libre. Referencia para la carga de datos CGM y los reportes. Descripción publicada en documentación de Abbott; no se encontró una fuente directa de un panel de población equivalente. |
| **Dexcom Clarity** | La clínica crea cuentas de paciente y el paciente autoriza compartir datos; el profesional ve reportes interactivos. Referencia para el modelo de consentimiento y los reportes estándar. Ver [Dexcom Clarity](https://www.dexcom.com/en-bh/clarity). |

Referencias clínicas: Consenso Internacional de Tiempo en Rango (Battelino et al., *Diabetes Care* 2019) y ADA Standards of Care (ver [Metricas-clinicas.md](Metricas-clinicas.md)).

## 8. Cómo funciona, en palabras simples

```
Clínica (contrato)
   |  importa pacientes (FHIR/CSV) y emite credenciales
   v
Paciente activa su cuenta y registra glucosa, insulina, comidas, actividad, síntomas
   |
   v
Insumap calcula métricas y evalúa reglas de alerta
   |                          |
   v                          v
La IA propone (pronóstico,   Alertas con escalamiento
riesgo, patrones, ajustes)   (paciente, médico principal, equipo, admin)
   |
   v
El médico aprueba, modifica o rechaza con motivo  -->  se aplica al plan  -->  auditoría
```

## 9. Equipo y repositorios

| Integrante | Cuenta | Enfoque |
|---|---|---|
| Nicolas Diaz | `NicoalsD` | Producto, frontend y UX, DevOps y documentación global. |
| Drako Salazar | `Drako2305` | Backend, base de datos, seguridad y patrones de diseño. |
| Nicolas Mora | `nicomora70` | IA, datos simulados y simulador; registros del paciente y cliente de IA en el backend. |

Repositorios: `insumap-backend` (este, con la documentación canónica), `insumap-database`, `insumap-frontend`, `insumap-ai` e `insumap-simulator`. Reparto detallado en [Roles-y-planeacion.md](Roles-y-planeacion.md).

## 10. Descargo de responsabilidad

- Insumap es un trabajo **académico**. No está registrado ni validado como dispositivo médico (SaMD) y no debe usarse para decisiones clínicas reales.
- La **IA solo apoya al médico**. Toda recomendación es una propuesta que el médico aprueba, modifica o rechaza. La IA nunca da dosis ni diagnósticos al paciente.
- Todo dato de la clínica demo es **simulado**, se genera con `insumap-simulator` y se muestra como "Datos simulados".
- Las cifras epidemiológicas citadas son de fuentes públicas con su periodo; algunas provienen de prensa especializada que cita informes oficiales y deben contrastarse con el informe original antes de un uso formal.
- El aviso se muestra en la UI, los reportes y la documentación.

## Documentos relacionados

[Requerimientos.md](Requerimientos.md) · [Historias-de-usuario.md](Historias-de-usuario.md) · [Actores-y-permisos.md](Actores-y-permisos.md) · [Arquitectura.md](Arquitectura.md) · [Modulo-IA.md](Modulo-IA.md) · [Seguridad.md](Seguridad.md) · [Cumplimiento-y-privacidad.md](Cumplimiento-y-privacidad.md) · [Datos-simulados.md](Datos-simulados.md) · [Glosario.md](Glosario.md) · [Riesgos.md](Riesgos.md)
