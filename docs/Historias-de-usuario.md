# Historias de usuario

Este documento define 56 historias de usuario (HU-01 a HU-56), agrupadas por módulo (M1 a M13). Cada historia tiene actor, enunciado, prioridad, fase del plan, requisitos relacionados y criterios de aceptación en formato Dado/Cuando/Entonces. Los requisitos están en [Requerimientos.md](Requerimientos.md) y los permisos en [Actores-y-permisos.md](Actores-y-permisos.md).

> **Aviso:** Insumap es un proyecto académico, no es un dispositivo médico y la IA solo apoya al médico. Los pacientes son simulados.

## Convenciones

- **Prioridad:** `MVP` (fases 1 a 9 y `backfill`) o `Post-MVP` (fases 10 a 12).
- **Fase:** fase del plan en la que se construye (ver [Roles-y-planeacion.md](Roles-y-planeacion.md)).
- **Requisitos:** `RF-xx` y `RNF-xx` de [Requerimientos.md](Requerimientos.md).
- **Valores:** los umbrales, metas y duraciones de los ejemplos son semillas de configuración, no constantes del código.
- **Códigos de error:** `UPPER_SNAKE_CASE` en inglés; el mensaje al usuario va en español. Formato: `{"error":{"code":"...","message":"...","details":{},"request_id":"..."}}`.

| Código | Significado | HTTP |
|---|---|---|
| `INVALID_CREDENTIALS` | Correo o contraseña incorrectos (mensaje genérico). | 401 |
| `UNAUTHORIZED` | Token ausente, vencido o inválido. | 401 |
| `FORBIDDEN` | El rol no tiene el permiso. | 403 |
| `MFA_REQUIRED` | El personal debe completar el MFA. | 403 |
| `ACCOUNT_NOT_ACTIVE` | La cuenta no está `ACTIVE`. | 403 |
| `CONSENT_REQUIRED` | Falta un consentimiento vigente. | 403 |
| `NOT_FOUND` | El recurso no existe, es de otra clínica o el paciente no está asignado. | 404 |
| `CONFLICT` | Duplicado o conflicto de estado. | 409 |
| `INVALID_STATE_TRANSITION` | Transición de estado no permitida. | 409 |
| `INVITATION_INVALID` | Código de activación usado, vencido, revocado o reemplazado. | 410 |
| `VALIDATION_ERROR` | Un campo no cumple sus límites; `details` indica el campo. | 400 |
| `REASON_REQUIRED` | Falta el motivo (10 a 500 caracteres). | 422 |
| `GLUCOSE_OUT_OF_RANGE` | Valor de glucosa fuera del rango fisiológico configurado. | 422 |
| `RATE_LIMITED` | Se superó un límite de tasa; incluye `Retry-After`. | 429 |

## Resumen de rangos

| Módulo | Historias | Cantidad |
|---|---|---|
| M1 Identidad y acceso | HU-01 a HU-03 | 3 |
| M2 Clínicas y usuarios | HU-04 a HU-05 | 2 |
| M3 Onboarding y credenciales | HU-06 a HU-11 | 6 |
| M4 Equipo de atención | HU-12 a HU-14 | 3 |
| M5 Registros del paciente | HU-15 a HU-23 | 9 |
| M6 Plan de tratamiento | HU-24 a HU-28 | 5 |
| M7 Métricas glucémicas | HU-29 a HU-30 | 2 |
| M8 Alertas y notificaciones | HU-31 a HU-36 | 6 |
| M9 IA y soporte a decisiones | HU-37 a HU-44 | 8 |
| M10 Dashboard y reportes | HU-45 a HU-48 | 4 |
| M11 Mensajería y seguimiento | HU-49 a HU-50 | 2 |
| M12 Auditoría y cumplimiento | HU-51 a HU-53 | 3 |
| M13 Datos simulados | HU-54 a HU-56 | 3 |
| **Total** | | **56** |

---

## M1: Identidad y acceso

### HU-01: Iniciar sesión

- **Actor:** cualquier usuario con cuenta activa (`PLATFORM_ADMIN`, `CLINIC_ADMIN`, `DOCTOR`, `PATIENT`).
- **Historia:** Como usuario de Insumap, quiero ingresar con mi correo y contraseña, para acceder solo a lo que mi rol permite.
- **Prioridad:** MVP. **Fase:** 3. **RF:** RF-01, RF-05, RF-07, RF-08.

```gherkin
Escenario: ingreso correcto de un paciente
  Dado una cuenta de paciente en estado ACTIVE con contraseña válida
  Cuando envía POST /auth/login con su correo y contraseña
  Entonces recibe un access token de 15 minutos y un refresh token opaco
  Y GET /auth/current-user devuelve su rol PATIENT, su clínica y sus permisos

Escenario: credenciales incorrectas
  Dado una cuenta existente
  Cuando envía una contraseña incorrecta
  Entonces recibe 401 INVALID_CREDENTIALS con un mensaje genérico que no revela si el correo existe

Escenario: bloqueo por intentos repetidos
  Dado una cuenta con intentos fallidos consecutivos por encima del límite configurado
  Cuando intenta ingresar de nuevo
  Entonces recibe 429 RATE_LIMITED con la cabecera Retry-After
  Y el intento queda registrado en los eventos de seguridad

Escenario: cuenta no activa
  Dado una cuenta de paciente en estado SUSPENDED
  Cuando intenta ingresar con credenciales válidas
  Entonces recibe 403 ACCOUNT_NOT_ACTIVE
```

### HU-02: Activar el segundo factor del personal

- **Actor:** `PLATFORM_ADMIN`, `CLINIC_ADMIN`, `DOCTOR`.
- **Historia:** Como médico, quiero activar un segundo factor TOTP, para proteger el acceso a datos clínicos sensibles.
- **Prioridad:** MVP. **Fase:** 3. **RF:** RF-03.

```gherkin
Escenario: enrolar MFA en el primer ingreso
  Dado un médico que ingresó por primera vez sin MFA
  Cuando intenta usar cualquier endpoint distinto del enrolamiento
  Entonces recibe 403 MFA_REQUIRED
  Y puede escanear el código QR, confirmar con un código TOTP válido y recibir códigos de respaldo de un solo uso

Escenario: login con MFA
  Dado un médico con MFA activo
  Cuando envía su contraseña correcta y un código TOTP válido
  Entonces recibe sus tokens

Escenario: código de respaldo usado
  Dado un médico que usó un código de respaldo
  Cuando intenta usar el mismo código otra vez
  Entonces el sistema lo rechaza con 401 INVALID_CREDENTIALS
```

### HU-03: Cerrar sesiones y recuperar la contraseña

- **Actor:** cualquier usuario con cuenta.
- **Historia:** Como usuario, quiero cerrar mis sesiones y recuperar mi contraseña, para recuperar el control de mi cuenta si pierdo un dispositivo.
- **Prioridad:** MVP. **Fase:** 3. **RF:** RF-02, RF-04, RF-06.

```gherkin
Escenario: cerrar todas las sesiones
  Dado un usuario con sesiones en dos dispositivos
  Cuando solicita cerrar todas las sesiones
  Entonces todos sus refresh tokens quedan revocados y los access tokens vigentes expiran en 15 minutos

Escenario: reutilización de un refresh token
  Dado un refresh token que ya se rotó
  Cuando alguien lo presenta de nuevo
  Entonces recibe 401 UNAUTHORIZED
  Y toda la familia de tokens queda revocada y se registra un evento de seguridad

Escenario: recuperar contraseña
  Dado un usuario que olvidó su contraseña
  Cuando solicita la recuperación y usa el enlace de un solo uso antes de que venza
  Entonces define una contraseña nueva que cumple la política y no repite las anteriores
  Y todas sus sesiones previas se revocan

Escenario: enlace usado o vencido
  Dado un enlace ya utilizado
  Cuando se vuelve a usar
  Entonces recibe 410 INVITATION_INVALID
```

## M2: Clínicas y usuarios

### HU-04: Dar de alta una clínica y su primer administrador

- **Actor:** `PLATFORM_ADMIN`.
- **Historia:** Como administrador de la plataforma, quiero crear una clínica y su primer administrador, para que una clínica contratante empiece a usar Insumap.
- **Prioridad:** MVP. **Fase:** 4. **RF:** RF-09, RF-10, RF-11.

```gherkin
Escenario: crear una clínica
  Dado un PLATFORM_ADMIN autenticado con MFA
  Cuando crea una clínica con nombre e identificación fiscal
  Entonces la clínica queda ACTIVE como tenant aislado
  Y puede crear su primer CLINIC_ADMIN, que recibe una invitación y debe enrolar MFA

Escenario: nombre repetido
  Dado una clínica con el mismo nombre
  Cuando intenta crear otra igual
  Entonces recibe 409 CONFLICT

Escenario: suspender una clínica
  Dado una clínica activa con personal y pacientes
  Cuando el PLATFORM_ADMIN la suspende con motivo
  Entonces ningún usuario de esa clínica puede iniciar sesión hasta que se reactive

Escenario: sin acceso clínico
  Dado un PLATFORM_ADMIN
  Cuando intenta consultar un paciente de cualquier clínica
  Entonces recibe 403 FORBIDDEN
```

### HU-05: Gestionar el personal de la clínica

- **Actor:** `CLINIC_ADMIN`.
- **Historia:** Como administrador de la clínica, quiero crear y desactivar médicos y administradores, para mantener el personal actualizado.
- **Prioridad:** MVP. **Fase:** 4. **RF:** RF-12, RF-13, RF-15.

```gherkin
Escenario: crear un médico
  Dado un CLINIC_ADMIN autenticado
  Cuando crea un usuario DOCTOR con nombre, correo, registro profesional y especialidad
  Entonces el usuario queda en su clínica y recibe credenciales de un solo uso
  Y debe enrolar MFA en su primer ingreso

Escenario: desactivar un médico con pacientes
  Dado un médico asignado a pacientes
  Cuando el CLINIC_ADMIN lo desactiva
  Entonces sus sesiones se revocan
  Y el administrador ve la lista de pacientes sin médico asignado para reasignarlos

Escenario: personal de otra clínica
  Dado un usuario de otra clínica
  Cuando el CLINIC_ADMIN intenta consultarlo por ID
  Entonces recibe 404 NOT_FOUND
```

## M3: Onboarding desde la BD de la clínica y credenciales

### HU-06: Importar pacientes desde un Bundle FHIR

- **Actor:** `CLINIC_ADMIN`.
- **Historia:** Como administrador de la clínica, quiero importar a mis pacientes desde un Bundle FHIR R4 exportado de nuestro sistema, para no capturarlos uno por uno.
- **Prioridad:** MVP. **Fase:** 4. **RF:** RF-14, RF-16, RF-18, RF-19, RF-21.

```gherkin
Escenario: previsualización del Bundle
  Dado un Bundle FHIR R4 con 100 recursos Patient válidos y 5 con errores
  Cuando el administrador lo carga
  Entonces ve una previsualización con 100 filas válidas y 5 con su causa
  Y todavía no se crea ninguna cuenta

Escenario: confirmar la importación
  Dado una previsualización revisada
  Cuando el administrador confirma el lote
  Entonces se crean 100 pacientes en estado IMPORTED
  Y el documento de identidad se guarda cifrado y con hash

Escenario: paciente repetido
  Dado un paciente ya importado con el mismo número de historia (MRN)
  Cuando se importa de nuevo el mismo Bundle
  Entonces no se crea un segundo paciente y la fila queda como SKIPPED_DUPLICATE

Escenario: recurso no soportado
  Dado un Bundle con un recurso de tipo no soportado
  Cuando se procesa
  Entonces el recurso se reporta sin detener el lote
```

### HU-07: Importar pacientes desde un CSV

- **Actor:** `CLINIC_ADMIN`.
- **Historia:** Como administrador de la clínica, quiero importar pacientes desde un CSV con una plantilla, para clínicas que no exportan FHIR.
- **Prioridad:** MVP. **Fase:** 4. **RF:** RF-17, RF-18, RF-19, RF-21.

```gherkin
Escenario: descargar la plantilla y cargarla
  Dado un CLINIC_ADMIN
  Cuando descarga la plantilla CSV y carga un archivo con las columnas correctas
  Entonces se procesa y ve la previsualización por fila

Escenario: columnas faltantes
  Dado un CSV sin la columna de MRN
  Cuando lo carga
  Entonces recibe 422 con el nombre de la columna faltante

Escenario: codificación o tamaño inválido
  Dado un archivo que supera el tamaño máximo o no es UTF-8
  Cuando lo carga
  Entonces se rechaza con VALIDATION_ERROR sin procesar filas
```

### HU-08: Revisar los lotes de importación

- **Actor:** `CLINIC_ADMIN`.
- **Historia:** Como administrador de la clínica, quiero ver el historial de lotes y sus errores, para corregir los datos de origen y volver a importar.
- **Prioridad:** MVP. **Fase:** 4. **RF:** RF-18, RF-20.

```gherkin
Escenario: consultar un lote
  Dado un lote importado
  Cuando el administrador lo abre
  Entonces ve los totales (creados, omitidos, con error), el autor, el origen y la fecha

Escenario: descargar los errores
  Dado un lote con filas con error
  Cuando descarga el reporte de errores
  Entonces obtiene un CSV con la fila, la columna y la causa, sin datos clínicos
```

### HU-09: Emitir, reenviar y revocar credenciales

- **Actor:** `CLINIC_ADMIN`.
- **Historia:** Como administrador de la clínica, quiero emitir credenciales de un solo uso a mis pacientes importados, para que activen su cuenta de forma segura.
- **Prioridad:** MVP. **Fase:** 4. **RF:** RF-22, RF-23, RF-25.

```gherkin
Escenario: emitir credenciales por correo
  Dado un paciente en estado IMPORTED con correo
  Cuando el administrador emite su invitación por correo
  Entonces se crea un código de activación de un solo uso con expiración, guardado como hash
  Y el paciente pasa a INVITED y recibe el correo

Escenario: emitir credenciales impresas
  Dado un paciente sin correo
  Cuando el administrador elige imprimir
  Entonces obtiene una hoja con el código, visible una sola vez

Escenario: reenviar
  Dado un paciente INVITED
  Cuando el administrador reenvía la invitación
  Entonces el código anterior queda inválido y se emite uno nuevo

Escenario: revocar
  Dado un paciente INVITED
  Cuando el administrador revoca la invitación
  Entonces el paciente vuelve a IMPORTED y el código se rechaza con 410 INVITATION_INVALID

Escenario: fallo de envío
  Dado un servidor de correo caído
  Cuando se emite una invitación
  Entonces el envío queda registrado como fallido y puede reintentarse
```

### HU-10: Activar la cuenta del paciente

- **Actor:** `PATIENT` (sin sesión previa).
- **Historia:** Como paciente invitado por mi clínica, quiero activar mi cuenta con el código, definir mi contraseña y aceptar el tratamiento de mis datos, para empezar a registrar mi tratamiento.
- **Prioridad:** MVP. **Fase:** 4. **RF:** RF-24, RF-90.

```gherkin
Escenario: activación correcta
  Dado un paciente INVITED con un código vigente
  Cuando ingresa el código, define una contraseña válida y acepta el consentimiento versionado
  Entonces la cuenta pasa a ACTIVE y el código se consume
  Y queda registrada la versión del consentimiento y la fecha

Escenario: sin consentimiento
  Dado un paciente con código vigente
  Cuando intenta activar sin aceptar el consentimiento
  Entonces recibe 403 CONSENT_REQUIRED y la cuenta sigue INVITED

Escenario: código inválido
  Dado un código ya usado, vencido o revocado
  Cuando intenta activar
  Entonces recibe 410 INVITATION_INVALID

Escenario: fuerza bruta
  Dado muchos intentos de código incorrectos desde una misma IP
  Cuando supera el límite
  Entonces recibe 429 RATE_LIMITED
```

### HU-11: Suspender, reactivar y desactivar cuentas

- **Actor:** `CLINIC_ADMIN`.
- **Historia:** Como administrador de la clínica, quiero suspender, reactivar o dar de baja a un paciente, para controlar el acceso cuando hay un problema de seguridad o termina la atención.
- **Prioridad:** MVP. **Fase:** 4. **RF:** RF-26.

```gherkin
Escenario: suspender
  Dado un paciente ACTIVE
  Cuando el administrador lo suspende con motivo
  Entonces pasa a SUSPENDED, sus sesiones se revocan y no puede ingresar

Escenario: reactivar
  Dado un paciente SUSPENDED
  Cuando el administrador lo reactiva
  Entonces vuelve a ACTIVE

Escenario: desactivar es terminal
  Dado un paciente DEACTIVATED
  Cuando el administrador intenta reactivarlo
  Entonces recibe 409 INVALID_STATE_TRANSITION

Escenario: sin motivo
  Dado un paciente ACTIVE
  Cuando el administrador intenta suspenderlo sin motivo
  Entonces recibe 422 REASON_REQUIRED
```

## M4: Equipo de atención

### HU-12: Asignar médicos y designar al principal

- **Actor:** `CLINIC_ADMIN`.
- **Historia:** Como administrador de la clínica, quiero asignar uno o varios médicos a cada paciente y marcar uno como principal, para que haya un responsable claro.
- **Prioridad:** MVP. **Fase:** 4. **RF:** RF-27, RF-28.

```gherkin
Escenario: asignar un equipo
  Dado un paciente de la clínica y dos médicos activos de la misma clínica
  Cuando el administrador asigna ambos y marca uno como principal
  Entonces el paciente tiene dos médicos con exactamente un principal

Escenario: cambiar al principal
  Dado un paciente con médico principal
  Cuando el administrador designa a otro como principal
  Entonces el anterior deja de ser principal en la misma operación

Escenario: médico de otra clínica
  Dado un médico de otra clínica
  Cuando el administrador intenta asignarlo
  Entonces recibe 404 NOT_FOUND
```

### HU-13: Reasignar o retirar médicos

- **Actor:** `CLINIC_ADMIN`.
- **Historia:** Como administrador de la clínica, quiero reasignar o retirar médicos con motivo, para cubrir ausencias y cambios de equipo.
- **Prioridad:** MVP. **Fase:** 4. **RF:** RF-29.

```gherkin
Escenario: retirar a un médico
  Dado un paciente con dos médicos asignados
  Cuando el administrador retira a uno con motivo
  Entonces ese médico deja de ver al paciente y recibe 404 al intentarlo
  Y el historial conserva la asignación con fechas y motivo

Escenario: no dejar al paciente sin principal
  Dado un paciente con un solo médico, que es el principal
  Cuando el administrador intenta retirarlo sin reemplazo
  Entonces recibe 409 CONFLICT
```

### HU-14: Ver solo a los pacientes asignados

- **Actor:** `DOCTOR`.
- **Historia:** Como médico, quiero ver únicamente a mis pacientes asignados, para respetar la confidencialidad y el alcance de mi atención.
- **Prioridad:** MVP. **Fase:** 4. **RF:** RF-14, RF-30.

```gherkin
Escenario: paciente asignado
  Dado un médico asignado a un paciente
  Cuando consulta su detalle clínico
  Entonces recibe los datos y el acceso queda auditado

Escenario: paciente no asignado
  Dado un paciente de la misma clínica no asignado al médico
  Cuando el médico lo consulta por ID
  Entonces recibe 404 NOT_FOUND

Escenario: paciente de otra clínica
  Dado un paciente de otra clínica
  Cuando el médico lo consulta por ID
  Entonces recibe 404 NOT_FOUND

Escenario: administrador sin detalle clínico
  Dado un CLINIC_ADMIN
  Cuando intenta consultar la glucosa de un paciente
  Entonces recibe 403 FORBIDDEN
```

## M5: Registros del paciente

### HU-15: Registrar glucosa

- **Actor:** `PATIENT`.
- **Historia:** Como paciente, quiero registrar mi glucosa con su contexto en pocos pasos, para que mi médico vea mi control.
- **Prioridad:** MVP. **Fase:** 5. **RF:** RF-31, RF-33.

```gherkin
Escenario: registro manual
  Dado un paciente ACTIVE en la app
  Cuando ingresa 142 mg/dL, hora y contexto "ayunas"
  Entonces la lectura se guarda en mg/dL con fuente MANUAL
  Y aparece en su gráfica

Escenario: valor inverosímil
  Dado un valor fuera del rango fisiológico configurado
  Cuando intenta guardarlo
  Entonces recibe 422 GLUCOSE_OUT_OF_RANGE y la app le pide confirmar o corregir

Escenario: unidad en mmol/L
  Dado un paciente que ingresa 7,8 mmol/L
  Cuando guarda
  Entonces el sistema la convierte a mg/dL y la guarda en mg/dL

Escenario: fecha futura
  Dado una lectura con fecha posterior a la actual
  Cuando intenta guardar
  Entonces se rechaza con VALIDATION_ERROR

Escenario: hipoglucemia
  Dado una lectura de 52 mg/dL
  Cuando se guarda
  Entonces la app muestra el aviso de acción inmediata configurado por la clínica y se evalúan las reglas de alerta
```

### HU-16: Registrar sin conexión y sincronizar por lotes

- **Actor:** `PATIENT`.
- **Historia:** Como paciente, quiero registrar mis datos aunque no tenga internet, para no perder lecturas en la calle o en el transporte.
- **Prioridad:** MVP. **Fase:** 5. **RF:** RF-32, RF-33.

```gherkin
Escenario: cola local
  Dado un paciente sin conexión
  Cuando registra tres lecturas
  Entonces quedan en la cola local con un UUID cada una y se marcan "pendiente"

Escenario: sincronización idempotente
  Dado tres lecturas pendientes
  Cuando recupera la conexión y la app envía el lote
  Entonces cada lectura devuelve CREATED
  Y si el lote se reenvía devuelve DUPLICATE sin duplicar datos

Escenario: lectura rechazada en el lote
  Dado un lote con una lectura inválida
  Cuando se envía
  Entonces las válidas se guardan y la inválida devuelve REJECTED con su causa para corregirla
```

### HU-17: Registrar insulina

- **Actor:** `PATIENT`.
- **Historia:** Como paciente, quiero registrar mis dosis de insulina, para que mi equipo vea cuánto y cuándo me inyecto.
- **Prioridad:** MVP. **Fase:** 5. **RF:** RF-34.

```gherkin
Escenario: registrar una dosis
  Dado un paciente con plan activo
  Cuando registra 10 unidades de insulina de acción rápida a las 13:05
  Entonces la dosis se guarda con producto, tipo (bolo) y unidades y aparece en la línea de tiempo

Escenario: dosis fuera de límites
  Dado un valor de unidades por encima del límite técnico
  Cuando intenta guardar
  Entonces recibe VALIDATION_ERROR

Escenario: sin sugerencia de dosis
  Dado un paciente registrando una dosis
  Cuando abre la pantalla
  Entonces la app no calcula ni sugiere ninguna dosis; solo registra lo que él indica
```

### HU-18: Registrar comidas y actividad

- **Actor:** `PATIENT`.
- **Historia:** Como paciente, quiero registrar mis comidas y mi actividad física, para que mi médico entienda mis picos y mis descensos.
- **Prioridad:** MVP. **Fase:** 5. **RF:** RF-35, RF-36.

```gherkin
Escenario: registrar una comida
  Dado un paciente ACTIVE
  Cuando registra almuerzo con 60 g de carbohidratos estimados
  Entonces la comida se guarda y aparece junto a la glucosa posterior

Escenario: registrar actividad
  Dado un paciente ACTIVE
  Cuando registra 30 minutos de caminata de intensidad moderada
  Entonces la actividad se guarda y se usa como contexto en los patrones

Escenario: valores inválidos
  Dado carbohidratos negativos o duración fuera de límites
  Cuando intenta guardar
  Entonces recibe VALIDATION_ERROR indicando el campo
```

### HU-19: Registrar síntomas

- **Actor:** `PATIENT`.
- **Historia:** Como paciente, quiero registrar cómo me siento, para que mi equipo vea síntomas junto a mis lecturas.
- **Prioridad:** MVP. **Fase:** 5. **RF:** RF-37.

```gherkin
Escenario: registrar un síntoma común
  Dado un paciente ACTIVE
  Cuando selecciona "sed" y "visión borrosa" con hora
  Entonces se guardan y aparecen en la línea de tiempo

Escenario: síntoma de alarma
  Dado un síntoma configurado como de alarma (por ejemplo, confusión o pérdida de conocimiento)
  Cuando lo registra
  Entonces la app muestra el aviso "contacta a tu equipo o a urgencias" y se crea una alerta para su equipo

Escenario: texto libre acotado
  Dado una nota de más caracteres que el límite
  Cuando intenta guardar
  Entonces recibe VALIDATION_ERROR
```

### HU-20: Registrar HbA1c

- **Actor:** `PATIENT`, `DOCTOR`.
- **Historia:** Como paciente o médico, quiero registrar el resultado de HbA1c, para seguir el control a largo plazo.
- **Prioridad:** MVP. **Fase:** 5. **RF:** RF-38.

```gherkin
Escenario: autorreporte del paciente
  Dado un paciente con un resultado de laboratorio en mano
  Cuando registra 7,4 % con la fecha del examen
  Entonces se guarda con origen PATIENT_REPORTED

Escenario: resultado confirmado por el médico
  Dado un médico asignado
  Cuando registra el resultado del laboratorio
  Entonces se guarda con origen LAB y reemplaza al autorreporte en las gráficas de tendencia

Escenario: valor fuera de rango
  Dado un valor de HbA1c fuera del rango permitido
  Cuando intenta guardar
  Entonces se rechaza con VALIDATION_ERROR
```

### HU-21: Corregir un registro

- **Actor:** `PATIENT`.
- **Historia:** Como paciente, quiero corregir un registro equivocado con un motivo, para que mis datos sean correctos sin perder el historial.
- **Prioridad:** MVP. **Fase:** 5. **RF:** RF-39.

```gherkin
Escenario: corregir una lectura
  Dado una lectura de 410 mg/dL registrada por error
  Cuando el paciente la corrige a 140 mg/dL con motivo
  Entonces se crea un registro nuevo que apunta al original
  Y el original sigue visible en el historial como "corregido"

Escenario: sin motivo
  Dado un intento de corrección sin motivo
  Cuando se envía
  Entonces recibe 422 REASON_REQUIRED

Escenario: no existe el borrado
  Dado cualquier registro clínico
  Cuando se busca una operación de borrado en la API
  Entonces no existe; solo se corrige o se anula
```

### HU-22: Ver mis gráficas y mi línea de tiempo

- **Actor:** `PATIENT`.
- **Historia:** Como paciente, quiero ver mi glucosa y mis eventos en una gráfica y una línea de tiempo, para entender mi día.
- **Prioridad:** MVP. **Fase:** 5. **RF:** RF-40, RF-42.

```gherkin
Escenario: gráfica del día
  Dado un paciente con lecturas del día
  Cuando abre su inicio
  Entonces ve la gráfica con su rango objetivo y sus dosis, comidas y actividad sobre la línea de tiempo

Escenario: legibilidad en escritorio y en celular
  Dado una pantalla de escritorio de 1440 px de ancho o, como criterio secundario, una de 360 px
  Cuando abre la gráfica
  Entonces se ve completa sin desplazamiento horizontal y no depende solo del color

Escenario: datos de otro paciente
  Dado otro paciente de la misma clínica
  Cuando el paciente pide sus datos por ID
  Entonces recibe 404 NOT_FOUND
```

### HU-23: Importar un CSV de mi sensor (CGM)

- **Actor:** `PATIENT`.
- **Historia:** Como paciente con un sensor CGM, quiero cargar el archivo de exportación de mi sensor, para que mi equipo vea todas mis lecturas.
- **Prioridad:** MVP. **Fase:** 5. **RF:** RF-41.

```gherkin
Escenario: formato soportado
  Dado un CSV de exportación con un formato soportado
  Cuando el paciente lo carga
  Entonces las lecturas pasan por la validación en cadena y se guardan con fuente CGM

Escenario: formato desconocido
  Dado un CSV con un formato no soportado
  Cuando lo carga
  Entonces se rechaza con la lista de formatos admitidos

Escenario: lecturas repetidas
  Dado un archivo con lecturas ya cargadas
  Cuando lo carga
  Entonces las repetidas se marcan DUPLICATE y no se duplican
```

## M6: Plan de tratamiento

### HU-24: Gestionar plantillas de protocolo

- **Actor:** `CLINIC_ADMIN`.
- **Historia:** Como administrador de la clínica, quiero definir plantillas de protocolo (por ejemplo, "Basal-bolo adulto DM1"), para estandarizar los tratamientos de la clínica.
- **Prioridad:** MVP. **Fase:** 6. **RF:** RF-43.

```gherkin
Escenario: crear una plantilla
  Dado un CLINIC_ADMIN
  Cuando crea una plantilla con su estructura de insulinas, horarios y metas por defecto
  Entonces queda versionada y disponible para los médicos de su clínica

Escenario: retirar una plantilla
  Dado una plantilla en uso por planes
  Cuando el administrador la retira
  Entonces no se puede clonar más, pero los planes existentes no cambian

Escenario: sin acceso del médico a la edición
  Dado un DOCTOR
  Cuando intenta editar una plantilla de la clínica
  Entonces recibe 403 FORBIDDEN
```

### HU-25: Crear el plan de un paciente desde una plantilla

- **Actor:** `DOCTOR`.
- **Historia:** Como médico, quiero clonar una plantilla y personalizarla para mi paciente, para no empezar de cero.
- **Prioridad:** MVP. **Fase:** 6. **RF:** RF-44, RF-45.

```gherkin
Escenario: clonar y personalizar
  Dado un médico asignado y una plantilla vigente
  Cuando la clona para su paciente y ajusta las dosis
  Entonces el plan nace en DRAFT y la plantilla original no cambia

Escenario: plan inválido
  Dado un plan con una dosis fuera de los límites o horarios solapados
  Cuando intenta activarlo
  Entonces recibe 422 con la lista de invariantes incumplidas

Escenario: paciente no asignado
  Dado un paciente no asignado al médico
  Cuando intenta crearle un plan
  Entonces recibe 404 NOT_FOUND
```

### HU-26: Activar, versionar y restaurar un plan

- **Actor:** `DOCTOR`.
- **Historia:** Como médico, quiero activar un plan y poder volver a versiones anteriores, para cambiar el tratamiento sin perder el historial.
- **Prioridad:** MVP. **Fase:** 6. **RF:** RF-46, RF-47.

```gherkin
Escenario: activar un plan
  Dado un plan DRAFT válido
  Cuando el médico lo activa
  Entonces pasa a ACTIVE, el anterior pasa a SUPERSEDED y el paciente ve el plan nuevo

Escenario: nueva versión
  Dado un plan ACTIVE
  Cuando el médico quiere cambiarlo
  Entonces se crea una copia en DRAFT y el plan activo no cambia hasta activar la nueva

Escenario: restaurar
  Dado una versión anterior con su foto guardada
  Cuando el médico la restaura
  Entonces se crea una versión nueva en DRAFT con ese contenido y el historial permanece
```

### HU-27: Configurar y asignar metas glucémicas

- **Actor:** `CLINIC_ADMIN`, `DOCTOR`.
- **Historia:** Como administrador, quiero definir perfiles de metas (TIR, TBR, TAR), y como médico quiero asignar uno a mi paciente, para que las métricas se evalúen con la meta correcta.
- **Prioridad:** MVP. **Fase:** 6. **RF:** RF-48.

```gherkin
Escenario: crear un perfil de metas
  Dado un CLINIC_ADMIN
  Cuando define un perfil "Adulto DM1" con TIR mínimo, TBR máximo y TAR máximo
  Entonces se guarda versionado en la base de datos

Escenario: asignar a un paciente
  Dado un médico asignado y un perfil vigente
  Cuando lo asigna a su paciente
  Entonces las métricas del paciente se comparan con ese perfil

Escenario: cambiar el perfil
  Dado un perfil modificado
  Cuando se crea una versión nueva
  Entonces los cálculos pasados conservan la versión con la que se hicieron
```

### HU-28: Ver mi plan y recibir recordatorios

- **Actor:** `PATIENT`, `DOCTOR`.
- **Historia:** Como paciente, quiero ver mi plan en lenguaje claro y recibir recordatorios, para cumplir mi tratamiento.
- **Prioridad:** MVP. **Fase:** 6. **RF:** RF-49, RF-50.

```gherkin
Escenario: ver el plan activo
  Dado un paciente con plan ACTIVE
  Cuando abre "Mi plan"
  Entonces ve sus insulinas, horarios y metas, sin opciones para editar dosis

Escenario: recordatorio en su hora
  Dado un recordatorio de medición programado por el médico
  Cuando llega su hora
  Entonces el paciente lo recibe por sus canales elegidos

Escenario: horario de silencio
  Dado un paciente con horario de silencio
  Cuando un recordatorio no crítico cae en ese horario
  Entonces se difiere hasta que termine
```

## M7: Métricas glucémicas

### HU-29: Ver las métricas de un paciente

- **Actor:** `DOCTOR`, `PATIENT`.
- **Historia:** Como médico, quiero ver TIR, TBR, TAR, GMI y CV de mi paciente por ventanas, para evaluar su control.
- **Prioridad:** MVP. **Fase:** 7. **RF:** RF-51, RF-52, RF-54, RF-55.

```gherkin
Escenario: métricas de 14 días
  Dado un paciente asignado con datos suficientes
  Cuando el médico abre las métricas de 14 días
  Entonces ve TIR, TBR (< 70 y < 54), TAR (> 180 y > 250), media, GMI y CV según el perfil de metas

Escenario: comparación con el periodo anterior
  Dado dos ventanas de 14 días
  Cuando el médico compara
  Entonces ve la variación del TIR en puntos porcentuales con su signo

Escenario: datos insuficientes
  Dado una cobertura de datos menor al mínimo configurado
  Cuando se piden las métricas
  Entonces la respuesta indica "datos insuficientes" y no muestra un porcentaje

Escenario: el paciente ve las propias
  Dado un paciente
  Cuando abre sus métricas
  Entonces ve su resumen en lenguaje simple y solo el suyo
```

### HU-30: Ver el AGP

- **Actor:** `DOCTOR`.
- **Historia:** Como médico, quiero ver el perfil ambulatorio de glucosa (AGP) de 14 días, para identificar patrones por hora del día.
- **Prioridad:** MVP. **Fase:** 7. **RF:** RF-53, RF-55.

```gherkin
Escenario: AGP con datos suficientes
  Dado un paciente con 14 días de datos con cobertura suficiente
  Cuando el médico abre el AGP
  Entonces ve las curvas de los percentiles 5, 25, 50, 75 y 95 por hora y la banda del rango objetivo

Escenario: AGP con datos insuficientes
  Dado un paciente con pocos datos
  Cuando abre el AGP
  Entonces ve el aviso "datos insuficientes" en lugar de una curva engañosa
```

## M8: Alertas y notificaciones

### HU-31: Configurar reglas de alerta

- **Actor:** `CLINIC_ADMIN`.
- **Historia:** Como administrador de la clínica, quiero configurar las reglas de alerta, para adaptar umbrales y tiempos a la política de la clínica.
- **Prioridad:** MVP. **Fase:** 8. **RF:** RF-56.

```gherkin
Escenario: regla de hipoglucemia
  Dado un CLINIC_ADMIN
  Cuando crea una regla de umbral "glucosa menor a 70 mg/dL" con prioridad alta
  Entonces queda versionada y se evalúa con las lecturas nuevas

Escenario: regla compuesta
  Dado una regla "glucosa mayor a 250 mg/dL durante 2 horas Y sin dosis registrada"
  Cuando la crea
  Entonces se guarda como un árbol de condiciones combinadas

Escenario: regla activa inmutable
  Dado una regla en uso
  Cuando intenta editarla
  Entonces se crea una versión nueva y la anterior queda para el historial
```

### HU-32: Recibir una alerta de hipoglucemia o hiperglucemia

- **Actor:** `PATIENT`, `DOCTOR`.
- **Historia:** Como paciente y médico, queremos recibir una alerta cuando hay hipoglucemia o hiperglucemia sostenida, para actuar a tiempo.
- **Prioridad:** MVP. **Fase:** 8. **RF:** RF-57, RF-58, RF-61.

```gherkin
Escenario: hipoglucemia nivel 2
  Dado un paciente con una regla de hipoglucemia
  Cuando se guarda una lectura de 50 mg/dL
  Entonces se crea una alerta de nivel 2 en estado OPEN
  Y se publica el evento HypoglycemiaDetected
  Y el paciente recibe una notificación inmediata por sus canales

Escenario: hiperglucemia sostenida
  Dado una regla de glucosa mayor a 250 mg/dL durante la duración configurada
  Cuando las lecturas cumplen la duración
  Entonces se crea una alerta; un pico aislado no la crea

Escenario: un canal caído
  Dado que el Web Push falla
  Cuando se envía la notificación
  Entonces los demás canales se envían y el fallo queda registrado
```

### HU-33: Reconocer y resolver una alerta

- **Actor:** `DOCTOR`, `PATIENT`.
- **Historia:** Como médico, quiero reconocer y resolver las alertas de mis pacientes con una nota, para que el equipo sepa que se atendió.
- **Prioridad:** MVP. **Fase:** 8. **RF:** RF-59, RF-65.

```gherkin
Escenario: reconocer
  Dado una alerta OPEN de un paciente asignado
  Cuando el médico la reconoce
  Entonces pasa a ACKNOWLEDGED con quién y cuándo

Escenario: resolver
  Dado una alerta ACKNOWLEDGED
  Cuando el médico la resuelve con una nota
  Entonces pasa a RESOLVED y queda en el historial

Escenario: transición inválida
  Dado una alerta RESOLVED
  Cuando alguien intenta reconocerla
  Entonces recibe 409 INVALID_STATE_TRANSITION

Escenario: el paciente reconoce la suya
  Dado una alerta propia OPEN
  Cuando el paciente la reconoce
  Entonces pasa a ACKNOWLEDGED y el médico la ve con esa marca
```

### HU-34: Escalar una alerta sin atender

- **Actor:** sistema, `DOCTOR`, `CLINIC_ADMIN`.
- **Historia:** Como clínica, quiero que una alerta sin reconocer escale por la cadena de responsables, para que ningún evento grave quede sin atención.
- **Prioridad:** MVP. **Fase:** 8. **RF:** RF-60.

```gherkin
Escenario: escalamiento por la cadena
  Dado una alerta crítica OPEN sin reconocer
  Cuando pasa el tiempo configurado para el paciente
  Entonces se notifica al médico principal
  Y si pasa el tiempo del médico, al equipo, y luego al administrador de la clínica

Escenario: escalamiento detenido
  Dado una alerta escalada
  Cuando alguien la reconoce
  Entonces pasa a ACKNOWLEDGED y se detiene la cadena

Escenario: el administrador no ve detalle
  Dado una alerta escalada al administrador
  Cuando la recibe
  Entonces ve solo que hay una alerta sin atender y de qué equipo, sin valores de glucosa
```

### HU-35: Evitar la fatiga de alertas

- **Actor:** `DOCTOR`, `PATIENT`.
- **Historia:** Como médico, quiero que las alertas no se repitan ni me saturen, para atender de verdad las importantes.
- **Prioridad:** MVP. **Fase:** 8. **RF:** RF-61, RF-62, RF-63.

```gherkin
Escenario: sin duplicados
  Dado una alerta de hipoglucemia OPEN
  Cuando llega otra lectura baja del mismo episodio
  Entonces no se crea una segunda alerta; se actualiza la existente

Escenario: horario de silencio
  Dado un paciente con horario de silencio
  Cuando ocurre una alerta de baja prioridad en ese horario
  Entonces se difiere y las alertas críticas se envían igual

Escenario: falta de registros
  Dado un paciente que no registra durante el periodo configurado
  Cuando vence el periodo
  Entonces recibe un recordatorio y, si persiste, se avisa a su equipo como alerta de adherencia

Escenario: preferencias de canal
  Dado un usuario que elige solo correo e in-app
  Cuando hay una notificación no crítica
  Entonces solo se envía por esos canales
```

### HU-36: Recibir un aviso preventivo por pronóstico

- **Actor:** `PATIENT`, `DOCTOR`.
- **Historia:** Como paciente, quiero un aviso cuando se prevé que mi glucosa baje o suba pronto, para actuar antes de que ocurra.
- **Prioridad:** MVP. **Fase:** 9. **RF:** RF-64, RF-66.

```gherkin
Escenario: pronóstico con riesgo de hipoglucemia
  Dado un paciente con serie CGM reciente
  Cuando el pronóstico indica riesgo alto de glucosa baja en los próximos 60 minutos
  Entonces se crea una alerta de tipo PREDICTIVE y el paciente recibe un aviso con la banda p10 a p90

Escenario: la IA no responde
  Dado un servicio de IA caído
  Cuando se evalúa el pronóstico
  Entonces se usa la tendencia lineal como respaldo y la alerta indica "Respaldo por reglas"

Escenario: sin consejo de dosis
  Dado un aviso preventivo
  Cuando se muestra al paciente
  Entonces no incluye ninguna cantidad de insulina
```

## M9: IA y soporte a decisiones

### HU-37: Ver el triage de riesgo explicado

- **Actor:** `DOCTOR`.
- **Historia:** Como médico, quiero que mis pacientes aparezcan ordenados por riesgo con la razón de cada posición, para saber a quién ver primero.
- **Prioridad:** MVP. **Fase:** 9. **RF:** RF-67.

```gherkin
Escenario: orden por riesgo
  Dado un médico con 40 pacientes asignados
  Cuando abre el triage
  Entonces ve los pacientes ordenados por puntaje de riesgo, cada uno con al menos un factor legible (por ejemplo, "TIR cayó 18 puntos frente a la quincena anterior")

Escenario: respaldo por reglas
  Dado un servicio de IA caído
  Cuando abre el triage
  Entonces ve el orden calculado con reglas tipo TIDE y la insignia "Respaldo por reglas"

Escenario: solo pacientes asignados
  Dado pacientes no asignados al médico
  Cuando abre el triage
  Entonces no aparecen
```

### HU-38: Ver patrones y anomalías detectados

- **Actor:** `DOCTOR`.
- **Historia:** Como médico, quiero ver patrones detectados (hipoglucemias nocturnas, fenómeno del alba, picos posprandiales, dosis omitidas), para decidir ajustes con evidencia.
- **Prioridad:** MVP. **Fase:** 9. **RF:** RF-68.

```gherkin
Escenario: hallazgo con evidencia
  Dado un paciente con tres hipoglucemias entre las 2 y las 4 de la madrugada en 7 días
  Cuando se analiza su serie
  Entonces aparece un hallazgo "hipoglucemia nocturna recurrente" con la ventana, las fechas y la confianza

Escenario: lectura inverosímil
  Dado una lectura con un salto imposible
  Cuando se analiza
  Entonces se marca como sospechosa en lugar de ocultarse

Escenario: descartar un hallazgo
  Dado un hallazgo que el médico considera irrelevante
  Cuando lo descarta con una nota
  Entonces queda registrado y no se vuelve a mostrar como nuevo
```

### HU-39: Aprobar, modificar o rechazar una recomendación

- **Actor:** `DOCTOR`.
- **Historia:** Como médico, quiero revisar una recomendación de la IA y aprobarla, modificarla o rechazarla con motivo, para mantener el control de las decisiones.
- **Prioridad:** MVP. **Fase:** 9. **RF:** RF-69, RF-70, RF-71.

```gherkin
Escenario: recomendación propuesta
  Dado glucosas en ayunas persistentemente altas con el plan activo
  Cuando la IA propone subir la insulina basal
  Entonces la recomendación queda en PROPOSED con su explicación y datos de apoyo, y no cambia el plan

Escenario: aprobar
  Dado una recomendación PROPOSED de un paciente asignado
  Cuando el médico la aprueba
  Entonces pasa a APPROVED y se crea una versión DRAFT del plan para activar
  Y se publica el evento RecommendationApproved y la decisión queda auditada

Escenario: aprobar con cambios
  Dado una recomendación PROPOSED
  Cuando el médico cambia la dosis propuesta y la aprueba con un motivo
  Entonces pasa a APPROVED_WITH_CHANGES y se guardan el texto original, el modificado y el motivo

Escenario: rechazar
  Dado una recomendación PROPOSED
  Cuando el médico la rechaza con motivo
  Entonces pasa a REJECTED y el motivo queda guardado

Escenario: sin motivo
  Dado una modificación o rechazo sin motivo
  Cuando se envía
  Entonces recibe 422 REASON_REQUIRED

Escenario: expiración
  Dado una recomendación sin decisión pasado su plazo
  Cuando vence
  Entonces pasa a EXPIRED y ya no se puede decidir

Escenario: paciente no asignado
  Dado un médico no asignado
  Cuando intenta decidir la recomendación
  Entonces recibe 404 NOT_FOUND
```

### HU-40: Mantener el servicio si la IA falla

- **Actor:** sistema, `DOCTOR`.
- **Historia:** Como médico, quiero que el sistema siga funcionando si la IA no responde, para no perder la vigilancia de mis pacientes.
- **Prioridad:** MVP. **Fase:** 9. **RF:** RF-75, RF-76.

```gherkin
Escenario: circuito abierto
  Dado un servicio de IA que falla varias veces seguidas
  Cuando el circuito se abre
  Entonces triage, alertas y pronóstico usan el respaldo determinista
  Y la interfaz muestra "Respaldo por reglas"

Escenario: sin sugerencias de ajuste
  Dado un servicio de IA caído
  Cuando el médico abre las recomendaciones
  Entonces no se genera ninguna sugerencia de ajuste y se informa el motivo

Escenario: minimización
  Dado una llamada al servicio de IA
  Cuando se arma la carga útil
  Entonces contiene un seudónimo y datos clínicos necesarios, nunca nombre, documento, MRN ni contacto

Escenario: trazabilidad
  Dado una salida de IA
  Cuando se guarda
  Entonces registra la versión del modelo, las entradas seudonimizadas y la explicación
```

### HU-41: Generar un resumen previo a la consulta

- **Actor:** `DOCTOR`.
- **Historia:** Como médico, quiero un resumen del paciente antes de la consulta, para aprovechar el tiempo con él.
- **Prioridad:** Post-MVP. **Fase:** 10. **RF:** RF-72.

```gherkin
Escenario: resumen con referencias
  Dado un paciente asignado con 14 días de datos
  Cuando el médico pide el resumen previo a la consulta
  Entonces recibe una narrativa del AGP, los eventos, la adherencia y los cambios de plan, cada afirmación con referencia a los datos
  Y el LLM solo recibió datos seudonimizados

Escenario: LLM no disponible
  Dado un LLM sin respuesta
  Cuando se pide el resumen
  Entonces se genera una plantilla determinista con las mismas cifras

Escenario: marca de apoyo
  Dado un resumen generado
  Cuando se muestra
  Entonces indica "Generado con IA como apoyo; verifica con los datos"
```

### HU-42: Consultar al asistente educativo

- **Actor:** `PATIENT`.
- **Historia:** Como paciente, quiero hacer preguntas sobre mi diabetes a un asistente, para aprender sin esperar a mi consulta.
- **Prioridad:** Post-MVP. **Fase:** 10. **RF:** RF-73.

```gherkin
Escenario: pregunta educativa
  Dado un paciente ACTIVE
  Cuando pregunta "¿qué es la hipoglucemia?"
  Entonces recibe una respuesta basada en material aprobado por su clínica

Escenario: petición de dosis
  Dado una pregunta como "¿cuánta insulina me pongo ahora?"
  Cuando el asistente la evalúa
  Entonces responde que la dosis la define su médico y no da cantidades

Escenario: síntoma de alarma
  Dado un mensaje que describe confusión o desmayo
  Cuando se evalúa
  Entonces muestra el aviso de urgencia y avisa al equipo, sin continuar la conversación educativa

Escenario: asistente no disponible
  Dado un LLM caído
  Cuando el paciente escribe
  Entonces recibe respuestas predefinidas del material de la clínica
```

### HU-43: Identificar y contactar pacientes en riesgo de abandono

- **Actor:** `CLINIC_ADMIN`, `DOCTOR`.
- **Historia:** Como clínica, quiero saber qué pacientes están dejando de usar el sistema, para contactarlos antes de perderlos.
- **Prioridad:** MVP (detección) y Post-MVP (tareas de contacto). **Fase:** 9 y 11. **RF:** RF-74, RF-87.

```gherkin
Escenario: lista de riesgo de abandono
  Dado pacientes con caída de registros
  Cuando el administrador abre la lista de riesgo de abandono
  Entonces ve nombre administrativo, estado y días sin registrar, sin valores clínicos

Escenario: respaldo por inactividad
  Dado un servicio de IA caído
  Cuando se evalúa el riesgo
  Entonces se usa la regla de días sin registros configurada

Escenario: tarea de contacto
  Dado un paciente en riesgo
  Cuando la clínica crea una tarea de contacto y registra el resultado
  Entonces queda ligada al paciente y a quien la atendió
```

### HU-44: Evaluar la IA frente al respaldo

- **Actor:** `PLATFORM_ADMIN`, `CLINIC_ADMIN`.
- **Historia:** Como equipo, quiero comparar la IA con el respaldo por reglas, para saber si realmente ayuda.
- **Prioridad:** Post-MVP. **Fase:** 10. **RF:** RF-77.

```gherkin
Escenario: comparación de pronóstico
  Dado un backtest sobre datos simulados
  Cuando se calcula la evaluación
  Entonces el tablero muestra MAE, RMSE y Clarke Error Grid de la IA y del respaldo por versión de modelo

Escenario: comparación de riesgo
  Dado el triage de un periodo
  Cuando se evalúa
  Entonces se muestran AUROC y calibración, y se indica que los datos son simulados

Escenario: sin datos clínicos
  Dado un CLINIC_ADMIN
  Cuando abre la evaluación
  Entonces ve solo métricas agregadas, no series de pacientes
```

## M10: Dashboard médico y reportes

### HU-45: Usar el dashboard de triage

- **Actor:** `DOCTOR`.
- **Historia:** Como médico, quiero un panel con mis pacientes ordenados por prioridad, alertas y recomendaciones pendientes, para empezar el día sabiendo a quién atender.
- **Prioridad:** MVP. **Fase:** 7 (reglas) y 9 (IA). **RF:** RF-78, RF-79.

```gherkin
Escenario: panel del día
  Dado un médico con pacientes asignados
  Cuando abre el dashboard
  Entonces ve cada paciente con su bandera de riesgo, alertas abiertas y recomendaciones pendientes

Escenario: cambiar la ventana
  Dado el panel abierto
  Cuando elige 7 días en lugar de 14
  Entonces las métricas y banderas se recalculan para esa ventana

Escenario: marcar como revisado
  Dado un paciente con bandera
  Cuando el médico lo marca como revisado
  Entonces baja de prioridad hasta que su situación cambie

Escenario: carga en tiempo objetivo
  Dado 200 pacientes asignados
  Cuando abre el dashboard
  Entonces carga en el tiempo objetivo de RNF-07
```

### HU-46: Ver el detalle del paciente y escribir notas

- **Actor:** `DOCTOR`.
- **Historia:** Como médico, quiero abrir el detalle de un paciente con su AGP, métricas, línea de tiempo y plan, y dejar notas, para preparar y documentar mi decisión.
- **Prioridad:** MVP. **Fase:** 7. **RF:** RF-80, RF-81.

```gherkin
Escenario: abrir el detalle
  Dado un paciente asignado
  Cuando el médico abre su detalle
  Entonces ve AGP, TIR, línea de tiempo, plan, alertas y recomendaciones
  Y la apertura queda en la auditoría

Escenario: escribir una nota
  Dado un paciente asignado
  Cuando el médico escribe una nota clínica
  Entonces se guarda sin posibilidad de edición; si se equivoca, escribe otra nota que la corrige

Escenario: el administrador no ve notas
  Dado un CLINIC_ADMIN
  Cuando intenta leer una nota clínica
  Entonces recibe 403 FORBIDDEN
```

### HU-47: Generar el reporte de un paciente

- **Actor:** `DOCTOR`, `PATIENT`.
- **Historia:** Como médico, quiero generar un reporte del paciente en PDF o HTML, para la consulta o para entregárselo.
- **Prioridad:** MVP. **Fase:** 7. **RF:** RF-82.

```gherkin
Escenario: reporte en PDF
  Dado un paciente asignado con datos
  Cuando el médico genera el reporte en PDF
  Entonces incluye AGP, métricas, eventos y plan, con la fecha y el periodo

Escenario: mismo contenido en HTML
  Dado el mismo paciente
  Cuando genera el reporte en HTML
  Entonces contiene la misma información que el PDF

Escenario: clínica demo
  Dado un paciente de la clínica demo
  Cuando se genera cualquier reporte
  Entonces lleva la marca "Datos simulados"

Escenario: el paciente genera el suyo
  Dado un paciente ACTIVE
  Cuando genera su propio reporte
  Entonces solo contiene sus datos
```

### HU-48: Ver los indicadores de la clínica

- **Actor:** `CLINIC_ADMIN`.
- **Historia:** Como administrador de la clínica, quiero ver indicadores de adopción y de control de la clínica sin ver datos clínicos individuales, para gestionar el servicio.
- **Prioridad:** MVP. **Fase:** 7. **RF:** RF-83.

```gherkin
Escenario: KPIs de adopción
  Dado una clínica con pacientes en distintos estados
  Cuando el administrador abre el panel
  Entonces ve pacientes por estado de cuenta, tasa de activación, adherencia y alertas abiertas

Escenario: sin datos individuales
  Dado el panel de KPIs
  Cuando el administrador revisa cualquier indicador
  Entonces no puede llegar a la glucosa ni a las dosis de un paciente

Escenario: conteos pequeños
  Dado un indicador con muy pocos pacientes
  Cuando se muestra
  Entonces se agrupa para no identificar a una persona
```

## M11: Mensajería y seguimiento

### HU-49: Conversar con mi equipo de atención

- **Actor:** `PATIENT`, `DOCTOR`.
- **Historia:** Como paciente, quiero escribirle a mi equipo y recibir respuesta, para resolver dudas entre consultas.
- **Prioridad:** Post-MVP. **Fase:** 11. **RF:** RF-84, RF-85.

```gherkin
Escenario: enviar un mensaje
  Dado un paciente ACTIVE con equipo asignado
  Cuando escribe un mensaje
  Entonces su médico principal y el equipo lo ven en el hilo del paciente

Escenario: aviso de no emergencia
  Dado el hilo de mensajes
  Cuando se abre
  Entonces muestra el aviso de que no es un canal de emergencias

Escenario: palabras de alarma
  Dado un mensaje con palabras de alarma
  Cuando se envía
  Entonces la app sugiere llamar a urgencias y avisa al equipo

Escenario: privacidad
  Dado un CLINIC_ADMIN
  Cuando intenta leer un hilo
  Entonces recibe 403 FORBIDDEN
```

### HU-50: Programar controles de seguimiento

- **Actor:** `DOCTOR`, `PATIENT`.
- **Historia:** Como médico, quiero programar controles de seguimiento y que el paciente los vea y los recuerde, para sostener la continuidad de la atención.
- **Prioridad:** Post-MVP. **Fase:** 11. **RF:** RF-86.

```gherkin
Escenario: programar un control
  Dado un paciente asignado
  Cuando el médico programa un control en una fecha futura
  Entonces el paciente lo ve y recibe un recordatorio antes de la fecha

Escenario: control cumplido o perdido
  Dado un control programado
  Cuando el médico lo cierra como realizado o pasa la fecha sin asistir
  Entonces queda DONE o MISSED y el seguimiento alimenta el riesgo de abandono

Escenario: control en fecha pasada
  Dado una fecha anterior a hoy
  Cuando intenta programar
  Entonces recibe VALIDATION_ERROR
```

## M12: Auditoría y cumplimiento

### HU-51: Auditar los accesos y consultar la auditoría

- **Actor:** `CLINIC_ADMIN`, `PLATFORM_ADMIN`.
- **Historia:** Como administrador, quiero ver quién accedió a qué y cuándo, para demostrar el cumplimiento y detectar usos indebidos.
- **Prioridad:** MVP (registro) y Post-MVP (consola e integridad). **Fase:** 3, 7 y 11. **RF:** RF-88, RF-89, RF-91, RF-92, RF-95.

```gherkin
Escenario: lectura clínica auditada
  Dado un médico asignado
  Cuando abre el detalle de un paciente
  Entonces se registra quién, a qué paciente, qué recurso y cuándo

Escenario: auditoría inalterable
  Dado una fila de auditoría
  Cuando alguien intenta actualizarla o borrarla
  Entonces el trigger lo impide

Escenario: consola sin contenido clínico
  Dado un CLINIC_ADMIN
  Cuando consulta la auditoría con filtros por usuario, acción y fecha
  Entonces ve las acciones sin valores de glucosa ni textos de notas

Escenario: verificar integridad
  Dado una cadena de hashes alterada en un entorno de prueba
  Cuando se ejecuta la verificación
  Entonces falla y señala la primera fila inconsistente

Escenario: eventos de seguridad
  Dado un inicio de sesión fallido o una reutilización de refresh token
  Cuando ocurre
  Entonces queda un evento de seguridad sin secretos
```

### HU-52: Gestionar mi consentimiento

- **Actor:** `PATIENT`.
- **Historia:** Como paciente, quiero conocer y poder retirar mi consentimiento para el tratamiento de mis datos, para controlar mi información.
- **Prioridad:** MVP. **Fase:** 3 y 4. **RF:** RF-90.

```gherkin
Escenario: consultar el consentimiento
  Dado un paciente ACTIVE
  Cuando abre "Privacidad"
  Entonces ve la versión que aceptó, la fecha y los usos descritos

Escenario: nueva versión
  Dado una versión nueva del consentimiento
  Cuando el paciente ingresa
  Entonces debe aceptarla antes de seguir registrando

Escenario: retirar el consentimiento
  Dado un paciente ACTIVE
  Cuando retira su consentimiento
  Entonces no se guardan nuevos registros y la clínica recibe un aviso para tramitar la baja o la retención
```

### HU-53: Ejercer mis derechos sobre mis datos

- **Actor:** `PATIENT`, `CLINIC_ADMIN`.
- **Historia:** Como paciente, quiero solicitar copia, corrección o supresión de mis datos, para ejercer mis derechos como titular.
- **Prioridad:** Post-MVP. **Fase:** 11 y 12. **RF:** RF-93, RF-94.

```gherkin
Escenario: solicitar una copia
  Dado un paciente ACTIVE
  Cuando solicita sus datos
  Entonces se crea una solicitud con plazo y estado y la clínica la tramita

Escenario: exportación
  Dado una solicitud aprobada
  Cuando se atiende
  Entonces el paciente recibe sus datos en JSON y FHIR

Escenario: baja y retención
  Dado un paciente DEACTIVATED
  Cuando se cumple la política de retención del tipo de dato
  Entonces los datos se anonimizan conservando estadísticas agregadas
```

## M13: Datos simulados

### HU-54: Importar la clínica demo generada por el simulador

- **Actor:** `PLATFORM_ADMIN`, `CLINIC_ADMIN` (demo).
- **Historia:** Como equipo, quiero importar una clínica demo completa generada por el simulador, para probar y demostrar Insumap sin datos reales.
- **Prioridad:** MVP. **Fase:** 4 y 9. **RF:** RF-97, RF-99, RF-100.

```gherkin
Escenario: backfill por el importador real
  Dado el simulador en modo backfill con una clínica de 5 médicos y unos 150 pacientes
  Cuando genera un Bundle FHIR R4 y un CSV
  Entonces el CLINIC_ADMIN demo los importa por el mismo flujo de HU-06 y HU-07 sin código especial

Escenario: escenarios inyectados
  Dado una semilla fija
  Cuando el simulador genera la serie de un paciente con "hipoglucemias nocturnas"
  Entonces el patrón aparece en sus datos y es reproducible

Escenario: sin datos reales
  Dado cualquier dato generado
  Cuando se revisa
  Entonces los nombres son ficticios, los correos usan example.test y los documentos son inválidos a propósito
```

### HU-55: Distinguir los datos simulados

- **Actor:** todos los roles.
- **Historia:** Como usuario, quiero ver claramente cuándo los datos son simulados, para no confundirlos con datos reales.
- **Prioridad:** MVP. **Fase:** 4. **RF:** RF-96.

```gherkin
Escenario: marca en pantalla
  Dado un usuario de una clínica con is_demo verdadero
  Cuando navega por cualquier pantalla
  Entonces ve la marca "Datos simulados"

Escenario: marca en la API y los reportes
  Dado una respuesta de la API o un reporte de la clínica demo
  Cuando se genera
  Entonces la API incluye simulated en verdadero y el reporte lleva "Datos simulados"

Escenario: clínica no demo
  Dado una clínica con is_demo falso
  Cuando se consultan sus datos
  Entonces no aparece la marca
```

### HU-56: Simular lecturas en vivo

- **Actor:** `PLATFORM_ADMIN` (equipo), sistema.
- **Historia:** Como equipo, quiero que el simulador envíe lecturas periódicas en vivo, para demostrar alertas y el dashboard en tiempo real.
- **Prioridad:** Post-MVP. **Fase:** 11. **RF:** RF-98, RF-99.

```gherkin
Escenario: lecturas en vivo
  Dado el simulador en modo live con tokens de pacientes demo
  Cuando envía una lectura cada intervalo configurado
  Entonces pasa por la misma validación en cadena y se evalúan las reglas de alerta

Escenario: disparar una alerta de demostración
  Dado el escenario "hipoglucemia nocturna"
  Cuando el simulador produce una lectura de 52 mg/dL
  Entonces se crea la alerta y aparece en el dashboard del médico asignado

Escenario: solo en la clínica demo
  Dado un token de una clínica no demo
  Cuando el simulador intenta enviar lecturas
  Entonces el sistema las rechaza con 403 FORBIDDEN
```

---

## Matriz de trazabilidad HU → RF

| HU | RF |
|---|---|
| HU-01 | RF-01, RF-05, RF-07, RF-08 |
| HU-02 | RF-03 |
| HU-03 | RF-02, RF-04, RF-06 |
| HU-04 | RF-09, RF-10, RF-11 |
| HU-05 | RF-12, RF-13, RF-15 |
| HU-06 | RF-14, RF-16, RF-18, RF-19, RF-21 |
| HU-07 | RF-17, RF-18, RF-19, RF-21 |
| HU-08 | RF-18, RF-20 |
| HU-09 | RF-22, RF-23, RF-25 |
| HU-10 | RF-24, RF-90 |
| HU-11 | RF-26 |
| HU-12 | RF-27, RF-28 |
| HU-13 | RF-29 |
| HU-14 | RF-14, RF-30 |
| HU-15 | RF-31, RF-33 |
| HU-16 | RF-32, RF-33 |
| HU-17 | RF-34 |
| HU-18 | RF-35, RF-36 |
| HU-19 | RF-37 |
| HU-20 | RF-38 |
| HU-21 | RF-39 |
| HU-22 | RF-40, RF-42 |
| HU-23 | RF-41 |
| HU-24 | RF-43 |
| HU-25 | RF-44, RF-45 |
| HU-26 | RF-46, RF-47 |
| HU-27 | RF-48 |
| HU-28 | RF-49, RF-50 |
| HU-29 | RF-51, RF-52, RF-54, RF-55 |
| HU-30 | RF-53, RF-55 |
| HU-31 | RF-56 |
| HU-32 | RF-57, RF-58, RF-61 |
| HU-33 | RF-59, RF-65 |
| HU-34 | RF-60 |
| HU-35 | RF-61, RF-62, RF-63 |
| HU-36 | RF-64, RF-66 |
| HU-37 | RF-67 |
| HU-38 | RF-68 |
| HU-39 | RF-69, RF-70, RF-71 |
| HU-40 | RF-75, RF-76 |
| HU-41 | RF-72 |
| HU-42 | RF-73 |
| HU-43 | RF-74, RF-87 |
| HU-44 | RF-77 |
| HU-45 | RF-78, RF-79 |
| HU-46 | RF-80, RF-81 |
| HU-47 | RF-82 |
| HU-48 | RF-83 |
| HU-49 | RF-84, RF-85 |
| HU-50 | RF-86 |
| HU-51 | RF-88, RF-89, RF-91, RF-92, RF-95 |
| HU-52 | RF-90 |
| HU-53 | RF-93, RF-94 |
| HU-54 | RF-97, RF-99, RF-100 |
| HU-55 | RF-96 |
| HU-56 | RF-98, RF-99 |

## Documentos relacionados

[Insumap.md](Insumap.md) · [Requerimientos.md](Requerimientos.md) · [Actores-y-permisos.md](Actores-y-permisos.md) · [API.md](API.md) · [Plan-de-commits.md](Plan-de-commits.md)
