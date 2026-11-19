# Despliegue

> Cómo se construye, configura y ejecuta Insumap en local y en AWS. Plan vigente desde el 2026-11-19: **todo en una cuenta de AWS (us-east-1)**, con un presupuesto de unos USD 72 de crédito y una vida de una semana. Reemplaza el plan anterior (Render, Vercel y Neon). Los pendientes están en la sección 13.

## 1. Visión general

| Pieza | Servicio de AWS | Qué se despliega | Notas |
|---|---|---|---|
| PWA (`insumap-frontend`) | S3 privado detrás de CloudFront (OAC) | `dist/` del build con `VITE_USE_MOCKS=false` | HTTPS con el dominio `*.cloudfront.net`; una CloudFront Function sirve `index.html` en los enlaces profundos |
| API (`insumap-backend`) | EC2 `t3.small` (Amazon Linux 2023) con Docker Compose | Imagen del `Dockerfile` publicada en ECR (`insumap-api`) | CloudFront envía `/api/*` y `/health` al puerto 80 del host |
| Base de datos | PostgreSQL 18 (`postgres:18-alpine`) en el mismo host | Volumen Docker sobre EBS gp3 cifrado de 20 GB | No tiene puerto publicado: solo la ve la API por la red de Compose |
| Migraciones | Repo `insumap-database` (Alembic) | `alembic upgrade head` en la etiqueta de `db-schema.lock` | Las ejecuta `deploy.sh` en cada despliegue (sección 6) |
| Secretos | Secrets Manager (`insumap/app`) con llave KMS propia (`alias/insumap-secrets`) | Llaves de la API y contraseñas de la base | Solo el rol del host los lee (sección 5) |
| Servicio de IA (`insumap-ai`) | No se despliega | Sin código todavía | Sin `AI_SERVICE_URL`, la API usa el respaldo por reglas |
| Simulador | No se despliega | Local | La semilla de desarrollo llena la base demo |

Todo está en una sola plantilla de CloudFormation: [`infra/aws/insumap.yaml`](../infra/aws/insumap.yaml), stack `insumap`. Desmontar es un solo `DeleteStack` (sección 14).

```text
Navegador ──HTTPS──> CloudFront ──/*──────────> S3 (PWA)
                          └──/api/*, /health──> EC2 :80 ──> api (uvicorn :8000) ──> db (PostgreSQL 18)
GitHub Actions ──OIDC──> ECR (imagen) + SSM Run Command (deploy.sh) / S3 + invalidación
```

Por qué así:

- **Mismo origen y HTTPS.** La cookie de refresh es `Secure` y `SameSite=Strict`, y el frontend llama a `/api/v1` relativo. Una sola distribución sirve la PWA y la API, así no hace falta CORS ni un dominio propio.
- **Costo.** El host `t3.small`, su IP elástica, el EBS, la llave KMS, el secreto y CloudFront cuestan menos de USD 10 por semana. RDS y Fargate costarían varias veces eso sin ganar nada para una demo de una semana.
- **Sin SSH.** El host no tiene puertos de administración abiertos. Se opera con SSM (Run Command y Session Manager).

Restricciones:

- El grupo de seguridad del host solo acepta el puerto 80 desde la lista administrada `com.amazonaws.global.cloudfront.origin-facing`. Por eso `FORWARDED_ALLOW_IPS=*` es seguro: todo lo que llega viene de CloudFront.
- La API nunca recibe las credenciales del superusuario de PostgreSQL. Se conecta como `insumap_app`.
- Es una sola instancia sin alta disponibilidad. Para una demo de una semana se acepta; no es una arquitectura de producción clínica.

## 2. Imagen Docker

El `Dockerfile` de la raíz tiene dos etapas (`uv` para resolver dependencias y `python:3.13-slim-bookworm` para ejecutar), corre como el usuario sin privilegios `app` (uid `10001`) y expone `8000`.

Reglas:

- El build no ejecuta pruebas. Las pruebas corren en CI antes de construir la imagen.
- `--proxy-headers` hace que uvicorn lea `X-Forwarded-For` y `X-Forwarded-Proto` de las IP listadas en `FORWARDED_ALLOW_IPS`. En AWS vale `*` (sección 1). Sin ella, todas las peticiones parecerían venir de CloudFront y el límite de intentos por IP del login y del MFA se compartiría entre todos los usuarios.
- Una instancia de uvicorn por contenedor (un worker).
- El `HEALTHCHECK` de la imagen llama a `127.0.0.1:8000/health`; por eso `ALLOWED_HOSTS` incluye `127.0.0.1` y `localhost`.

Prueba local de la imagen:

```bash
docker build -t insumap-api:local .
docker run --rm -p 8000:8000 --env-file .env --add-host=host.docker.internal:host-gateway \
  -e DATABASE_URL="postgresql://insumap_app:cambia-esto-password@host.docker.internal:5432/insumap" \
  insumap-api:local
curl -fsS http://localhost:8000/health
```

## 3. Entorno local

El entorno local no cambia: `~/Projects/insumap/dev/up.sh` (fuera de los repos) levanta PostgreSQL, la API y Vite, o se usa el `docker-compose.yml` de este repo. La base local nunca usa datos reales.

## 4. AWS

### 4.1 Recursos de la stack `insumap`

| Recurso | Nombre | Para qué |
|---|---|---|
| `AWS::EC2::Instance` + `AWS::EC2::EIP` | `insumap-host` | Host de Docker. La IP elástica fija el nombre `ec2-<ip>.compute-1.amazonaws.com` que usa CloudFront como origen |
| `AWS::EC2::SecurityGroup` | | Puerto 80 solo desde CloudFront |
| `AWS::IAM::Role` (host) | | SSM, lectura del secreto `insumap/app`, del parámetro `/insumap/web-origin` y de la imagen en ECR |
| `AWS::ECR::Repository` | `insumap-api` | Imágenes de la API; conserva las 5 últimas |
| `AWS::S3::Bucket` | `insumap-web-<cuenta>` | Build de la PWA; privado, solo CloudFront lo lee (OAC) |
| `AWS::CloudFront::Distribution` | | `/*` a S3 con caché; `/api/*` y `/health` al host sin caché (`CachingDisabled`, `AllViewerExceptHostHeader`) |
| `AWS::CloudFront::Function` | `insumap-spa-rewrite` | Rutas sin extensión a `/index.html`, solo en el comportamiento de S3. Las respuestas de error personalizadas no sirven: afectan a toda la distribución y convertirían los 404 de la API en HTML |
| `AWS::KMS::Key` + `AWS::SecretsManager::Secret` | `alias/insumap-secrets`, `insumap/app` | Secretos de la API (sección 5) |
| `AWS::SSM::Parameter` | `/insumap/web-origin` | `https://<distribución>.cloudfront.net`, para `CORS_ORIGINS`, `ALLOWED_HOSTS` y los enlaces de correo |
| `AWS::IAM::OIDCProvider` y dos roles | `insumap-github-backend-deploy`, `insumap-github-frontend-deploy` | GitHub Actions sin llaves de larga duración. Cada rol solo acepta su repo en la rama `develop` |

### 4.2 Variables de la API

`deploy.sh` escribe `/opt/insumap/env/api.env` (permisos `600`) en cada despliegue:

| Variable | Valor |
|---|---|
| `APP_ENV` | `production` (activa HSTS y exige `ALLOWED_HOSTS`) |
| `DATABASE_URL` | `postgresql://insumap_app:<secreto>@db:5432/insumap` |
| `CORS_ORIGINS`, `WEB_APP_BASE_URL` | Valor de `/insumap/web-origin` |
| `ALLOWED_HOSTS` | Host de CloudFront, `*.compute-1.amazonaws.com` (el Host que reenvía CloudFront), `localhost` y `127.0.0.1` |
| `API_DOCS_ENABLED` | `false` |
| `JWT_SECRET`, `MFA_ENCRYPTION_KEY`, `CODE_HMAC_KEY`, `APP_HMAC_KEY` | Del secreto `insumap/app` |
| `FORWARDED_ALLOW_IPS` | `*`, en `infra/aws/host/compose.yaml` |

El resto usa los valores por defecto de `Settings` ([`configuration.md`](configuration.md)).

### 4.3 Health check

- `GET /health` responde `200` sin consultar la base. Lo usan el `HEALTHCHECK` de Docker, `deploy.sh` y la verificación por CloudFront (`https://<distribución>/health`).

### 4.4 Scheduler

Todavía no hay scheduler en el código. Cuando exista, corre en el mismo host como un servicio más de `compose.yaml` con `SCHEDULER_ENABLED=true`. Hay una sola instancia, así que no hay riesgo de duplicar alertas.

## 5. Secretos

El secreto `insumap/app` es un JSON con `postgres_password`, `app_db_password`, `jwt_secret`, `mfa_encryption_key`, `code_hmac_key`, `app_hmac_key` e `initialized`.

- La stack lo crea con un valor de relleno (`initialized=false`). `deploy.sh` se niega a desplegar hasta que tenga los valores reales.
- Un operador escribe los valores una sola vez con `PutSecretValue`, generados con `os.urandom(32)` en base64. Nunca pasan por el repo, por un chat ni por un log.
- Está cifrado con la llave KMS propia de la stack, con rotación anual de la llave activada. Solo el rol del host puede descifrarla, y solo a través de Secrets Manager (`kms:ViaService`) y por HTTPS (`aws:SecureTransport`).
- No tiene rotación automática del valor: `MFA_ENCRYPTION_KEY` y `CODE_HMAC_KEY` no se pueden rotar sin re-cifrar los datos (sección 10).
- Auditoría: el historial de eventos de CloudTrail (90 días, sin costo) registra cada `GetSecretValue`.

## 6. Migraciones

Las migraciones son responsabilidad de `insumap-database`. El backend nunca corre Alembic desde su código ni llama a `metadata.create_all`.

En AWS, `deploy.sh` hace en cada despliegue:

1. Clona `insumap-database` en el host y hace checkout de la etiqueta de `db-schema.lock`.
2. Ejecuta `uv run alembic upgrade head` en un contenedor de `uv` conectado a la red de Compose, con el superusuario de PostgreSQL. `migrations/env.py` cambia a `insumap_migrator` por su cuenta.
3. Fija la contraseña de `insumap_app` (las migraciones crean los roles sin contraseña).
4. Si `iam.users` está vacía, corre la semilla de desarrollo (`tests.support.dev_seed`): Clínica del Valle, 13 pacientes y 14 días de lecturas CGM.

Reglas que siguen vigentes:

- **Expand, luego contract.** Una columna nueva entra nullable o con valor por defecto; la limpieza va en otra versión.
- **Sin "deshacer".** Una migración aplicada no se edita. Un error se corrige con una migración nueva.
- **Datos clínicos append-only.** Una corrección entra como fila nueva.
- **Orden.** Para subir el esquema, se publica la etiqueta `db-vX.Y.Z` y se sube `db-schema.lock` en el PR del backend que la necesita. El merge de ese PR despliega el esquema y el código juntos.

## 7. CI/CD

| Paso | Qué ocurre | Quién |
|---|---|---|
| 1. PR a `develop` | Corre la CI de cada repo (lint, tipos, pruebas, build). No despliega | CI |
| 2. Merge a `develop` | Merge commit con la cuenta del autor del PR | Autor del PR |
| 3. Despliegue del backend | Job `deploy` de `ci.yml`, tras `quality` en verde: construye la imagen, la publica en ECR con el SHA como etiqueta y ejecuta `infra/aws/host/deploy.sh` en el host por SSM Run Command | GitHub Actions (rol `insumap-github-backend-deploy`) |
| 4. Despliegue del frontend | Job `deploy` de `ci.yml`, tras `verify`: build con `VITE_USE_MOCKS=false`, `s3 sync` (`assets/` inmutable; `index.html` con `no-cache`) e invalidación de CloudFront | GitHub Actions (rol `insumap-github-frontend-deploy`) |
| 5. Verificación | `/health` responde `200` por CloudFront, un enlace profundo carga la PWA y un `/api/v1/...` desconocido devuelve un 404 en JSON | Quien desplegó |

Variables de GitHub Actions (variables del repo, no secretos: no contienen credenciales):

| Repo | Variables |
|---|---|
| `insumap-backend` | `AWS_REGION`, `AWS_DEPLOY_ROLE_ARN`, `ECR_REPOSITORY_URI`, `AWS_INSTANCE_ID` |
| `insumap-frontend` | `AWS_REGION`, `AWS_DEPLOY_ROLE_ARN`, `WEB_BUCKET`, `CLOUDFRONT_DISTRIBUTION_ID` |

Reglas:

- Se despliega desde `develop` porque `main` está muy atrasada; la demo es la integración vigente. Los releases a `main` siguen el flujo de [`workflow.md`](workflow.md).
- El job de despliegue no corre en PR ni si faltan las variables (`vars.AWS_DEPLOY_ROLE_ARN`).
- Nunca se fusiona un PR en rojo.

## 8. Versiones y etiquetas

| Etiqueta | Dónde | Significado |
|---|---|---|
| `vX.Y.Z` | Este repo, en `main` | Versión publicada del backend |
| `db-vX.Y.Z` | `insumap-database` | Versión del esquema. El backend la fija en `db-schema.lock` |

Cada imagen en ECR lleva como etiqueta el SHA del commit desplegado.

## 9. Rollback

### 9.1 Código

Volver a desplegar un commit anterior: revertir el cambio en `develop` con un PR `revert:`, o relanzar el job `deploy` de un run anterior en GitHub Actions. La imagen anterior sigue en ECR (se guardan 5).

### 9.2 Esquema

Se corrige hacia adelante: migración nueva, etiqueta nueva y `db-schema.lock` actualizado.

### 9.3 Datos

La base de la demo solo tiene datos simulados y se puede regenerar: borrar el volumen `insumap_db-data` en el host (por SSM) y volver a desplegar; `deploy.sh` migra y siembra de nuevo. No hay PITR.

## 10. Rotación de secretos

| Secreto | Efecto de rotarlo | Procedimiento |
|---|---|---|
| `jwt_secret` | Cierra todas las sesiones | Cambiar el valor en `insumap/app` y volver a desplegar |
| `mfa_encryption_key` | Los secretos TOTP guardados no se pueden leer | No rotar sin un plan de re-cifrado; en la demo, regenerar la base (9.3) |
| `code_hmac_key`, `app_hmac_key` | Invalida códigos de activación y de respaldo; reinicia contadores | Cambiar el valor y volver a desplegar |
| `postgres_password`, `app_db_password` | La API no conecta hasta el siguiente despliegue | Cambiar el valor y volver a desplegar; `deploy.sh` vuelve a fijar la contraseña de `insumap_app`. La del superusuario solo se aplica al crear el volumen |

Un secreto nunca se pega en un PR, en un issue ni en un chat.

## 11. Logs y observabilidad

- Los logs son JSON, con `request_id`, nivel y nombre del evento. Nunca aparecen tokens, contraseñas, documentos ni datos clínicos.
- En el host: `docker compose -p insumap logs api` por Session Manager. No se envían a CloudWatch Logs para no sumar costo.
- La salida de cada despliegue queda en el historial de SSM Run Command y en el log del job de GitHub Actions.

## 12. Lista de verificación de un despliegue

- [ ] CI en verde y PR fusionado con la cuenta del autor.
- [ ] `db-schema.lock` apunta a una etiqueta `db-vX.Y.Z` existente.
- [ ] Las variables nuevas de `Settings` están en `.env.example`, en `configuration.md` y, si aplica, en `deploy.sh`.
- [ ] El job `deploy` termina en verde y `https://<distribución>/health` responde `200`.
- [ ] Iniciar sesión con la cuenta de prueba y recargar la página mantiene la sesión (cookie de refresh).

## 13. Pendientes por verificar

| Tema | Por qué importa |
|---|---|
| Región us-east-1 para datos de Colombia | Solo hay datos simulados; con datos reales sería una transmisión internacional que exige contrato ([Cumplimiento-y-privacidad.md](../docs/Cumplimiento-y-privacidad.md), sección 11) |
| Correo (SMTP o proveedor por HTTPS) | Las invitaciones y recordatorios por correo no salen todavía |
| Hosting del servicio de IA | Cuando `insumap-ai` tenga código: otro servicio en el mismo `compose.yaml` si cabe en memoria |
| Memoria real de la API y PostgreSQL en 2 GB | El host tiene 2 GB de swap como margen; si no alcanza, cambiar `InstanceType` a `t3.medium` |
| Dominio propio | Hoy se usa `*.cloudfront.net` |

## 14. Desmontar

Al terminar la semana, borrar la stack `insumap` (CloudFormation, `DeleteStack`). Se eliminan el host con su volumen, la IP elástica, el bucket (vaciarlo antes), ECR, CloudFront, los roles y el proveedor OIDC. La llave KMS queda programada para borrarse en 7 días y el secreto se recupera durante 30 días salvo que se borre con `ForceDeleteWithoutRecovery`.

Relacionados: [`AGENTS.md`](../AGENTS.md), [`configuration.md`](configuration.md), [`workflow.md`](workflow.md), [`testing-plan.md`](testing-plan.md)
