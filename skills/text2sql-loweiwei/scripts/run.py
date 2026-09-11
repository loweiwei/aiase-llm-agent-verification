#!/usr/bin/env python3
"""Text2SQL file-based output wrapper.

Reads CLI flags, JSON from argv[1], or JSON from stdin; normalizes one SQLite
SELECT query; optionally validates it against `db_schema`/`schema_ddl` with
sqlite3 EXPLAIN; and writes a compact JSON result to AIASE_RESULT_PATH or
./aiase_result.json. It does not print fenced JSON; stdout is not the official
output channel.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import tempfile


CONTRACT_FIELDS = ("task_id", "sql", "rationale", "confidence")
FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|ATTACH|DETACH|REPLACE|TRUNCATE|VACUUM|PRAGMA|BEGIN|COMMIT|ROLLBACK)\b",
    re.IGNORECASE,
)
OUT_OF_ENVELOPE = re.compile(
    r"\bWITH\b|\bWITH\s+RECURSIVE\b|\bOVER\s*\(",
    re.IGNORECASE,
)
FENCED_SQL = re.compile(r"```(?:sql)?\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL)
SAFE_FALLBACK_SQL = "SELECT NULL WHERE 0"
SQL_DELIMITER = "__AIASE_SQL_V1__"


def resolve_result_path() -> str:
    return os.environ.get("AIASE_RESULT_PATH") or os.path.join(os.getcwd(), "aiase_result.json")


def write_result(obj: dict) -> str:
    path = resolve_result_path()
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".aiase_result_", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
            f.write("\n")
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
    return path


def _clean_sql(sql: str) -> str:
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
    text = str(sql or "").strip()
    masked = _mask_sql(text)
    positions = [i for i, ch in enumerate(masked) if ch == ";"]
    if not positions:
        return False
    return len(positions) > 1 or bool(masked[positions[0] + 1:].strip())


def _append_reason(rationale: str, message: str) -> str:
    base = str(rationale or "").strip()
    return (base + " " if base else "") + message


def _validate_schema(schema_ddl: str, sql: str) -> str:
    if not str(schema_ddl or "").strip():
        return ""
    try:
        from validate_sql import validate

        ok, err = validate(str(schema_ddl), sql)
        return "" if ok else str(err)
    except Exception:
        pass
    con = sqlite3.connect(":memory:")
    try:
        con.executescript(str(schema_ddl))
        con.execute("EXPLAIN " + sql)
    except sqlite3.Error as exc:
        return str(exc)
    finally:
        con.close()
    return ""


def emit_contract(obj: dict) -> int:
    original_sql = str(obj.get("sql", ""))
    sql_body = _extract_sql_body(original_sql)
    sql = _strip_optional_trailing_semicolon(sql_body)
    confidence = _clamp_confidence(obj.get("confidence", 0.5))
    rationale = str(obj.get("rationale", ""))
    masked = _mask_sql(sql)
    contract_violation = False
    if not sql:
        confidence = min(confidence, 0.0)
        contract_violation = True
    if not sql.lstrip().upper().startswith("SELECT"):
        confidence = min(confidence, 0.2)
        contract_violation = True
    if _has_multiple_statements(sql_body):
        confidence = min(confidence, 0.2)
        contract_violation = True
    if FORBIDDEN.search(masked) or OUT_OF_ENVELOPE.search(masked):
        confidence = min(confidence, 0.2)
        contract_violation = True
    schema_ddl = obj.get("db_schema", obj.get("schema_ddl", ""))
    if sql and not contract_violation:
        err = _validate_schema(str(schema_ddl or ""), sql)
        if err:
            confidence = min(confidence, 0.2)
            rationale = _append_reason(rationale, f"Local SQLite validation failed: {err}")
            contract_violation = True
    if contract_violation:
        if not sql:
            confidence = min(confidence, 0.0)
        else:
            confidence = min(confidence, 0.2)
        sql = SAFE_FALLBACK_SQL
        rationale = _append_reason(rationale, "Replaced invalid SQL with safe read-only fallback.")
    out = {
        "task_id": str(obj.get("task_id", "")),
        "sql": sql,
        "rationale": rationale,
        "confidence": confidence,
    }
    # 任何 extra fields 一律忽略(規格書 §1.4 #3)。
    write_result(out)
    return 0


def _clamp_confidence(v) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    if f < 0.0:
        return 0.0
    if f > 1.0:
        return 1.0
    return f


def parse_payload(raw: str) -> dict:
    text = raw.lstrip()
    payload, end = json.JSONDecoder().raw_decode(text)
    if not isinstance(payload, dict):
        raise ValueError("payload not an object")
    remainder = text[end:].strip()
    if remainder:
        lines = remainder.splitlines()
        if not lines or lines[0].strip() != SQL_DELIMITER:
            raise ValueError("unexpected content after payload")
        sql = "\n".join(lines[1:]).strip()
        payload = dict(payload)
        payload["sql"] = sql
        payload.setdefault("rationale", "Candidate SQL validated against the supplied schema.")
        payload.setdefault("confidence", 0.8)
    return payload


def main(argv: list[str]) -> int:
    if any(arg.startswith("--") for arg in argv[1:]):
        import argparse

        ap = argparse.ArgumentParser()
        ap.add_argument("--task_id", required=True)
        ap.add_argument("--sql", required=True)
        ap.add_argument("--rationale", default="")
        ap.add_argument("--confidence", type=float, default=0.5)
        ap.add_argument("--db_schema", default="")
        ap.add_argument("--schema_ddl", default="")
        args = ap.parse_args(argv[1:])

        payload = {
            "task_id": args.task_id,
            "sql": args.sql,
            "rationale": args.rationale,
            "confidence": args.confidence,
            "db_schema": args.db_schema or args.schema_ddl,
        }
        return emit_contract(payload)

    raw = argv[1] if len(argv) >= 2 else sys.stdin.read()
    if not raw.strip():
        # 失敗也要產出契約 JSON,不可只噴錯(規格書 §1.4 #7)。
        return emit_contract({
            "task_id": "",
            "sql": "",
            "rationale": "run.py invoked without argv payload",
            "confidence": 0.0,
        })

    try:
        payload = parse_payload(raw)
    except (json.JSONDecodeError, ValueError) as e:
        return emit_contract({
            "task_id": "",
            "sql": "",
            "rationale": f"invalid input JSON: {e}",
            "confidence": 0.0,
        })

    return emit_contract(payload)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
