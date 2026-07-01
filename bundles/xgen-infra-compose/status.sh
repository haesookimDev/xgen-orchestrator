#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/k3s-infra"
PROJECT="${COMPOSE_PROJECT:-xgen-infra}"
docker compose -p "$PROJECT" ps
