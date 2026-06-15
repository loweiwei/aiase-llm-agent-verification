#!/usr/bin/env python3
"""Deterministic SQLite SQL validator for the Text2SQL skill.

The public contract used by local tests/development is:

    validate(schema_ddl: str, sql: str) -> tuple[bool, str]

The CLI accepts a JSON object with `schema_ddl` (or `db_schema`) and `sql`, then
prints one fenced JSON block containing `{ok, error}`. It never executes the
query against user data; it creates an in-memory SQLite database from the DDL
and runs `EXPLAIN` to catch syntax, table, and column errors.
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys


FORBIDDEN_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|ATTACH|DETACH|REPLACE|TRUNCATE|VACUUM|PRAGMA|BEGIN|COMMIT|ROLLBACK)\b",
    re.IGNORECASE,
)
OUT_OF_ENVELOPE = re.compile(
    r"\bWITH\b|\bWITH\s+RECURSIVE\b|\bOVER\s*\(",
    re.IGNORECASE,
)
FENCED_SQL = re.compile(r"```(?:sql)?\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL)


def _clean_sql(sql: str) -> str:
    """Strip markdown fences and one optional trailing semicolon."""
    text = _extract_sql_body(sql)
    return _strip_optional_trailing_semicolon(text)


def _extract_sql_body(sql: str) -> str:
    text = str(sql or "").strip()
    matches = FENCED_SQL.findall(text)
    if matches:
        return matches[-1].strip()
    return text


def _mask_sql(sql: str) -> str:
    out: list[str] = []
    i = 0
    quote = ""
    while i < len(sql):
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < len(sql) else ""
        if quote:
            out.append(" ")
            if ch == quote:
                if i + 1 < len(sql) and sql[i + 1] == quote:
                    out.append(" ")
                    i += 2
                    continue
                quote = ""
            i += 1
        elif ch in {"'", '"'}:
            quote = ch
            out.append(" ")
            i += 1
        elif ch == "-" and nxt == "-":
            while i < len(sql) and sql[i] != "\n":
                out.append(" ")
                i += 1
            if i < len(sql):
                out.append(sql[i])
                i += 1
        elif ch == "/" and nxt == "*":
            out.extend([" ", " "])
            i += 2
            while i < len(sql):
                if sql[i] == "*" and i + 1 < len(sql) and sql[i + 1] == "/":
                    out.extend([" ", " "])
                    i += 2
                    break
                out.append(" ")
                i += 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _semicolon_positions(sql: str) -> list[int]:
    masked = _mask_sql(sql)
    return [i for i, ch in enumerate(masked) if ch == ";"]


def _strip_optional_trailing_semicolon(sql: str) -> str:
    text = str(sql or "").strip()
    masked = _mask_sql(text)
    positions = [i for i, ch in enumerate(masked) if ch == ";"]
    if positions and not masked[positions[-1] + 1:].strip():
        text = text[:positions[-1]].rstrip()
    return text.strip()


def _has_multiple_statements(sql: str) -> bool:
    """Reject semicolons before the final optional terminator."""
    stripped = str(sql or "").strip()
    masked = _mask_sql(stripped)
    positions = [i for i, ch in enumerate(masked) if ch == ";"]
    if not positions:
        return False
    return len(positions) > 1 or bool(masked[positions[0] + 1:].strip())


def validate(schema_ddl: str, sql: str) -> tuple[bool, str]:
    """Validate that `sql` is a single read-only SQLite SELECT over `schema_ddl`."""
    sql_body = _extract_sql_body(sql)
    cleaned = _strip_optional_trailing_semicolon(sql_body)
    if not cleaned:
        return False, "SQL is empty."
    if _has_multiple_statements(sql_body):
        return False, "Multiple SQL statements not allowed."
    masked = _mask_sql(cleaned)
    if FORBIDDEN_KEYWORDS.search(masked):
        return False, "DDL/DML keyword detected."
    if not cleaned.lstrip().upper().startswith("SELECT"):
        return False, "Only SELECT queries are allowed."
    if OUT_OF_ENVELOPE.search(masked):
        return False, "Out-of-envelope SQL construct detected."

    con = sqlite3.connect(":memory:")
    try:
        con.executescript(str(schema_ddl or ""))
        con.execute("EXPLAIN " + cleaned)
    except sqlite3.Error as e:
        return False, str(e)
    finally:
        con.close()
    return True, ""


def _emit(obj: dict) -> int:
    sys.stdout.write("```json\n")
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.stdout.write("\n```\n")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        return _emit({"ok": False, "error": "usage: validate_sql.py '<json>'"})
    try:
        payload = json.loads(argv[1])
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
    except (json.JSONDecodeError, ValueError) as e:
        return _emit({"ok": False, "error": f"invalid input JSON: {e}"})

    ok, err = validate(
        str(payload.get("schema_ddl", payload.get("db_schema", ""))),
        str(payload.get("sql", "")),
    )
    return _emit({"ok": ok, "error": err})


if __name__ == "__main__":
    sys.exit(main(sys.argv))
