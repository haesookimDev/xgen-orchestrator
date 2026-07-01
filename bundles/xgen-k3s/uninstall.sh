#!/usr/bin/env bash
# k3s 서버 제거 (k3s 설치 스크립트가 남긴 uninstaller 사용).
set -euo pipefail
if [ -x /usr/local/bin/k3s-uninstall.sh ]; then
  sudo /usr/local/bin/k3s-uninstall.sh
  echo "[xgen-k3s] uninstalled"
else
  echo "[xgen-k3s] k3s-uninstall.sh not found — k3s not installed?" >&2
  exit 1
fi
