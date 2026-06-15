#!/usr/bin/env python3
"""Black-box self-test for open-test-killer-loweiwei."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import run as runner


ROOT = Path(__file__).resolve().parent
RUN = ROOT / "run.py"
SKILL = ROOT.parent / "SKILL.md"
OPEN_TRACK = ROOT.parents[2] / "OPEN_TRACK.md"
SCENARIOS = [
    ROOT / "public_scenarios" / "merge_intervals.json",
    ROOT / "public_scenarios" / "valid_parentheses.json",
    ROOT / "public_scenarios" / "top_k_frequent.json",
]


def emit(obj: dict) -> int:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
    sys.stdout.write("\n")
    sys.stdout.flush()
    return 0


def call_run(payload: dict, use_payload_arg: bool = False) -> dict:
    fd, result_path = tempfile.mkstemp(prefix="open_killer_selftest_", suffix=".json")
    os.close(fd)
    os.remove(result_path)
    raw = json.dumps(payload, ensure_ascii=False)
    cmd = [sys.executable, str(RUN), "--payload", raw] if use_payload_arg else [sys.executable, str(RUN)]
    proc = subprocess.run(
        cmd,
        input="" if use_payload_arg else raw,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env=dict(os.environ, AIASE_RESULT_PATH=result_path),
    )
    try:
        if proc.returncode != 0:
            raise AssertionError(f"run.py exited {proc.returncode}: {proc.stderr}")
        if proc.stdout.strip():
            raise AssertionError(f"stdout should be empty: {proc.stdout!r}")
        with open(result_path, encoding="utf-8") as f:
            return json.load(f)
    finally:
        if os.path.exists(result_path):
            os.remove(result_path)


def verify(payload: dict, output: dict) -> tuple[bool, str]:
    if not output.get("ok"):
        return False, f"run failed: {output}"
    required = {"task_id", "entry_point", "selected_tests", "killed_mutants", "unkilled_mutants", "kill_rate", "num_selected_tests"}
    if not required.issubset(output):
        return False, "missing required output fields"
    if output["task_id"] != payload["task_id"] or output["entry_point"] != payload["entry_point"]:
        return False, "task_id or entry_point mismatch"
    candidates = {c["id"]: c for c in payload["candidate_inputs"]}
    mutants = {m["id"]: m["code"] for m in payload["mutants"]}
    mutant_order = [m["id"] for m in payload["mutants"]]
    actual_killed: set[str] = set()
    if output["num_selected_tests"] != len(output["selected_tests"]):
        return False, "num_selected_tests mismatch"
    if output["num_selected_tests"] > int(payload["max_tests"]):
        return False, "too many selected tests"
    for test in output["selected_tests"]:
        if test.get("id") not in candidates:
            return False, f"unknown selected test {test.get('id')}"
        cand = candidates[test["id"]]
        ref = runner.call_function(payload["reference_code"], payload["entry_point"], cand.get("args", []), cand.get("kwargs", {}))
        if ref.get("status") != "ok":
            return False, f"selected test has invalid reference result {test['id']}"
        if ref["value"] != test.get("expected"):
            return False, f"expected mismatch for {test['id']}"
        real_kills = []
        for mid in mutant_order:
            got = runner.call_function(mutants[mid], payload["entry_point"], cand.get("args", []), cand.get("kwargs", {}))
            if got.get("status") in {"exception", "timeout"} or got.get("value") != ref["value"]:
                real_kills.append(mid)
        if test.get("kills") != real_kills:
            return False, f"kill list mismatch for {test['id']}"
        actual_killed.update(real_kills)
    expected_killed = [mid for mid in mutant_order if mid in actual_killed]
    expected_unkilled = [mid for mid in mutant_order if mid not in actual_killed]
    if output["killed_mutants"] != expected_killed or output["unkilled_mutants"] != expected_unkilled:
        return False, "killed/unkilled mutant lists mismatch"
    expected_rate = len(expected_killed) / len(mutant_order)
    if abs(float(output["kill_rate"]) - expected_rate) > 1e-12:
        return False, "kill_rate mismatch"
    if output["kill_rate"] < 0.8:
        return False, "kill_rate below 0.8"
    return True, ""


def verify_docs() -> tuple[bool, str]:
    skill_text = SKILL.read_text(encoding="utf-8")
    open_text = OPEN_TRACK.read_text(encoding="utf-8")
    for name, text in (("SKILL.md", skill_text), ("OPEN_TRACK.md", open_text)):
        for forbidden in ("REPO_ROOT", "git rev-parse", "/home/vivian", "/Users", "C:" + "\\Users"):
            if forbidden in text:
                return False, f"{name} contains forbidden text: {forbidden}"
    if "python3 <skill_dir>/scripts/run.py" not in skill_text:
        return False, "SKILL.md missing skill_dir run.py command"
    if "python3 <skill_dir>/scripts/run.py" not in open_text:
        return False, "OPEN_TRACK.md missing skill_dir run.py command"
    return True, ""


def main() -> int:
    scenarios = []
    failures = []
    docs_ok, docs_message = verify_docs()
    scenarios.append({"name": "docs", "ok": docs_ok, "kill_rate": 1.0 if docs_ok else 0.0})
    if not docs_ok:
        failures.append({"name": "docs", "message": docs_message})
    for path in SCENARIOS:
        name = path.stem
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            output = call_run(payload)
            ok, message = verify(payload, output)
            scenarios.append({"name": name, "ok": ok, "kill_rate": output.get("kill_rate", 0.0)})
            if not ok:
                failures.append({"name": name, "message": message})
        except Exception as exc:
            scenarios.append({"name": name, "ok": False, "kill_rate": 0.0})
            failures.append({"name": name, "message": f"{type(exc).__name__}: {exc}"})
    try:
        payload = json.loads(SCENARIOS[0].read_text(encoding="utf-8"))
        output = call_run(payload, use_payload_arg=True)
        ok, message = verify(payload, output)
        scenarios.append({"name": "payload_arg", "ok": ok, "kill_rate": output.get("kill_rate", 0.0)})
        if not ok:
            failures.append({"name": "payload_arg", "message": message})
    except Exception as exc:
        scenarios.append({"name": "payload_arg", "ok": False, "kill_rate": 0.0})
        failures.append({"name": "payload_arg", "message": f"{type(exc).__name__}: {exc}"})
    passed = sum(1 for item in scenarios if item["ok"])
    failed = len(scenarios) - passed
    if failed:
        return emit({"ok": False, "passed": passed, "failed": failed, "failures": failures}) or 1
    return emit({"ok": True, "passed": passed, "failed": 0, "scenarios": scenarios})


if __name__ == "__main__":
    sys.exit(main())
