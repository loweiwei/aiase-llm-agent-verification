#!/usr/bin/env python3
"""Run deterministic component ablations on development/reference fixtures."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "artifacts" / "benchmarks"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def text2sql_ablation() -> dict:
    validator = load_module(
        "ablation_text2sql_validator",
        ROOT / "skills" / "text2sql-loweiwei" / "scripts" / "validate_sql.py",
    )
    schema = "CREATE TABLE A (id INTEGER, name TEXT); CREATE TABLE B (id INTEGER, name TEXT);"
    fixtures = [
        ("valid", "SELECT A.name FROM A", True),
        ("unknown_column", "SELECT missing FROM A", False),
        ("unknown_table", "SELECT id FROM Missing", False),
        ("ambiguous_column", "SELECT name FROM A JOIN B ON A.id = B.id", False),
        ("multiple_statements", "SELECT id FROM A; SELECT id FROM B", False),
        ("write_statement", "DELETE FROM A", False),
    ]
    rows = []
    for name, sql, should_accept in fixtures:
        format_only = bool(sql.strip())
        validated, error = validator.validate(schema, sql)
        rows.append({
            "fixture": name,
            "should_accept": should_accept,
            "format_only_accepts": format_only,
            "schema_validation_accepts": validated,
            "validation_error": error,
        })
    invalid = [row for row in rows if not row["should_accept"]]
    return {
        "dataset": "curated_development_validation_fixtures",
        "fixture_count": len(rows),
        "format_only_invalid_acceptance_rate": sum(row["format_only_accepts"] for row in invalid) / len(invalid),
        "schema_validation_invalid_acceptance_rate": sum(row["schema_validation_accepts"] for row in invalid) / len(invalid),
        "rows": rows,
    }


def load_reference_tasks() -> list[dict]:
    base = ROOT / "dev_set" / "pairwise" / "reference_tasks"
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(base.glob("task_pair_*.json"))]


def code_author_ablation(tasks: list[dict]) -> dict:
    runner = load_module(
        "ablation_code_author",
        ROOT / "skills" / "code-author-loweiwei" / "scripts" / "run.py",
    )
    rows = []
    for task in tasks:
        entry = task["constraints"]["entry_function"]
        cases = task["test_cases"]
        raw_passed, raw_failed, _ = runner._run_cases(task["buggy_code"], entry, cases)
        validated_candidate = runner._llm_candidate_result(task["buggy_code"], entry, cases, task["constraints"])
        template_candidate = runner._template_result(
            task,
            entry,
            task["task_description"].lower(),
            cases,
            task["constraints"],
        )
        full = runner._build_contract(task, task["buggy_code"])
        full_result = full["self_test_results"]
        rows.append({
            "task_id": task["task_id"],
            "raw_buggy_candidate_passes": raw_failed == 0 and raw_passed == len(cases),
            "sample_validated_candidate_passes": bool(
                validated_candidate
                and validated_candidate.source == "llm"
                and validated_candidate.failed == 0
            ),
            "template_only_passes": template_candidate.failed == 0,
            "full_validation_passes": full_result["failed"] == 0,
            "full_selected_source": full["rationale"],
        })
    unsafe_candidates = [
        ("syntax_error", "def solution(:\n    pass\n"),
        ("missing_entry", "def other(x):\n    return x\n"),
        ("banned_import", "import os\ndef solution(x):\n    return x\n"),
        ("banned_open", "def solution(x):\n    open('data.txt')\n    return x\n"),
        ("unsafe_top_level", "print('side effect')\ndef solution(x):\n    return x\n"),
    ]
    policy_rows = []
    constraints = {"max_loc": 50, "imports_forbidden": ["os", "sys", "subprocess"]}
    for name, code in unsafe_candidates:
        validation = runner._validate_candidate(code, "solution", constraints)
        policy_rows.append({
            "fixture": name,
            "format_only_accepts": bool(code.strip()),
            "ast_policy_accepts": bool(validation["ok"]),
            "errors": validation["errors"],
        })
    return {
        "dataset": "course_reference_buggy_candidates",
        "task_count": len(rows),
        "raw_buggy_candidate_pass_rate": sum(row["raw_buggy_candidate_passes"] for row in rows) / len(rows),
        "sample_validated_candidate_pass_rate": sum(row["sample_validated_candidate_passes"] for row in rows) / len(rows),
        "template_only_pass_rate": sum(row["template_only_passes"] for row in rows) / len(rows),
        "full_validation_fallback_pass_rate": sum(row["full_validation_passes"] for row in rows) / len(rows),
        "unsafe_fixture_count": len(policy_rows),
        "format_only_unsafe_acceptance_rate": sum(row["format_only_accepts"] for row in policy_rows) / len(policy_rows),
        "ast_policy_unsafe_acceptance_rate": sum(row["ast_policy_accepts"] for row in policy_rows) / len(policy_rows),
        "policy_rows": policy_rows,
        "rows": rows,
    }


def bug_pairs(obj: dict) -> set[tuple[int, str]]:
    return {(int(bug["line_start"]), str(bug["type"])) for bug in obj.get("bugs", [])}


def bug_hunter_ablation(tasks: list[dict]) -> dict:
    runner = load_module(
        "ablation_bug_hunter",
        ROOT / "skills" / "bug-hunter-loweiwei" / "scripts" / "run.py",
    )
    rows = []
    report = {"verdict": "clean", "bugs": [], "confidence": 0.6}
    for task in tasks:
        for variant, code_key, bugs_key in (
            ("buggy", "buggy_code", "bugs_in_buggy"),
            ("tricky", "tricky_code", "bugs_in_tricky"),
        ):
            payload = {
                "task_id": task["task_id"],
                "task_description": task["task_description"],
                "constraints": task["constraints"],
                "code": task[code_key],
            }
            expected = {(int(bug["line_start"]), str(bug["type"])) for bug in task[bugs_key]}
            report_only = runner._normalize_candidate_report(payload, report)
            full = runner._normalize_with_audit(payload, report)
            rows.append({
                "task_id": task["task_id"],
                "variant": variant,
                "report_only_hit": bool(bug_pairs(report_only) & expected),
                "dynamic_audit_hit": bool(bug_pairs(full) & expected),
            })
    clean_false_positives = 0
    for task in tasks:
        payload = {
            "task_id": task["task_id"],
            "task_description": task["task_description"],
            "constraints": task["constraints"],
            "code": task["clean_code"],
        }
        if runner._normalize_with_audit(payload, report).get("bugs"):
            clean_false_positives += 1
    return {
        "dataset": "course_reference_clean_buggy_tricky_variants",
        "bug_variant_count": len(rows),
        "report_only_recall": sum(row["report_only_hit"] for row in rows) / len(rows),
        "dynamic_audit_recall": sum(row["dynamic_audit_hit"] for row in rows) / len(rows),
        "dynamic_audit_clean_false_positive_rate": clean_false_positives / len(tasks),
        "rows": rows,
    }


def markdown(result: dict) -> str:
    text = result["text2sql"]
    author = result["code_author"]
    hunter = result["bug_hunter"]
    return (
        "# Deterministic Component Ablations\n\n"
        "Development/reference fixtures only; these are not raw-LLM or held-out results.\n\n"
        "| Component | Reduced configuration | Full configuration | Metric |\n"
        "|---|---:|---:|---|\n"
        f"| Text2SQL schema validation | {text['format_only_invalid_acceptance_rate']:.3f} | "
        f"{text['schema_validation_invalid_acceptance_rate']:.3f} | invalid acceptance rate, lower is better |\n"
        f"| Code Author validation/fallback | {author['raw_buggy_candidate_pass_rate']:.3f} | "
        f"{author['full_validation_fallback_pass_rate']:.3f} | reference-case pass rate |\n"
        f"| Code Author AST/policy | {author['format_only_unsafe_acceptance_rate']:.3f} | "
        f"{author['ast_policy_unsafe_acceptance_rate']:.3f} | unsafe acceptance rate, lower is better |\n"
        f"| Code Author templates | {author['sample_validated_candidate_pass_rate']:.3f} | "
        f"{author['template_only_pass_rate']:.3f} | reference-case pass rate |\n"
        f"| Bug Hunter dynamic audit | {hunter['report_only_recall']:.3f} | "
        f"{hunter['dynamic_audit_recall']:.3f} | line/type overlap recall |\n\n"
        f"Bug Hunter full configuration clean false-positive rate: "
        f"{hunter['dynamic_audit_clean_false_positive_rate']:.3f}.\n"
    )


def main() -> int:
    tasks = load_reference_tasks()
    result = {
        "scope": "deterministic_component_ablation_on_development_reference_fixtures",
        "text2sql": text2sql_ablation(),
        "code_author": code_author_ablation(tasks),
        "bug_hunter": bug_hunter_ablation(tasks),
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "component_ablations.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUTPUT_DIR / "component_ablations.md").write_text(markdown(result), encoding="utf-8")
    print(json.dumps({"ok": True, "tasks": len(tasks)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
