#!/usr/bin/env bash
# Despliega la API en el host EC2. Lo ejecuta GitHub Actions por SSM Run Command:
#   deploy.sh <imagen-ecr> <sha-del-backend>
# Pasos: secretos -> PostgreSQL -> migraciones (tag de db-schema.lock) ->
# contraseña de insumap_app -> semilla (solo con la base vacía) -> API -> /health.
set -euo pipefail

IMAGE="${1:?uso: deploy.sh <imagen> <sha>}"
SHA="${2:?uso: deploy.sh <imagen> <sha>}"
REGION="us-east-1"
ROOT=/opt/insumap
SRC="$ROOT/backend"
DBREPO="$ROOT/database"
COMPOSE=(docker compose -f "$SRC/infra/aws/host/compose.yaml")
UV_IMAGE=ghcr.io/astral-sh/uv:python3.13-bookworm-slim
export API_IMAGE="$IMAGE"

log() { echo "[deploy] $*"; }

# 1. Código del backend en el commit desplegado (trae db-schema.lock y la semilla).
if [ ! -d "$SRC/.git" ]; then
  git clone -q https://github.com/NicoalsD/insumap-backend.git "$SRC"
fi
git -C "$SRC" fetch -q origin
git -C "$SRC" checkout -q --force "$SHA"

# 2. Secretos: Secrets Manager -> archivos de entorno con permisos 600.
install -d -m 700 "$ROOT/env"
SECRET_JSON=$(aws secretsmanager get-secret-value --region "$REGION" \
  --secret-id insumap/app --query SecretString --output text)
WEB_ORIGIN=$(aws ssm get-parameter --region "$REGION" --name /insumap/web-origin \
  --query Parameter.Value --output text)
secret() { python3 -c 'import json,sys; print(json.loads(sys.argv[1])[sys.argv[2]])' "$SECRET_JSON" "$1"; }
if [ "$(secret initialized)" != "true" ]; then
  echo "insumap/app no tiene los valores reales (ver .agents/deployment.md, sección 5)" >&2
  exit 1
fi
POSTGRES_PASSWORD=$(secret postgres_password)
APP_DB_PASSWORD=$(secret app_db_password)
WEB_HOST="${WEB_ORIGIN#https://}"
umask 077
cat > "$ROOT/env/db.env" <<EOF
POSTGRES_USER=postgres
POSTGRES_PASSWORD=$POSTGRES_PASSWORD
POSTGRES_DB=insumap
EOF
cat > "$ROOT/env/api.env" <<EOF
APP_ENV=production
LOG_LEVEL=INFO
DATABASE_URL=postgresql://insumap_app:$APP_DB_PASSWORD@db:5432/insumap
CORS_ORIGINS=$WEB_ORIGIN
ALLOWED_HOSTS=$WEB_HOST,*.compute-1.amazonaws.com,localhost,127.0.0.1
WEB_APP_BASE_URL=$WEB_ORIGIN
API_DOCS_ENABLED=false
JWT_SECRET=$(secret jwt_secret)
MFA_ENCRYPTION_KEY=$(secret mfa_encryption_key)
CODE_HMAC_KEY=$(secret code_hmac_key)
APP_HMAC_KEY=$(secret app_hmac_key)
EOF
umask 022
MIGRATOR_URL="postgresql://postgres:$POSTGRES_PASSWORD@db:5432/insumap"

# 3. PostgreSQL.
"${COMPOSE[@]}" up -d --wait db
NET=insumap_default
psql_db() { "${COMPOSE[@]}" exec -T db psql -v ON_ERROR_STOP=1 -U postgres -d insumap -tA "$@"; }

# 4. Migraciones de insumap-database en la etiqueta fijada por db-schema.lock.
TAG=$(tr -d '[:space:]' < "$SRC/db-schema.lock")
if [ ! -d "$DBREPO/.git" ]; then
  git clone -q https://github.com/NicoalsD/insumap-database.git "$DBREPO"
fi
git -C "$DBREPO" fetch -q --tags origin
git -C "$DBREPO" checkout -q --force "$TAG"
log "migraciones $TAG"
docker run --rm --network "$NET" -v "$DBREPO":/src -w /src -v insumap-uv-cache:/root/.cache/uv \
  -e UV_PROJECT_ENVIRONMENT=/tmp/venv -e DATABASE_URL_MIGRATOR="$MIGRATOR_URL" \
  "$UV_IMAGE" uv run --frozen --no-dev alembic upgrade head

# 5. Contraseña del rol de la API (las migraciones crean los roles sin contraseña).
psql_db -c "ALTER ROLE insumap_app PASSWORD '$APP_DB_PASSWORD'" >/dev/null

# 6. Semilla de la Clínica del Valle, solo si la base no tiene usuarios.
USERS=$(psql_db -c "SELECT count(*) FROM iam.users")
if [ "$USERS" = "0" ]; then
  log "semilla de desarrollo"
  docker run --rm --network "$NET" -v "$SRC":/src -w /src -v insumap-uv-cache:/root/.cache/uv \
    -e UV_PROJECT_ENVIRONMENT=/tmp/venv --env-file "$ROOT/env/api.env" \
    -e DATABASE_URL_MIGRATOR="$MIGRATOR_URL" \
    "$UV_IMAGE" uv run --frozen python -m tests.support.dev_seed
fi

# 7. API con la imagen nueva.
log "API $IMAGE"
aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS --password-stdin "${IMAGE%%/*}" >/dev/null
"${COMPOSE[@]}" pull -q api
"${COMPOSE[@]}" up -d --wait --wait-timeout 120 api
for _ in $(seq 1 30); do
  if curl -fsS -H "Host: localhost" http://127.0.0.1/health >/dev/null; then
    log "salud OK"
    docker image prune -af --filter "until=72h" >/dev/null || true
    exit 0
  fi
  sleep 2
done
"${COMPOSE[@]}" logs --tail 80 api
exit 1
