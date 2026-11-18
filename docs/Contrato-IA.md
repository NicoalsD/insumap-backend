# Contrato entre el backend y el servicio de IA

Este documento define el contrato HTTP entre `insumap-backend` (cliente, `AiServiceClientAdapter`) y `insumap-ai` (servicio). Es la referencia para implementar cualquiera de los dos lados y para escribir las pruebas de contrato. El porqué de cada capacidad está en [Modulo-IA.md](Modulo-IA.md).

Principios:

- `insumap-ai` **no tiene estado** y **no accede a la base de datos**. Recibe datos, devuelve una salida con versión del modelo y explicación.
- El backend decide cuándo pedir, guarda la salida en el esquema `ai` y, si la IA falla, responde con su respaldo por reglas.
- **Minimización:** nunca viajan nombres, documentos, número de historia ni datos de contacto. El paciente se identifica con un seudónimo `subject_ref`.
- Ningún lado confía en el otro: cada uno valida lo que recibe.
- Los parámetros clínicos (umbrales, metas, límites de titulación) llegan en la petición; el servicio no tiene valores clínicos quemados.
- Los identificadores, campos JSON, rutas y códigos de error van en inglés; el `message` de los errores va en español.

> **Aviso:** proyecto académico, no es un dispositivo médico. La IA solo apoya al médico.

## 1. Endpoints

Prefijo del servicio: `/v1`. (El prefijo de la API pública del backend es `/api/v1`; son distintos.)

| Método | Ruta | Autenticación | Caso | Uso |
|---|---|---|---|---|
| POST | `/v1/glucose-forecasts` | Token de servicio | IA1 | Pronóstico de glucosa y riesgo de hipo o hiperglucemia |
| POST | `/v1/risk-assessments` | Token de servicio | IA2, IA7 | Riesgo de deterioro (triage) o de abandono |
| POST | `/v1/pattern-detections` | Token de servicio | IA3 | Patrones y anomalías |
| POST | `/v1/titration-suggestions` | Token de servicio | IA4 | Sugerencia de ajuste de basal |
| POST | `/v1/clinical-summaries` | Token de servicio | IA5 | Resumen clínico previo a la consulta |
| POST | `/v1/assistant-replies` | Token de servicio | IA6 | Respuesta del asistente educativo |
| GET | `/v1/health` | Ninguna | | Vivo (*liveness*). No revela nada del modelo. |
| GET | `/v1/ready` | Ninguna | | Listo para atender (modelos cargados) |
| GET | `/v1/models` | Token de servicio | | Modelos cargados, versiones y estado |

Swagger del servicio (en español) en `/docs`; se apaga con `API_DOCS_ENABLED=false` en producción.

## 2. Autenticación y rotación del token de servicio

### 2.1 Mecanismo

- Cabecera: `Authorization: Bearer <service token>`.
- Al menos 32 bytes aleatorios. Generación recomendada: `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
- Comparación en tiempo constante (`hmac.compare_digest`). Sin valor por defecto: si `AI_SERVICE_TOKEN` falta, el servicio **no arranca**.
- El token nunca aparece en logs; los logs redactan `Authorization`. Los cuerpos de las peticiones **nunca** se registran.
- Token ausente o inválido: `401 INVALID_SERVICE_TOKEN` con `WWW-Authenticate: Bearer`. El cuerpo no dice si el token existe ni cuál falló.
- `/v1/health` y `/v1/ready` no piden token y no devuelven información sensible.

### 2.2 Rotación sin corte (actual y anterior)

El servicio acepta dos tokens: `AI_SERVICE_TOKEN` (actual) y `AI_SERVICE_TOKEN_PREVIOUS` (opcional, el anterior).

| Paso | Dónde | Acción | Resultado |
|---|---|---|---|
| 1 | `insumap-ai` | `AI_SERVICE_TOKEN=<nuevo>` y `AI_SERVICE_TOKEN_PREVIOUS=<viejo>` | El servicio acepta ambos |
| 2 | `insumap-backend` | `AI_SERVICE_TOKEN=<nuevo>` | El backend usa el nuevo |
| 3 | `insumap-ai` | Quitar `AI_SERVICE_TOKEN_PREVIOUS` | Solo queda el nuevo |

El orden es obligatorio: si el paso 2 va antes del 1, el backend recibe `401` y el circuito se abre. Cada rotación queda en `iam.security_events`. Un token filtrado se rota de inmediato con el mismo procedimiento. Los secretos viven solo en variables de entorno.

## 3. Versionado, timeouts y límites

### 3.1 Versionado

- La versión mayor va en la ruta (`/v1`). Dentro de `v1` solo se agregan campos opcionales y valores de enumeraciones; el cliente **ignora campos desconocidos de la respuesta**. El servicio **rechaza campos desconocidos de la petición** (`extra="forbid"`, `422 VALIDATION_ERROR`).
- Un cambio incompatible crea `/v2` y ambas versiones conviven mientras el backend migra. Un cambio de contrato se coordina en el mismo ciclo con `AiServiceClientAdapter`.
- `contract_version` aparece en `GET /v1/models` (por ejemplo `1.0.0`) y en la sección 9.

### 3.2 Timeouts del backend (semilla, variables de entorno)

| Endpoint | Timeout total | Reintentos |
|---|---|---|
| Conexión (todos) | 2 s | 0 |
| `glucose-forecasts` | 5 s | 1 (solo en error de red) |
| `risk-assessments` | 3 s | 1 |
| `pattern-detections` | 5 s | 1 |
| `titration-suggestions` | 3 s | 1 |
| `clinical-summaries` | 30 s | 0 |
| `assistant-replies` | 20 s | 0 |

Son valores iniciales (`AI_TIMEOUT_*_SECONDS`) y se ajustan tras medir (Modulo-IA.md, sección 9). Al agotarse: `fallback_reason = AI_TIMEOUT`.

### 3.3 Límites del servicio

| Límite | Valor semilla | Variable | Error |
|---|---|---|---|
| Puntos máximos en `glucose-forecasts` | 2048 | `MAX_FORECAST_POINTS` | `422 INVALID_SERIES` (`reason = TOO_MANY_POINTS`) |
| Puntos máximos por serie en `pattern-detections` | 4500 (14 días a 5 min son 4032) | `MAX_PATTERN_POINTS` | igual |
| Puntos mínimos para pronosticar | 36 (3 h a 5 min) | `FORECAST_MIN_POINTS` | `INSUFFICIENT_DATA` (ver sección 4.2) |
| Dosis máximas por petición | 500 | `MAX_DOSES` | `422 VALIDATION_ERROR` |
| Fragmentos de contexto máximos (`context_documents`) | 8, de 4000 caracteres cada uno | `MAX_CONTEXT_DOCS` | `422 VALIDATION_ERROR` |
| Largo del mensaje del paciente | 1000 caracteres | `MAX_MESSAGE_CHARS` | `422 VALIDATION_ERROR` |
| Tamaño del cuerpo | 512 KiB | `MAX_BODY_BYTES` | `413 PAYLOAD_TOO_LARGE` |

Son límites técnicos del servicio (variables de entorno); los límites clínicos viajan en la petición.

## 4. Elementos comunes

### 4.1 Cabeceras

| Cabecera | Dirección | Uso |
|---|---|---|
| `Authorization: Bearer <token>` | petición | Token de servicio |
| `X-Request-Id` | petición, respuesta | UUID del backend. El servicio lo devuelve y lo usa en logs (sin cuerpo). Si falta, el servicio genera uno. |
| `Content-Type: application/json` | ambas | Todo es JSON en UTF-8 |

### 4.2 Reglas de datos

- **Glucosa siempre en mg/dL.** Un valor en otra unidad se convierte en el backend antes de enviar.
- **Marcas de tiempo en ISO-8601 con offset** (`2026-11-14T22:05:00-05:00`). Las ventanas nocturnas y matutinas se calculan en `clinic_timezone` (nombre IANA, por ejemplo `America/Bogota`), que el backend envía.
- **`subject_ref`:** seudónimo del paciente, patrón `^sub_[0-9a-f]{32}$`. Lo deriva el backend con HMAC-SHA256 del `patient_id` y una clave por entorno; no es reversible desde el servicio. **Nunca nombres, documentos ni número de historia.** Un mismo paciente conserva su `subject_ref` entre peticiones.
- Los números decimales usan punto. Los campos desconocidos se rechazan.

### 4.3 Campos comunes de la respuesta `200`

Todas las respuestas de los `POST` traen:

| Campo | Tipo | Descripción |
|---|---|---|
| `request_id` | UUID | Eco de `X-Request-Id` |
| `model_name` | texto | Por ejemplo `chronos-bolt-small` o `risk-gbm` |
| `model_version` | texto | `<semver>+<huella>`, por ejemplo `1.2.0+sim1.0.0.seed42`. Para el respaldo: `fallback-linear@1.0.0` |
| `input_hash` | texto | SHA-256 hexadecimal del JSON canónico de la entrada (sin `request_id`) |
| `generated_at` | ISO-8601 con zona | Momento de la inferencia |
| `is_fallback` | booleano | `true` si la salida la produjo un respaldo y no el modelo |
| `fallback_reason` | texto o `null` | Ver sección 5. `null` si `is_fallback = false` |
| `explanation` | objeto | Ver abajo |

Objeto `explanation`:

| Campo | Tipo | Descripción |
|---|---|---|
| `summary` | texto (máx. 500) | Frase en español para el médico |
| `factors[]` | arreglo | `name` (texto), `direction` (`INCREASES_RISK`, `DECREASES_RISK`, `NEUTRAL`), `value` (número o texto), `unit` (texto o `null`), `contribution` (número 0 a 1) |
| `data_refs[]` | arreglo | `kind` (`WINDOW`, `READINGS`, `DOSES`, `METRIC`), `from`, `to` (ISO-8601) y `count` (entero), para enlazar a los datos |

Cuando una salida la genera el servicio como respaldo propio (por ejemplo IA1 con extrapolación lineal), `is_fallback = true` y `fallback_reason = AI_ERROR` o `INSUFFICIENT_DATA`. Si un guardrail del asistente bloquea la salida del LLM, la respuesta usa el texto predefinido, `is_fallback = true`, `fallback_reason = AI_ERROR` y `guardrails_triggered` indica qué eslabón actuó (el bloqueo por política no es un fallo del modelo, pero reutiliza el mismo código para mantener cerrada la enumeración).

## 5. Semántica del respaldo en el backend

El backend nunca deja al usuario sin respuesta por una falla de IA. `RemoteAiServiceProxy` (P11) decide, y `CircuitBreakerState` (P18) cuenta fallos.

| `fallback_reason` | Quién lo produce | Cuándo |
|---|---|---|
| `AI_TIMEOUT` | Backend | El servicio no respondió dentro del timeout (incluye arranque en frío) |
| `CIRCUIT_OPEN` | Backend | El circuito está abierto: no se llama al servicio |
| `AI_ERROR` | Backend o servicio | `5xx`, `503 MODEL_NOT_READY`, `401` (token mal configurado), respuesta inválida o falla interna del modelo o del LLM |
| `INSUFFICIENT_DATA` | Backend o servicio | No hay datos suficientes para el modelo (por ejemplo menos de `FORECAST_MIN_POINTS` o un paciente con SMBG para IA1) |

Cómo reacciona el backend a cada respuesta:

| Respuesta | Reacción | Cuenta como fallo del circuito |
|---|---|---|
| `200` con `is_fallback = false` | Guarda la salida de IA | No |
| `200` con `is_fallback = true` | Guarda la salida marcada como respaldo del servicio | No |
| `401 INVALID_SERVICE_TOKEN` | Respaldo con `AI_ERROR`; alerta operativa (token mal configurado) | Sí |
| `413`, `422` | Respaldo con `AI_ERROR` (un error de contrato es un defecto del backend); log sin cuerpo | No |
| `503 MODEL_NOT_READY` | Respaldo con `AI_ERROR` | Sí |
| `5xx`, error de red | Respaldo con `AI_ERROR` (reintento si aplica) | Sí |
| Timeout | Respaldo con `AI_TIMEOUT` | Sí |

Circuit breaker (semilla, variables de entorno): se abre con 5 fallos consecutivos o 50 % de fallos en 60 s (mínimo 10 llamadas); permanece abierto 30 s; luego `HALF_OPEN` deja pasar 1 llamada de prueba. Si tiene éxito, `CLOSED`; si falla, vuelve a `OPEN`. El estado vive en memoria del proceso del backend.

El backend guarda siempre `is_fallback`, `fallback_reason`, `model_version` e `input_hash` junto a la salida. El dashboard (M10) muestra el porcentaje de respaldo y marca cada salida de respaldo con "Calculado con reglas".

## 6. Idempotencia y ausencia de estado

- Todos los `POST` son **funciones de la entrada**: no crean recursos ni guardan nada. Repetir una petición es seguro (no hace falta `Idempotency-Key`). Con la misma entrada y el mismo `model_version`, IA1 a IA4 e IA7 devuelven la misma salida; IA5 e IA6 usan temperatura 0 y no garantizan igualdad textual.
- `input_hash` permite al backend detectar una entrada repetida y reutilizar la salida guardada sin llamar de nuevo.
- Dos peticiones concurrentes no se afectan. No hay sesión, ni cookies, ni memoria de conversación en el servicio: la conversación del asistente viaja completa (`history[]`) en cada petición.
- `CachingForecaster` (P09) puede cachear internamente por `input_hash`; es una optimización invisible para el contrato.

## 7. Errores

Formato único:

```json
{
  "error": {
    "code": "INVALID_SERIES",
    "message": "La serie tiene marcas de tiempo repetidas.",
    "details": { "reason": "TIMESTAMPS_NOT_INCREASING" }
  },
  "request_id": "0192f4b2-7c1a-7d00-8a31-5e9f0c2b6a10"
}
```

`code` en inglés, `message` en español, sin datos del paciente ni de la entrada.

| HTTP | `code` | Cuándo | `details` |
|---|---|---|---|
| 401 | `INVALID_SERVICE_TOKEN` | Token ausente o inválido | Ninguno |
| 413 | `PAYLOAD_TOO_LARGE` | Cuerpo mayor que `MAX_BODY_BYTES` | `max_bytes` |
| 422 | `VALIDATION_ERROR` | Esquema inválido, campo desconocido, tipo o rango incorrecto | `fields[]` con `path` y `reason` |
| 422 | `INVALID_SERIES` | Serie de glucosa inválida | `reason`: `LENGTH_MISMATCH`, `TIMESTAMPS_NOT_INCREASING`, `TIMESTAMP_PARSE_ERROR`, `NOT_FINITE_VALUE`, `VALUE_OUT_OF_RANGE`, `TOO_MANY_POINTS`, `INVALID_INTERVAL` |
| 503 | `MODEL_NOT_READY` | El modelo aún carga o falló al cargar | `retry_after_seconds` (y cabecera `Retry-After`) |
| 500 | `INTERNAL_ERROR` | Error no previsto | Ninguno |

Los datos insuficientes **no** son un error HTTP: se responden con `200`, `is_fallback = true` y `fallback_reason = INSUFFICIENT_DATA`, para que el backend trate todo respaldo igual. `VALUE_OUT_OF_RANGE` aplica a glucosa fuera de un rango físicamente posible configurado en el servicio (`GLUCOSE_PLAUSIBLE_MIN` y `GLUCOSE_PLAUSIBLE_MAX`, límites técnicos de sensor, no metas clínicas).

## 8. Endpoints de inferencia

Los ejemplos usan datos simulados y valores ilustrativos. No son predicciones reales.

### 8.1 `POST /v1/glucose-forecasts` (IA1)

**Petición**

| Campo | Tipo | Regla |
|---|---|---|
| `subject_ref` | texto | Seudónimo (sección 4.2) |
| `mode` | enum | `SHORT_TERM` (horizontes en minutos) u `OVERNIGHT` (hasta el fin de la ventana nocturna) |
| `series.timestamps` | arreglo de ISO-8601 con offset | Estrictamente crecientes; máximo `MAX_FORECAST_POINTS` |
| `series.values_mg_dl` | arreglo de número | Mismo largo; finitos |
| `series.interval_minutes` | entero | `5` o `15` (el intervalo nominal del sensor; los huecos se envían tal cual) |
| `horizons_minutes` | arreglo de entero | Solo `SHORT_TERM`: cada uno entre 5 y 120; máximo 6 elementos |
| `quantile_levels` | arreglo de número | Exactamente `[0.1, 0.5, 0.9]` en v1 |
| `thresholds.low_mg_dl` | número | Umbral de hipoglucemia del perfil de metas |
| `thresholds.high_mg_dl` | número | Umbral de hiperglucemia del perfil de metas |
| `clinic_timezone` | texto IANA | Para la ventana nocturna |
| `night_window` | objeto | `start` y `end` en `HH:MM` local (por ejemplo `00:00` y `06:00`), de la configuración de la clínica |

```json
{
  "subject_ref": "sub_5f2c8e7a9b1d4c3e8a6f0d2b7c9e1a43",
  "mode": "SHORT_TERM",
  "series": {
    "timestamps": [
      "2026-11-14T21:30:00-05:00", "2026-11-14T21:35:00-05:00",
      "2026-11-14T21:40:00-05:00", "2026-11-14T21:45:00-05:00"
    ],
    "values_mg_dl": [128.0, 121.0, 113.0, 108.0],
    "interval_minutes": 5
  },
  "horizons_minutes": [30, 60, 120],
  "quantile_levels": [0.1, 0.5, 0.9],
  "thresholds": { "low_mg_dl": 70, "high_mg_dl": 180 },
  "clinic_timezone": "America/Bogota",
  "night_window": { "start": "00:00", "end": "06:00" }
}
```

(El ejemplo abrevia la serie a 4 puntos; en producción son al menos `FORECAST_MIN_POINTS`.)

**Respuesta `200`** (campos comunes de 4.3 más):

| Campo | Tipo | Descripción |
|---|---|---|
| `trend` | enum | `FALLING`, `STABLE`, `RISING` |
| `points[]` | arreglo | `horizon_minutes`, `timestamp`, `p10`, `p50`, `p90` (mg/dL, con `p10 <= p50 <= p90`) |
| `risk.hypo_probability[]` | arreglo | Por horizonte: `horizon_minutes` y `probability` (0 a 1) de quedar bajo `low_mg_dl` |
| `risk.hyper_probability[]` | arreglo | Igual, sobre `high_mg_dl` |

La probabilidad se aproxima por interpolación de los cuantiles; es una estimación, no una probabilidad calibrada. Si el modelo devuelve cuantiles cruzados, el servicio los reordena.

```json
{
  "request_id": "0192f4b2-7c1a-7d00-8a31-5e9f0c2b6a10",
  "model_name": "chronos-bolt-small",
  "model_version": "2.3.2+chronos-bolt-small",
  "input_hash": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
  "generated_at": "2026-11-14T21:46:02-05:00",
  "is_fallback": false,
  "fallback_reason": null,
  "trend": "FALLING",
  "points": [
    { "horizon_minutes": 30, "timestamp": "2026-11-14T22:15:00-05:00", "p10": 74.0, "p50": 92.0, "p90": 108.0 },
    { "horizon_minutes": 60, "timestamp": "2026-11-14T22:45:00-05:00", "p10": 61.0, "p50": 84.0, "p90": 106.0 },
    { "horizon_minutes": 120, "timestamp": "2026-11-14T23:45:00-05:00", "p10": 55.0, "p50": 82.0, "p90": 112.0 }
  ],
  "risk": {
    "hypo_probability": [
      { "horizon_minutes": 30, "probability": 0.06 },
      { "horizon_minutes": 60, "probability": 0.21 },
      { "horizon_minutes": 120, "probability": 0.27 }
    ],
    "hyper_probability": [
      { "horizon_minutes": 30, "probability": 0.0 },
      { "horizon_minutes": 60, "probability": 0.0 },
      { "horizon_minutes": 120, "probability": 0.01 }
    ]
  },
  "explanation": {
    "summary": "Glucosa en descenso de 128 a 108 mg/dL en 15 minutos; en 60 minutos el rango probable es 61 a 106 mg/dL.",
    "factors": [
      { "name": "recent_slope", "direction": "INCREASES_RISK", "value": -1.3, "unit": "mg/dL/min", "contribution": 0.7 },
      { "name": "latest_value", "direction": "NEUTRAL", "value": 108.0, "unit": "mg/dL", "contribution": 0.3 }
    ],
    "data_refs": [{ "kind": "READINGS", "from": "2026-11-14T21:30:00-05:00", "to": "2026-11-14T21:45:00-05:00", "count": 4 }]
  }
}
```

Respaldo propio del servicio: extrapolación lineal de la tasa de cambio de los últimos 30 min; `model_version = fallback-linear@1.0.0`, `is_fallback = true`.

### 8.2 `POST /v1/risk-assessments` (IA2 e IA7)

**Petición**

| Campo | Tipo | Regla |
|---|---|---|
| `subject_ref` | texto | Seudónimo |
| `assessment_type` | enum | `DETERIORATION` (IA2) o `DROPOUT` (IA7) |
| `window_days` | entero | Ventana de las características (por ejemplo 14), entre 7 y 90 |
| `diabetes_type` | enum | `T1D`, `T2D`, `GESTATIONAL` |
| `features` | objeto | Ver abajo; todos los campos son opcionales con `null` si no hay dato, salvo `data_sufficiency_pct` |

`features` para `DETERIORATION` (calculadas por el backend en M7):

| Campo | Unidad |
|---|---|
| `tir_pct`, `tbr_l1_pct`, `tbr_l2_pct`, `tar_l1_pct`, `tar_l2_pct` | % |
| `mean_glucose_mg_dl`, `gmi_pct`, `cv_pct` | mg/dL, %, % |
| `data_sufficiency_pct` | % de datos CGM de la ventana |
| `hypo_events_count`, `severe_hypo_events_count` | conteos |
| `last_hba1c_pct`, `hba1c_delta_pct` | % |
| `tir_delta_vs_prior_pct` | puntos porcentuales frente al periodo anterior |
| `readings_per_day_avg`, `days_since_last_reading`, `open_alerts_count` | conteos |
| `target_tir_pct` | meta del perfil (para contexto del modelo) |

`features` para `DROPOUT`: `weekly_reading_counts[]` (últimas 8 semanas, más antigua primero), `days_since_last_reading`, `dose_logging_pct`, `app_opens_last_14d`, `unanswered_messages_count`, `account_age_days`.

```json
{
  "subject_ref": "sub_5f2c8e7a9b1d4c3e8a6f0d2b7c9e1a43",
  "assessment_type": "DETERIORATION",
  "window_days": 14,
  "diabetes_type": "T1D",
  "features": {
    "tir_pct": 48.2, "tbr_l1_pct": 5.9, "tbr_l2_pct": 1.8, "tar_l1_pct": 30.1, "tar_l2_pct": 14.0,
    "mean_glucose_mg_dl": 176.0, "gmi_pct": 7.5, "cv_pct": 41.3, "data_sufficiency_pct": 92.0,
    "hypo_events_count": 6, "severe_hypo_events_count": 0,
    "last_hba1c_pct": 8.1, "hba1c_delta_pct": 0.6, "tir_delta_vs_prior_pct": -17.0,
    "readings_per_day_avg": 270, "days_since_last_reading": 0, "open_alerts_count": 3, "target_tir_pct": 70
  }
}
```

**Respuesta `200`** (campos comunes más):

| Campo | Tipo | Descripción |
|---|---|---|
| `assessment_type` | enum | Eco |
| `risk_probability` | número 0 a 1 | Calibrada (modelo) o puntaje de reglas (respaldo; ver `calibrated`) |
| `calibrated` | booleano | `false` en el respaldo por reglas |
| `risk_tier` | enum | `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`, según los cortes de la ficha del modelo (`GET /v1/models`) |

```json
{
  "request_id": "0192f4b3-1a20-7e11-9c4d-6a1b2c3d4e5f",
  "model_name": "risk-gbm",
  "model_version": "0.3.0+sim1.0.0.seed42",
  "input_hash": "2c26b46b68ffc68ff99b453c1d30413413422d706483bfa0f98a5e886266e7ae",
  "generated_at": "2026-11-15T06:00:04-05:00",
  "is_fallback": false,
  "fallback_reason": null,
  "assessment_type": "DETERIORATION",
  "risk_probability": 0.64,
  "calibrated": true,
  "risk_tier": "HIGH",
  "explanation": {
    "summary": "Riesgo alto: el TIR cayó 17 puntos frente al periodo anterior y hubo 6 episodios de hipoglucemia en 14 días.",
    "factors": [
      { "name": "tir_delta_vs_prior_pct", "direction": "INCREASES_RISK", "value": -17.0, "unit": "pp", "contribution": 0.38 },
      { "name": "hypo_events_count", "direction": "INCREASES_RISK", "value": 6, "unit": null, "contribution": 0.31 },
      { "name": "data_sufficiency_pct", "direction": "DECREASES_RISK", "value": 92.0, "unit": "%", "contribution": 0.08 }
    ],
    "data_refs": [{ "kind": "WINDOW", "from": "2026-11-01T00:00:00-05:00", "to": "2026-11-14T23:59:59-05:00", "count": 3780 }]
  }
}
```

Con `data_sufficiency_pct` menor que el mínimo del perfil (por defecto 70), `DETERIORATION` responde `INSUFFICIENT_DATA`. El respaldo del backend es `RuleBasedRiskStrategy` (tipo TIDE); si el respaldo lo emite el servicio, `calibrated = false`.

### 8.3 `POST /v1/pattern-detections` (IA3)

**Petición**

| Campo | Tipo | Regla |
|---|---|---|
| `subject_ref` | texto | Seudónimo |
| `period.from`, `period.to` | ISO-8601 con offset | Hasta 14 días |
| `series` | objeto | Igual que en 8.1 (`timestamps`, `values_mg_dl`, `interval_minutes`); máximo `MAX_PATTERN_POINTS`. Para SMBG se envía `interval_minutes = null` |
| `source` | enum | `CGM` o `SMBG` |
| `doses[]` | arreglo | `timestamp`, `insulin_kind` (`BASAL`, `BOLUS`, `MIXED`), `units` (número), `source` (`MANUAL`, `PEN_REPORTED`) |
| `expected_doses_per_day` | entero o `null` | Del plan activo |
| `meals[]` | arreglo | `timestamp`, `carbs_g` (número o `null`) |
| `thresholds` | objeto | `low_mg_dl`, `high_mg_dl`, `very_low_mg_dl` del perfil de metas |
| `clinic_timezone`, `night_window` | | Igual que en 8.1 |
| `detectors` | arreglo de enum o `null` | Opcional: subconjunto de tipos a evaluar |

```json
{
  "subject_ref": "sub_5f2c8e7a9b1d4c3e8a6f0d2b7c9e1a43",
  "period": { "from": "2026-11-08T00:00:00-05:00", "to": "2026-11-14T23:59:59-05:00" },
  "source": "CGM",
  "series": { "timestamps": ["2026-11-14T03:00:00-05:00", "2026-11-14T03:05:00-05:00"], "values_mg_dl": [62.0, 58.0], "interval_minutes": 5 },
  "doses": [{ "timestamp": "2026-11-13T22:00:00-05:00", "insulin_kind": "BASAL", "units": 24.0, "source": "MANUAL" }],
  "expected_doses_per_day": 1,
  "meals": [],
  "thresholds": { "low_mg_dl": 70, "high_mg_dl": 180, "very_low_mg_dl": 54 },
  "clinic_timezone": "America/Bogota",
  "night_window": { "start": "00:00", "end": "06:00" },
  "detectors": null
}
```

**Respuesta `200`** (campos comunes más `findings[]`; `findings` puede venir vacío):

| Campo de `findings[]` | Tipo | Descripción |
|---|---|---|
| `pattern_type` | enum | `NOCTURNAL_HYPOGLYCEMIA`, `DAWN_PHENOMENON`, `POSTPRANDIAL_SPIKE`, `MISSED_DOSE`, `DUPLICATE_DOSE`, `ADHERENCE_DROP`, `IMPLAUSIBLE_READING` |
| `window.from`, `window.to` | ISO-8601 | Periodo del hallazgo |
| `confidence` | número 0 a 1 | Confianza del detector |
| `severity` | enum | `INFO`, `WARNING`, `CRITICAL` (según los umbrales enviados) |
| `evidence` | objeto | Datos del hallazgo, por ejemplo `nights_affected`, `nights_observed`, `min_mg_dl` |
| `explanation` | objeto | Mismo formato que en 4.3 |

```json
{
  "request_id": "0192f4b4-0b12-7f00-8d10-3a4b5c6d7e8f",
  "model_name": "pattern-detectors",
  "model_version": "0.2.0+sim1.0.0.seed42",
  "input_hash": "fcde2b2edba56bf408601fb721fe9b5c338d10ee429ea04fae5511b68fbf8fb9",
  "generated_at": "2026-11-15T06:00:09-05:00",
  "is_fallback": false,
  "fallback_reason": null,
  "findings": [
    {
      "pattern_type": "NOCTURNAL_HYPOGLYCEMIA",
      "window": { "from": "2026-11-08T00:00:00-05:00", "to": "2026-11-14T06:00:00-05:00" },
      "confidence": 0.88,
      "severity": "WARNING",
      "evidence": { "nights_affected": 4, "nights_observed": 7, "min_mg_dl": 58.0 },
      "explanation": {
        "summary": "4 de 7 noches con glucosa por debajo de 70 mg/dL entre las 00:00 y las 06:00; la más baja, 58 mg/dL.",
        "factors": [{ "name": "nights_below_threshold_ratio", "direction": "INCREASES_RISK", "value": 0.57, "unit": null, "contribution": 1.0 }],
        "data_refs": [{ "kind": "WINDOW", "from": "2026-11-08T00:00:00-05:00", "to": "2026-11-14T06:00:00-05:00", "count": 2016 }]
      }
    }
  ]
}
```

### 8.4 `POST /v1/titration-suggestions` (IA4)

**Petición**

| Campo | Tipo | Regla |
|---|---|---|
| `subject_ref` | texto | Seudónimo |
| `insulin_kind` | enum | `BASAL` (solo basal en v1) |
| `current_dose_units` | número | Dosis basal vigente del plan |
| `fasting_glucose[]` | arreglo | `date` (fecha local), `value_mg_dl`, `source` (`CGM`, `SMBG`); entre 3 y 14 elementos |
| `recent_hypo_events[]` | arreglo | `timestamp`, `min_mg_dl`, `level` (1, 2 o 3) |
| `last_adjustment_date` | fecha o `null` | |
| `protocol` | objeto | Del plan o plantilla: `fasting_target_low_mg_dl`, `fasting_target_high_mg_dl`, `step_units`, `max_change_units`, `min_days_between_adjustments`, `decrease_on_hypo_level` |

```json
{
  "subject_ref": "sub_5f2c8e7a9b1d4c3e8a6f0d2b7c9e1a43",
  "insulin_kind": "BASAL",
  "current_dose_units": 24.0,
  "fasting_glucose": [
    { "date": "2026-11-12", "value_mg_dl": 168, "source": "CGM" },
    { "date": "2026-11-13", "value_mg_dl": 172, "source": "CGM" },
    { "date": "2026-11-14", "value_mg_dl": 160, "source": "CGM" }
  ],
  "recent_hypo_events": [],
  "last_adjustment_date": "2026-11-01",
  "protocol": {
    "fasting_target_low_mg_dl": 80, "fasting_target_high_mg_dl": 130,
    "step_units": 2.0, "max_change_units": 4.0, "min_days_between_adjustments": 3,
    "decrease_on_hypo_level": 2
  }
}
```

**Respuesta `200`** (campos comunes más):

| Campo | Tipo | Descripción |
|---|---|---|
| `suggestion.action` | enum | `INCREASE`, `DECREASE`, `MAINTAIN`, `NO_SUGGESTION` |
| `suggestion.current_dose_units` | número | Eco |
| `suggestion.proposed_dose_units` | número o `null` | `null` si `NO_SUGGESTION` |
| `suggestion.delta_units` | número o `null` | Nunca mayor que `max_change_units` en valor absoluto |
| `suggestion.rule_id` | texto | Regla de titulación aplicada |
| `requires_doctor_approval` | booleano | **Siempre `true`** |

```json
{
  "request_id": "0192f4b5-5c31-7a22-9b01-1d2e3f4a5b6c",
  "model_name": "titration-rules",
  "model_version": "0.1.0",
  "input_hash": "a3f5c1e9b7d24680fedcba9876543210a3f5c1e9b7d24680fedcba9876543210",
  "generated_at": "2026-11-15T06:00:11-05:00",
  "is_fallback": false,
  "fallback_reason": null,
  "suggestion": {
    "action": "INCREASE",
    "current_dose_units": 24.0,
    "proposed_dose_units": 26.0,
    "delta_units": 2.0,
    "rule_id": "FASTING_ABOVE_TARGET_NO_HYPO"
  },
  "requires_doctor_approval": true,
  "explanation": {
    "summary": "Ayunos de 168, 172 y 160 mg/dL sobre la meta de 80 a 130 mg/dL y sin hipoglucemias recientes.",
    "factors": [
      { "name": "fasting_median_mg_dl", "direction": "INCREASES_RISK", "value": 168, "unit": "mg/dL", "contribution": 0.8 },
      { "name": "recent_hypo_events", "direction": "DECREASES_RISK", "value": 0, "unit": null, "contribution": 0.2 }
    ],
    "data_refs": [{ "kind": "READINGS", "from": "2026-11-12T00:00:00-05:00", "to": "2026-11-14T23:59:59-05:00", "count": 3 }]
  }
}
```

Respaldo: `suggestion.action = NO_SUGGESTION`, `is_fallback = true`. El backend crea una `Recommendation` en `PROPOSED` solo si la acción no es `NO_SUGGESTION` ni `MAINTAIN`, y nunca la muestra al paciente antes de `APPLIED`. La dosis propuesta se valida otra vez en el backend contra el protocolo del plan.

### 8.5 `POST /v1/clinical-summaries` (IA5)

**Petición**

| Campo | Tipo | Regla |
|---|---|---|
| `subject_ref` | texto | Seudónimo |
| `period.from`, `period.to` | ISO-8601 con offset | |
| `language` | enum | `es` |
| `diabetes_type` | enum | `T1D`, `T2D`, `GESTATIONAL` |
| `metrics` | objeto | `tir_pct`, `tbr_l1_pct`, `tbr_l2_pct`, `tar_l1_pct`, `tar_l2_pct`, `mean_glucose_mg_dl`, `gmi_pct`, `cv_pct`, `data_sufficiency_pct`, `agp_percentiles[]` (por hora local: `hour`, `p5`, `p25`, `p50`, `p75`, `p95`) |
| `targets` | objeto | Metas del perfil activo (`tir_target_pct` etc.), para comparar |
| `events[]` | arreglo | `ref_id` (texto), `kind` (`HYPOGLYCEMIA`, `PATTERN`, `ALERT`, `SYMPTOM`), `timestamp`, `detail` (texto corto sin datos personales) |
| `adherence` | objeto | `readings_per_day_avg`, `dose_logging_pct` |
| `plan_changes[]` | arreglo | `ref_id`, `date`, `description` |
| `last_hba1c` | objeto o `null` | `value_pct`, `date` |

La petición **no** contiene nombres ni documentos; los textos libres (`detail`, `description`) se redactan en el backend y de nuevo en el servicio (`PhiRedactingTextGenerator`).

**Respuesta `200`** (campos comunes más):

| Campo | Tipo | Descripción |
|---|---|---|
| `summary_text` | texto plano | Narrativa completa en español |
| `sections[]` | arreglo | `title`, `text`, `refs[]` (cada una con un `ref_id` de la entrada o una métrica) |
| `numeric_check` | objeto | `numbers_in_text`, `numbers_matched`, `all_matched` (booleano): validación de fidelidad numérica |

```json
{
  "request_id": "0192f4b6-9a40-7b33-8e02-2e3f4a5b6c7d",
  "model_name": "clinical-summary-llm",
  "model_version": "0.1.0+prompt-v3",
  "input_hash": "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9",
  "generated_at": "2026-11-15T06:00:30-05:00",
  "is_fallback": false,
  "fallback_reason": null,
  "summary_text": "En los últimos 14 días el tiempo en rango fue 48,2 %, por debajo de la meta de 70 %. Hubo 6 episodios de hipoglucemia, concentrados en la madrugada.",
  "sections": [
    { "title": "Resumen del periodo", "text": "TIR 48,2 % (meta 70 %). GMI 7,5 %.", "refs": ["metric:tir_pct", "metric:gmi_pct"] },
    { "title": "Eventos", "text": "6 episodios de hipoglucemia, 4 entre las 00:00 y las 06:00.", "refs": ["evt-0042", "evt-0047"] }
  ],
  "numeric_check": { "numbers_in_text": 6, "numbers_matched": 6, "all_matched": true },
  "explanation": {
    "summary": "Resumen generado solo con las cifras recibidas; todas las cifras coinciden con la entrada.",
    "factors": [],
    "data_refs": [{ "kind": "WINDOW", "from": "2026-11-01T00:00:00-05:00", "to": "2026-11-14T23:59:59-05:00", "count": 3780 }]
  }
}
```

Si `numeric_check.all_matched = false`, el servicio descarta el texto y responde con la plantilla determinista (`is_fallback = true`, `fallback_reason = AI_ERROR`).

### 8.6 `POST /v1/assistant-replies` (IA6)

**Petición**

| Campo | Tipo | Regla |
|---|---|---|
| `subject_ref` | texto | Seudónimo |
| `message` | texto | Mensaje del paciente, máximo `MAX_MESSAGE_CHARS` |
| `history[]` | arreglo | Hasta 10 turnos: `role` (`PATIENT`, `ASSISTANT`) y `text` |
| `context_documents[]` | arreglo | Material aprobado por la clínica recuperado por el backend: `doc_id`, `title`, `text`; máximo `MAX_CONTEXT_DOCS` |
| `language` | enum | `es` |

El mensaje puede traer datos personales que el paciente escribió. Los redacta el primer eslabón de la cadena (Modulo-IA.md, sección 7).

```json
{
  "subject_ref": "sub_5f2c8e7a9b1d4c3e8a6f0d2b7c9e1a43",
  "message": "¿Qué hago si me siento tembloroso y con sudor frío?",
  "history": [],
  "context_documents": [
    { "doc_id": "doc-hipo-01", "title": "Qué es la hipoglucemia", "text": "La hipoglucemia es una glucosa baja. Los síntomas incluyen temblor, sudor y mareo. Mide tu glucosa y avisa a tu equipo." }
  ],
  "language": "es"
}
```

**Respuesta `200`** (campos comunes más):

| Campo | Tipo | Descripción |
|---|---|---|
| `reply_text` | texto plano | Respuesta en español, sin dosis ni diagnósticos |
| `citations[]` | arreglo | `doc_id` de los documentos usados |
| `escalation.level` | enum | `NONE`, `CONTACT_DOCTOR`, `EMERGENCY` |
| `escalation.message` | texto o `null` | Mensaje de escalamiento mostrado al paciente |
| `guardrails_triggered[]` | arreglo | Eslabones que actuaron: `PHI_REDACTION`, `DOSE_AND_DIAGNOSIS`, `EMERGENCY_SYMPTOM`, `OFF_TOPIC` |

```json
{
  "request_id": "0192f4b7-2c50-7c44-9f03-3f4a5b6c7d8e",
  "model_name": "assistant-llm",
  "model_version": "0.1.0+prompt-v2",
  "input_hash": "6b86b273ff34fce19d6b804eff5a3f5747ada4eaa22f1d49c01e52ddb7875b4b",
  "generated_at": "2026-11-15T10:12:44-05:00",
  "is_fallback": false,
  "fallback_reason": null,
  "reply_text": "Esos síntomas pueden indicar una glucosa baja. Si puedes, mide tu glucosa ahora y avisa a tu equipo de atención. Si te sientes confundido o no puedes tragar, pide ayuda de inmediato o llama a emergencias.",
  "citations": ["doc-hipo-01"],
  "escalation": { "level": "CONTACT_DOCTOR", "message": "Avisaremos a tu equipo de atención. Si empeoras, acude a urgencias." },
  "guardrails_triggered": [],
  "explanation": { "summary": "Respuesta basada en el material aprobado 'Qué es la hipoglucemia'.", "factors": [], "data_refs": [] }
}
```

Reglas de salida: el servicio garantiza (con prueba) que `reply_text` no contiene dosis ni diagnósticos; ante síntomas de alarma, `escalation.level` es `EMERGENCY` o `CONTACT_DOCTOR` y el backend avisa al médico. Con un bloqueo, `reply_text` es el texto predefinido, `is_fallback = true`, `fallback_reason = AI_ERROR`.

## 9. Salud, disponibilidad y modelos

### 9.1 `GET /v1/health`

Siempre `200` si el proceso vive, sin autenticación y sin detalle: `{ "status": "ok" }`.

### 9.2 `GET /v1/ready`

`200 { "status": "ready" }` cuando los modelos están cargados. Mientras cargan (arranque en frío) o si fallaron: `503 { "status": "not_ready" }` con `Retry-After`. No pide token ni revela nada sensible.

### 9.3 `GET /v1/models`

Requiere token. Lista los modelos y su estado:

```json
{
  "contract_version": "1.0.0",
  "provider_family": "offline",
  "models": [
    {
      "name": "chronos-bolt-small", "version": "2.3.2+chronos-bolt-small", "capability": "glucose-forecasts",
      "status": "READY", "loaded_at": "2026-11-15T05:58:00-05:00"
    },
    {
      "name": "risk-gbm", "version": "0.3.0+sim1.0.0.seed42", "capability": "risk-assessments",
      "status": "READY", "loaded_at": "2026-11-15T05:58:01-05:00",
      "risk_tier_cutoffs": { "medium": 0.2, "high": 0.5, "critical": 0.8 },
      "training": { "simulator_version": "1.0.0", "seed": 42 }
    }
  ]
}
```

`status`: `READY`, `LOADING`, `FAILED`. `provider_family`: `openai_compatible` u `offline`. No se devuelven claves ni la URL del LLM.

## 10. Variables de entorno

### 10.1 Backend

| Variable | Descripción |
|---|---|
| `AI_SERVICE_URL` | URL base del servicio (sin `/v1`) |
| `AI_SERVICE_TOKEN` | Token de servicio. Sin valor por defecto |
| `AI_TIMEOUT_CONNECT_SECONDS`, `AI_TIMEOUT_*_SECONDS` | Timeouts de la sección 3.2 |
| `AI_CIRCUIT_FAILURE_THRESHOLD`, `AI_CIRCUIT_OPEN_SECONDS` | Circuit breaker |
| `AI_ENABLED` | Si es `false`, el backend usa siempre el respaldo (`CIRCUIT_OPEN`) |

### 10.2 Servicio de IA

| Variable | Descripción |
|---|---|
| `AI_SERVICE_TOKEN`, `AI_SERVICE_TOKEN_PREVIOUS` | Tokens actual y anterior (mínimo 32 bytes) |
| `AI_PROVIDER_FAMILY` | `openai_compatible` u `offline`. Elige la familia de `AiProviderFactory` |
| `CHRONOS_MODEL_ID` | `amazon/chronos-bolt-tiny` o `amazon/chronos-bolt-small` |
| `MODEL_ARTIFACT_DIR` | Carpeta de los modelos de scikit-learn y sus `model_card.json` |
| `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` | **Únicas** variables del LLM. Proveedor compatible con OpenAI, elegido en la Fase 10 |
| `LLM_TIMEOUT_SECONDS` | Timeout de la llamada al LLM (menor que el del backend) |
| `MAX_BODY_BYTES`, `MAX_FORECAST_POINTS`, `MAX_PATTERN_POINTS`, `FORECAST_MIN_POINTS`, `MAX_DOSES`, `MAX_CONTEXT_DOCS`, `MAX_MESSAGE_CHARS` | Límites de la sección 3.3 |
| `GLUCOSE_PLAUSIBLE_MIN`, `GLUCOSE_PLAUSIBLE_MAX` | Rango físico del sensor |
| `API_DOCS_ENABLED` | Swagger |

Todas se documentan en `.env.example` de cada repo; las que son secretos no tienen valor por defecto.

## 11. Pruebas de contrato

| Prueba | Lado | Qué verifica |
|---|---|---|
| Esquema de cada endpoint | Servicio | Respuestas validan contra los modelos Pydantic y los ejemplos de este documento |
| Rechazo de campos desconocidos | Servicio | `422 VALIDATION_ERROR` |
| Token | Servicio | Ausente, inválido, actual y anterior |
| Ningún dato personal en los logs | Servicio | Los cuerpos no se registran |
| Cada `fallback_reason` | Backend | El proxy produce el motivo correcto con un servicio simulado (timeout, circuito abierto, `5xx`, datos insuficientes) |
| Igualdad de formato del respaldo | Backend | La salida de respaldo tiene la misma forma que la de IA |
| Dosis nunca al paciente | Backend | Una `Recommendation` en `PROPOSED` no aparece en ninguna respuesta del rol `PATIENT` |
| Contrato compartido | Ambos | Los ejemplos JSON de este documento se usan como fixtures en los dos repos |

## 12. Historial del contrato

| Versión | Cambios |
|---|---|
| 1.0.0 | Versión inicial: seis endpoints de inferencia, salud y modelos |
