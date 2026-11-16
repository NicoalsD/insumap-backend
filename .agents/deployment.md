# Despliegue del backend

> Cómo se construye, configura y ejecuta `insumap-backend` en local y en la nube. Piezas: API en Render, PostgreSQL 18 en Neon, migraciones desde `insumap-database`, frontend en Vercel (repo `insumap-frontend`) y servicio de IA (repo `insumap-ai`). Lo que aún no está decidido se marca como pendiente, en la sección 13.

## 1. Visión general

| Pieza | Plataforma | Qué se despliega | Notas |
|---|---|---|---|
| API | Render, Web Service con Docker | Imagen construida desde el `Dockerfile` de este repo | Health check en `/health` |
| Base de datos | Neon, PostgreSQL 18 | Proyecto con la rama `main` (producción) y ramas de desarrollo y vista previa | Pooler para la app, conexión directa para migraciones y diagnóstico |
| Migraciones | Repo `insumap-database` (Alembic) | `alembic upgrade head` con el rol `insumap_migrator` | Nunca desde el backend (sección 6) |
| Frontend | Vercel | Build de `insumap-frontend` | Su URL va en `CORS_ORIGINS` |
| Servicio de IA | Repo `insumap-ai` | Imagen propia, sin estado | Hosting pendiente (sección 13) |
| Scheduler | Dentro de la API (APScheduler) o cron externo | Recordatorios, evaluación de alertas, triage nocturno | Una sola instancia (sección 4.4) |

Restricciones:

- La API y la base corren en planes gratuitos o de bajo costo. El diseño debe funcionar con sus límites de memoria y de suspensión.
- El backend nunca tiene credenciales del rol `insumap_migrator` en su servicio de Render.
- El paciente no pierde la sesión por una suspensión del servicio: el frontend muestra "conectando" en lugar de fallar.

## 2. Imagen Docker

El `Dockerfile` tiene dos etapas. Ambas usan la misma imagen base, para que el entorno virtual de la primera funcione en la segunda.

```dockerfile
# syntax=docker/dockerfile:1

FROM python:3.13-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:<version-exacta> /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0
WORKDIR /app

# Primero solo las dependencias: esta capa se reutiliza mientras no cambie uv.lock
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-install-project --no-dev

# Después el código y la instalación del proyecto
COPY src ./src
RUN uv sync --locked --no-dev

FROM python:3.13-slim AS runtime
RUN groupadd --system --gid 10001 insumap \
 && useradd --system --uid 10001 --gid insumap --no-create-home insumap
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s \
  CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"
CMD ["sh", "-c", "exec uvicorn insumap.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers"]
```

Reglas:

- `<version-exacta>` se reemplaza por la versión fija de uv vigente al crear el `Dockerfile`. Nunca `latest`.
- El build no ejecuta pruebas. Las pruebas corren en CI antes de llegar aquí.
- El contenedor corre como usuario sin privilegios (uid `10001`). No hay `sudo`, ni escritura fuera de `/tmp`.
- `exec` en el `CMD` hace que `uvicorn` reciba `SIGTERM` directamente y cierre con elegancia.
- `PORT` la define Render. El valor `8000` solo aplica en local.
- `--proxy-headers` hace que uvicorn lea `X-Forwarded-For` y `X-Forwarded-Proto`, pero solo de las IP listadas en `FORWARDED_ALLOW_IPS`. El valor por defecto de uvicorn es `127.0.0.1`, así que sin esta variable todas las peticiones parecerían venir del proxy. El límite de intentos por IP del login y de la activación quedaría mal calculado. Por eso la variable va en el blueprint (sección 4.1) con el valor que confirme la documentación de Render (pendiente, sección 13).
- Una instancia de uvicorn por contenedor (un worker). El plan gratuito tiene poca memoria; escalar se hace con más instancias, no con más workers.
- `HEALTHCHECK` solo lo usa Docker. Render no lo lee: su chequeo se configura en `render.yaml` (sección 4.1).

`.dockerignore`:

```text
.git
.venv
.env
.env.*
!.env.example
__pycache__
*.py[cod]
.pytest_cache
.mypy_cache
.ruff_cache
.coverage
htmlcov
tests
docs
```

Build y prueba local de la imagen:

```bash
docker build -t insumap-api:local .
docker run --rm -p 8000:8000 --env-file .env \
  --add-host=host.docker.internal:host-gateway \
  -e DATABASE_URL="postgresql+psycopg://insumap_app:cambia-esto-password@host.docker.internal:5432/insumap" \
  insumap-api:local
curl -fsS http://localhost:8000/health
```

`host.docker.internal` apunta a la máquina anfitriona desde el contenedor. En Linux, `--add-host` lo habilita.

## 3. Docker Compose para local

La base de datos la levanta el compose de `insumap-database`, que aplica las migraciones del tag fijado:

```bash
(cd ../insumap-database && docker compose up -d)
uv sync
uv run uvicorn insumap.main:app --reload
```

Para probar la imagen completa con la base en la misma red de Compose, el repo puede incluir el compose de la base:

```yaml
include:
  - path: ../insumap-database/compose.yaml  # confirmar nombre del archivo en insumap-database

services:
  api:
    build: .
    env_file: .env
    environment:
      DATABASE_URL: postgresql+psycopg://insumap_app:cambia-esto-password@postgres:5432/insumap  # confirmar nombre del servicio de la base
    ports:
      - "8000:8000"
    depends_on:
      postgres:
        condition: service_healthy
```

Reglas:

- El desarrollo normal usa `uv` en el host. El contenedor de la API sirve para verificar la imagen.
- `.env` se copia desde `.env.example` y se reemplazan los marcadores `cambia-esto-...`. No se versiona.
- La base local nunca usa datos reales. Los datos de demostración vienen de `insumap-simulator`.
- Localhost se trata como contexto seguro para las cookies de refresh (`Secure`) en los navegadores soportados. Verificar en el navegador del equipo antes de depender de ello.

## 4. Render

### 4.1 Blueprint

La configuración vive en `render.yaml` en la raíz del repo. Cada secreto se declara con `sync: false`: el valor se pega en el panel de Render y nunca entra al repo.

```yaml
services:
  - type: web
    name: insumap-api
    runtime: docker
    dockerfilePath: ./Dockerfile
    plan: free
    region: ohio  # cercana a Neon us-east-2 (confirmar la región de Neon)
    branch: main
    autoDeploy: false
    healthCheckPath: /health
    envVars:
      # Valores fijos del blueprint
      - key: APP_ENV
        value: production
      - key: LOG_LEVEL
        value: INFO
      - key: JWT_ACCESS_MINUTES
        value: "15"
      - key: SMTP_PORT
        value: "587"
      - key: SCHEDULER_ENABLED
        value: "true"  # solo en la instancia que corre el scheduler (sección 4.4)
      - key: FORWARDED_ALLOW_IPS
        sync: false  # valor confirmado con la documentación de Render (sección 13)
      # Configuración del equipo, pegada en el panel
      - key: CORS_ORIGINS
        sync: false
      - key: REFRESH_TOKEN_DAYS
        sync: false
      - key: AI_SERVICE_URL
        sync: false
      - key: AI_TIMEOUT_SECONDS
        sync: false
      - key: SMTP_HOST
        sync: false
      - key: SMTP_USER
        sync: false
      - key: SMTP_FROM
        sync: false
      - key: VAPID_PUBLIC_KEY
        sync: false
      - key: VAPID_SUBJECT
        sync: false
      # Secretos: nunca en el repo
      - key: DATABASE_URL
        sync: false
      - key: DATABASE_URL_UNPOOLED
        sync: false
      - key: JWT_SECRET
        sync: false
      - key: FIELD_ENCRYPTION_KEY
        sync: false
      - key: LOOKUP_HMAC_KEY
        sync: false
      - key: AI_SERVICE_TOKEN
        sync: false
      - key: SMTP_PASSWORD
        sync: false
      - key: VAPID_PRIVATE_KEY
        sync: false
```

Reglas:

- `autoDeploy: false`: un merge a `main` no despliega solo. El despliegue lo dispara el flujo de la sección 7.
- Las variables con `sync: false` no tienen valor por defecto en el blueprint: el valor se pega en el panel. Si una variable de `Settings` no tiene valor por defecto y falta aquí, el servicio no arranca. Por eso esta lista cubre toda la tabla 6.1 de [`configuration.md`](configuration.md), salvo `INSUMAP_DATABASE_DIR`, que es solo de pruebas.
- Los secretos no usan `generateValue`. Su formato (por ejemplo, la clave de cifrado de 32 bytes en base64) lo genera el equipo con `openssl` y se pega en el panel.
- Una variable nueva entra al `render.yaml`, a `.env.example` y a la tabla 6.1 en el mismo PR.

### 4.2 Variables por grupo

| Grupo | Variables | Origen del valor |
|---|---|---|
| Aplicación | `APP_ENV`, `LOG_LEVEL`, `JWT_ACCESS_MINUTES`, `REFRESH_TOKEN_DAYS` | Valores fijos del blueprint o del panel |
| Base de datos | `DATABASE_URL`, `DATABASE_URL_UNPOOLED` | Neon, rama `main`, rol `insumap_app`. La URL directa también usa `insumap_app` |
| Seguridad | `JWT_SECRET`, `FIELD_ENCRYPTION_KEY`, `LOOKUP_HMAC_KEY` | Generados fuera de Render con `openssl`, según su formato |
| IA | `AI_SERVICE_URL`, `AI_SERVICE_TOKEN`, `AI_TIMEOUT_SECONDS` | Servicio de `insumap-ai`; el token se genera aparte |
| Web y red | `CORS_ORIGINS`, `FORWARDED_ALLOW_IPS` | URL de producción de la PWA en Vercel; IP del proxy de Render |
| Correo y notificaciones | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `VAPID_*` | Proveedor de correo y claves VAPID generadas una vez |
| Operación | `SCHEDULER_ENABLED` | Por instancia |

El detalle de cada variable está en [`configuration.md`](configuration.md), sección 6.

### 4.3 Health check y suspensión

- `GET /health` responde `200` con un cuerpo mínimo (`{"status": "ok"}`), sin detalles de componentes. Render lo consulta según `healthCheckPath`.
- `/health` no consulta la base. Así un arranque lento de Neon no marca el servicio como caído.
- El plan gratuito suspende el servicio tras un periodo sin tráfico. La primera petición tarda más. El frontend muestra "conectando" y reintenta, en lugar de mostrar un error.

### 4.4 Scheduler y réplicas

- El scheduler (recordatorios, evaluación de alertas, triage nocturno) corre dentro de la API con `SCHEDULER_ENABLED=true`, o como cron externo que llama a un comando.
- Dos instancias con el scheduler activo duplicarían alertas y recordatorios. Solo una instancia tiene `SCHEDULER_ENABLED=true`. Las demás lo tienen en `false`.
- La decisión final (scheduler interno o cron externo) está en la sección 13.

## 5. Neon

### 5.1 Proyecto, ramas y roles

| Rama | Uso | Quién la usa |
|---|---|---|
| `main` | Producción. La API de Render se conecta aquí | Render en producción |
| `dev` | Desarrollo compartido y pruebas manuales. Se crea desde `main` cuando hace falta | Equipo |
| Vista previa | Rama temporal para validar un cambio de esquema antes de migrar `main` | Quien valida el cambio |

Reglas:

- Las pruebas automatizadas no usan Neon. Usan Testcontainers con PostgreSQL 18 local.
- Una rama de vista previa se crea desde `main`, se usa y se elimina al terminar.
- Los roles son `insumap_app` (la API), `insumap_migrator` (migraciones, desde `insumap-database`) e `insumap_readonly` (diagnóstico). Sus contraseñas se generan una vez, se guardan en el gestor del equipo y no se escriben en el repo.

### 5.2 Conexiones

| Uso | Host | Driver y opciones | Variable |
|---|---|---|---|
| API | Host con `-pooler` en el nombre | `postgresql+psycopg://`, `?sslmode=require` | `DATABASE_URL` |
| Conexión directa de la API, si el pooler no sirve a una herramienta | Host directo, sin `-pooler`, con el rol `insumap_app` | `postgresql+psycopg://`, `?sslmode=require` | `DATABASE_URL_UNPOOLED` |
| Migraciones | Host directo, sin `-pooler`, con el rol `insumap_migrator` | Las ejecuta `insumap-database` con Alembic | No pasan por el backend ni por Render |

Notas:

- `DATABASE_URL_UNPOOLED` es la conexión directa de Neon. Es la misma forma que necesitan las migraciones, pero la API no la usa en el tráfico normal, y el servicio de Render nunca recibe credenciales de `insumap_migrator`.
- El pooler de Neon funciona en modo transacción. Con ese modo, los `set_config('app.clinic_id', ..., true)` por transacción funcionan, porque su efecto dura solo la transacción.
- En modo transacción no conviene reutilizar prepared statements del lado del cliente. Desactivarlos en psycopg es una decisión que se toma al conectar y se verifica con una prueba de integración. Verificar la forma de pasarlo con SQLAlchemy.
- Las migraciones usan la conexión directa porque pueden necesitar comandos de sesión que el pooler no garantiza.
- Neon exige TLS. `sslmode=require` es suficiente para la API; nunca se usa `sslmode=disable` contra Neon.

### 5.3 Ciclo de vida y respaldos

- **Suspensión:** el compute de Neon se suspende sin actividad. La primera consulta tras una suspensión tarda más; por eso `/health` no depende de la base.
- **Respaldo:** Neon ofrece restauración a un punto en el tiempo (PITR). La ventana depende del plan y se confirma en el panel antes de depender de ella.
- **Datos simulados:** las ramas copian el esquema y los datos. Según la sección 3.5 de `AGENTS.md`, no hay datos reales de pacientes en ningún entorno: todo viene de `insumap-simulator` o de fixtures de prueba.

## 6. Migraciones

Las migraciones son responsabilidad de `insumap-database`. El backend:

- nunca corre Alembic;
- nunca llama a `metadata.create_all`;
- nunca tiene credenciales de `insumap_migrator` en Render.

Flujo de un cambio de esquema:

1. PR en `insumap-database` con la migración nueva. Pasan sus pruebas de esquema.
2. Merge y etiqueta `db-vX.Y.Z`.
3. Migración en la rama de vista previa de Neon. Se comprueba con `insumap_readonly`.
4. Migración en `main` de Neon, con la conexión directa del rol `insumap_migrator`. Lo ejecuta el job de `insumap-database` en su entorno protegido, o un miembro del equipo con la URL fuera del repo.
5. PR en el backend que sube `db-schema.lock` a la etiqueta nueva y, si hace falta, el código que la usa. Va en el mismo PR que el cambio que la necesita.
6. Despliegue del backend (sección 7).

Reglas:

- **Expand, luego contract.** Una columna nueva entra nullable o con valor por defecto. El código nuevo tolera la columna vieja y la nueva durante el cambio. La limpieza (quitar la columna vieja) va en otra versión.
- **Sin "deshacer".** Una migración aplicada no se edita. Un error se corrige con una migración nueva.
- **Datos clínicos append-only.** Una corrección entra como fila nueva, no como `UPDATE` ni `DELETE`.
- **Orden de despliegue.** La base cambia antes que el código que la necesita. El código que no necesita el cambio se despliega antes sin problema.

## 7. CI/CD

| Paso | Qué ocurre | Quién |
|---|---|---|
| 1. PR a `develop` | Corren `commit-lint`, ruff, `mypy --strict`, `lint-imports`, pruebas unitarias, de API y de contrato; integración con el checkout de `insumap-database` en `db-schema.lock`; cobertura; Gitleaks y CodeQL. La imagen se construye sin publicar | CI |
| 2. Merge a `develop` | Merge commit, con la cuenta del autor del PR | Autor del PR |
| 3. Release | Rama `release/vX.Y.Z` desde `develop`, PR a `main` con notas en español | Quien prepara la versión |
| 4. Merge a `main` y a `develop` | Merge commit del release en `main`. Luego, el mismo release se fusiona de vuelta en `develop` para que no pierda los arreglos hechos en la rama de release | Autor del PR |
| 5. Etiqueta | `vX.Y.Z` sobre el commit de `main`, con release de GitHub y notas en español | Quien prepara la versión |
| 6. Despliegue | Un deploy hook de Render, disparado desde el workflow de release, construye la imagen de `main` y la despliega | CI, con el secreto del hook en GitHub |
| 7. Verificación | `/health` responde `200`, `/docs` carga y el inicio de sesión de la cuenta de prueba funciona | Quien desplegó |

Reglas:

- Nunca se fusiona un PR en rojo. Ningún PR queda abierto al terminar.
- La etiqueta y las notas no llevan atribución a IA.
- `db-schema.lock` apunta a una etiqueta existente antes de etiquetar la versión.
- El deploy hook es un secreto de GitHub. No aparece en el repo ni en los logs.

## 8. Versiones y etiquetas

| Etiqueta | Dónde | Significado |
|---|---|---|
| `vX.Y.Z` | Este repo, en `main` | Versión publicada del backend |
| `db-vX.Y.Z` | `insumap-database` | Versión del esquema. El backend la fija en `db-schema.lock` |

- Fase 0 → `v0.1.0`. MVP (fases 1 a 9) → `v0.9.0`. Entrega → `v1.0.0`.
- Incremento de `X` (mayor): cambio incompatible en `/api/v1` o en el contrato con la IA.
- Incremento de `Y` (menor): funcionalidad nueva compatible.
- Incremento de `Z` (parche): corrección sin cambio de contrato.
- Cada release registra en sus notas la versión de `db-schema.lock` que usa.

## 9. Rollback

El rollback tiene dos partes independientes: el código y los datos.

### 9.1 Código

1. Declarar el incidente y detener cualquier despliegue en curso.
2. Identificar el último despliegue sano en el historial de Render.
3. Volver a ese despliegue desde el panel de Render (o redesplegar la etiqueta anterior).
4. Verificar `/health`, `/docs` y el inicio de sesión de la cuenta de prueba.
5. Registrar el incidente en las notas de la versión siguiente.

### 9.2 Esquema

- Si la versión anterior del código funciona con el esquema actual (regla expand/contract), no se toca la base.
- Si no funciona, se corrige hacia adelante: una migración nueva en `insumap-database`, etiqueta nueva y `db-schema.lock` actualizado. Es la vía preferida.

### 9.3 Datos

Usar solo cuando un error de datos no se puede corregir con filas nuevas:

1. Crear en Neon una rama desde un punto en el tiempo anterior al error (PITR).
2. Comprobar los datos en esa rama con `insumap_readonly`.
3. Decidir con el equipo entre dos opciones:
   - corregir con filas nuevas en `main` (lo habitual, porque los datos clínicos son append-only);
   - apuntar `DATABASE_URL` a la rama restaurada. Las escrituras hechas después del punto de restauración se pierden. Esta opción requiere acuerdo explícito del equipo y queda registrada en las notas del incidente.
4. Cambiar el secreto `DATABASE_URL` en Render solo después de la comprobación.

### 9.4 Después del rollback

- El arreglo definitivo entra por PR, con su prueba de regresión. No se reescribe `main` ni se hace force-push.
- Si la reversión tiene que quedar en el historial, se hace con un commit `revert:` en un PR hacia `develop`.

## 10. Rotación de secretos

| Secreto | Efecto de rotarlo | Procedimiento |
|---|---|---|
| `JWT_SECRET` | Cierra todas las sesiones activas | Programar fuera de horario clínico; avisar al equipo de frontend |
| `AI_SERVICE_TOKEN` | El backend y la IA quedan desalineados si no se coordina | Coordinar la ventana con el equipo de `insumap-ai` y cambiar ambos lados en la misma ventana |
| `FIELD_ENCRYPTION_KEY` | Los campos cifrados no se leen con la clave nueva | No rotar sin un plan de re-cifrado aprobado por el equipo |
| `LOOKUP_HMAC_KEY` | Las búsquedas por documento dejan de coincidir | No rotar sin reconstruir los índices de búsqueda |
| Contraseñas de Neon | La conexión falla hasta actualizar Render | Restablecer en Neon y pegar el valor nuevo en Render |
| `SMTP_PASSWORD`, `VAPID_PRIVATE_KEY` | Las notificaciones fallan hasta actualizar | Rotar en el proveedor y pegar en Render |

Reglas: un secreto nunca se pega en un PR, en un issue ni en un chat. Si se expone, se rota de inmediato, aunque se borre el commit.

## 11. Logs y observabilidad

- Los logs son JSON, con `request_id`, nivel y nombre del evento.
- Nunca aparecen `Authorization`, `Cookie`, `password`, `token`, `secret`, documentos, nombres ni datos clínicos. Una prueba verifica la redacción (sección 6 de [`testing-plan.md`](testing-plan.md)).
- `LOG_LEVEL` vale `INFO` en producción. `DEBUG` solo en local.
- Render conserva los logs según el plan. Lo que se necesite para una auditoría se guarda en la auditoría del sistema (P09), no en los logs.

## 12. Lista de verificación antes de una versión

- [ ] CI en verde en todos los PR incluidos. Cada PR fusionado por la cuenta de su autor, con merge commit.
- [ ] `db-schema.lock` apunta a una etiqueta `db-vX.Y.Z` existente y aplicada a Neon `main`.
- [ ] Las variables nuevas están en `.env.example`, en `render.yaml`, en el panel de Render y en `configuration.md`.
- [ ] Ningún secreto ni valor por defecto inseguro en el repo (Gitleaks en verde).
- [ ] `docker build` y `docker run` de la imagen responden `200` en `/health`.
- [ ] `/docs` carga y `docs/openapi.json` está actualizado.
- [ ] `CORS_ORIGINS` incluye la URL de producción de Vercel.
- [ ] Hay un plan de reversión: el despliegue anterior identificado y PITR disponible en Neon.
- [ ] Las notas de la versión están en español y sin atribución a IA.
- [ ] La clínica demo muestra la marca "Datos simulados" en la API y en los reportes.
- [ ] El aviso de proyecto académico y de que no es un dispositivo médico aparece en la descripción de la API.

## 13. Pendientes por verificar

| Tema | Por qué importa |
|---|---|
| Región de Render y de Neon | Latencia para los usuarios de Colombia y cumplimiento |
| Memoria real de la API con la carga de la demo | Define el plan de Render |
| Hosting del servicio de IA: Render o un proveedor de modelos | Depende de la memoria que necesite el modelo de series de tiempo |
| Compatibilidad del pooler de Neon con `set_config` y prepared statements en psycopg 3 | Afecta el aislamiento por clínica |
| Scheduler interno o cron externo | Riesgo de duplicar alertas con más de una instancia |
| Ventana de PITR del plan de Neon | Define cuánto se puede retroceder |
| Documento `docs/Seguridad.md` con la lista de cabeceras y la duración del refresh | Parámetros de `Settings` y de las pruebas de seguridad |
| Procedimiento de rotación de `FIELD_ENCRYPTION_KEY` y `LOOKUP_HMAC_KEY` | Hoy solo hay una prohibición, sin procedimiento escrito |
| Swagger en producción | Si se apaga, se hace con un campo de `Settings` |
| Valor de `FORWARDED_ALLOW_IPS` en Render | Sin él, el límite de intentos por IP cuenta todas las peticiones como una sola |

Relacionados: [`AGENTS.md`](../AGENTS.md) (secciones 4, 5.5 y 6), [`configuration.md`](configuration.md), [`api-documentation.md`](api-documentation.md), [`testing-plan.md`](testing-plan.md), [`workflow.md`](workflow.md)
