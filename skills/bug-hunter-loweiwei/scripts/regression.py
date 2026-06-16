#!/usr/bin/env python3
"""Offline regression checks for bug-hunter-loweiwei.

This helper is intentionally separate from the official runtime path. It reads
the local pairwise reference tasks only to calibrate the deterministic analyzer
against clean, buggy, and tricky reference-author outputs. The official
``run.py`` skill entry point does not import this module and does not read the
dev set or reference skills.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RUN = ROOT / "run.py"
REPO_ROOT = ROOT.parents[2]
TASK_DIR = REPO_ROOT / "dev_set" / "pairwise" / "reference_tasks"
CORPUS_SCRIPT = REPO_ROOT / "skills" / "code-author-loweiwei" / "scripts" / "reference_training_corpus.py"


def _load_runner() -> Any:
    spec = importlib.util.spec_from_file_location("bug_hunter_run_for_regression", RUN)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load run.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


runner = _load_runner()


def _load_reference_corpus() -> dict[str, Any]:
    spec = importlib.util.spec_from_file_location("pairwise_reference_training_corpus", CORPUS_SCRIPT)
    if spec is None or spec.loader is None:
        return {"records": [], "_error": "reference corpus script unavailable"}
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod.build_corpus()


def _tasks() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not TASK_DIR.exists():
        return out
    for path in sorted(TASK_DIR.glob("*.json")):
        if path.name.endswith("_GROUND_TRUTH.json"):
            continue
        try:
            task = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(task, dict):
            out.append(task)
    return out


def _payload(task: dict[str, Any], code_key: str) -> dict[str, Any]:
    return {
        "task_id": str(task.get("task_id", "")),
        "task_description": str(task.get("task_description", "")),
        "constraints": task.get("constraints", {}),
        "code": str(task.get(code_key, "")),
    }


def _bug_set(obj: dict[str, Any]) -> set[tuple[int, int, str]]:
    bugs = obj.get("bugs") if isinstance(obj, dict) else []
    out: set[tuple[int, int, str]] = set()
    if not isinstance(bugs, list):
        return out
    for bug in bugs:
        if not isinstance(bug, dict):
            continue
        try:
            start = int(bug.get("line_start"))
            end = int(bug.get("line_end", start))
            out.add((start, max(start, end), str(bug.get("type", "")).strip()))
        except (TypeError, ValueError):
            continue
    return out


def _expected_bug_set(task: dict[str, Any], field: str) -> set[tuple[int, int, str]]:
    return _bug_set({"bugs": task.get(field, [])})


def _overlap_hit(got: set[tuple[int, int, str]], expected: set[tuple[int, int, str]]) -> bool:
    for got_start, got_end, got_type in got:
        for exp_start, exp_end, exp_type in expected:
            if got_type == exp_type and got_start <= exp_end and exp_start <= got_end:
                return True
    return False


def _audit(task: dict[str, Any], code_key: str) -> dict[str, Any]:
    return runner._audit_payload(_payload(task, code_key))


def run_regression() -> dict[str, Any]:
    tasks = _tasks()
    corpus = _load_reference_corpus()
    corpus_bad_outputs = 0
    for record in corpus.get("records", []):
        for author in record.get("author_outputs", {}).values():
            corpus_bad_outputs += int(author.get("_returncode") != 0 or not author.get("code"))
        for reports in record.get("bug_hunter_reports", {}).values():
            for report in reports.values():
                corpus_bad_outputs += int(report.get("_returncode") != 0 or "verdict" not in report)
    clean_false_positives: list[str] = []
    buggy_hits = 0
    buggy_total = 0
    tricky_hits = 0
    tricky_total = 0
    details: list[dict[str, Any]] = []

    for task in tasks:
        task_id = str(task.get("task_id", ""))
        if task.get("clean_code"):
            clean = _audit(task, "clean_code")
            if clean.get("verdict") == "buggy" or clean.get("bugs"):
                clean_false_positives.append(task_id)
            details.append({"task_id": task_id, "variant": "clean", "verdict": clean.get("verdict")})

        if task.get("buggy_code"):
            buggy_total += 1
            expected = _expected_bug_set(task, "bugs_in_buggy")
            got = _bug_set(_audit(task, "buggy_code"))
            if _overlap_hit(got, expected):
                buggy_hits += 1
            details.append({"task_id": task_id, "variant": "buggy", "hit": _overlap_hit(got, expected)})

        if task.get("tricky_code"):
            tricky_total += 1
            audit = _audit(task, "tricky_code")
            got = _bug_set(audit)
            if audit.get("verdict") == "buggy" and got:
                tricky_hits += 1
            details.append({"task_id": task_id, "variant": "tricky", "hit": bool(audit.get("verdict") == "buggy" and got)})

    ok = corpus_bad_outputs == 0 and not clean_false_positives and buggy_hits == buggy_total and tricky_hits >= max(1, tricky_total // 2)
    return {
        "ok": ok,
        "reference_corpus_records": len(corpus.get("records", [])),
        "reference_corpus_bad_outputs": corpus_bad_outputs,
        "tasks": len(tasks),
        "clean_false_positives": clean_false_positives,
        "buggy_hits": buggy_hits,
        "buggy_total": buggy_total,
        "tricky_hits": tricky_hits,
        "tricky_total": tricky_total,
        "details": details,
    }


def main() -> int:
    result = run_regression()
    sys.stdout.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
