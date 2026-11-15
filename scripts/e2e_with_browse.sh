#!/usr/bin/env bash
# End to end across both services: submit -> screen -> announce (coauthored-submit), then
# serve the paper (coauthored-browse) from the same SQLite database and local store.
# usage: scripts/e2e_with_browse.sh BROWSE_DIR PAPER.json PAPER.pdf [ANNOUNCE_ISO] [WORK_DIR]
set -euo pipefail
HERE=$(cd "$(dirname "$0")/.." && pwd)
BROWSE=$(cd "$1" && pwd); FIELDS=$(realpath "$2"); PDF=$(realpath "$3")
WHEN=${4:-2026-11-16T20:00:00Z}; WORK=${5:-$(mktemp -d)}
UV="uvx --from uv>=0.9 uv"
mkdir -p "$WORK/store"
OUT=$(cd "$HERE" && PYTHONPATH="$HERE" $UV run python scripts/e2e_publish.py "$WORK/e2e.db" "$WORK/store" "$FIELDS" "$PDF" "$WHEN")
echo "$OUT"
PID=$(echo "$OUT" | grep -o 'coauthored:[0-9]\{4\}\.[0-9]\{5\}' | head -1 | cut -d: -f2)
YYMM=${PID:0:4}
echo '{}' > "$WORK/store/reasons.json.tmp"; [ -f "$WORK/store/reasons.json" ] || mv "$WORK/store/reasons.json.tmp" "$WORK/store/reasons.json"; rm -f "$WORK/store/reasons.json.tmp"
PRIMARY=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['primary_category'])" "$FIELDS")
(cd "$BROWSE" && $UV run python "$HERE/scripts/e2e_check_browse.py" "$WORK/e2e.db" "$WORK/store" "$PID" \
  "/list/$PRIMARY/20${YYMM:0:2}-${YYMM:2:2}" "$PDF" "$WORK/out")
