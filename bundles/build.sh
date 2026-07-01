#!/usr/bin/env bash
# build.sh — 번들 레시피(우리 저장소) + 외부 xgen-infra 자산(빌드 시 참조)을
# 조립해 아티팩트(tar.gz)로 패키징하고 sha256 출력. (15-real-infra-packaging.md §4)
#
# 사용:
#   bundles/build.sh <recipe_dir> <out.tar.gz>
#
#   recipe_dir 예: bundles/xgen-infra-compose (manifest.json + *.sh [+ sources.txt])
#   sources.txt(선택): "<src-relative-to-XGEN_INFRA_PATH>  <dest-in-bundle>" 줄 목록.
#     각 줄의 자산을 빌드 시점에 $XGEN_INFRA_PATH 에서 복사(비벤더 — 커밋엔 없음).
#
# 예:
#   XGEN_INFRA_PATH=~/Desktop/orche/xgen-infra \
#     bundles/build.sh bundles/xgen-infra-compose dist/xgen-infra-compose.tar.gz
#
# 산출 tarball 루트 = 에이전트 실행 cwd. manifest의 entry(예: "bash install.sh")가
# 가리키는 스크립트가 루트에 있어야 한다.
set -euo pipefail

RECIPE="${1:?usage: build.sh <recipe_dir> <out.tar.gz>}"
OUT="${2:?usage: build.sh <recipe_dir> <out.tar.gz>}"

[ -d "$RECIPE" ] || { echo "no such recipe dir: $RECIPE" >&2; exit 1; }
[ -f "$RECIPE/manifest.json" ] || { echo "recipe has no manifest.json: $RECIPE" >&2; exit 1; }

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

# 1) 레시피 파일 복사 (sources.txt 제외 — 빌드 지시서라 번들에 넣지 않음)
for f in "$RECIPE"/*; do
  [ "$(basename "$f")" = "sources.txt" ] && continue
  cp -R "$f" "$STAGE/"
done

# 2) sources.txt 의 외부 자산을 $XGEN_INFRA_PATH 에서 조립
if [ -f "$RECIPE/sources.txt" ]; then
  : "${XGEN_INFRA_PATH:?sources.txt present but XGEN_INFRA_PATH not set}"
  [ -d "$XGEN_INFRA_PATH" ] || { echo "XGEN_INFRA_PATH not a dir: $XGEN_INFRA_PATH" >&2; exit 1; }
  while read -r SRC DEST || [ -n "$SRC" ]; do
    case "$SRC" in ''|'#'*) continue ;; esac   # 빈 줄/주석 스킵
    [ -e "$XGEN_INFRA_PATH/$SRC" ] || { echo "source missing: $SRC" >&2; exit 1; }
    mkdir -p "$STAGE/$(dirname "$DEST")"
    cp -R "$XGEN_INFRA_PATH/$SRC" "$STAGE/$DEST"
  done < "$RECIPE/sources.txt"
fi

# 2.5) 비밀/VCS 아티팩트 제거 — 번들에 .env(실 시크릿)·.git 이 섞이지 않도록.
#      install.sh 가 .env 를 params/secret 로 새로 생성한다.
find "$STAGE" \( -name '.env' -o -name '.git' \) -exec rm -rf {} +

# 3) BUILD_INFO — xgen-infra git ref(built_from) 추적성
REF="unknown"
if [ -n "${XGEN_INFRA_PATH:-}" ] && git -C "$XGEN_INFRA_PATH" rev-parse --short HEAD >/dev/null 2>&1; then
  REF="$(git -C "$XGEN_INFRA_PATH" rev-parse --short HEAD)"
fi
{
  echo "built_from=$REF"
  echo "recipe=$(basename "$RECIPE")"
} > "$STAGE/BUILD_INFO"

# 4) 패키징 + sha256
mkdir -p "$(dirname "$OUT")"
tar -C "$STAGE" -czf "$OUT" .
if command -v sha256sum >/dev/null 2>&1; then
  SHA=$(sha256sum "$OUT" | cut -d' ' -f1)
else
  SHA=$(shasum -a 256 "$OUT" | cut -d' ' -f1)
fi
echo "built $OUT (built_from=$REF)"
echo "sha256 $SHA"
