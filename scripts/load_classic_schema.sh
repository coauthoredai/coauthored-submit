#!/usr/bin/env bash
# Load arxiv-base's classic schema (arxiv/db/arxiv_db_schema.sql, from the pinned commit)
# into an EMPTY MySQL 8 database, with every table converted to utf8mb4 so that titles,
# abstracts and names outside Latin-1 are stored correctly.
#
#   scripts/load_classic_schema.sh [mysql client options] DATABASE
#   MYSQL="docker compose exec -T mysql mysql" scripts/load_classic_schema.sh -ucoauthored -p... coauthored
#   scripts/load_classic_schema.sh --print > classic.sql      # just write the converted SQL
#
# The dump's view DEFINER (arXiv's own host) is dropped, so the view belongs to the loading
# user. The dump starts each table with DROP TABLE IF EXISTS, so this refuses to run against a
# database that already has arXiv_metadata.
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-.venv/bin/python}"
SCHEMA="$("$PY" -c 'import pathlib, arxiv.db; print(pathlib.Path(arxiv.db.__file__).with_name("arxiv_db_schema.sql"))')"

convert() {
  sed -E \
    -e 's/CHARSET=(latin1|utf8mb3)/CHARSET=utf8mb4/g' \
    -e 's/COLLATE=(latin1|utf8mb3)_[a-z0-9_]+/COLLATE=utf8mb4_0900_ai_ci/g' \
    -e 's/CHARACTER SET (latin1|utf8mb3) COLLATE (latin1|utf8mb3)_[a-z0-9_]+/CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci/g' \
    -e 's/CHARACTER SET (latin1|utf8mb3)/CHARACTER SET utf8mb4/g' \
    -e '/^\/\*!50013 DEFINER=/d' \
    "$SCHEMA"
}

if [[ "${1:-}" == "--print" ]]; then convert; exit 0; fi

MYSQL_CMD=(${MYSQL:-mysql})
if [[ -n "$("${MYSQL_CMD[@]}" "$@" -N -e "SHOW TABLES LIKE 'arXiv_metadata'")" ]]; then
  echo "refusing: arXiv_metadata already exists in this database" >&2
  exit 1
fi
convert | "${MYSQL_CMD[@]}" "$@"
echo "classic schema loaded"
