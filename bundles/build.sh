#!/usr/bin/env bash
# build.sh — 솔루션 디렉토리를 번들 아티팩트(tar.gz)로 패키징하고 sha256 출력.
#
# 사용:
#   bundles/build.sh <solution_dir> <out.tar.gz>
#
# 실제 xgen-infra 번들 (비벤더, 빌드 시 참조 — 01-repo-structure.md):
#   bundles/build.sh "$XGEN_INFRA_PATH/compose/full-stack" dist/xgen-docker.tar.gz
#   → compose/setup-k3s.sh 등 실제 설치 자산을 묶는다. manifest는 해당 솔루션의 manifest.json.
#
# 산출 tarball 안에 manifest의 entry(예: "sh install.sh")가 가리키는 스크립트가 있어야 한다.
set -euo pipefail

SRC="${1:?usage: build.sh <solution_dir> <out.tar.gz>}"
OUT="${2:?usage: build.sh <solution_dir> <out.tar.gz>}"

[ -d "$SRC" ] || { echo "no such dir: $SRC" >&2; exit 1; }
mkdir -p "$(dirname "$OUT")"
tar -C "$SRC" -czf "$OUT" .

if command -v sha256sum >/dev/null 2>&1; then
  SHA=$(sha256sum "$OUT" | cut -d' ' -f1)
else
  SHA=$(shasum -a 256 "$OUT" | cut -d' ' -f1)
fi
echo "built $OUT"
echo "sha256 $SHA"
