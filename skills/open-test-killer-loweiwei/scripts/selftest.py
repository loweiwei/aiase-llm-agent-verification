#!/usr/bin/env python3
"""Black-box self-test for open-test-killer-loweiwei."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import copy
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


def _stdout_json(text: str) -> dict:
    raw = str(text or "").strip()
    if raw.startswith("```json"):
        raw = raw[len("```json"):].strip()
    if raw.endswith("```"):
        raw = raw[:-3].strip()
    return json.loads(raw)


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
        stdout_obj = _stdout_json(proc.stdout)
        with open(result_path, encoding="utf-8") as f:
            file_obj = json.load(f)
        if stdout_obj != file_obj:
            raise AssertionError("stdout JSON and result file differ")
        return file_obj
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
    if output.get("survived_mutants") != expected_unkilled:
        return False, "survived_mutants alias mismatch"
    expected_rate = len(expected_killed) / len(mutant_order)
    if abs(float(output["kill_rate"]) - expected_rate) > 1e-12:
        return False, "kill_rate mismatch"
    stats = output.get("evaluation_stats")
    if not isinstance(stats, dict) or "evaluation_truncated" not in stats or "selection_strategy" not in stats:
        return False, "missing evaluation_stats fields"
    expected_verdict = "pass" if output["kill_rate"] >= 0.8 and not stats.get("evaluation_truncated") else "fail"
    if output.get("verdict") != expected_verdict:
        return False, "verdict threshold mismatch"
    if output["kill_rate"] < 0.8:
        return False, "kill_rate below 0.8"
    return True, ""


def perturb_payload(payload: dict) -> dict:
    out = copy.deepcopy(payload)
    out["task_id"] = str(payload.get("task_id", "scenario")) + "_perturbed"
    out["candidate_inputs"] = list(reversed(out["candidate_inputs"]))
    out["mutants"] = list(reversed(out["mutants"]))
    out["candidate_inputs"].append({"id": "irrelevant_extra", "args": out["candidate_inputs"][0].get("args", []), "kwargs": out["candidate_inputs"][0].get("kwargs", {})})
    out["max_tests"] = max(1, min(int(out.get("max_tests", 1)), 3))
    return out


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


def typing_payload() -> dict:
    return {
        "task_id": "typing_import_case",
        "entry_point": "total",
        "max_tests": 1,
        "reference_code": "from typing import List, Optional, Dict, Tuple\ndef total(xs: List[int]) -> int:\n    meta: Optional[Dict[str, Tuple[int, int]]] = {'v': (1, 2)}\n    return sum(xs) + meta['v'][0] - 1\n",
        "mutants": [{"id": "typing_mutant", "code": "from typing import List\ndef total(xs: List[int]) -> int:\n    return len(xs)\n"}],
        "candidate_inputs": [{"id": "numbers", "args": [[2, 3, 4]], "kwargs": {}}],
    }


def class_payload() -> dict:
    return {
        "task_id": "class_definition_case",
        "entry_point": "score",
        "max_tests": 1,
        "reference_code": "class Helper:\n    def __init__(self, base):\n        self.base = base\n    def add(self, x):\n        return self.base + x\ndef score(x):\n    return Helper(10).add(x)\n",
        "mutants": [{"id": "class_mutant", "code": "class Helper:\n    def __init__(self, base):\n        self.base = base\n    def add(self, x):\n        return self.base - x\ndef score(x):\n    return Helper(10).add(x)\n"}],
        "candidate_inputs": [{"id": "five", "args": [5], "kwargs": {}}],
    }


def greedy_trap_payload() -> dict:
    mutants = []
    kill_map = {
        "m1": {"c0", "c1"},
        "m2": {"c0", "c1", "c2"},
        "m3": {"c0", "c2"},
        "m4": {"c1"},
        "m5": {"c2"},
    }
    for mid, killed_by in kill_map.items():
        values = sorted(killed_by)
        mutants.append({"id": mid, "code": "def probe(x):\n    return 1 if x in " + repr(values) + " else 0\n"})
    return {
        "task_id": "exact_search_greedy_trap",
        "entry_point": "probe",
        "max_tests": 2,
        "reference_code": "def probe(x):\n    return 0\n",
        "mutants": mutants,
        "candidate_inputs": [
            {"id": "c0", "args": ["c0"], "kwargs": {}},
            {"id": "c1", "args": ["c1"], "kwargs": {}},
            {"id": "c2", "args": ["c2"], "kwargs": {}},
        ],
    }


def renamed_mutant_payload() -> dict:
    payload = greedy_trap_payload()
    payload["task_id"] = "mutant_id_rename_case"
    renamed = []
    for idx, mutant in enumerate(payload["mutants"]):
        renamed.append({"id": f"renamed_mutant_{idx + 1}", "code": mutant["code"]})
    payload["mutants"] = list(reversed(renamed))
    return payload


def verdict_threshold_payload() -> dict:
    mutants = []
    for idx in range(5):
        killed = idx < 3
        mutants.append({"id": f"m{idx}", "code": f"def probe(x):\n    return {1 if killed else 0}\n"})
    return {
        "task_id": "verdict_threshold_case",
        "entry_point": "probe",
        "max_tests": 1,
        "reference_code": "def probe(x):\n    return 0\n",
        "mutants": mutants,
        "candidate_inputs": [{"id": "only", "args": [0], "kwargs": {}}],
    }


def verify_extra(name: str, payload: dict, expect_pass_metric: bool = True) -> tuple[bool, str, float]:
    output = call_run(payload)
    if expect_pass_metric:
        ok, message = verify(payload, output)
        if not ok:
            return False, message, float(output.get("kill_rate", 0.0))
        return True, "", float(output.get("kill_rate", 0.0))
    if not output.get("ok"):
        return False, f"run failed: {output}", float(output.get("kill_rate", 0.0))
    stats = output.get("evaluation_stats", {})
    if output.get("verdict") != "fail":
        return False, "kill_rate below threshold must have fail verdict", float(output.get("kill_rate", 0.0))
    if output.get("kill_rate", 0.0) >= 0.8 or stats.get("evaluation_truncated"):
        return False, "threshold scenario did not exercise low kill_rate", float(output.get("kill_rate", 0.0))
    return True, "", float(output.get("kill_rate", 0.0))


def verify_truncated_verdict() -> tuple[bool, str]:
    payload = typing_payload()
    candidates = [{"id": "numbers", "args": [[2, 3, 4]], "kwargs": {}, "expected": 9, "kills_set": {"typing_mutant"}, "order": 0}]
    output = runner.select_tests(payload, candidates, {"evaluation_truncated": True, "evaluated_candidates": 1, "evaluated_calls": 2})
    if output.get("verdict") != "fail":
        return False, "truncated evaluation must force fail verdict"
    if "truncated" not in str(output.get("rationale", "")).lower():
        return False, "truncated rationale missing"
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
            perturbed = perturb_payload(payload)
            perturbed_output = call_run(perturbed)
            pok, pmessage = verify(perturbed, perturbed_output)
            scenarios.append({"name": f"{name}_perturbed", "ok": pok, "kill_rate": perturbed_output.get("kill_rate", 0.0)})
            if not pok:
                failures.append({"name": f"{name}_perturbed", "message": pmessage})
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
    for name, payload, expect_pass_metric in (
        ("typing_import", typing_payload(), True),
        ("class_definition", class_payload(), True),
        ("exact_search_greedy_trap", greedy_trap_payload(), True),
        ("mutant_id_rename", renamed_mutant_payload(), True),
        ("verdict_threshold", verdict_threshold_payload(), False),
    ):
        try:
            ok, message, kill_rate = verify_extra(name, payload, expect_pass_metric)
            scenarios.append({"name": name, "ok": ok, "kill_rate": kill_rate})
            if not ok:
                failures.append({"name": name, "message": message})
        except Exception as exc:
            scenarios.append({"name": name, "ok": False, "kill_rate": 0.0})
            failures.append({"name": name, "message": f"{type(exc).__name__}: {exc}"})
    truncated_ok, truncated_message = verify_truncated_verdict()
    scenarios.append({"name": "truncated_verdict", "ok": truncated_ok, "kill_rate": 1.0 if truncated_ok else 0.0})
    if not truncated_ok:
        failures.append({"name": "truncated_verdict", "message": truncated_message})
    passed = sum(1 for item in scenarios if item["ok"])
    failed = len(scenarios) - passed
    if failed:
        return emit({"ok": False, "passed": passed, "failed": failed, "failures": failures}) or 1
    return emit({"ok": True, "passed": passed, "failed": 0, "scenarios": scenarios})


if __name__ == "__main__":
    sys.exit(main())
