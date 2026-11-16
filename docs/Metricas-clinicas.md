# Métricas clínicas y perfiles de metas

Este documento define las métricas glucémicas que calcula Insumap (módulo M7), cómo se calcula cada una, qué metas se usan por población y de dónde sale cada número. Lo usan el dashboard (M10), las alertas (M8), el triage por reglas, las características de la IA ([Modulo-IA.md](Modulo-IA.md)) y los reportes.

> **Aviso:** proyecto académico, no es un dispositivo médico. Las metas son referencias de guías publicadas, no una indicación para un paciente. El médico fija y ajusta las metas de cada paciente.

## 1. Regla central: las metas son datos, no código

**Todos los umbrales de este documento son semillas** (*seeds*) que se cargan en la tabla `care.target_profiles` al crear la base de datos (`insumap-database`) y que el `CLINIC_ADMIN` puede versionar y ajustar. El código **nunca** contiene un `70`, un `180` ni un `4 %` como constante clínica:

- El backend lee el perfil activo del paciente (`care.target_profiles`) y se lo pasa a las funciones de métricas, a las reglas de alerta y a la IA (`thresholds` en las peticiones; ver [Contrato-IA.md](Contrato-IA.md)).
- Los perfiles son **versionados**: cambiar una meta crea una versión nueva; las métricas históricas guardan la versión con que se calcularon.
- Un paciente tiene un perfil asignado por el médico; si no tiene, aplica el perfil por defecto de su población.
- Solo constantes físicas o de unidad llevan nombre en el código (por ejemplo `MG_DL_PER_MMOL_L`). Una prueba de deriva verifica que `care.target_profiles` y las funciones de métricas no compartan literales.

Las fuentes de las semillas están en la sección 9.

## 2. Datos de entrada y suficiencia

### 2.1 Fuentes de lecturas

| Fuente (`source`) | Descripción | Métricas que admite |
|---|---|---|
| `CGM` | Sensor continuo, lectura cada 5 o 15 min (hasta 288 por día a 5 min) | Todas las métricas de la sección 3 |
| `SMBG` | Glucómetro capilar, 1 a 4 mediciones por día | Métricas de la sección 5 (sin AGP ni CV fiable) |
| `MANUAL` | Valor ingresado a mano | Como `SMBG`, marcado como manual |

La glucosa se guarda siempre en **mg/dL**. Los valores en mmol/L se convierten al recibirlos con la constante `MG_DL_PER_MMOL_L` (18.0156 mg/dL por mmol/L); la conversión redondea al guardar a un decimal.

### 2.2 Suficiencia de datos (CGM)

- **Periodo estándar:** 14 días.
- **Suficiencia:** `data_sufficiency_pct = lecturas_válidas / lecturas_esperadas × 100`, donde `lecturas_esperadas = minutos_del_periodo / intervalo_nominal_min` (por ejemplo 14 días a 5 min son 4032).
- **Mínimo para reportar métricas:** **70 %** del periodo de 14 días (semilla `min_data_sufficiency_pct = 70`, `min_days = 14`).
- Si la suficiencia es menor, el backend **igualmente calcula** las métricas pero las marca como `LOW_CONFIDENCE`, el dashboard muestra "datos insuficientes" y la IA responde `INSUFFICIENT_DATA` (ver contrato).
- Para otros periodos (7, 30, 90 días) se usa el mismo porcentaje mínimo; la ventana de 14 días se conserva como la de referencia para el AGP.
- Una lectura es **válida** si pasó la `GlucoseReadingValidationHandler` (rango físico del sensor, sin duplicado, sin marca futura) y no fue corregida como inválida.

### 2.3 Día, noche y zona horaria

- **Todos los cálculos por día usan la zona horaria de la clínica** (`clinic.clinics.timezone`, por ejemplo `America/Bogota`), nunca UTC ni la del servidor.
- Un "día" es el intervalo local `[00:00, 24:00)`. Un periodo de N días son N días locales completos terminados en el día anterior a hoy (el día en curso se muestra aparte como parcial).
- La **noche** es una ventana de configuración de la clínica (semilla `00:00` a `06:00` local), usada por las métricas nocturnas y por IA1 e IA3.
- Los cambios de horario de verano (si la zona los tiene) se manejan con aritmética de zona horaria (`zoneinfo`), no sumando 24 horas. Un día puede tener 23 o 25 horas.
- Las marcas de tiempo se guardan en UTC (`timestamptz`) y se convierten a la zona local solo para agrupar.
- La hora actual sale del `Clock` inyectado, no de la del sistema.

## 3. Métricas CGM

Notación: `G` es el conjunto de lecturas válidas del periodo; `n = |G|`; `Δ` es el intervalo entre lecturas. Cuando el intervalo no es uniforme se pondera por el tiempo que representa cada lectura (hasta la lectura siguiente, con un máximo de `Δ_max`, semilla 20 min; más allá, el tramo es un hueco que no cuenta). Con muestreo regular, la ponderación por tiempo equivale a contar lecturas.

### 3.1 Tiempo en rango, bajo rango y sobre rango

`pct_en_rango(a, b) = tiempo con glucosa en el intervalo / tiempo total con datos × 100`

| Métrica | Definición (valores semilla del perfil estándar) | Notas |
|---|---|---|
| **TIR** (tiempo en rango) | 70 ≤ glucosa ≤ 180 mg/dL | Límites inclusivos en el extremo |
| **TBR nivel 1** | 54 ≤ glucosa < 70 mg/dL | |
| **TBR nivel 2** | glucosa < 54 mg/dL | |
| **TBR total** | glucosa < 70 mg/dL | TBR1 + TBR2 |
| **TAR nivel 1** | 180 < glucosa ≤ 250 mg/dL | |
| **TAR nivel 2** | glucosa > 250 mg/dL | |
| **TAR total** | glucosa > 180 mg/dL | TAR1 + TAR2 |

Las cinco franjas son mutuamente excluyentes y cubren todas las lecturas, por lo que **TBR2 + TBR1 + TIR + TAR1 + TAR2 = 100 %** (se verifica en las pruebas; el redondeo a un decimal puede dar 99.9 o 100.1 y no se "corrige" artificialmente). Los límites (`54`, `70`, `180`, `250`) son columnas del perfil (`target_profiles`), no constantes.

Equivalencia en tiempo: `% × 24 h / 100` por día; por ejemplo 70 % de TIR son 16 h 48 min por día. El dashboard puede mostrar ambos.

### 3.2 Glucosa media

`mean_glucose = Σ(g_i × w_i) / Σ(w_i)` (con `w_i` el tiempo que representa cada lectura).
Redondeo: **al entero más cercano en mg/dL** para mostrar; se guarda con un decimal.

### 3.3 GMI (indicador de gestión de glucosa)

Fórmula de Bergenstal et al. (2018):

```
GMI (%)       = 3.31 + 0.02392 × glucosa_media (mg/dL)
GMI (mmol/mol) = 12.71 + 4.70587 × glucosa_media (mmol/L)
```

- Redondeo: **un decimal** en porcentaje (la práctica clínica reporta 0.1 %).
- Requiere suficiencia de datos; los autores recomiendan al menos 10 y preferiblemente 14 o más días de CGM.
- **No es la HbA1c:** estima la HbA1c que se esperaría según el CGM y puede diferir de la medida en laboratorio. La interfaz lo rotula "GMI (estimación)" y nunca lo llama HbA1c.
- Los coeficientes son constantes de la fórmula publicada (constantes con nombre en el código), no metas clínicas.

### 3.4 Variabilidad: coeficiente de variación (CV)

`CV (%) = desviación estándar / glucosa media × 100`

- Desviación estándar **muestral ponderada por tiempo** de las lecturas válidas del periodo.
- Redondeo a un decimal. Meta del perfil estándar: **CV ≤ 36 %** (algunas guías sugieren < 33 % para más protección frente a hipoglucemia en personas con insulina o sulfonilureas).
- Solo se calcula con suficiencia de datos y con al menos un número mínimo de lecturas (semilla `min_readings_for_cv = 100`).

### 3.5 Perfil ambulatorio de glucosa (AGP)

El AGP resume el periodo (14 días) superponiendo los días sobre un eje de 24 horas locales.

- Se divide el día en **intervalos de una hora** (24 *bins*) o de 15 min en una vista fina (parámetro de la vista).
- Para cada intervalo se toman todas las lecturas válidas de todos los días del periodo y se calculan los **percentiles 5, 25, 50 (mediana), 75 y 95** con interpolación lineal (método por defecto de `numpy.percentile`).
- Luego se suaviza la curva (media móvil de 3 intervalos, parámetro) solo para dibujar; los datos guardados son los crudos.
- Se dibuja: la mediana; la banda intercuartil (25 a 75), que muestra la variabilidad habitual; y la banda 5 a 95, que muestra los extremos. Las líneas de las metas (70 y 180 por defecto) salen del perfil.
- Requiere suficiencia de datos de 70 % en 14 días; si no, se muestra el aviso.
- Los percentiles 5/25/50/75/95 son la presentación estándar del AGP en la práctica clínica; el consenso internacional exige que el AGP incluya las métricas y metas principales junto a un perfil compuesto de 14 días. Los números de los percentiles son configuración de la vista, no metas.

### 3.6 Episodios de hipoglucemia

| Nivel | Definición | Fuente |
|---|---|---|
| **Nivel 1** | glucosa < 70 mg/dL y ≥ 54 mg/dL | ADA 2026, Tabla 6.4 |
| **Nivel 2** | glucosa < 54 mg/dL | ADA 2026, Tabla 6.4 |
| **Nivel 3** | Evento grave con alteración del estado mental o físico que requiere asistencia de otra persona, **sin importar el valor de glucosa** | ADA 2026, Tabla 6.4 |

- El nivel 3 **no se deduce de la glucosa**: se registra cuando el paciente o el médico lo reporta (campo de síntoma o evento clínico). Las métricas CGM solo cuentan niveles 1 y 2.
- **Episodio CGM:** secuencia de al menos **15 minutos consecutivos** bajo el umbral (el consenso lista los episodios de 15 min entre las métricas; Tabla 1 del consenso 2019). El episodio **termina** cuando la glucosa vuelve a estar en o sobre el umbral durante al menos 15 minutos seguidos (criterio del consenso de 2017; valor semilla `hypo_episode_min_minutes = 15`).
- Se cuenta un episodio de nivel 2 si en algún momento alcanzó < 54 mg/dL durante al menos 15 minutos; un episodio de nivel 1 que luego baja de 54 se reclasifica como nivel 2 (se cuenta una vez, en su nivel máximo).
- `hypo_events_count` (de 14 días) y su desglose por nivel y por franja (diurna o nocturna) alimentan el triage y la IA.

### 3.7 Resumen de redondeos

| Métrica | Se muestra | Se guarda |
|---|---|---|
| TIR, TBR, TAR | 1 decimal (%) | 2 decimales |
| Glucosa media | Entero (mg/dL) | 1 decimal |
| GMI | 1 decimal (%) | 2 decimales |
| CV | 1 decimal (%) | 2 decimales |
| Suficiencia de datos | Entero (%) | 1 decimal |
| Percentiles del AGP | Entero (mg/dL) | 1 decimal |

El redondeo es el de "mitad hacia arriba" (`ROUND_HALF_UP`) con `Decimal`, no el redondeo bancario de Python, para que coincida con lo que lee el médico.

## 4. Comparaciones entre periodos

Para el triage y la IA se compara el periodo actual con el anterior de igual duración:

- `tir_delta_vs_prior_pct = TIR_actual − TIR_anterior` (en **puntos porcentuales**).
- Un descenso de más de 15 puntos o más de 25 % del tiempo sobre 180 mg/dL son ejemplos de banderas tipo TIDE; los números de las banderas son **reglas de alerta en BD** (`alerts.alert_rules`), no constantes.
- Las ventanas habituales son 24 h, 7, 14 y 30 días. Todas respetan la suficiencia de datos propia de su duración.

## 5. Métricas de glucometría (SMBG)

Aplican a DM2 y gestacional con medición capilar. Con pocos puntos por día **no** se calcula TIR por tiempo, AGP ni CV como en CGM: la estructura de las mediciones no es continua.

| Métrica | Definición | Redondeo |
|---|---|---|
| **Mediciones por día** | `n_lecturas / días_con_alguna_lectura`, y `días_con_lectura / días_del_periodo` | 1 decimal |
| **Media de glucosa** | Media aritmética de las lecturas del periodo | Entero |
| **Porcentaje de lecturas en rango** | Lecturas dentro del rango del perfil / lecturas totales × 100 (conteo, no tiempo) | 1 decimal |
| **Porcentaje bajo 70 y bajo 54** | Idem con los umbrales de hipoglucemia nivel 1 y 2 | 1 decimal |
| **Glucosa en ayunas** | Mediana de las lecturas con contexto `FASTING` | Entero |
| **Posprandial** | Mediana (o máximo) de las lecturas `POST_MEAL` | Entero |
| **Lecturas fuera de meta por contexto** | Porcentaje fuera de meta en ayuno, antes de la comida y posprandial (metas ADA, sección 6.3) | 1 decimal |
| **Variabilidad** | Desviación estándar y CV, **solo** si hay al menos `min_readings_for_cv_smbg` lecturas (semilla 30) y se rotulan "estimación con pocos puntos" | 1 decimal |

Reglas:

- El porcentaje de lecturas **no** equivale al tiempo en rango: se rotula "% de lecturas en rango".
- El GMI no se calcula con SMBG (la fórmula es para CGM).
- La suficiencia en SMBG se mide como días con al menos una lectura sobre los días del periodo (semilla mínima del perfil: 70 %), con el patrón de medición indicado por el médico en el plan.

## 6. HbA1c

- Es una **medición de laboratorio** (`monitoring.lab_results`), no un cálculo del sistema. En FHIR llega como `Observation` con LOINC `4548-4`, unidad `%`.
- Se muestra con **un decimal** (%) y, si el laboratorio la entrega en mmol/mol, se convierte con la ecuación estándar IFCC-NGSP: `NGSP (%) = 0.09148 × IFCC (mmol/mol) + 2.152`. Constante con nombre en el código.
- Frecuencia: la guía de ADA sugiere medirla al menos dos veces al año en pacientes estables y cuatro en los que cambian de tratamiento; el simulador la genera cada trimestre. El recordatorio es una regla en BD (`care.reminder_schedules`).
- La HbA1c y el GMI se muestran juntos con la diferencia, que se llama "discordancia" y no se interpreta automáticamente.
- Meta del perfil (semilla): ver la sección 7.

## 7. Perfiles de metas por población (semillas)

Cada fila es un registro de `care.target_profiles`. Todos los números son **semillas editables** (sección 1). Los códigos de perfil (`code`) son identificadores en inglés; las etiquetas visibles (`label`) van en español.

### 7.1 Adultos estándar con DM1 o DM2 (`ADULT_STANDARD`)

| Métrica | Meta semilla | Fuente |
|---|---|---|
| TIR (70 a 180 mg/dL) | > 70 % (más de 16 h 48 min por día) | Consenso 2019, Tabla 3; ADA 2026, Tabla 6.2 |
| TBR < 70 mg/dL (niveles 1 y 2) | < 4 % (menos de 1 h por día) | Consenso 2019; ADA 2026 |
| TBR < 54 mg/dL (nivel 2) | < 1 % (menos de 15 min por día) | Consenso 2019; ADA 2026 |
| TAR > 180 mg/dL (niveles 1 y 2) | < 25 % (menos de 6 h por día) | Consenso 2019; ADA 2026 |
| TAR > 250 mg/dL (nivel 2) | < 5 % (menos de 1 h 12 min por día) | Consenso 2019; ADA 2026 |
| CV | ≤ 36 % | Consenso 2019; ADA 2026 |
| Datos | ≥ 70 % de 14 días | Consenso 2019; ADA 2026 |
| HbA1c | < 7 % (< 53 mmol/mol) para muchos adultos no embarazadas | ADA 2026, Rec. 6.3a |
| Glucosa capilar preprandial | 80 a 130 mg/dL | ADA 2026, Tabla 6.3 |
| Glucosa capilar posprandial (pico) | < 180 mg/dL | ADA 2026, Tabla 6.3 |

Variantes que el médico puede elegir: un objetivo más estricto de HbA1c (< 6.5 %) o menos estricto (hasta 8 %) según el paciente (ADA 2026, Rec. 6.3a).

### 7.2 Adultos mayores o de alto riesgo (`OLDER_OR_HIGH_RISK`)

| Métrica | Meta semilla | Fuente |
|---|---|---|
| TIR (70 a 180 mg/dL) | > 50 % (más de 12 h por día) | Consenso 2019, Tabla 3; ADA 2026, Tabla 6.2 |
| TBR < 70 mg/dL | < 1 % (menos de 15 min por día) | Consenso 2019; ADA 2026 |
| TBR < 54 mg/dL | < 1 % | ADA 2026, Tabla 6.2 |
| TAR > 250 mg/dL | < 10 % (menos de 2 h 24 min por día) | Consenso 2019; ADA 2026 |
| TAR > 180 mg/dL | < 50 % (niveles 1 y 2 combinados) | ADA 2026, Tabla 6.2 |
| CV | ≤ 36 % | ADA 2026 |
| HbA1c | Menos estricta (hasta 8 %) según el criterio del médico | ADA 2026, Rec. 6.3a |

Nota: en el consenso de 2019 este perfil cita como límite de TAR el nivel > 250 mg/dL; ADA 2026 lo complementa con TAR > 180 mg/dL < 50 %. El perfil semilla incluye ambos.

### 7.3 Embarazo con DM1 (`PREGNANCY_T1D`)

| Métrica | Meta semilla | Fuente |
|---|---|---|
| Rango objetivo | **63 a 140 mg/dL** (3.5 a 7.8 mmol/L) | Consenso 2019, Tabla 4; ADA 2026 Sec. 15 |
| TIR (63 a 140 mg/dL) | > 70 % | Consenso 2019, Tabla 4; ADA 2026 Sec. 15 |
| TBR < 63 mg/dL | < 4 % | Consenso 2019; ADA 2026 Sec. 15 |
| TBR < 54 mg/dL | < 1 % | Consenso 2019; ADA 2026 Sec. 15 |
| TAR > 140 mg/dL | < 25 % | ADA 2026 Sec. 15 |
| Glucosa en ayunas | < 95 mg/dL | ADA 2026 Sec. 15, Rec. 15.8 |
| Glucosa a 1 h posprandial | < 140 mg/dL | ADA 2026 Sec. 15, Rec. 15.8 |
| Glucosa a 2 h posprandial | < 120 mg/dL | ADA 2026 Sec. 15, Rec. 15.8 |
| HbA1c | < 6 % (< 42 mmol/mol) si se logra sin hipoglucemia significativa; puede relajarse a < 7 % | ADA 2026 Sec. 15, Rec. 15.9 |

### 7.4 Embarazo con DM2 o diabetes gestacional (`PREGNANCY_T2D_GDM`)

El consenso de 2019 **no** da metas porcentuales de TIR para estos grupos porque falta evidencia. Se usa glucometría con las metas de ADA 2026 Sec. 15 (glucosa en ayunas < 95 mg/dL; a 1 h posprandial < 140 mg/dL; a 2 h posprandial < 120 mg/dL; HbA1c < 6 % si es seguro, o < 7 %). Las métricas de la sección 5 son las que se calculan y se comparan con esas metas; si la paciente usa CGM, se muestran las métricas CGM sin meta porcentual hasta que el equipo clínico fije una.

### 7.5 Estructura sugerida de `care.target_profiles`

Esquema conceptual; la definición canónica está en [Modelo-de-datos.md](Modelo-de-datos.md) y en `insumap-database`. Esta tabla fija solo **qué debe poder guardar** el perfil.

| Columna | Tipo | Ejemplo semilla `ADULT_STANDARD` |
|---|---|---|
| `code`, `label`, `version`, `is_default`, `population` | texto, entero, booleano | `ADULT_STANDARD`, "Adulto estándar" |
| `range_low_mg_dl`, `range_high_mg_dl` | número | 70, 180 |
| `very_low_mg_dl`, `very_high_mg_dl` | número | 54, 250 |
| `tir_min_pct` | número | 70 |
| `tbr_l1_max_pct`, `tbr_l2_max_pct` | número | 4, 1 |
| `tar_l1_max_pct`, `tar_l2_max_pct` | número | 25, 5 |
| `cv_max_pct` | número | 36 |
| `min_data_sufficiency_pct`, `min_days` | número, entero | 70, 14 |
| `hba1c_goal_pct` | número | 7.0 |
| `fasting_low_mg_dl`, `fasting_high_mg_dl` | número | 80, 130 |
| `postprandial_max_mg_dl` | número | 180 |
| `night_start`, `night_end` | hora local | 00:00, 06:00 |

(En el perfil de embarazo `range_low_mg_dl = 63` y `range_high_mg_dl = 140`, y las tolerancias de TBR y TAR se aplican a esos límites. Los porcentajes de TAR del perfil `ADULT_STANDARD` se interpretan como el total sobre 180 mg/dL en `tar_l1_max_pct` y el nivel 2 en `tar_l2_max_pct`, como en el consenso.)

## 8. Uso de las metas en el sistema

| Uso | Cómo |
|---|---|
| Dashboard y AGP | Colorea y dibuja las metas del perfil del paciente |
| Triage por reglas y banderas | Reglas de `alerts.alert_rules` que comparan con el perfil |
| Alertas (M8) | Los umbrales de hipo e hiper vienen de reglas en BD (compuestas, P08) |
| IA | El backend envía `thresholds` y metas en cada petición; el servicio de IA no tiene valores clínicos |
| Reportes | Imprimen el perfil activo y su versión |
| Simulador | No copia metas; genera pacientes con metas variadas y deja que el backend las aplique |

## 9. Fuentes

Las metas clínicas (secciones 3.1, 3.3, 3.6 y 7) se contrastaron con las fuentes primarias el 15 de noviembre de 2026. Lo que no se pudo verificar se lista al final de esta sección.

| Tema | Fuente |
|---|---|
| Consenso internacional de tiempo en rango (TIR 70 a 180, TBR < 70 y < 54, TAR > 180 y > 250, CV ≤ 36 %, 14 días y 70 % de datos, metas por población, embarazo 63 a 140) | Battelino T, Danne T, Bergenstal RM, et al. *Clinical Targets for Continuous Glucose Monitoring Data Interpretation: Recommendations From the International Consensus on Time in Range.* Diabetes Care 2019;42(8):1593-1603. [doi:10.2337/dci19-0028](https://doi.org/10.2337/dci19-0028), [texto completo en PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC6973648/) |
| GMI (fórmula y recomendación de 10 a 14 días de datos) | Bergenstal RM, Beck RW, Close KL, et al. *Glucose Management Indicator (GMI): A New Term for Estimating A1C From Continuous Glucose Monitoring.* Diabetes Care 2018;41(11):2275-2280. [doi:10.2337/dc18-1581](https://doi.org/10.2337/dc18-1581), [PMC6196826](https://pmc.ncbi.nlm.nih.gov/articles/PMC6196826/) |
| Niveles de hipoglucemia 1, 2 y 3; métricas CGM de la Tabla 6.2; HbA1c < 7 %; glucosa capilar 80 a 130 y < 180 | American Diabetes Association Professional Practice Committee. *6. Glycemic Goals, Hypoglycemia, and Hyperglycemic Crises: Standards of Care in Diabetes—2026.* Diabetes Care 2026;49(Suppl 1):S132-S149. [doi:10.2337/dc26-S006](https://doi.org/10.2337/dc26-S006), [PMC12690178](https://pmc.ncbi.nlm.nih.gov/articles/PMC12690178) |
| Metas en embarazo (ayuno < 95, 1 h < 140, 2 h < 120; HbA1c < 6 %; sensor 63 a 140 con TIR > 70 %, TBR < 4 % y < 1 %, TAR < 25 %) | American Diabetes Association Professional Practice Committee. *15. Management of Diabetes in Pregnancy: Standards of Care in Diabetes—2026.* Diabetes Care 2026;49(Suppl 1):S321-S338. [doi:10.2337/dc26-S015](https://doi.org/10.2337/dc26-S015), [PMC12690181](https://pmc.ncbi.nlm.nih.gov/articles/PMC12690181) |
| Código LOINC de la HbA1c (4548-4) y de las lecturas de glucosa | [Servidor de terminología FHIR R4, tx.fhir.org](https://tx.fhir.org/r4/) (búsqueda del código en el sistema `http://loinc.org`) |

Puntos **no verificados** textualmente en las fuentes accesibles y que se tratan como supuestos de diseño (configurables):

- La definición del *episodio* de hipoglucemia de 15 minutos consecutivos y su criterio de fin proviene del consenso de 2017 (Danne T, et al., *International Consensus on Use of Continuous Glucose Monitoring*, Diabetes Care 2017;40:1631-1640); en la fuente de 2019 solo se pudo confirmar que el episodio de 15 min aparece como métrica.
- La descripción de los percentiles 5, 25, 50, 75 y 95 del AGP y el suavizado son la práctica de presentación habitual; las fuentes consultadas exigen el perfil de 14 días pero no detallan los percentiles en el texto disponible.
- La frecuencia recomendada de HbA1c y la ecuación IFCC-NGSP son conocimiento clínico estándar que se revisará al implementar la métrica; no se contrastaron en esta redacción.

## 10. Pruebas esperadas

| Prueba | Qué comprueba |
|---|---|
| Suma de franjas | TBR2 + TBR1 + TIR + TAR1 + TAR2 = 100 % (con tolerancia de redondeo) |
| Fórmula GMI | Valores de referencia: media 154 mg/dL, GMI 7.0 % |
| CV | Serie sintética con CV conocido |
| AGP | Percentiles de una serie sintética contra `numpy.percentile` |
| Zonas horarias | Un día que cruza medianoche UTC pero no la local cae en el día local correcto; un día con cambio de horario tiene 23 o 25 horas |
| Suficiencia | 69 % y 70 % de datos en 14 días dan resultados distintos |
| Sin literales | Una prueba de deriva compara los umbrales del código con `care.target_profiles` |
| Perfiles | Cada perfil semilla carga con sus fuentes y versión |
