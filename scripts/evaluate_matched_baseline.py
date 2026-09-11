#!/usr/bin/env python3
"""Replay identical raw model responses through strict, format-only and full paths."""

from __future__ import annotations

import importlib.util
import json
import re
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESPONSE_DIR = ROOT / "artifacts" / "model_experiments" / "matched_raw" / "responses"
OUTPUT_DIR = ROOT / "artifacts" / "model_experiments"
FENCED_JSON = re.compile(r"```json\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


contract = load_module("matched_contract", ROOT / "aiase_contract.py")
sql_validator = load_module("matched_sql_validator", ROOT / "skills" / "text2sql-loweiwei" / "scripts" / "validate_sql.py")
code_runner = load_module("matched_code_author", ROOT / "skills" / "code-author-loweiwei" / "scripts" / "run.py")
bug_runner = load_module("matched_bug_hunter", ROOT / "skills" / "bug-hunter-loweiwei" / "scripts" / "run.py")


def extract_json(text: str) -> dict | None:
    fences = FENCED_JSON.findall(text)
    candidates = list(reversed(fences))
    candidates.append(text.strip())
    decoder = json.JSONDecoder()
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            try:
                start = candidate.index("{")
                value, _ = decoder.raw_decode(candidate[start:])
            except (ValueError, json.JSONDecodeError):
                continue
        if isinstance(value, dict):
            return value
    return None


def strict_json(text: str) -> dict | None:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def load_tasks() -> dict[str, dict]:
    tasks = {}
    for path in sorted((ROOT / "dev_set" / "basic").glob("task_nl2sql_*.json")):
        task = json.loads(path.read_text(encoding="utf-8"))
        tasks[f"text2sql__{task['task_id']}"] = task
    for path in sorted((ROOT / "dev_set" / "pairwise" / "reference_tasks").glob("task_pair_*.json")):
        task = json.loads(path.read_text(encoding="utf-8"))
        tasks[f"code_author__{task['task_id']}"] = task
        tasks[f"bug_hunter__{task['task_id']}__buggy"] = task
        tasks[f"bug_hunter__{task['task_id']}__clean"] = task
    return tasks


def grade_sql(task: dict, obj: dict | None, full: bool) -> tuple[bool, str]:
    if not isinstance(obj, dict) or obj.get("task_id") != task["task_id"] or not isinstance(obj.get("sql"), str):
        return False, "contract"
    sql = obj["sql"].strip().rstrip(";")
    if full:
        valid, _ = sql_validator.validate(task["db_schema"], sql)
        if not valid:
            sql = "SELECT NULL WHERE 0"
    try:
        got = contract.run_sql(str(ROOT / task["db_path"]), sql)
        gold = contract.run_sql(str(ROOT / task["db_path"]), task["gold_sql"])
    except sqlite3.Error:
        return False, "execution"
    return (True, "passed") if contract.bag_equal(got, gold) else (False, "semantic")


def grade_code(task: dict, obj: dict | None, full: bool) -> tuple[bool, str]:
    if not isinstance(obj, dict) or obj.get("task_id") != task["task_id"] or not isinstance(obj.get("code"), str):
        return False, "contract"
    if full:
        contract_obj = code_runner._build_contract(task, obj["code"])
        code = contract_obj["code"]
    else:
        code = obj["code"]
    passed, failed, errors = code_runner._run_cases(code, task["constraints"]["entry_function"], task["test_cases"])
    if failed == 0 and passed == len(task["test_cases"]):
        return True, "passed"
    if any("compile/exec" in error or "runtime error" in error or "timeout" in error for error in errors):
        return False, "execution"
    return False, "semantic"


def bug_pairs(obj: dict | None) -> set[tuple[int, str]]:
    if not isinstance(obj, dict) or not isinstance(obj.get("bugs"), list):
        return set()
    pairs = set()
    for bug in obj["bugs"]:
        try:
            pairs.add((int(bug["line_start"]), str(bug["type"])))
        except (KeyError, TypeError, ValueError):
            continue
    return pairs


def grade_bug(task: dict, variant: str, obj: dict | None, full: bool) -> tuple[bool, str]:
    if not isinstance(obj, dict) or obj.get("task_id") != task["task_id"]:
        return False, "contract"
    if full:
        payload = {
            "task_id": task["task_id"],
            "task_description": task["task_description"],
            "constraints": task["constraints"],
            "code": task[f"{variant}_code"],
        }
        obj = bug_runner._normalize_with_audit(payload, obj)
    found = bug_pairs(obj)
    if variant == "clean":
        return (True, "passed") if not found else (False, "false_positive")
    expected = {(int(bug["line_start"]), str(bug["type"])) for bug in task["bugs_in_buggy"]}
    return (True, "passed") if found & expected else (False, "false_negative")


def evaluate_record(record: dict, task: dict) -> list[dict]:
    response = str(record.get("response", ""))
    parsed = {"raw_strict": strict_json(response), "format_only": extract_json(response)}
    parsed["full_validation"] = parsed["format_only"]
    rows = []
    for configuration, obj in parsed.items():
        if record["kind"] == "text2sql":
            passed, reason = grade_sql(task, obj, configuration == "full_validation")
        elif record["kind"] == "code_author":
            passed, reason = grade_code(task, obj, configuration == "full_validation")
        else:
            passed, reason = grade_bug(task, str(record["variant"]), obj, configuration == "full_validation")
        rows.append({"configuration": configuration, "passed": passed, "reason": reason})
    return rows


def main() -> int:
    tasks = load_tasks()
    records = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(RESPONSE_DIR.glob("r*__*.json"))]
    task_rows = []
    rates: dict[tuple[str, str, int], list[bool]] = defaultdict(list)
    reasons: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    collection_elapsed: dict[str, list[float]] = defaultdict(list)
    for record in records:
        task = tasks[record["case_id"]]
        evaluations = evaluate_record(record, task)
        task_rows.append({**{key: record.get(key) for key in ("repetition", "case_id", "kind", "task_id", "variant", "elapsed_sec", "returncode")}, "evaluations": evaluations})
        collection_elapsed[record["kind"]].append(float(record.get("elapsed_sec", 0.0)))
        for evaluation in evaluations:
            rates[(record["kind"], evaluation["configuration"], int(record["repetition"]))].append(evaluation["passed"])
            reasons[(record["kind"], evaluation["configuration"])][evaluation["reason"]] += 1
    summaries = []
    for kind in ("text2sql", "code_author", "bug_hunter"):
        for configuration in ("raw_strict", "format_only", "full_validation"):
            repetition_rates = [
                sum(rates[(kind, configuration, repetition)]) / len(rates[(kind, configuration, repetition)])
                for repetition in (1, 2, 3)
                if rates[(kind, configuration, repetition)]
            ]
            if not repetition_rates:
                continue
            summaries.append({
                "kind": kind,
                "configuration": configuration,
                "repetition_rates": repetition_rates,
                "mean_pass_rate": statistics.mean(repetition_rates),
                "sample_stdev_pass_rate": statistics.stdev(repetition_rates) if len(repetition_rates) > 1 else 0.0,
                "reason_counts": dict(sorted(reasons[(kind, configuration)].items())),
                "mean_collection_elapsed_sec": statistics.mean(collection_elapsed[kind]),
            })
    complete = len(records) == 108
    output = {"experiment": "matched_raw_format_full_gemma4_3x", "complete": complete, "response_count": len(records), "summaries": summaries, "task_results": task_rows}
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "matched_raw_format_full_gemma4_3x.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# Matched Raw / Format-Only / Full Validation", "", f"Responses collected: {len(records)}/108. Complete: {complete}.", "", "| Track | Configuration | Repetition rates | Mean | Sample SD |", "|---|---|---|---:|---:|"]
    for item in summaries:
        values = ", ".join(f"{value:.3f}" for value in item["repetition_rates"])
        lines.append(f"| {item['kind']} | {item['configuration']} | {values} | {item['mean_pass_rate']:.3f} | {item['sample_stdev_pass_rate']:.3f} |")
    lines.extend(["", "## Failure Reasons", ""])
    for item in summaries:
        failures = {key: value for key, value in item["reason_counts"].items() if key != "passed"}
        lines.append(f"- `{item['kind']}/{item['configuration']}`: {json.dumps(failures, sort_keys=True)}")
    lines.extend(["", "The same raw response is replayed through all three configurations. Public development/reference tasks; not held-out."])
    (OUTPUT_DIR / "matched_raw_format_full_gemma4_3x.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "responses": len(records), "complete": complete}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
