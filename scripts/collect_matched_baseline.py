#!/usr/bin/env python3
"""Collect raw no-tool model responses for matched baseline replay."""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "artifacts" / "model_experiments" / "matched_raw"
TIMEOUT_SEC = 180
SESSION_FOOTER = re.compile(r"\n+session_id:\s*[^\n]+\s*$", re.IGNORECASE)


def load_cases() -> list[dict]:
    cases = []
    for path in sorted((ROOT / "dev_set" / "basic").glob("task_nl2sql_*.json")):
        task = json.loads(path.read_text(encoding="utf-8"))
        cases.append({"case_id": f"text2sql__{task['task_id']}", "kind": "text2sql", "task": task})
    for path in sorted((ROOT / "dev_set" / "pairwise" / "reference_tasks").glob("task_pair_*.json")):
        task = json.loads(path.read_text(encoding="utf-8"))
        cases.append({"case_id": f"code_author__{task['task_id']}", "kind": "code_author", "task": task})
        for variant in ("buggy", "clean"):
            cases.append({
                "case_id": f"bug_hunter__{task['task_id']}__{variant}",
                "kind": "bug_hunter",
                "variant": variant,
                "task": task,
            })
    return cases


def prompt_for(case: dict) -> str:
    task = case["task"]
    common = "Do not use tools. Return only one JSON object with no Markdown fences or explanation. "
    if case["kind"] == "text2sql":
        payload = {key: task.get(key) for key in ("task_id", "question", "db_schema", "dialect")}
        return common + "Generate one read-only SQLite SELECT. Output keys: task_id, sql, rationale, confidence. Input: " + json.dumps(payload, ensure_ascii=False)
    if case["kind"] == "code_author":
        payload = {
            "task_id": task["task_id"],
            "task_description": task["task_description"],
            "constraints": task["constraints"],
            "samples": task["test_cases"][:3],
        }
        return common + "Generate a Python solution. Output keys: task_id, code, rationale, confidence. Input: " + json.dumps(payload, ensure_ascii=False)
    variant = case["variant"]
    payload = {
        "task_id": task["task_id"],
        "task_description": task["task_description"],
        "constraints": task["constraints"],
        "code": task[f"{variant}_code"],
    }
    return common + (
        "Review the Python code. Output keys: task_id, verdict, bugs, confidence. "
        "verdict is clean or buggy. Each bug has line_start, line_end, severity, type, description, suggested_fix. Input: "
        + json.dumps(payload, ensure_ascii=False)
    )


def call_model(prompt: str) -> tuple[int, str, float]:
    cmd = ["hermes", "chat", "-Q", "-t", "", "--max-turns", "1", "--ignore-rules", "-q", prompt]
    started = time.monotonic()
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", start_new_session=True)
    try:
        stdout, _ = process.communicate(timeout=TIMEOUT_SEC)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        return 124, "", time.monotonic() - started
    response = SESSION_FOOTER.sub("", stdout or "").strip()
    return process.returncode, response, time.monotonic() - started


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repetition", type=int, required=True, choices=(1, 2, 3))
    parser.add_argument("--case", default="", help="optional exact case_id for smoke testing")
    args = parser.parse_args()
    cases = load_cases()
    if args.case:
        cases = [case for case in cases if case["case_id"] == args.case]
        if not cases:
            raise SystemExit(f"unknown case: {args.case}")
    response_dir = OUTPUT_DIR / "responses"
    response_dir.mkdir(parents=True, exist_ok=True)
    for index, case in enumerate(cases, 1):
        output_path = response_dir / f"r{args.repetition}__{case['case_id']}.json"
        if output_path.exists():
            print(f"[{index}/{len(cases)}] skip {case['case_id']}", flush=True)
            continue
        returncode, response, elapsed = call_model(prompt_for(case))
        record = {
            "repetition": args.repetition,
            "case_id": case["case_id"],
            "kind": case["kind"],
            "task_id": case["task"]["task_id"],
            "variant": case.get("variant"),
            "returncode": returncode,
            "elapsed_sec": elapsed,
            "response": response,
            "token_usage": None,
        }
        output_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"[{index}/{len(cases)}] {case['case_id']} rc={returncode} chars={len(response)} elapsed={elapsed:.2f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
