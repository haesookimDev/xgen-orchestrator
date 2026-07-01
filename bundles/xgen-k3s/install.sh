#!/usr/bin/env bash
# xgen-k3s 부트스트랩 — WSL(Linux)에서 setup-k3s.sh의 'k3s' 서브커맨드 실행.
# k3s만 설치(내장 traefik 비활성). 전체 인프라/앱(infra/apps)은 후속 액션.
#
# 전제: sudo 사용 가능(WSL 기본 passwordless), 인터넷(get.k3s.io) 도달.
# params(env): HOST_IP(선택, 비우면 자동감지), FORCE(재설치 시 true).
set -euo pipefail
cd "$(dirname "$0")"

SCRIPT="xgen-infra/k3s/scripts/setup-k3s.sh"
[ -f "$SCRIPT" ] || { echo "[xgen-k3s] missing $SCRIPT in bundle" >&2; exit 1; }

echo "[xgen-k3s] bootstrapping k3s via setup-k3s.sh k3s"
bash "$SCRIPT" k3s
echo "[xgen-k3s] k3s bootstrap complete"
