#!/usr/bin/env python3
"""Summarize an explicit matched set of run_dev reports."""

from __future__ import annotations

import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "dev_run_results"
OUTPUT_DIR = ROOT / "artifacts" / "model_experiments"


def category(reason: str) -> str:
    text = reason.lower()
    if "no result" in text or "missing result" in text or "contract violation" in text:
        return "contract_or_tool_use"
    if "schema invalid" in text or "invalid json" in text:
        return "format_or_schema"
    if "execution failed" in text or "execution error" in text or "timeout" in text:
        return "execution"
    if "differs from gold" in text or "recall=" in text or "cases failed" in text:
        return "semantic_model_error"
    return "other"


def sample_stdev(values: list[float]) -> float:
    return statistics.stdev(values) if len(values) > 1 else 0.0


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        raise SystemExit("usage: summarize_controlled_experiment.py experiments/<manifest>.json")
    manifest_path = ROOT / argv[1]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    stem = manifest["experiment_id"]
    output_json = OUTPUT_DIR / f"{stem}.json"
    output_markdown = OUTPUT_DIR / f"{stem}.md"
    required_reports = [REPORT_DIR / report for run in manifest["runs"] for report in run["reports"]]
    if not all(path.exists() for path in required_reports):
        if output_json.exists() and output_markdown.exists():
            print(json.dumps({"ok": True, "experiment": stem, "skipped": "source reports unavailable; preserved sanitized artifact"}, ensure_ascii=False))
            return 0
        missing = [str(path.name) for path in required_reports if not path.exists()]
        raise SystemExit(f"missing source reports and no existing artifact: {missing}")
    grouped: dict[str, list[dict]] = defaultdict(list)
    task_stability: dict[str, Counter[str]] = defaultdict(Counter)
    run_results = []
    safe_extra_fields = {"student_rowcount", "gold_rowcount", "passed_cases", "total_cases", "jaccard", "recall_like", "clean_fp"}
    for run in manifest["runs"]:
        for report_name in run["reports"]:
            path = REPORT_DIR / report_name
            report = json.loads(path.read_text(encoding="utf-8"))
            report["report"] = report_name
            report["repetition"] = run["repetition"]
            key = str(report["skill"])
            grouped[key].append(report)
            clean_results = []
            for item in report.get("results", []):
                task_stability[key][str(item["task_id"])] += int(bool(item.get("passed")))
                extras = item.get("extras") or {}
                clean_results.append({
                    "task_id": item.get("task_id"),
                    "passed": bool(item.get("passed")),
                    "reason": item.get("reason", ""),
                    "elapsed_sec": float(item.get("elapsed_sec", 0.0)),
                    "metrics": {name: extras[name] for name in sorted(safe_extra_fields) if name in extras},
                })
            run_results.append({
                "repetition": run["repetition"],
                "report": report_name,
                "skill": key,
                "pass_rate": float(report["pass_rate"]),
                "results": clean_results,
            })

    skills = []
    for skill, reports in sorted(grouped.items()):
        rates = [float(report["pass_rate"]) for report in reports]
        elapsed = [float(item.get("elapsed_sec", 0.0)) for report in reports for item in report.get("results", [])]
        failures: Counter[str] = Counter()
        total = passed = 0
        recall_values = []
        clean_fp = 0
        clean_evaluations = 0
        for report in reports:
            total += int(report["total"])
            passed += int(report["passed"])
            for item in report.get("results", []):
                if not item.get("passed"):
                    failures[category(str(item.get("reason", "")))] += 1
                extras = item.get("extras") or {}
                if "recall_like" in extras:
                    recall_values.append(float(extras["recall_like"]))
                if "clean_fp" in extras:
                    clean_evaluations += 1
                    clean_fp += int(extras["clean_fp"])
        skills.append({
            "skill": skill,
            "repetition_pass_rates": rates,
            "mean_pass_rate": statistics.mean(rates),
            "sample_stdev_pass_rate": sample_stdev(rates),
            "pooled_pass_rate": passed / total if total else 0.0,
            "passed_task_runs": passed,
            "total_task_runs": total,
            "mean_task_elapsed_sec": statistics.mean(elapsed) if elapsed else 0.0,
            "sample_stdev_task_elapsed_sec": sample_stdev(elapsed),
            "failure_counts": dict(sorted(failures.items())),
            "failure_rates": {name: count / total for name, count in sorted(failures.items())},
            "mean_recall_like": statistics.mean(recall_values) if recall_values else None,
            "clean_false_positive_rate": clean_fp / clean_evaluations if clean_evaluations else None,
            "task_passes_across_repetitions": dict(sorted(task_stability[skill].items())),
        })
    output = {
        **manifest,
        "manifest": str(manifest_path.relative_to(ROOT)),
        "skills": skills,
        "sanitized_task_level_results": run_results,
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        f"# Controlled Model Experiment: {stem}",
        "",
        "Three matched repetitions on course public development tasks. These are not held-out results.",
        "",
        "| Skill | Repetition rates | Mean | Sample SD | Pooled | Mean task sec |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for item in skills:
        rates = ", ".join(f"{value:.3f}" for value in item["repetition_pass_rates"])
        lines.append(
            f"| {item['skill']} | {rates} | {item['mean_pass_rate']:.3f} | "
            f"{item['sample_stdev_pass_rate']:.3f} | {item['pooled_pass_rate']:.3f} | "
            f"{item['mean_task_elapsed_sec']:.2f} |"
        )
    lines.extend(["", "## Failure Counts", ""])
    for item in skills:
        lines.append(f"- `{item['skill']}`: {json.dumps(item['failure_counts'], ensure_ascii=False, sort_keys=True)}")
    lines.extend([
        "",
        "Token usage is unavailable and remains `null`. One invalid model-alias setup run was excluded before analysis and is documented in the manifest.",
    ])
    output_markdown.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "experiment": stem, "skills": len(skills)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
