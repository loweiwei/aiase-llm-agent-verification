#!/usr/bin/env python3
"""Offline regression checks for code-author-loweiwei.

This helper uses local pairwise reference tasks only as calibration data. It is
not imported by the official runtime path and does not affect Hermes execution.
The checks focus on generalized quality gates: generated code must pass the
task-provided cases, avoid sandbox/import violations, and avoid matching known
buggy/tricky behavior on the same probes.
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
CORPUS = ROOT / "reference_training_corpus.py"


def _load_runner() -> Any:
    spec = importlib.util.spec_from_file_location("code_author_run_for_regression", RUN)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load run.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


runner = _load_runner()


def _load_reference_corpus() -> dict[str, Any]:
    spec = importlib.util.spec_from_file_location("pairwise_reference_training_corpus", CORPUS)
    if spec is None or spec.loader is None:
        return {"records": [], "_error": "reference corpus script unavailable"}
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod.build_corpus()


def _tasks() -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    if not TASK_DIR.exists():
        return tasks
    for path in sorted(TASK_DIR.glob("*.json")):
        if path.name.endswith("_GROUND_TRUTH.json"):
            continue
        try:
            task = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(task, dict):
            tasks.append(task)
    return tasks


def _payload(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": str(task.get("task_id", "")),
        "task_description": str(task.get("task_description", "")),
        "constraints": task.get("constraints", {}),
        "test_cases": task.get("test_cases", []),
    }


def _entry(task: dict[str, Any]) -> str:
    constraints = task.get("constraints", {})
    if isinstance(constraints, dict):
        return str(constraints.get("entry_function", "solution"))
    return "solution"


def _candidate_contract(task: dict[str, Any]) -> dict[str, Any]:
    return runner._build_contract(_payload(task), "")


def _case_results(code: str, entry: str, cases: list[dict[str, Any]]) -> tuple[int, int, list[str]]:
    return runner._run_cases(code, entry, cases)


def _variant_fails(task: dict[str, Any], code_key: str) -> bool:
    code = str(task.get(code_key, ""))
    cases = task.get("test_cases", [])
    if not code or not isinstance(cases, list):
        return True
    _passed, failed, _errors = _case_results(code, _entry(task), cases)
    return failed > 0


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
    details: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for task in tasks:
        task_id = str(task.get("task_id", ""))
        cases = task.get("test_cases", [])
        if not isinstance(cases, list):
            cases = []
        entry = _entry(task)
        contract = _candidate_contract(task)
        code = str(contract.get("code", ""))
        passed, failed, errors = _case_results(code, entry, cases)
        imports, sandbox = runner._static_checks(code, task.get("constraints", {}).get("imports_forbidden", []) if isinstance(task.get("constraints"), dict) else [])
        buggy_fails = _variant_fails(task, "buggy_code")
        tricky_fails = _variant_fails(task, "tricky_code")
        ok = corpus_bad_outputs == 0 and failed == 0 and not imports and not sandbox and buggy_fails
        item = {
            "task_id": task_id,
            "passed_cases": passed,
            "failed_cases": failed,
            "buggy_variant_fails_cases": buggy_fails,
            "tricky_variant_fails_cases": tricky_fails,
            "tricky_survived_public_cases": not tricky_fails,
            "rationale": contract.get("rationale", ""),
        }
        details.append(item)
        if not ok:
            failures.append({**item, "errors": errors[:3], "import_violations": imports, "sandbox_violations": sandbox})

    return {
        "ok": not failures,
        "reference_corpus_records": len(corpus.get("records", [])),
        "reference_corpus_bad_outputs": corpus_bad_outputs,
        "tasks": len(tasks),
        "failures": failures,
        "details": details,
    }


def main() -> int:
    result = run_regression()
    sys.stdout.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
