#!/bin/sh
# 샘플 솔루션 설치 (실제 xgen-infra에서는 compose up / setup-k3s.sh 가 들어갈 자리).
set -e
echo "[sample] installing on $(hostname) ($(uname -s)/$(uname -m))"
if command -v docker >/dev/null 2>&1; then
  echo "[sample] docker: $(docker --version 2>/dev/null || echo present)"
  echo "[sample] would run: docker compose up -d"
else
  echo "[sample] docker not present — demo mode (no real containers)"
fi
echo "[sample] install complete"
