"""The Python schema loader's conversion and statement splitting on the real dump."""
from submit.classic_schema import converted_sql, statements


def test_conversion_is_utf8mb4_without_definer():
    sql = converted_sql()
    assert "latin1" not in sql and "utf8mb3" not in sql
    assert "DEFINER=" not in sql
    assert "utf8mb4" in sql


def test_statements_cover_every_table():
    stmts = list(statements(converted_sql()))
    creates = [s for s in stmts if s.lstrip().upper().startswith("CREATE TABLE")]
    assert len(creates) == converted_sql().count("CREATE TABLE")
    assert all(s.rstrip().endswith(";") for s in stmts)
    assert not any(s.lstrip().startswith("--") for s in stmts)
