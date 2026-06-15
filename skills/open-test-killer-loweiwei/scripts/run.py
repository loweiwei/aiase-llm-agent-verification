#!/usr/bin/env python3
"""Deterministic mutation-test selector for Open Track.

Reads one JSON payload from stdin and writes exactly one JSON object to
AIASE_RESULT_PATH, or ./aiase_result.json when AIASE_RESULT_PATH is unset.
Stdout is intentionally unused.
"""

from __future__ import annotations

import contextlib
import io
import json
import multiprocessing as mp
import os
import queue
import sys
import tempfile
import time
from typing import Any


TIMEOUT_SEC = 1.0
GLOBAL_DEADLINE_SEC = 110.0
MAX_EVAL_CALLS = 2000
REQUIRED_FIELDS = {"task_id", "entry_point", "max_tests", "reference_code", "mutants", "candidate_inputs"}


def resolve_result_path() -> str:
    return os.environ.get("AIASE_RESULT_PATH") or os.path.join(os.getcwd(), "aiase_result.json")


def write_result(obj: dict) -> str:
    path = resolve_result_path()
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".aiase_result_", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
            f.write("\n")
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
    return path


def emit(obj: dict) -> int:
    write_result(obj)
    return 0


def fail(error_type: str, message: str) -> dict:
    return {"ok": False, "error_type": error_type, "message": message}


def normalize(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, tuple):
        return [normalize(v) for v in value]
    if isinstance(value, list):
        return [normalize(v) for v in value]
    if isinstance(value, dict):
        out = {}
        for key in sorted(value, key=lambda x: str(x)):
            if not isinstance(key, (str, int, float, bool)) and key is not None:
                raise TypeError("dict key is not JSON serializable")
            out[str(key)] = normalize(value[key])
        return out
    raise TypeError(f"output of type {type(value).__name__} is not JSON serializable")


def ensure_jsonable(value: Any) -> Any:
    normalized = normalize(value)
    json.dumps(normalized, ensure_ascii=False, sort_keys=True)
    return normalized


def _worker(source: str, entry_point: str, args: list, kwargs: dict, outq: mp.Queue) -> None:
    try:
        ns: dict[str, Any] = {"__builtins__": __builtins__}
        sink = io.StringIO()
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            exec(compile(source, "<candidate_code>", "exec"), ns)
            fn = ns.get(entry_point)
            if not callable(fn):
                outq.put({"status": "exception", "error": f"entry point {entry_point!r} not callable"})
                return
            result = fn(*args, **kwargs)
        outq.put({"status": "ok", "value": ensure_jsonable(result)})
    except BaseException as exc:
        outq.put({"status": "exception", "error": f"{type(exc).__name__}: {exc}"})


def call_function(source: str, entry_point: str, args: list, kwargs: dict, timeout: float = TIMEOUT_SEC) -> dict:
    outq: mp.Queue = mp.Queue(maxsize=1)
    proc = mp.Process(target=_worker, args=(source, entry_point, args, kwargs, outq))
    proc.daemon = True
    proc.start()
    proc.join(timeout)
    if proc.is_alive():
        proc.terminate()
        proc.join(0.2)
        return {"status": "timeout", "error": "timeout"}
    try:
        return outq.get_nowait()
    except queue.Empty:
        return {"status": "exception", "error": "no result returned"}


def validate_payload(payload: Any) -> tuple[dict | None, dict | None]:
    if not isinstance(payload, dict):
        return None, fail("invalid_input_schema", "top-level input must be an object")
    missing = sorted(REQUIRED_FIELDS - set(payload))
    if missing:
        return None, fail("invalid_input_schema", f"missing required fields: {missing}")
    if not isinstance(payload.get("task_id"), str) or not payload["task_id"]:
        return None, fail("invalid_input_schema", "task_id must be a non-empty string")
    if not isinstance(payload.get("entry_point"), str) or not payload["entry_point"]:
        return None, fail("invalid_input_schema", "entry_point must be a non-empty string")
    if not isinstance(payload.get("reference_code"), str) or not payload["reference_code"]:
        return None, fail("invalid_input_schema", "reference_code must be a non-empty string")
    if not isinstance(payload.get("mutants"), list):
        return None, fail("invalid_input_schema", "mutants must be an array")
    if not payload["mutants"]:
        return None, fail("no_mutants", "mutants must not be empty")
    if not isinstance(payload.get("candidate_inputs"), list):
        return None, fail("invalid_input_schema", "candidate_inputs must be an array")
    if not payload["candidate_inputs"]:
        return None, fail("no_candidates", "candidate_inputs must not be empty")
    try:
        max_tests = int(payload.get("max_tests"))
    except (TypeError, ValueError):
        return None, fail("invalid_input_schema", "max_tests must be an integer")
    if max_tests < 0:
        return None, fail("invalid_input_schema", "max_tests must be non-negative")
    mutant_ids = set()
    for idx, mutant in enumerate(payload["mutants"]):
        if not isinstance(mutant, dict) or not isinstance(mutant.get("id"), str) or not isinstance(mutant.get("code"), str):
            return None, fail("invalid_input_schema", f"mutants[{idx}] must contain string id and code")
        if mutant["id"] in mutant_ids:
            return None, fail("invalid_input_schema", f"duplicate mutant id: {mutant['id']}")
        mutant_ids.add(mutant["id"])
    candidate_ids = set()
    for idx, cand in enumerate(payload["candidate_inputs"]):
        if not isinstance(cand, dict) or not isinstance(cand.get("id"), str):
            return None, fail("invalid_input_schema", f"candidate_inputs[{idx}] must contain string id")
        if cand["id"] in candidate_ids:
            return None, fail("invalid_input_schema", f"duplicate candidate id: {cand['id']}")
        candidate_ids.add(cand["id"])
        if not isinstance(cand.get("args", []), list):
            return None, fail("invalid_input_schema", f"candidate_inputs[{idx}].args must be an array")
        if not isinstance(cand.get("kwargs", {}), dict):
            return None, fail("invalid_input_schema", f"candidate_inputs[{idx}].kwargs must be an object")
    return payload, None


def _guard_exceeded(start_time: float, eval_calls: int) -> bool:
    return eval_calls >= MAX_EVAL_CALLS or (time.monotonic() - start_time) > GLOBAL_DEADLINE_SEC


def build_matrix(payload: dict, start_time: float) -> tuple[list[dict], dict | None, dict]:
    entry = payload["entry_point"]
    valid_candidates: list[dict] = []
    eval_calls = 0
    truncated = False
    for cand_index, cand in enumerate(payload["candidate_inputs"]):
        args = cand.get("args", [])
        kwargs = cand.get("kwargs", {})
        if _guard_exceeded(start_time, eval_calls):
            truncated = True
            break
        eval_calls += 1
        ref_result = call_function(payload["reference_code"], entry, args, kwargs)
        if ref_result["status"] == "timeout":
            continue
        if ref_result["status"] != "ok":
            continue
        expected = ref_result["value"]
        kills: set[str] = set()
        candidate_complete = True
        for mutant in payload["mutants"]:
            if _guard_exceeded(start_time, eval_calls):
                truncated = True
                candidate_complete = False
                break
            eval_calls += 1
            got = call_function(mutant["code"], entry, args, kwargs)
            if got["status"] in {"exception", "timeout"} or got.get("value") != expected:
                kills.add(mutant["id"])
        if not candidate_complete:
            break
        valid_candidates.append({
            "id": cand["id"],
            "args": args,
            "kwargs": kwargs,
            "expected": expected,
            "kills_set": kills,
            "order": cand_index,
        })
        if truncated:
            break
    stats = {"evaluation_truncated": truncated, "evaluated_candidates": len(valid_candidates), "evaluated_calls": eval_calls}
    if not valid_candidates:
        # Distinguish global reference failure only when every candidate timed out or errored.
        return [], fail("reference_execution_error", "reference implementation failed or timed out on all candidates"), stats
    return valid_candidates, None, stats


def greedy_select(payload: dict, candidates: list[dict], stats: dict | None = None) -> dict:
    mutant_order = [m["id"] for m in payload["mutants"]]
    remaining = set(mutant_order)
    selected: list[dict] = []
    max_tests = int(payload["max_tests"])
    while len(selected) < max_tests:
        best = None
        best_key = None
        for cand in candidates:
            if any(cand["id"] == chosen["id"] for chosen in selected):
                continue
            newly = cand["kills_set"] & remaining
            if not newly:
                continue
            key = (len(newly), -cand["order"], tuple([-ord(ch) for ch in cand["id"]]))
            if best is None or key > best_key:
                best = cand
                best_key = key
        if best is None:
            break
        selected.append(best)
        remaining -= best["kills_set"]
    killed = [mid for mid in mutant_order if mid not in remaining]
    unkilled = [mid for mid in mutant_order if mid in remaining]
    selected_tests = []
    for cand in selected:
        selected_tests.append({
            "id": cand["id"],
            "args": cand["args"],
            "kwargs": cand["kwargs"],
            "expected": cand["expected"],
            "kills": [mid for mid in mutant_order if mid in cand["kills_set"]],
        })
    out = {
        "ok": True,
        "task_id": payload["task_id"],
        "entry_point": payload["entry_point"],
        "selected_tests": selected_tests,
        "killed_mutants": killed,
        "unkilled_mutants": unkilled,
        "kill_rate": len(killed) / len(mutant_order),
        "num_selected_tests": len(selected_tests),
    }
    return out


def run(payload: dict) -> dict:
    start_time = time.monotonic()
    valid, err = validate_payload(payload)
    if err is not None:
        return err
    try:
        candidates, matrix_err, stats = build_matrix(valid, start_time)
        if matrix_err is not None:
            return matrix_err
        return greedy_select(valid, candidates, stats)
    except Exception as exc:
        return fail("internal_error", f"{type(exc).__name__}: {exc}")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    if len(argv) >= 3 and argv[1] == "--payload":
        raw = argv[2]
    else:
        raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return emit(fail("invalid_json", str(exc)))
    return emit(run(payload))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
