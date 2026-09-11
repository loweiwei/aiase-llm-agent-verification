#!/usr/bin/env python3
"""Summarize local model-dependent dev reports without claiming held-out results."""

from __future__ import annotations

import json
import statistics
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INPUT_DIR = ROOT / "dev_run_results"
OUTPUT_DIR = ROOT / "artifacts" / "benchmarks"


def classify(reason: str) -> str:
    text = reason.lower()
    if not text:
        return "passed"
    if "no result" in text or "missing result" in text or "contract violation" in text:
        return "contract_or_tool_use"
    if "schema invalid" in text or "invalid json" in text:
        return "format_or_schema"
    if "execution failed" in text or "execution error" in text or "timeout" in text:
        return "execution"
    if "differs from gold" in text or "recall=" in text or "cases failed" in text:
        return "semantic_model_error"
    return "other"


def summarize_report(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    results = data.get("results", [])
    elapsed = [float(item.get("elapsed_sec", 0.0)) for item in results]
    categories = Counter(
        "passed" if item.get("passed") else classify(str(item.get("reason", "")))
        for item in results
    )
    return {
        "report": path.name,
        "track": data.get("track"),
        "skill": data.get("skill"),
        "role": data.get("role"),
        "total": int(data.get("total", len(results))),
        "passed": int(data.get("passed", 0)),
        "pass_rate": float(data.get("pass_rate", 0.0)),
        "mean_elapsed_sec": statistics.mean(elapsed) if elapsed else 0.0,
        "stdev_elapsed_sec": statistics.pstdev(elapsed) if len(elapsed) > 1 else 0.0,
        "failure_categories": dict(sorted(categories.items())),
        "token_usage": None,
    }


def aggregate_reports(reports: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for report in reports:
        grouped.setdefault(str(report.get("skill") or "unknown"), []).append(report)
    aggregates = []
    for skill, items in sorted(grouped.items()):
        total = sum(item["total"] for item in items)
        passed = sum(item["passed"] for item in items)
        categories: Counter[str] = Counter()
        for item in items:
            categories.update(item["failure_categories"])
        aggregates.append({
            "skill": skill,
            "report_count": len(items),
            "total_task_runs": total,
            "passed_task_runs": passed,
            "weighted_pass_rate": passed / total if total else 0.0,
            "mean_report_elapsed_sec": statistics.mean(item["mean_elapsed_sec"] for item in items),
            "categories": dict(sorted(categories.items())),
        })
    return aggregates


def markdown(report: dict) -> str:
    lines = [
        "# Local Model-Dependent Run Summary",
        "",
        "Historical development runs; public tasks were used during tuning and are not held-out results.",
        "",
        "## Aggregate",
        "",
        "| Skill | Reports | Passed task-runs | Weighted rate | Mean report sec |",
        "|---|---:|---:|---:|---:|",
    ]
    for item in report["aggregates"]:
        lines.append(
            f"| {item['skill']} | {item['report_count']} | {item['passed_task_runs']}/{item['total_task_runs']} | "
            f"{item['weighted_pass_rate']:.3f} | {item['mean_report_elapsed_sec']:.2f} |"
        )
    lines.extend([
        "",
        "## Reports",
        "",
        "| Report | Skill | Passed | Rate | Mean sec | Main failure categories |",
        "|---|---|---:|---:|---:|---|",
    ])
    for item in report["reports"]:
        failures = ", ".join(f"{key}:{value}" for key, value in item["failure_categories"].items() if key != "passed") or "none"
        lines.append(
            f"| {item['report']} | {item['skill']} | {item['passed']}/{item['total']} | "
            f"{item['pass_rate']:.3f} | {item['mean_elapsed_sec']:.2f} | {failures} |"
        )
    lines.extend(["", "Token usage is unavailable in the current run_dev report schema and is reported as null."])
    return "\n".join(lines) + "\n"


def main() -> int:
    paths = sorted(INPUT_DIR.glob("*.json"))
    existing_json = OUTPUT_DIR / "model_runs_summary.json"
    existing_markdown = OUTPUT_DIR / "model_runs_summary.md"
    if not paths and existing_json.exists() and existing_markdown.exists():
        print(json.dumps({"ok": True, "reports": 0, "skipped": "no local dev reports; preserved existing sanitized artifacts"}, ensure_ascii=False))
        return 0
    reports = []
    for path in paths:
        try:
            reports.append(summarize_report(path))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
    output = {
        "dataset": "historical_public_dev_runs",
        "report_count": len(reports),
        "aggregates": aggregate_reports(reports),
        "reports": reports,
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "model_runs_summary.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUTPUT_DIR / "model_runs_summary.md").write_text(markdown(output), encoding="utf-8")
    print(json.dumps({"ok": True, "reports": len(reports)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
