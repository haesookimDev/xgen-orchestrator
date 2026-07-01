#!/usr/bin/env bash
set -euo pipefail
if command -v kubectl >/dev/null 2>&1; then
  kubectl get nodes -o wide
else
  sudo k3s kubectl get nodes -o wide
fi
