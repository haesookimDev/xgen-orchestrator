#!/usr/bin/env bash
# xgen-agent 원클릭 설치 (CP의 /install.sh 로 서빙).
# 사용: curl -sSL https://<cp>/install.sh | sudo bash -s -- --token <JOIN> --server https://<cp>
#
# 신뢰 모델 (P0-1, docs/design/02-enrollment-security.md):
#   - 이 스크립트 다운로드는 CP의 신뢰 CA TLS로 검증된다 (curl이 정상 TLS 검증, TOFU 아님).
#   - 받은 에이전트 바이너리는 cosign 서명으로 검증한다 (무결성+진위).
set -euo pipefail

JOIN_TOKEN=""
SERVER=""
INSTALL_DIR="/etc/xgen-agent"
BIN_PATH="/usr/local/bin/xgen-agent"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --token)  JOIN_TOKEN="$2"; shift 2 ;;
    --server) SERVER="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
done

[[ -n "$JOIN_TOKEN" ]] || { echo "--token required" >&2; exit 1; }
[[ -n "$SERVER" ]]     || { echo "--server required" >&2; exit 1; }

# 1. OS/arch 감지
OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
case "$(uname -m)" in
  x86_64)  ARCH="amd64" ;;
  aarch64|arm64) ARCH="arm64" ;;
  *) echo "unsupported arch: $(uname -m)" >&2; exit 1 ;;
esac

echo "[xgen-agent] os=${OS} arch=${ARCH} server=${SERVER}"

# 2. 바이너리 다운로드 (신뢰 CA TLS) + cosign 서명 검증
#    TODO:
#      curl -fsSL "${SERVER}/dist/xgen-agent-${OS}-${ARCH}" -o "${BIN_PATH}.new"
#      curl -fsSL "${SERVER}/dist/xgen-agent-${OS}-${ARCH}.sig" -o "${BIN_PATH}.sig"
#      cosign verify-blob --key <pub> --signature "${BIN_PATH}.sig" "${BIN_PATH}.new"
#      install -m 0755 "${BIN_PATH}.new" "${BIN_PATH}"

# 3. 설정 디렉토리 (0700) + config.yaml
install -d -m 0700 "${INSTALL_DIR}"
# TODO: cat > ${INSTALL_DIR}/config.yaml  (server, join_token)

# 4. systemd 유닛 설치 + 기동 (부팅 시 등록 -> stream)
#    TODO: write /etc/systemd/system/xgen-agent.service
#          systemctl daemon-reload && systemctl enable --now xgen-agent

echo "[xgen-agent] 설치 스켈레톤 — TODO 채우면 등록까지 원클릭."
