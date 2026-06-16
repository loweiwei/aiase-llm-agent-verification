#!/usr/bin/env python3
"""Generate an offline pairwise reference corpus for local calibration.

The corpus intentionally uses all six reference skills as data producers:

- reference-author-clean / buggy / tricky generate code variants.
- reference-bug-hunter-aggressive / conservative / noisy audit those variants.

This script is not imported by Code Author or Bug Hunter runtime paths. It is a
training/regression data generator only; official skills must continue to make
decisions from their payload, candidate code, AST checks, probes, and samples.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
TASK_DIR = ROOT / "dev_set" / "pairwise" / "reference_tasks"
SKILLS_DIR = ROOT / "skills"

AUTHOR_SKILLS = {
    "clean": "reference-author-clean",
    "buggy": "reference-author-buggy",
    "tricky": "reference-author-tricky",
}

HUNTER_SKILLS = {
    "aggressive": "reference-bug-hunter-aggressive",
    "conservative": "reference-bug-hunter-conservative",
    "noisy": "reference-bug-hunter-noisy",
}


def _extract_json_object(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if "```" in raw:
        parts = raw.split("```")
        for part in parts:
            body = part.strip()
            if body.startswith("json"):
                body = body[4:].strip()
            if body.startswith("{"):
                try:
                    obj = json.loads(body)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    return obj
    decoder = json.JSONDecoder()
    for idx, ch in enumerate(raw):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(raw[idx:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def _run_reference(skill_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    script = SKILLS_DIR / skill_name / "scripts" / "run.py"
    proc = subprocess.run(
        [sys.executable, str(script), json.dumps(payload, ensure_ascii=False)],
        text=True,
        capture_output=True,
        check=False,
    )
    obj = _extract_json_object(proc.stdout)
    if obj is None:
        obj = {
            "task_id": str(payload.get("task_id", "")),
            "_error": "reference output missing json",
            "_returncode": proc.returncode,
            "_stderr_tail": proc.stderr[-500:],
        }
    obj["_reference_skill"] = skill_name
    obj["_returncode"] = proc.returncode
    return obj


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


def _author_payload(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": str(task.get("task_id", "")),
        "task_description": str(task.get("task_description", "")),
        "constraints": task.get("constraints", {}),
        "samples": task.get("test_cases", [])[:3],
    }


def _hunter_payload(task: dict[str, Any], code: str) -> dict[str, Any]:
    return {
        "task_id": str(task.get("task_id", "")),
        "task_description": str(task.get("task_description", "")),
        "code": code,
    }


def build_corpus() -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for task in _tasks():
        task_id = str(task.get("task_id", ""))
        author_outputs: dict[str, dict[str, Any]] = {}
        hunter_reports: dict[str, dict[str, dict[str, Any]]] = {}

        for variant, skill_name in AUTHOR_SKILLS.items():
            author = _run_reference(skill_name, _author_payload(task))
            author_outputs[variant] = author
            code = str(author.get("code", ""))
            hunter_reports[variant] = {}
            for hunter_kind, hunter_skill in HUNTER_SKILLS.items():
                hunter_reports[variant][hunter_kind] = _run_reference(hunter_skill, _hunter_payload(task, code))

        records.append({
            "task_id": task_id,
            "entry_function": (task.get("constraints") or {}).get("entry_function", ""),
            "task_description": task.get("task_description", ""),
            "author_outputs": author_outputs,
            "bug_hunter_reports": hunter_reports,
            "training_uses": {
                "code_author": "learn clean-code targets and anti-patterns from buggy/tricky variants",
                "bug_hunter": "calibrate recall/precision using clean/buggy/tricky variants and hunter report disagreement",
            },
        })

    return {
        "schema": "aiase_pairwise_reference_training_corpus_v1",
        "reference_author_skills": list(AUTHOR_SKILLS.values()),
        "reference_bug_hunter_skills": list(HUNTER_SKILLS.values()),
        "records": records,
    }


def main() -> int:
    corpus = build_corpus()
    sys.stdout.write(json.dumps(corpus, ensure_ascii=False, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
