#!/usr/bin/env python3
"""Deterministic mutation-test selector for Open Track.

Reads one JSON payload from stdin, writes one JSON object to AIASE_RESULT_PATH
when set, and always prints the final fenced JSON block to stdout.
"""

from __future__ import annotations

import contextlib
import io
import json
import builtins
import itertools
import math
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
MAX_EXACT_COMBINATIONS = 25000
REQUIRED_FIELDS = {"task_id", "entry_point", "max_tests", "reference_code", "mutants", "candidate_inputs"}
ALLOWED_IMPORTS = {"math", "collections", "itertools", "functools", "heapq", "bisect", "re", "string", "typing", "operator"}


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
    sys.stdout.write("```json\n")
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True))
    sys.stdout.write("\n```\n")
    return 0


def fail(error_type: str, message: str, payload: dict | None = None) -> dict:
    payload = payload if isinstance(payload, dict) else {}
    return {
        "ok": False,
        "task_id": str(payload.get("task_id", "")),
        "entry_point": str(payload.get("entry_point", "")),
        "selected_tests": [],
        "killed_mutants": [],
        "unkilled_mutants": [],
        "survived_mutants": [],
        "kill_rate": 0.0,
        "num_selected_tests": 0,
        "max_tests": int(payload.get("max_tests", 0)) if str(payload.get("max_tests", "0")).lstrip("-").isdigit() else 0,
        "total_mutants": len(payload.get("mutants", [])) if isinstance(payload.get("mutants"), list) else 0,
        "verdict": "fail",
        "confidence": 1.0,
        "rationale": "invalid or unevaluable payload",
        "error_type": error_type,
        "message": message,
    }


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


def _safe_import(name: str, globals_: Any = None, locals_: Any = None, fromlist: Any = (), level: int = 0) -> Any:
    root = str(name).split(".", 1)[0]
    if root not in ALLOWED_IMPORTS:
        raise ImportError(f"import not allowed: {name}")
    return __import__(name, globals_, locals_, fromlist, level)


def _safe_builtins() -> dict[str, Any]:
    names = {
        "abs", "all", "any", "bool", "dict", "enumerate", "filter", "float",
        "int", "isinstance", "len", "list", "map", "max", "min", "ord", "chr",
        "pow", "range", "reversed", "round", "set", "slice", "sorted", "str",
        "sum", "tuple", "zip", "print", "repr", "callable", "getattr", "hasattr",
        "setattr", "iter", "next", "divmod", "hash",
    }
    safe = {name: getattr(builtins, name) for name in names}
    safe.update({
        "Exception": Exception,
        "ValueError": ValueError,
        "TypeError": TypeError,
        "IndexError": IndexError,
        "KeyError": KeyError,
        "object": object,
        "__build_class__": builtins.__build_class__,
        "__import__": _safe_import,
    })
    return safe


def _worker(source: str, entry_point: str, args: list, kwargs: dict, outq: mp.Queue) -> None:
    try:
        ns: dict[str, Any] = {"__name__": "__candidate__", "__builtins__": _safe_builtins()}
        sink = io.StringIO()
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            exec(compile(source, "<candidate_code>", "exec"), ns, ns)
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
        return None, fail("invalid_input_schema", f"missing required fields: {missing}", payload)
    if not isinstance(payload.get("task_id"), str) or not payload["task_id"]:
        return None, fail("invalid_input_schema", "task_id must be a non-empty string", payload)
    if not isinstance(payload.get("entry_point"), str) or not payload["entry_point"]:
        return None, fail("invalid_input_schema", "entry_point must be a non-empty string", payload)
    if not isinstance(payload.get("reference_code"), str) or not payload["reference_code"]:
        return None, fail("invalid_input_schema", "reference_code must be a non-empty string", payload)
    if not isinstance(payload.get("mutants"), list):
        return None, fail("invalid_input_schema", "mutants must be an array", payload)
    if not payload["mutants"]:
        return None, fail("no_mutants", "mutants must not be empty", payload)
    if not isinstance(payload.get("candidate_inputs"), list):
        return None, fail("invalid_input_schema", "candidate_inputs must be an array", payload)
    if not payload["candidate_inputs"]:
        return None, fail("no_candidates", "candidate_inputs must not be empty", payload)
    try:
        max_tests = int(payload.get("max_tests"))
    except (TypeError, ValueError):
        return None, fail("invalid_input_schema", "max_tests must be an integer", payload)
    if max_tests < 0:
        return None, fail("invalid_input_schema", "max_tests must be non-negative", payload)
    mutant_ids = set()
    for idx, mutant in enumerate(payload["mutants"]):
        if not isinstance(mutant, dict) or not isinstance(mutant.get("id"), str) or not isinstance(mutant.get("code"), str):
            return None, fail("invalid_input_schema", f"mutants[{idx}] must contain string id and code", payload)
        if mutant["id"] in mutant_ids:
            return None, fail("invalid_input_schema", f"duplicate mutant id: {mutant['id']}", payload)
        mutant_ids.add(mutant["id"])
    candidate_ids = set()
    for idx, cand in enumerate(payload["candidate_inputs"]):
        if not isinstance(cand, dict) or not isinstance(cand.get("id"), str):
            return None, fail("invalid_input_schema", f"candidate_inputs[{idx}] must contain string id", payload)
        if cand["id"] in candidate_ids:
            return None, fail("invalid_input_schema", f"duplicate candidate id: {cand['id']}", payload)
        candidate_ids.add(cand["id"])
        if not isinstance(cand.get("args", []), list):
            return None, fail("invalid_input_schema", f"candidate_inputs[{idx}].args must be an array", payload)
        if not isinstance(cand.get("kwargs", {}), dict):
            return None, fail("invalid_input_schema", f"candidate_inputs[{idx}].kwargs must be an object", payload)
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
        return [], fail("reference_execution_error", "reference implementation failed or timed out on all candidates", payload), stats
    return valid_candidates, None, stats


def _combo_count(candidate_count: int, max_tests: int) -> int:
    limit = min(candidate_count, max_tests)
    total = 0
    for size in range(1, limit + 1):
        total += math.comb(candidate_count, size)
        if total > MAX_EXACT_COMBINATIONS:
            break
    return total


def _selection_rank(combo: tuple[dict, ...]) -> tuple[tuple[int, str], ...]:
    return tuple((int(cand["order"]), str(cand["id"])) for cand in combo)


def _better_selection(candidate_combo: tuple[dict, ...], candidate_kills: set[str], best_combo: tuple[dict, ...], best_kills: set[str]) -> bool:
    if len(candidate_kills) != len(best_kills):
        return len(candidate_kills) > len(best_kills)
    if len(candidate_combo) != len(best_combo):
        return len(candidate_combo) < len(best_combo)
    return _selection_rank(candidate_combo) < _selection_rank(best_combo)


def _exact_select(candidates: list[dict], max_tests: int) -> tuple[list[dict], bool, int]:
    candidate_count = len(candidates)
    total_combinations = _combo_count(candidate_count, max_tests)
    if max_tests <= 0 or candidate_count == 0:
        return [], True, 0
    if total_combinations > MAX_EXACT_COMBINATIONS:
        return [], False, total_combinations

    best_combo: tuple[dict, ...] = ()
    best_kills: set[str] = set()
    for size in range(1, min(candidate_count, max_tests) + 1):
        for combo in itertools.combinations(candidates, size):
            kills: set[str] = set()
            for cand in combo:
                kills.update(cand["kills_set"])
            if _better_selection(combo, kills, best_combo, best_kills):
                best_combo = combo
                best_kills = kills
    return list(best_combo), True, total_combinations


def _greedy_select(candidates: list[dict], max_tests: int, mutant_order: list[str]) -> list[dict]:
    remaining = set(mutant_order)
    selected: list[dict] = []
    while len(selected) < max_tests:
        best = None
        best_key = None
        for cand in candidates:
            if any(cand["id"] == chosen["id"] for chosen in selected):
                continue
            newly = cand["kills_set"] & remaining
            if not newly:
                continue
            key = (-len(newly), int(cand["order"]), str(cand["id"]))
            if best is None or key < best_key:
                best = cand
                best_key = key
        if best is None:
            break
        selected.append(best)
        remaining -= best["kills_set"]
    return selected


def select_tests(payload: dict, candidates: list[dict], stats: dict | None = None) -> dict:
    mutant_order = [m["id"] for m in payload["mutants"]]
    max_tests = int(payload["max_tests"])
    selected, exact_used, exact_combinations = _exact_select(candidates, max_tests)
    strategy = "exact" if exact_used else "greedy_fallback"
    if not exact_used:
        selected = _greedy_select(candidates, max_tests, mutant_order)
    remaining = set(mutant_order)
    for cand in selected:
        remaining -= cand["kills_set"]
    killed = [mid for mid in mutant_order if mid not in remaining]
    unkilled = [mid for mid in mutant_order if mid in remaining]
    kill_rate = len(killed) / len(mutant_order)
    evaluation_truncated = bool((stats or {}).get("evaluation_truncated"))
    verdict = "pass" if kill_rate >= 0.8 and not evaluation_truncated else "fail"
    rationale = "Deterministic exact max-coverage over execution-derived kill sets."
    if strategy == "greedy_fallback":
        rationale = "Deterministic greedy fallback over execution-derived kill sets after exact search budget was exceeded."
    if evaluation_truncated:
        rationale += " Evaluation was truncated, so the selection is best-effort and verdict is fail."
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
        "survived_mutants": unkilled,
        "kill_rate": kill_rate,
        "num_selected_tests": len(selected_tests),
        "max_tests": max_tests,
        "total_mutants": len(mutant_order),
        "verdict": verdict,
        "confidence": 1.0,
        "rationale": rationale,
    }
    selection_stats = {
        "selection_strategy": strategy,
        "exact_combinations_considered": exact_combinations if exact_used else 0,
        "exact_combination_budget": MAX_EXACT_COMBINATIONS,
    }
    if stats:
        out["evaluation_stats"] = {**stats, **selection_stats}
    else:
        out["evaluation_stats"] = selection_stats
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
        return select_tests(valid, candidates, stats)
    except Exception as exc:
        return fail("internal_error", f"{type(exc).__name__}: {exc}", payload)


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
