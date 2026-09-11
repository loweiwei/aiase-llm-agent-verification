#!/usr/bin/env python3
"""Run reproducible offline portfolio benchmarks."""

from __future__ import annotations

import importlib.util
import hashlib
import json
import platform
import random
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OPEN_DIR = ROOT / "skills" / "open-test-killer-loweiwei" / "scripts"
SCENARIO_DIR = OPEN_DIR / "public_scenarios"
OUTPUT_DIR = ROOT / "artifacts" / "benchmarks"


def load_open_runner():
    path = OPEN_DIR / "run.py"
    spec = importlib.util.spec_from_file_location("open_test_killer_runner", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def kill_rate(selected: list[dict], mutant_count: int) -> float:
    killed: set[str] = set()
    for candidate in selected:
        killed.update(candidate["kills_set"])
    return len(killed) / mutant_count if mutant_count else 0.0


def random_baseline(candidates: list[dict], selection_size: int, mutant_count: int, repeats: int = 100) -> dict:
    rates = []
    selection_size = min(selection_size, len(candidates))
    for seed in range(repeats):
        rng = random.Random(seed)
        selected = rng.sample(candidates, selection_size) if selection_size else []
        rates.append(kill_rate(selected, mutant_count))
    return {
        "repeats": repeats,
        "selected_test_count": selection_size,
        "mean_kill_rate": sum(rates) / len(rates) if rates else 0.0,
        "min_kill_rate": min(rates, default=0.0),
        "max_kill_rate": max(rates, default=0.0),
    }


def git_metadata() -> dict:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
    except (OSError, subprocess.SubprocessError):
        commit, dirty = "unknown", None
    return {"commit": commit, "dirty_worktree": dirty}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def benchmark_scenario(runner, path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    validated, error = runner.validate_payload(payload)
    if error is not None or validated is None:
        raise RuntimeError(f"invalid scenario {path.name}: {error}")
    started = time.monotonic()
    candidates, matrix_error, stats = runner.build_matrix(validated, started)
    if matrix_error is not None:
        raise RuntimeError(f"matrix failed for {path.name}: {matrix_error}")
    max_tests = int(validated["max_tests"])
    mutant_order = [item["id"] for item in validated["mutants"]]
    exact, exact_available, combinations = runner._exact_select(candidates, max_tests)
    if not exact_available:
        raise RuntimeError(f"public scenario exceeds exact budget: {path.name}")
    greedy = runner._greedy_select(candidates, max_tests, mutant_order)
    elapsed = time.monotonic() - started
    return {
        "scenario": path.stem,
        "candidate_count": len(candidates),
        "mutant_count": len(mutant_order),
        "max_tests": max_tests,
        "matrix_evaluated_calls": stats["evaluated_calls"],
        "evaluation_truncated": bool(stats["evaluation_truncated"]),
        "exact_combinations": combinations,
        "exact": {
            "kill_rate": kill_rate(exact, len(mutant_order)),
            "selected_test_count": len(exact),
            "selected_tests": [item["id"] for item in exact],
        },
        "greedy": {
            "kill_rate": kill_rate(greedy, len(mutant_order)),
            "selected_test_count": len(greedy),
            "selected_tests": [item["id"] for item in greedy],
        },
        "random": random_baseline(candidates, len(exact), len(mutant_order)),
        "elapsed_sec": elapsed,
    }


def markdown_report(report: dict) -> str:
    lines = [
        "# Open Track Selection Benchmark",
        "",
        "Public development scenarios; these are not held-out results.",
        "",
        "| Scenario | Tests | Exact | Greedy | Random mean | Candidates | Mutants |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for item in report["scenarios"]:
        lines.append(
            f"| {item['scenario']} | {item['exact']['selected_test_count']} | {item['exact']['kill_rate']:.3f} | "
            f"{item['greedy']['kill_rate']:.3f} | {item['random']['mean_kill_rate']:.3f} | "
            f"{item['candidate_count']} | {item['mutant_count']} |"
        )
    lines.extend([
        "",
        "Random reports the mean over deterministic seeds 0-99 at the same test count selected by exact search.",
        "Execution times are available in the JSON artifact and are environment-dependent.",
    ])
    return "\n".join(lines) + "\n"


def main() -> int:
    runner = load_open_runner()
    scenarios = [benchmark_scenario(runner, path) for path in sorted(SCENARIO_DIR.glob("*.json"))]
    report = {
        "benchmark": "open_track_selection",
        "dataset": "public_development_scenarios",
        "python": platform.python_version(),
        **git_metadata(),
        "input_hashes": {
            "benchmark_script": sha256(Path(__file__)),
            "open_runner": sha256(OPEN_DIR / "run.py"),
            "scenarios": {path.name: sha256(path) for path in sorted(SCENARIO_DIR.glob("*.json"))},
        },
        "truncation_rate": sum(1 for item in scenarios if item["evaluation_truncated"]) / len(scenarios) if scenarios else 0.0,
        "scenarios": scenarios,
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUTPUT_DIR / "open_selection.json"
    markdown_path = OUTPUT_DIR / "open_selection.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(markdown_report(report), encoding="utf-8")
    print(json.dumps({"ok": True, "json": str(json_path), "markdown": str(markdown_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
