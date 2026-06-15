#!/usr/bin/env python3
"""Legacy debug helper for deterministic edge-input probing.

This script is not used by the official bug-hunter scoring path. The official
entry point is run.py, which writes the contract JSON to AIASE_RESULT_PATH.

Usage:
    python analyze.py '{
        "code": "...",
        "entry_function": "<entry_name>",
        "edge_inputs": [          # optional; if omitted, a generic battery is used
            {"input": [[]],          "label": "empty container"},
            {"input": [0],           "label": "zero"}
        ]
    }'

Prints a debug JSON object to stdout:
    {"entry_found": bool,
     "ast_lines": {"entry_def": int, "return_lines": [int], "loop_lines": [int]},
     "probes": [{"label": str, "outcome": "ok"|"crash"|"timeout", "error": str}],
     "suspicious_lines": [int],
     "summary": str}

Use this only for local debugging; it must not affect formal grading output.
"""

from __future__ import annotations

import ast
import json
import re
import signal
import sys
import traceback
from contextlib import contextmanager


def _emit(obj: dict) -> int:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
    return 0


def _ast_features(code: str, entry: str) -> dict:
    out = {"entry_def": -1, "return_lines": [], "loop_lines": [], "subscript_lines": [], "division_lines": [], "mutation_lines": []}
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == entry:
            out["entry_def"] = node.lineno
        if isinstance(node, ast.Return) and node.lineno:
            out["return_lines"].append(node.lineno)
        if isinstance(node, (ast.For, ast.While)) and node.lineno:
            out["loop_lines"].append(node.lineno)
        if isinstance(node, ast.Subscript) and node.lineno:
            out["subscript_lines"].append(node.lineno)
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)) and node.lineno:
            out["division_lines"].append(node.lineno)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {"sort", "append", "extend", "pop", "remove", "clear"} and node.lineno:
            out["mutation_lines"].append(node.lineno)
    out["return_lines"].sort()
    out["loop_lines"].sort()
    out["subscript_lines"].sort()
    out["division_lines"].sort()
    out["mutation_lines"].sort()
    return out


def _infer_entry(task_description: str, code: str) -> str:
    m = re.search(r"Implement\s+([A-Za-z_]\w*)\s*\(", task_description or "")
    if m:
        return m.group(1)
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return ""
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            return node.name
    return ""


def _pattern_findings(code: str, ast_lines: dict) -> list[dict]:
    findings: list[dict] = []
    lines = code.splitlines()
    for i, line in enumerate(lines, 1):
        compact = line.replace(" ", "")
        if "[0]" in compact and not any("if not " in prev or "len(" in prev for prev in lines[max(0, i-4):i-1]):
            findings.append({"line": i, "type": "edge_case", "reason": "index 0 access without a nearby empty-input guard"})
        if "range(len(" in compact and "-1" in compact:
            findings.append({"line": i, "type": "off_by_one", "reason": "range(len(x)-1) may skip the last element"})
        if "/" in line or "%" in line:
            findings.append({"line": i, "type": "edge_case", "reason": "division/modulo may need zero handling"})
        if ".sort(" in line:
            findings.append({"line": i, "type": "logic_error", "reason": "in-place sort mutates caller input"})
    for line in ast_lines.get("division_lines", []):
        if not any(f["line"] == line for f in findings):
            findings.append({"line": line, "type": "edge_case", "reason": "arithmetic division/modulo needs denominator boundary review"})
    return findings


class _Timeout(Exception):
    pass


@contextmanager
def _time_limit(seconds: float):
    """SIGALRM-based timeout. POSIX only; Windows users will get no timeout."""
    if not hasattr(signal, "SIGALRM"):
        yield
        return
    def _handler(signum, frame):
        raise _Timeout("probe timed out")
    old = signal.signal(signal.SIGALRM, _handler)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


def _default_battery() -> list[dict]:
    """
    Task-agnostic shape probes. Each item passes a single positional argument
    of a common "shape category" (empty container, singleton, two-element,
    extremes, None). The probe layer only judges "crash vs ok vs timeout" and
    pins a line if the traceback points inside <candidate>; whether a crash
    is a *real* bug is your skill's call.

    Probes that fail with TypeError because the entry function has a different
    arity will not contribute a `bad_line` (their traceback is outside
    <candidate>), so wrong-arity noise does not pollute suspicious_lines.

    For more targeted probing, callers should pass `edge_inputs` in the
    payload instead of relying on this generic battery.
    """
    return [
        {"input": [[]],                "label": "empty list"},
        {"input": [[0]],               "label": "singleton list"},
        {"input": [[0, 0]],            "label": "two-element list (repeats)"},
        {"input": [[0, 1]],            "label": "two-element list (distinct)"},
        {"input": [""],                "label": "empty string"},
        {"input": ["a"],               "label": "single-char string"},
        {"input": [0],                 "label": "zero"},
        {"input": [-1],                "label": "negative integer"},
        {"input": [10**6],             "label": "large integer"},
        {"input": [None],              "label": "None"},
    ]


def _probe(code: str, entry: str, sample: dict, timeout_sec: float) -> dict:
    ns: dict = {}
    try:
        exec(compile(code, "<candidate>", "exec"), ns)
    except Exception as e:
        return {"label": sample.get("label", "?"), "outcome": "crash",
                "error": f"compile/exec error: {e!r}"}
    fn = ns.get(entry)
    if not callable(fn):
        return {"label": sample.get("label", "?"), "outcome": "crash",
                "error": f"entry function {entry!r} not defined"}
    args = sample.get("input", [])
    try:
        with _time_limit(timeout_sec):
            _ = fn(*args) if isinstance(args, list) else fn(args)
        return {"label": sample.get("label", "?"), "outcome": "ok", "error": ""}
    except _Timeout as e:
        return {"label": sample.get("label", "?"), "outcome": "timeout", "error": str(e)}
    except Exception as e:
        tb = traceback.extract_tb(e.__traceback__)
        # 找 traceback 中對應 <candidate> 的最後一行,推測 suspicious line
        bad_line = -1
        for f in tb:
            if f.filename == "<candidate>" and f.lineno:
                bad_line = f.lineno
        return {
            "label": sample.get("label", "?"),
            "outcome": "crash",
            "error": f"{type(e).__name__}: {e}",
            "bad_line": bad_line,
        }


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        return _emit({"entry_found": False, "ast_lines": {}, "probes": [],
                      "suspicious_lines": [], "summary": "usage: analyze.py '<json>'"})
    try:
        payload = json.loads(argv[1])
    except json.JSONDecodeError as e:
        return _emit({"entry_found": False, "ast_lines": {}, "probes": [],
                      "suspicious_lines": [], "summary": f"argv JSON invalid: {e}"})

    code = str(payload.get("code", "")).replace("\r\n", "\n")
    task_description = str(payload.get("task_description", ""))
    entry = str(payload.get("entry_function", "")) or _infer_entry(task_description, code)
    samples = payload.get("edge_inputs") or _default_battery()
    timeout_sec = float(payload.get("timeout_sec", 1.0))

    ast_lines = _ast_features(code, entry)
    entry_found = ast_lines.get("entry_def", -1) > 0
    pattern_findings = _pattern_findings(code, ast_lines)

    probes = []
    suspicious: set[int] = set()
    for s in samples:
        r = _probe(code, entry, s, timeout_sec)
        probes.append(r)
        if r["outcome"] != "ok" and r.get("bad_line", -1) > 0:
            suspicious.add(r["bad_line"])

    crashes = sum(1 for r in probes if r["outcome"] == "crash")
    timeouts = sum(1 for r in probes if r["outcome"] == "timeout")
    summary = (
        f"{len(probes)} probes; {crashes} crash, {timeouts} timeout, "
        f"{len(probes)-crashes-timeouts} ok; "
        f"suspicious_lines={sorted(suspicious)}"
    )

    return _emit({
        "entry_found": entry_found,
        "entry_function": entry,
        "ast_lines": ast_lines,
        "probes": probes,
        "pattern_findings": pattern_findings,
        "suspicious_lines": sorted(suspicious),
        "summary": summary,
    })


if __name__ == "__main__":
    sys.exit(main(sys.argv))
