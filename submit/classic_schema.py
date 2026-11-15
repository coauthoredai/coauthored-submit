"""Load arxiv-base's classic schema into an empty MySQL database, converted to utf8mb4.

The same conversion as scripts/load_classic_schema.sh, in Python, so it can run where there
is no mysql client (a Cloud Run job): latin1/utf8mb3 tables become utf8mb4, and the view's
DEFINER (arXiv's own host) is dropped so the view belongs to the loading user. The schema
file is read from the installed arxiv-base package (MIT, arXiv, Inc.); nothing is copied
into this repository.
"""
import re
from pathlib import Path
from typing import Iterator

import arxiv.db
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

SCHEMA = Path(arxiv.db.__file__).with_name("arxiv_db_schema.sql")

_SUBS = [
    (re.compile(r"CHARSET=(latin1|utf8mb3)"), "CHARSET=utf8mb4"),
    (re.compile(r"COLLATE=(latin1|utf8mb3)_[a-z0-9_]+"), "COLLATE=utf8mb4_0900_ai_ci"),
    (re.compile(r"CHARACTER SET (latin1|utf8mb3) COLLATE (latin1|utf8mb3)_[a-z0-9_]+"),
     "CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"),
    (re.compile(r"CHARACTER SET (latin1|utf8mb3)"), "CHARACTER SET utf8mb4"),
]


def converted_sql(path: Path = SCHEMA) -> str:
    lines = [l for l in path.read_text(encoding="utf-8").splitlines()
             if not l.startswith("/*!50013 DEFINER=")]
    text = "\n".join(lines) + "\n"
    for pattern, repl in _SUBS:
        text = pattern.sub(repl, text)
    return text


def statements(sql: str) -> Iterator[str]:
    """Split a mysqldump file (no procedures or triggers) into statements: a statement ends
    at a line ending with ';'. Comment-only lines are skipped."""
    buf: list[str] = []
    for line in sql.splitlines():
        if not buf and (not line.strip() or line.startswith("--")):
            continue
        buf.append(line)
        if line.rstrip().endswith(";"):
            yield "\n".join(buf)
            buf = []
    if any(l.strip() for l in buf):
        yield "\n".join(buf)


def load(engine: Engine) -> int:
    """Run the converted schema on an empty MySQL database; returns the statement count."""
    if engine.dialect.name != "mysql":
        raise RuntimeError("the classic schema dump is MySQL-only; on SQLite use init-db")
    if inspect(engine).has_table("arXiv_metadata"):
        raise RuntimeError("refusing: arXiv_metadata already exists in this database")
    count = 0
    with engine.begin() as conn:
        for stmt in statements(converted_sql()):
            conn.exec_driver_sql(stmt)
            count += 1
    return count
