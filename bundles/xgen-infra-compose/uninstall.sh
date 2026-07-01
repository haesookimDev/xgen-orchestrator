#!/usr/bin/env bash
# 제거 — 컨테이너/네트워크 down. 데이터 볼륨은 보존(명시 삭제는 -v 후속).
# 각 Job은 tarball을 새 임시 dir에 추출하므로 install의 .env가 없다 →
# compose 변수 보간 경고 억제용 더미 .env를 생성(값은 down에 무의미).
set -euo pipefail
cd "$(dirname "$0")/k3s-infra"
cat > .env <<'EOF'
POSTGRES_USER=x
POSTGRES_PASSWORD=x
POSTGRES_DB=x
POSTGRES_PORT=5432
REDIS_PORT=6379
REDIS_PASSWORD=x
QDRANT_HTTP_PORT=6333
QDRANT_GRPC_PORT=6334
MINIO_API_PORT=9000
MINIO_CONSOLE_PORT=9001
MINIO_ROOT_USER=x
MINIO_ROOT_PASSWORD=x
EOF
PROJECT="${COMPOSE_PROJECT:-xgen-infra}"
docker compose -p "$PROJECT" down
echo "[xgen-infra-compose] uninstall complete (data volumes kept)"
