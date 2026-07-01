#!/usr/bin/env bash
# xgen-infra-compose 설치 — params/secret(env)로 .env 생성 후 docker compose up.
# 비밀(패스워드)은 secret_refs로 주입되어 env에만 존재. 포트는 params로 조정 가능.
set -euo pipefail
cd "$(dirname "$0")/k3s-infra"

: "${POSTGRES_PASSWORD:?secret POSTGRES_PASSWORD required (xgenctl install ... -s POSTGRES_PASSWORD)}"
: "${REDIS_PASSWORD:?secret REDIS_PASSWORD required}"
: "${MINIO_ROOT_PASSWORD:?secret MINIO_ROOT_PASSWORD required}"

cat > .env <<EOF
POSTGRES_USER=${POSTGRES_USER:-ailab}
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
POSTGRES_DB=${POSTGRES_DB:-xgen}
POSTGRES_PORT=${POSTGRES_PORT:-5432}
REDIS_PORT=${REDIS_PORT:-6379}
REDIS_PASSWORD=${REDIS_PASSWORD}
QDRANT_HTTP_PORT=${QDRANT_HTTP_PORT:-6333}
QDRANT_GRPC_PORT=${QDRANT_GRPC_PORT:-6334}
MINIO_API_PORT=${MINIO_API_PORT:-9000}
MINIO_CONSOLE_PORT=${MINIO_CONSOLE_PORT:-9001}
MINIO_ROOT_USER=${MINIO_ROOT_USER:-minio}
MINIO_ROOT_PASSWORD=${MINIO_ROOT_PASSWORD}
EOF

PROJECT="${COMPOSE_PROJECT:-xgen-infra}"
echo "[xgen-infra-compose] docker compose up (project=$PROJECT)"
docker compose -p "$PROJECT" up -d
docker compose -p "$PROJECT" ps
echo "[xgen-infra-compose] install complete"
