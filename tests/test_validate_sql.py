"""Tests for skills/text2sql-loweiwei/scripts/validate_sql.py."""

import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VS_PATH = REPO_ROOT / "skills" / "text2sql-loweiwei" / "scripts" / "validate_sql.py"
RUN_PATH = REPO_ROOT / "skills" / "text2sql-loweiwei" / "scripts" / "run.py"


def _load():
    spec = importlib.util.spec_from_file_location("validate_sql", VS_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vs = _load()


def _load_run():
    spec = importlib.util.spec_from_file_location("text2sql_run", RUN_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


run = _load_run()

SCHEMA = """
CREATE TABLE Students (sid INTEGER PRIMARY KEY, name TEXT, dept TEXT);
CREATE TABLE Courses (cid INTEGER PRIMARY KEY, title TEXT, professor TEXT, year INTEGER);
CREATE TABLE Enrollments (sid INTEGER, cid INTEGER, score INTEGER, PRIMARY KEY (sid, cid));
"""


def test_valid_select_passes():
    ok, err = vs.validate(SCHEMA, "SELECT name FROM Students WHERE dept = 'CS';")
    assert ok, err


def test_nonexistent_column_fails():
    ok, err = vs.validate(SCHEMA, "SELECT nonexistent FROM Students;")
    assert not ok
    assert "nonexistent" in err.lower() or "no such column" in err.lower()


def test_nonexistent_table_fails():
    ok, err = vs.validate(SCHEMA, "SELECT 1 FROM NoSuchTable;")
    assert not ok


def test_syntax_error_fails():
    ok, err = vs.validate(SCHEMA, "SELECT FROM WHERE;")
    assert not ok


def test_empty_sql_fails():
    ok, err = vs.validate(SCHEMA, "")
    assert not ok


def test_ddl_rejected():
    ok, err = vs.validate(SCHEMA, "CREATE TABLE X (id INTEGER);")
    assert not ok
    assert "DDL" in err or "DML" in err


def test_dml_rejected():
    for stmt in ("INSERT INTO Students VALUES (99, 'x', 'CS')",
                 "UPDATE Students SET name = 'y' WHERE sid = 1",
                 "DELETE FROM Students"):
        ok, err = vs.validate(SCHEMA, stmt)
        assert not ok, f"should reject: {stmt}"


def test_multiple_statements_rejected():
    ok, err = vs.validate(SCHEMA, "SELECT 1; SELECT 2")
    assert not ok


def test_trailing_semicolon_ok():
    ok, err = vs.validate(SCHEMA, "SELECT 1 FROM Students;")
    assert ok, err


def test_join_passes():
    sql = (
        "SELECT s.name FROM Students s "
        "JOIN Enrollments e ON s.sid = e.sid "
        "JOIN Courses c ON e.cid = c.cid "
        "WHERE c.title = 'AI Foundations'"
    )
    ok, err = vs.validate(SCHEMA, sql)
    assert ok, err


def test_marker_payload_preserves_schema_for_validation():
    raw = (
        '{"task_id":"task_1","question":"List students",'
        '"db_schema":"CREATE TABLE Students (sid INTEGER, name TEXT);"}'
        "\n__AIASE_SQL_V1__\n"
        "SELECT name FROM Students"
    )

    payload = run.parse_payload(raw)

    assert payload["task_id"] == "task_1"
    assert payload["db_schema"].startswith("CREATE TABLE Students")
    assert payload["sql"] == "SELECT name FROM Students"


def test_marker_payload_rejects_non_object_input():
    raw = '[1, 2]\n__AIASE_SQL_V1__\nSELECT 1'

    try:
        run.parse_payload(raw)
    except ValueError as exc:
        assert "not an object" in str(exc)
    else:
        raise AssertionError("non-object payload should fail")


def test_marker_text_inside_question_does_not_split_payload():
    raw = (
        '{"task_id":"task_1","question":"Explain __AIASE_SQL_V1__ safely",'
        '"db_schema":"CREATE TABLE T (value TEXT);"}'
        "\n__AIASE_SQL_V1__\n"
        "SELECT value FROM T"
    )

    payload = run.parse_payload(raw)

    assert payload["question"] == "Explain __AIASE_SQL_V1__ safely"
    assert payload["sql"] == "SELECT value FROM T"


def test_payload_requires_standalone_sql_marker():
    raw = '{"task_id":"task_1"}\nnot-the-marker\nSELECT 1'

    try:
        run.parse_payload(raw)
    except ValueError as exc:
        assert "unexpected content" in str(exc)
    else:
        raise AssertionError("unexpected trailing content should fail")


def test_wrapper_replaces_unknown_column_with_safe_fallback(tmp_path, monkeypatch):
    result_path = tmp_path / "result.json"
    monkeypatch.setenv("AIASE_RESULT_PATH", str(result_path))

    run.emit_contract({
        "task_id": "unknown_column",
        "db_schema": SCHEMA,
        "sql": "SELECT MissingTable.aid FROM Authors",
        "confidence": 0.9,
    })

    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["sql"] == run.SAFE_FALLBACK_SQL
    assert result["confidence"] <= 0.2


def test_wrapper_replaces_ambiguous_column_with_safe_fallback(tmp_path, monkeypatch):
    result_path = tmp_path / "result.json"
    monkeypatch.setenv("AIASE_RESULT_PATH", str(result_path))
    schema = "CREATE TABLE A (name TEXT); CREATE TABLE B (name TEXT);"

    run.emit_contract({
        "task_id": "ambiguous_column",
        "db_schema": schema,
        "sql": "SELECT name FROM A JOIN B",
        "confidence": 0.9,
    })

    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["sql"] == run.SAFE_FALLBACK_SQL
    assert result["confidence"] <= 0.2
