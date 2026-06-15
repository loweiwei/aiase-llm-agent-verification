#!/usr/bin/env python3
"""Deterministic Pairwise Code Author generator."""

from __future__ import annotations

import ast
import contextlib
import copy
import io
import json
import keyword
import os
import re
import signal
import sys
import tempfile
from dataclasses import dataclass
from typing import Any


CASE_TIMEOUT_SEC = 0.25
MAX_CASES = 20
MAX_ERROR_LEN = 300
CANDIDATE_MARKER = "__AIASERUN_CANDIDATE_CODE_V1__"
BANNED_CALLS = {"__import__", "eval", "exec", "open", "compile", "input", "breakpoint", "print"}
BANNED_ATTR_CALLS = {"import_module", "system", "popen", "remove", "unlink", "rmdir", "mkdir", "makedirs", "rename"}
AMBIGUOUS_ALIASES = {"search", "insert", "solve", "solution"}
BANNED_MODULES = {
    "os", "sys", "subprocess", "multiprocessing", "threading", "socket", "requests", "urllib",
    "http", "ftplib", "ssl", "importlib", "pathlib", "shutil", "glob", "runpy", "pkgutil",
    "pickle", "marshal", "ctypes", "asyncio", "concurrent",
}


@dataclass(frozen=True)
class Template:
    name: str
    aliases: tuple[str, ...]
    keyword_groups: tuple[tuple[str, ...], ...]
    body: str
    tests: tuple[dict, ...]
    confidence: float


@dataclass(frozen=True)
class CandidateResult:
    source: str
    code: str
    loc: int
    passed: int
    failed: int
    errors: list[str]
    import_violations: list[str]
    sandbox_violations: list[str]
    loc_violation: bool
    entry_missing: bool
    confidence: float
    rationale: str


class _Timeout(Exception):
    pass


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


def _clean_error(text: Any) -> str:
    return str(text).replace("\n", " ")[:MAX_ERROR_LEN]


def _limit_errors(errors: list[str]) -> list[str]:
    return [_clean_error(err) for err in errors[:5]]


def _emit(obj: dict) -> int:
    write_result(obj)
    return 0


def _split_payload_and_candidate(raw: str) -> tuple[str, str]:
    if CANDIDATE_MARKER not in raw:
        return raw.strip(), ""
    left, _, right = raw.partition(CANDIDATE_MARKER)
    return left.strip(), right.strip()


def _read_input(argv: list[str]) -> tuple[dict, str]:
    raw = argv[1] if len(argv) >= 2 and argv[1] != "-" else sys.stdin.read()
    payload_raw, candidate_raw = _split_payload_and_candidate(raw)
    if not payload_raw.strip():
        raise ValueError("empty JSON payload")
    try:
        payload = json.loads(payload_raw)
    except json.JSONDecodeError:
        if candidate_raw:
            raise
        decoder = json.JSONDecoder()
        payload, idx = decoder.raw_decode(payload_raw.lstrip())
        candidate_raw = payload_raw.lstrip()[idx:].strip()
    if not isinstance(payload, dict):
        raise ValueError("payload not an object")
    return payload, candidate_raw


def _strip_code_fences(code: str) -> str:
    text = str(code or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return text.strip() + ("\n" if text.strip() else "")


def _fallback_code() -> str:
    return "def solution(*args):\n    return None\n"


def _error_contract(task_id: str, rationale: str, message: str) -> dict:
    return {
        "task_id": str(task_id or ""),
        "code": _fallback_code(),
        "loc": 2,
        "self_test_results": {
            "passed": 0,
            "failed": 1,
            "errors": [_clean_error(message)],
            "sloc": 2,
            "loc_violation": False,
            "import_violations": [],
            "sandbox_violations": [],
        },
        "rationale": rationale,
        "confidence": 0.0,
    }


def _invalid_input_contract(message: str) -> dict:
    return _error_contract("", "invalid input fallback", f"invalid input JSON: {message}")


def _internal_error_contract(payload: dict | None, message: str) -> dict:
    task_id = payload.get("task_id", "") if isinstance(payload, dict) else ""
    return _error_contract(str(task_id), "internal error fallback", f"internal error: {message}")


def _safe_entry(name: Any) -> str:
    text = str(name or "solution").strip()
    if not re.match(r"^[A-Za-z_]\w*$", text) or keyword.iskeyword(text):
        return "solution"
    return text


def _sloc(code: str) -> int:
    return sum(1 for line in code.splitlines() if line.strip() and not line.strip().startswith("#"))


def _clamp(value: Any, default: float = 0.5) -> float:
    try:
        num = float(value)
    except (TypeError, ValueError):
        num = default
    return max(0.0, min(1.0, num))


def _to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_self_test_results(value: Any, passed: Any, failed: Any) -> dict:
    parsed = value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = None
    if not isinstance(parsed, dict):
        parsed = {}
    out = dict(parsed)
    out["passed"] = _to_int(out.get("passed", passed), 0)
    out["failed"] = _to_int(out.get("failed", failed), 0)
    return out


def _contract_from_cli_args(args: Any) -> dict:
    code = str(args.code or "")
    loc_default = _sloc(code)
    return {
        "task_id": str(args.task_id or ""),
        "code": code,
        "loc": _to_int(args.loc, loc_default),
        "self_test_results": _normalize_self_test_results(args.self_test_results, args.self_test_passed, args.self_test_failed),
        "rationale": str(args.rationale or ""),
        "confidence": _clamp(args.confidence),
    }


def _parse_cli_args(argv: list[str]) -> Any | None:
    if not any(arg.startswith("--") for arg in argv[1:]):
        return None
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--task_id")
    parser.add_argument("--code")
    parser.add_argument("--loc")
    parser.add_argument("--self_test_passed", default=0)
    parser.add_argument("--self_test_failed", default=0)
    parser.add_argument("--self_test_results", default="")
    parser.add_argument("--rationale", default="")
    parser.add_argument("--confidence", default=0.5)
    parser.add_argument("--payload", default="")
    parser.add_argument("--candidate_code", default="")
    return parser.parse_args(argv[1:])


def _payload_candidate_from_cli(args: Any) -> tuple[dict, str]:
    payload = json.loads(str(args.payload or ""))
    if not isinstance(payload, dict):
        raise ValueError("payload not an object")
    return payload, str(args.candidate_code or "")


def _render(entry: str, body: str) -> str:
    return body.strip().replace("__ENTRY__", entry) + "\n"


def _contains_entry(code: str, entry: str) -> bool:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False
    return any(isinstance(node, ast.FunctionDef) and node.name == entry for node in tree.body)


def _static_checks(code: str, forbidden: list[Any]) -> tuple[list[str], list[str]]:
    forbidden_roots = {str(item).split(".")[0] for item in forbidden if str(item).strip()}
    import_violations: set[str] = set()
    sandbox_violations: set[str] = set()
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [], [f"syntax error: {exc}"]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in forbidden_roots:
                    import_violations.add(alias.name)
                if root in BANNED_MODULES:
                    sandbox_violations.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".")[0]
            if root in forbidden_roots:
                import_violations.add(node.module)
            if root in BANNED_MODULES:
                sandbox_violations.add(node.module)
        elif isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id in BANNED_CALLS:
                sandbox_violations.add(fn.id)
            elif isinstance(fn, ast.Attribute):
                if fn.attr in BANNED_ATTR_CALLS:
                    sandbox_violations.add(fn.attr)
                if fn.attr == "import_module" and isinstance(fn.value, ast.Name) and fn.value.id == "importlib":
                    sandbox_violations.add("importlib.import_module")
    return sorted(import_violations), sorted(sandbox_violations)


def _import_roots(code: str) -> list[str]:
    roots: set[str] = set()
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return sorted(roots)


def _allowed_import_violations(code: str, constraints: dict) -> list[str]:
    if "imports_allowed" not in constraints:
        return []
    allowed_raw = constraints.get("imports_allowed", [])
    allowed = {str(item).split(".")[0] for item in allowed_raw if str(item).strip()} if isinstance(allowed_raw, list) else set()
    return [root for root in _import_roots(code) if root not in allowed]


def _literal_source(value: Any) -> str:
    return repr(value)


def _sample_hardcode_warnings(code: str, sample_cases: list[dict]) -> list[str]:
    if not sample_cases:
        return []
    warnings: list[str] = []
    compact_code = re.sub(r"\s+", "", code)
    has_general_flow = bool(re.search(r"\b(for|while)\b|\.append\(|yield\b|\breturn\s+\[.*for\s+", code))
    exact_branch = re.compile(r"\b(?:if|elif)\s+[^:\n]+==\s*([\[\(\{][^:\n]+[\]\)\}])\s*:")
    for case in sample_cases[:5]:
        raw_inputs = case.get("input", case.get("args", []))
        inputs = raw_inputs if isinstance(raw_inputs, list) else [raw_inputs]
        expected = case.get("expected", case.get("output"))
        for value in inputs:
            literal = re.sub(r"\s+", "", _literal_source(value))
            if len(literal) >= 6:
                for match in exact_branch.finditer(code):
                    compared = re.sub(r"\s+", "", match.group(1))
                    if compared == literal:
                        warnings.append("candidate appears to branch on an exact public sample input")
                        return warnings
        expected_literal = re.sub(r"\s+", "", _literal_source(expected))
        if expected_literal and len(expected_literal) >= 4 and compact_code.count("return") <= 1 and f"return{expected_literal}" in compact_code and not has_general_flow:
            warnings.append("candidate appears to return an exact public sample output without general logic")
            return warnings
    return warnings


def _is_safe_literal(node: ast.AST | None) -> bool:
    if node is None:
        return True
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return all(_is_safe_literal(item) for item in node.elts)
    if isinstance(node, ast.Dict):
        return all(_is_safe_literal(k) and _is_safe_literal(v) for k, v in zip(node.keys, node.values))
    if isinstance(node, ast.UnaryOp):
        return _is_safe_literal(getattr(node, "operand", None))
    return False


def _top_level_errors(tree: ast.Module) -> list[str]:
    errors: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.Import, ast.ImportFrom)):
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            continue
        if isinstance(node, ast.Assign) and _is_safe_literal(node.value):
            continue
        if isinstance(node, ast.AnnAssign) and _is_safe_literal(node.value):
            continue
        errors.append(f"unsafe top-level statement: {type(node).__name__}")
    return errors


def _validate_candidate(code: str, entry: str, constraints: dict) -> dict:
    cleaned = _strip_code_fences(code)
    errors: list[str] = []
    if not cleaned.strip():
        return {"ok": False, "code": "", "loc": 0, "import_violations": [], "sandbox_violations": [], "errors": ["empty candidate code"]}
    try:
        tree = ast.parse(cleaned)
    except SyntaxError as exc:
        return {"ok": False, "code": cleaned, "loc": _sloc(cleaned), "import_violations": [], "sandbox_violations": [], "errors": [f"syntax error: {exc}"]}
    errors.extend(_top_level_errors(tree))
    if not any(isinstance(node, ast.FunctionDef) and node.name == entry for node in tree.body):
        errors.append(f"entry function {entry!r} not defined")
    loc = _sloc(cleaned)
    try:
        max_loc = int(constraints.get("max_loc", 500))
    except (TypeError, ValueError):
        max_loc = 500
    if loc > max_loc:
        errors.append(f"loc violation: {loc} > {max_loc}")
    forbidden = constraints.get("imports_forbidden", [])
    forbidden = forbidden if isinstance(forbidden, list) else []
    import_violations, sandbox_violations = _static_checks(cleaned, forbidden)
    import_violations = sorted(set(import_violations) | set(_allowed_import_violations(cleaned, constraints)))
    errors.extend([f"forbidden import: {name}" for name in import_violations])
    errors.extend([f"sandbox violation: {name}" for name in sandbox_violations])
    return {
        "ok": not errors,
        "code": cleaned,
        "loc": loc,
        "import_violations": import_violations,
        "sandbox_violations": sandbox_violations,
        "errors": _limit_errors(errors),
    }


def _timeout_handler(signum: int, frame: Any) -> None:
    raise _Timeout()


class _time_limit:
    def __init__(self, seconds: float):
        self.seconds = seconds
        self.enabled = hasattr(signal, "setitimer") and hasattr(signal, "SIGALRM")
        self.old_handler: Any = None

    def __enter__(self) -> None:
        if self.enabled:
            self.old_handler = signal.getsignal(signal.SIGALRM)
            signal.signal(signal.SIGALRM, _timeout_handler)
            signal.setitimer(signal.ITIMER_REAL, self.seconds)

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self.enabled:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, self.old_handler)


def _normalize_case(case: Any) -> tuple[list, dict, Any, str | None]:
    if not isinstance(case, dict):
        return [], {}, None, "case not an object"
    expected = case.get("expected", case.get("output"))
    if "kwargs" in case:
        kwargs = case.get("kwargs")
        if not isinstance(kwargs, dict):
            return [], {}, expected, "kwargs not an object"
    else:
        kwargs = {}
    if "args" in case:
        args = case.get("args")
        if not isinstance(args, list):
            return [], kwargs, expected, "args not an array"
        return args, kwargs, expected, None
    if "input" in case:
        raw = case.get("input")
        return (raw if isinstance(raw, list) else [raw]), kwargs, expected, None
    if "kwargs" in case:
        return [], kwargs, expected, None
    return [], kwargs, expected, "missing input/args/kwargs"


def _run_cases(code: str, entry: str, cases: list[dict]) -> tuple[int, int, list[str]]:
    errors: list[str] = []
    ns: dict[str, Any] = {}
    try:
        with _time_limit(CASE_TIMEOUT_SEC):
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                exec(compile(code, "<candidate>", "exec"), ns)
    except _Timeout:
        return 0, len(cases), ["timeout during compile/exec"]
    except Exception as exc:
        return 0, len(cases), [f"compile/exec error: {type(exc).__name__}: {exc}"]
    fn = ns.get(entry)
    if not callable(fn):
        return 0, len(cases), [f"entry function {entry!r} not defined"]
    passed = 0
    for case in cases[:MAX_CASES]:
        try:
            case = copy.deepcopy(case)
        except Exception:
            pass
        args, kwargs, expected, err = _normalize_case(case)
        try:
            args = copy.deepcopy(args)
            kwargs = copy.deepcopy(kwargs)
            expected = copy.deepcopy(expected)
        except Exception:
            pass
        if err:
            errors.append(err)
            continue
        try:
            with _time_limit(CASE_TIMEOUT_SEC):
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    got = fn(*args, **kwargs)
        except _Timeout:
            errors.append(f"timeout on {args!r} {kwargs!r}")
            continue
        except Exception as exc:
            errors.append(f"runtime error on {args!r}: {type(exc).__name__}: {exc}")
            continue
        if got == expected:
            passed += 1
        else:
            errors.append(f"mismatch on {args!r}: got {got!r}, expected {expected!r}")
    return passed, min(len(cases), MAX_CASES) - passed, _limit_errors(errors)


def _norm_name(text: str) -> str:
    words = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(text)).replace("_", " ").replace("-", " ")
    return re.sub(r"\s+", " ", words.lower()).strip()


def _compact_name(text: str) -> str:
    return _norm_name(text).replace(" ", "")


def _match_score(template: Template, entry: str, desc: str) -> int:
    score = 0
    entry_norm = _norm_name(entry)
    entry_compact = _compact_name(entry)
    alias_norms = {_norm_name(a) for a in template.aliases}
    alias_compacts = {_compact_name(a) for a in template.aliases}
    template_norm = _norm_name(template.name)
    template_compact = _compact_name(template.name)
    if entry in template.aliases or entry_norm in alias_norms or entry_compact in alias_compacts:
        score += 100
    if entry_norm == template_norm or entry_compact == template_compact:
        score += 100
    for group in template.keyword_groups:
        if all(word in desc for word in group):
            score += 20 + len(group)
    return score


def _cases(payload: dict) -> list[dict]:
    for key in ("sample_inputs", "samples", "sample_tests", "public_tests", "tests", "examples", "test_cases"):
        value = payload.get(key)
        if isinstance(value, list):
            return value[:MAX_CASES]
    return []


def _template(name: str, aliases: tuple[str, ...], keywords: tuple[tuple[str, ...], ...], body: str, tests: tuple[dict, ...], confidence: float) -> Template:
    return Template(name, aliases, keywords, body, tests, confidence)


def _in(inp: list, exp: Any) -> dict:
    return {"input": inp, "expected": exp}


T = _template
TEMPLATES: tuple[Template, ...] = (
T("merge_intervals", ("merge_intervals", "mergeIntervals"), (("merge", "interval"), ("overlapping", "interval")), """
def __ENTRY__(intervals):
    if not intervals:
        return []
    intervals = sorted(intervals, key=lambda x: x[0])
    merged = []
    for start, end in intervals:
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return merged
""", (_in([[]], []), _in([[[1, 3], [2, 4]]], [[1, 4]]), _in([[[1, 2], [2, 3], [5, 7]]], [[1, 3], [5, 7]])), 0.95),
T("binary_search", ("binary_search", "binarySearch"), (("binary", "search"), ("sorted", "array", "target"), ("search", "sorted", "array"), ("log", "n")), """
def __ENTRY__(arr, target):
    lo, hi = 0, len(arr) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if arr[mid] == target:
            return mid
        if arr[mid] < target:
            lo = mid + 1
        else:
            hi = mid - 1
    return -1
""", (_in([[], 5], -1), _in([[5], 5], 0), _in([[1, 2, 3, 4, 5], 6], -1)), 0.94),
T("parse_csv_line", ("parse_csv_line", "parseCsvLine"), (("parse", "csv"), ("quoted", "field"), ("escaped", "quote")), """
def __ENTRY__(line):
    fields = []
    cur = []
    in_quotes = False
    i = 0
    while i < len(line):
        c = line[i]
        if in_quotes:
            if c == '"':
                if i + 1 < len(line) and line[i + 1] == '"':
                    cur.append('"')
                    i += 2
                    continue
                in_quotes = False
            else:
                cur.append(c)
        else:
            if c == '"':
                in_quotes = True
            elif c == ',':
                fields.append(''.join(cur))
                cur = []
            else:
                cur.append(c)
        i += 1
    fields.append(''.join(cur))
    return fields
""", (_in([""], [""]), _in(["a,\"b,c\",d"], ["a", "b,c", "d"]), _in(["\"hello \"\"world\"\"\""], ["hello \"world\""])), 0.93),
T("unique_paths", ("unique_paths", "uniquePaths"), (("unique", "paths"), ("grid", "right", "down")), """
def __ENTRY__(m, n):
    if m <= 0 or n <= 0:
        return 0
    a = m + n - 2
    b = min(m - 1, n - 1)
    result = 1
    for i in range(1, b + 1):
        result = result * (a - b + i) // i
    return result
""", (_in([1, 1], 1), _in([3, 7], 28), _in([0, 5], 0)), 0.95),
T("kth_smallest", ("kth_smallest", "kthSmallest"), (("kth", "smallest"), ("k-th", "smallest")), """
def __ENTRY__(nums, k):
    if not nums or k < 1 or k > len(nums):
        return None
    return sorted(nums)[k - 1]
""", (_in([[3, 1, 2], 2], 2), _in([[], 1], None), _in([[1, 1, 1], 2], 1)), 0.95),
T("remove_duplicates", ("remove_duplicates", "removeDuplicates"), (("remove", "duplicates"), ("deduplicate",), ("unique", "in-place"), ("in-place", "return", "number")), """
def __ENTRY__(nums):
    if not nums:
        return 0
    write = 1
    for read in range(1, len(nums)):
        if nums[read] != nums[write - 1]:
            nums[write] = nums[read]
            write += 1
    return write
""", (_in([[]], 0), _in([[1]], 1), _in([[1, 1, 2]], 2), _in([[0, 0, 1, 1, 2]], 3)), 0.92),
T("two_sum", ("two_sum", "twoSum"), (("two", "sum"), ("pair", "sum")), """
def __ENTRY__(nums, target):
    seen = {}
    for i, x in enumerate(nums):
        if target - x in seen:
            return [seen[target - x], i]
        seen[x] = i
    return []
""", (_in([[2, 7, 11], 9], [0, 1]), _in([[3, 2, 4], 6], [1, 2]), _in([[1, 2], 9], [])), 0.93),
T("contains_duplicate", ("contains_duplicate", "containsDuplicate"), (("contains", "duplicate"), ("any", "duplicate")), """
def __ENTRY__(nums):
    return len(set(nums)) != len(nums)
""", (_in([[1, 2, 3, 1]], True), _in([[1, 2, 3]], False), _in([[]], False)), 0.9),
T("majority_element", ("majority_element", "majorityElement"), (("majority", "element"),), """
def __ENTRY__(nums):
    if not nums:
        return None
    cand = None
    count = 0
    for x in nums:
        if count == 0:
            cand = x
        count += 1 if x == cand else -1
    return cand if nums.count(cand) > len(nums) // 2 else None
""", (_in([[3, 2, 3]], 3), _in([[2, 2, 1, 1, 1, 2, 2]], 2), _in([[1, 2, 3]], None)), 0.88),
T("move_zeroes", ("move_zeroes", "moveZeroes"), (("move", "zero"),), """
def __ENTRY__(nums):
    out = [x for x in nums if x != 0]
    out += [0] * (len(nums) - len(out))
    try:
        nums[:] = out
    except Exception:
        pass
    return out
""", (_in([[0, 1, 0, 3, 12]], [1, 3, 12, 0, 0]), _in([[0]], [0]), _in([[1]], [1])), 0.84),
T("product_except_self", ("product_except_self", "productExceptSelf"), (("product", "except", "self"),), """
def __ENTRY__(nums):
    out = [1] * len(nums)
    left = 1
    for i, x in enumerate(nums):
        out[i] = left
        left *= x
    right = 1
    for i in range(len(nums) - 1, -1, -1):
        out[i] *= right
        right *= nums[i]
    return out
""", (_in([[1, 2, 3, 4]], [24, 12, 8, 6]), _in([[0, 1, 2]], [2, 0, 0]), _in([[5]], [1])), 0.9),
T("max_subarray", ("max_subarray", "maxSubArray"), (("maximum", "subarray"), ("max", "subarray")), """
def __ENTRY__(nums):
    if not nums:
        return 0
    best = cur = nums[0]
    for x in nums[1:]:
        cur = max(x, cur + x)
        best = max(best, cur)
    return best
""", (_in([[-2,1,-3,4,-1,2,1,-5,4]], 6), _in([[1]], 1), _in([[-2, -1]], -1)), 0.92),
T("missing_number", ("missing_number", "missingNumber"), (("missing", "number"),), """
def __ENTRY__(nums):
    n = len(nums)
    return n * (n + 1) // 2 - sum(nums)
""", (_in([[3, 0, 1]], 2), _in([[0, 1]], 2), _in([[9,6,4,2,3,5,7,0,1]], 8)), 0.9),
T("intersection", ("intersection", "intersection_of_two_arrays", "intersectionOfTwoArrays"), (("intersection",), ("common", "elements")), """
def __ENTRY__(nums1, nums2):
    return sorted(set(nums1) & set(nums2))
""", (_in([[1, 2, 2, 1], [2, 2]], [2]), _in([[4,9,5], [9,4,9,8,4]], [4, 9]), _in([[], [1]], [])), 0.88),
T("is_anagram", ("is_anagram", "isAnagram"), (("anagram",),), """
def __ENTRY__(s, t):
    return sorted(s) == sorted(t)
""", (_in(["anagram", "nagaram"], True), _in(["rat", "car"], False), _in(["", ""], True)), 0.9),
T("valid_palindrome", ("valid_palindrome", "is_palindrome", "isPalindrome"), (("palindrome",),), """
def __ENTRY__(s):
    cleaned = ''.join(ch.lower() for ch in str(s) if ch.isalnum())
    return cleaned == cleaned[::-1]
""", (_in(["A man, a plan, a canal: Panama"], True), _in(["race a car"], False), _in([""], True)), 0.9),
T("valid_palindrome_ii", ("valid_palindrome_ii", "validPalindrome"), (("valid", "palindrome", "ii"), ("delete", "one"), ("remove", "one"), ("at", "most", "one")), """
def __ENTRY__(s):
    def is_pal(left, right):
        while left < right:
            if s[left] != s[right]:
                return False
            left += 1
            right -= 1
        return True
    left, right = 0, len(s) - 1
    while left < right:
        if s[left] != s[right]:
            return is_pal(left + 1, right) or is_pal(left, right - 1)
        left += 1
        right -= 1
    return True
""", (_in(["aba"], True), _in(["abca"], True), _in(["abc"], False)), 0.88),
T("longest_common_prefix", ("longest_common_prefix", "longestCommonPrefix"), (("longest", "common", "prefix"),), """
def __ENTRY__(strs):
    if not strs:
        return ""
    prefix = strs[0]
    for s in strs[1:]:
        while not s.startswith(prefix):
            prefix = prefix[:-1]
            if not prefix:
                return ""
    return prefix
""", (_in([["flower", "flow", "flight"]], "fl"), _in([["dog", "racecar"]], ""), _in([[]], "")), 0.88),
T("reverse_words", ("reverse_words", "reverseWords"), (("reverse", "words"),), """
def __ENTRY__(s):
    return ' '.join(str(s).split()[::-1])
""", (_in(["the sky is blue"], "blue is sky the"), _in(["  hello world  "], "world hello"), _in(["a"], "a")), 0.88),
T("first_unique_char", ("first_unique_char", "firstUniqChar", "first_unique_character"), (("first", "unique", "character"), ("first", "unique", "char")), """
def __ENTRY__(s):
    counts = {}
    for ch in s:
        counts[ch] = counts.get(ch, 0) + 1
    for i, ch in enumerate(s):
        if counts[ch] == 1:
            return i
    return -1
""", (_in(["leetcode"], 0), _in(["loveleetcode"], 2), _in(["aabb"], -1)), 0.88),
T("roman_to_int", ("roman_to_int", "romanToInt"), (("roman", "integer"), ("roman", "int")), """
def __ENTRY__(s):
    vals = {'I':1,'V':5,'X':10,'L':50,'C':100,'D':500,'M':1000}
    total = 0
    prev = 0
    for ch in reversed(s):
        v = vals[ch]
        total += -v if v < prev else v
        prev = max(prev, v)
    return total
""", (_in(["III"], 3), _in(["LVIII"], 58), _in(["MCMXCIV"], 1994)), 0.9),
T("int_to_roman", ("int_to_roman", "intToRoman"), (("integer", "roman"), ("int", "roman")), """
def __ENTRY__(num):
    vals = [(1000,'M'),(900,'CM'),(500,'D'),(400,'CD'),(100,'C'),(90,'XC'),(50,'L'),(40,'XL'),(10,'X'),(9,'IX'),(5,'V'),(4,'IV'),(1,'I')]
    out = []
    for v, sym in vals:
        while num >= v:
            out.append(sym)
            num -= v
    return ''.join(out)
""", (_in([3], "III"), _in([58], "LVIII"), _in([1994], "MCMXCIV")), 0.9),
T("valid_parentheses", ("valid_parentheses", "isValid", "validParentheses"), (("valid", "parentheses"), ("balanced", "brackets")), """
def __ENTRY__(s):
    pairs = {')':'(', ']':'[', '}':'{'}
    stack = []
    for ch in s:
        if ch in '([{':
            stack.append(ch)
        elif ch in pairs:
            if not stack or stack.pop() != pairs[ch]:
                return False
    return not stack
""", (_in(["()[]{}"], True), _in(["(]"], False), _in([""] , True)), 0.92),
T("length_of_longest_substring", ("length_of_longest_substring", "lengthOfLongestSubstring"), (("longest", "substring"), ("without", "repeating")), """
def __ENTRY__(s):
    seen = {}
    left = 0
    best = 0
    for right, ch in enumerate(s):
        if ch in seen and seen[ch] >= left:
            left = seen[ch] + 1
        seen[ch] = right
        best = max(best, right - left + 1)
    return best
""", (_in(["abcabcbb"], 3), _in(["bbbbb"], 1), _in([""], 0)), 0.9),
T("min_sub_array_len", ("min_sub_array_len", "minSubArrayLen"), (("minimum", "subarray", "sum"), ("min", "subarray", "len")), """
def __ENTRY__(target, nums):
    left = 0
    total = 0
    best = len(nums) + 1
    for right, x in enumerate(nums):
        total += x
        while total >= target:
            best = min(best, right - left + 1)
            total -= nums[left]
            left += 1
    return 0 if best == len(nums) + 1 else best
""", (_in([7, [2,3,1,2,4,3]], 2), _in([4, [1,4,4]], 1), _in([11, [1,1,1]], 0)), 0.88),
T("subarray_sum", ("subarray_sum", "subarraySum"), (("subarray", "sum"), ("prefix", "sum")), """
def __ENTRY__(nums, k):
    counts = {0: 1}
    total = 0
    ans = 0
    for x in nums:
        total += x
        ans += counts.get(total - k, 0)
        counts[total] = counts.get(total, 0) + 1
    return ans
""", (_in([[1,1,1], 2], 2), _in([[1,2,3], 3], 2), _in([[0,0], 0], 3)), 0.88),
T("max_profit", ("max_profit", "maxProfit"), (("max", "profit"), ("buy", "sell", "stock")), """
def __ENTRY__(prices):
    low = None
    best = 0
    for p in prices:
        low = p if low is None else min(low, p)
        best = max(best, p - low)
    return best
""", (_in([[7,1,5,3,6,4]], 5), _in([[7,6,4,3,1]], 0), _in([[]], 0)), 0.9),
T("search_insert", ("search_insert", "searchInsert"), (("search", "insert"), ("insert", "position"), ("search", "insert", "position"), ("sorted", "insert", "position")), """
def __ENTRY__(nums, target):
    lo, hi = 0, len(nums)
    while lo < hi:
        mid = (lo + hi) // 2
        if nums[mid] < target:
            lo = mid + 1
        else:
            hi = mid
    return lo
""", (_in([[1,3,5,6], 5], 2), _in([[1,3,5,6], 2], 1), _in([[1,3,5,6], 7], 4)), 0.9),
T("lower_bound", ("lower_bound", "lowerBound"), (("lower", "bound"), ("first", "not", "less")), """
def __ENTRY__(nums, target):
    lo, hi = 0, len(nums)
    while lo < hi:
        mid = (lo + hi) // 2
        if nums[mid] < target:
            lo = mid + 1
        else:
            hi = mid
    return lo
""", (_in([[1,2,4], 3], 2), _in([[], 1], 0), _in([[1,2,2], 2], 1)), 0.9),
T("search_rotated", ("search_rotated", "searchRotated", "search_rotated_array", "search"), (("search", "rotated"), ("rotated", "sorted"), ("rotated", "array"), ("rotated", "sorted", "array")), """
def __ENTRY__(nums, target):
    lo, hi = 0, len(nums) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if nums[mid] == target:
            return mid
        if nums[lo] <= nums[mid]:
            if nums[lo] <= target < nums[mid]:
                hi = mid - 1
            else:
                lo = mid + 1
        else:
            if nums[mid] < target <= nums[hi]:
                lo = mid + 1
            else:
                hi = mid - 1
    return -1
""", (_in([[4,5,6,7,0,1,2], 0], 4), _in([[4,5,6,7,0,1,2], 3], -1), _in([[1], 1], 0)), 0.88),
T("climb_stairs", ("climb_stairs", "climbStairs"), (("climb", "stairs"),), """
def __ENTRY__(n):
    if n <= 0:
        return 0
    a, b = 1, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b
""", (_in([1], 1), _in([2], 2), _in([5], 8)), 0.9),
T("coin_change", ("coin_change", "coinChange"), (("coin", "change"),), """
def __ENTRY__(coins, amount):
    dp = [amount + 1] * (amount + 1)
    dp[0] = 0
    for total in range(1, amount + 1):
        for coin in coins:
            if coin <= total:
                dp[total] = min(dp[total], dp[total - coin] + 1)
    return -1 if dp[amount] > amount else dp[amount]
""", (_in([[1,2,5], 11], 3), _in([[2], 3], -1), _in([[1], 0], 0)), 0.88),
T("house_robber", ("house_robber", "rob", "houseRobber"), (("house", "robber"), ("rob", "houses")), """
def __ENTRY__(nums):
    prev = cur = 0
    for x in nums:
        prev, cur = cur, max(cur, prev + x)
    return cur
""", (_in([[1,2,3,1]], 4), _in([[2,7,9,3,1]], 12), _in([[]], 0)), 0.9),
T("length_of_lis", ("length_of_lis", "lengthOfLIS"), (("longest", "increasing", "subsequence"),), """
def __ENTRY__(nums):
    tails = []
    for x in nums:
        lo, hi = 0, len(tails)
        while lo < hi:
            mid = (lo + hi) // 2
            if tails[mid] < x:
                lo = mid + 1
            else:
                hi = mid
        if lo == len(tails):
            tails.append(x)
        else:
            tails[lo] = x
    return len(tails)
""", (_in([[10,9,2,5,3,7,101,18]], 4), _in([[0,1,0,3,2,3]], 4), _in([[]], 0)), 0.9),
T("num_islands", ("num_islands", "numIslands"), (("number", "islands"), ("num", "islands")), """
def __ENTRY__(grid):
    if not grid:
        return 0
    def land(v):
        return v == '1' or v == 1
    seen = set()
    count = 0
    rows, cols = len(grid), len(grid[0])
    for r in range(rows):
        for c in range(cols):
            if land(grid[r][c]) and (r, c) not in seen:
                count += 1
                stack = [(r, c)]
                seen.add((r, c))
                while stack:
                    x, y = stack.pop()
                    for nx, ny in ((x+1,y),(x-1,y),(x,y+1),(x,y-1)):
                        if 0 <= nx < rows and 0 <= ny < cols and land(grid[nx][ny]) and (nx, ny) not in seen:
                            seen.add((nx, ny))
                            stack.append((nx, ny))
    return count
""", (_in([[['1','1','0'],['0','1','0'],['1','0','1']]], 3), _in([[[1,1,0],[0,1,0],[1,0,1]]], 3), _in([[['1']]], 1), _in([[]], 0)), 0.86),
T("flood_fill", ("flood_fill", "floodFill"), (("flood", "fill"),), """
def __ENTRY__(image, sr, sc, color):
    old = image[sr][sc]
    if old == color:
        return image
    rows, cols = len(image), len(image[0])
    stack = [(sr, sc)]
    image[sr][sc] = color
    while stack:
        r, c = stack.pop()
        for nr, nc in ((r+1,c),(r-1,c),(r,c+1),(r,c-1)):
            if 0 <= nr < rows and 0 <= nc < cols and image[nr][nc] == old:
                image[nr][nc] = color
                stack.append((nr, nc))
    return image
""", (_in([[[1,1,1],[1,1,0],[1,0,1]], 1, 1, 2], [[2,2,2],[2,2,0],[2,0,1]]), _in([[[0]], 0, 0, 0], [[0]]), _in([[[0,0]], 0, 1, 2], [[2,2]])), 0.86),
T("spiral_order", ("spiral_order", "spiralOrder"), (("spiral", "order"), ("spiral", "matrix")), """
def __ENTRY__(matrix):
    if not matrix:
        return []
    top, bottom = 0, len(matrix) - 1
    left, right = 0, len(matrix[0]) - 1
    out = []
    while top <= bottom and left <= right:
        for c in range(left, right + 1): out.append(matrix[top][c])
        top += 1
        for r in range(top, bottom + 1): out.append(matrix[r][right])
        right -= 1
        if top <= bottom:
            for c in range(right, left - 1, -1): out.append(matrix[bottom][c])
            bottom -= 1
        if left <= right:
            for r in range(bottom, top - 1, -1): out.append(matrix[r][left])
            left += 1
    return out
""", (_in([[[1,2,3],[4,5,6],[7,8,9]]], [1,2,3,6,9,8,7,4,5]), _in([[]], []), _in([[[1,2,3]]], [1,2,3])), 0.88),
T("transpose", ("transpose", "transpose_matrix", "transposeMatrix"), (("transpose", "matrix"),), """
def __ENTRY__(matrix):
    if not matrix:
        return []
    return [[matrix[r][c] for r in range(len(matrix))] for c in range(len(matrix[0]))]
""", (_in([[[1,2,3],[4,5,6]]], [[1,4],[2,5],[3,6]]), _in([[[1]]], [[1]]), _in([[]], [])), 0.88),
T("insert_interval", ("insert_interval", "insert", "insertInterval"), (("insert", "interval"),), """
def __ENTRY__(intervals, newInterval):
    out = []
    i = 0
    while i < len(intervals) and intervals[i][1] < newInterval[0]:
        out.append(intervals[i]); i += 1
    start, end = newInterval
    while i < len(intervals) and intervals[i][0] <= end:
        start = min(start, intervals[i][0])
        end = max(end, intervals[i][1])
        i += 1
    out.append([start, end])
    out.extend(intervals[i:])
    return out
""", (_in([[[1,3],[6,9]], [2,5]], [[1,5],[6,9]]), _in([[], [1,2]], [[1,2]]), _in([[[1,5]], [2,3]], [[1,5]])), 0.9),
T("erase_overlap_intervals", ("erase_overlap_intervals", "eraseOverlapIntervals"), (("erase", "overlap", "interval"), ("remove", "overlapping", "interval")), """
def __ENTRY__(intervals):
    if not intervals:
        return 0
    intervals = sorted(intervals, key=lambda x: x[1])
    count = 0
    end = intervals[0][1]
    for s, e in intervals[1:]:
        if s < end:
            count += 1
        else:
            end = e
    return count
""", (_in([[[1,2],[2,3],[3,4],[1,3]]], 1), _in([[[1,2],[1,2],[1,2]]], 2), _in([[]], 0)), 0.88),
)

FALLBACK_TEMPLATE = T("fallback", ("solution",), (), """
def __ENTRY__(*args):
    return None
""", (), 0.05)


def _rank_templates(entry: str, desc: str) -> list[tuple[int, int, Template]]:
    ranked = [(_match_score(t, entry, desc), i, t) for i, t in enumerate(TEMPLATES)]
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return ranked


def _select_template(entry: str, desc: str, sample_cases: list[dict] | None = None) -> Template:
    ranked = _rank_templates(entry, desc)
    if not ranked:
        return FALLBACK_TEMPLATE
    samples = sample_cases or []
    if not samples and ranked[0][0] <= 0:
        return FALLBACK_TEMPLATE
    if not samples:
        return ranked[0][2]
    best_key = None
    best_template = ranked[0][2]
    trial_count = 5 if ranked[0][0] > 0 else 12
    for score, neg_idx, template in ranked[:trial_count]:
        code = _render(entry, template.body)
        passed, failed, _ = _run_cases(code, entry, samples)
        key = (passed, -failed, score, -neg_idx)
        if best_key is None or key > best_key:
            best_key = key
            best_template = template
    if best_key is None or best_key[0] == 0:
        return FALLBACK_TEMPLATE
    return best_template


def _constraints(payload: dict) -> dict:
    constraints = payload.get("constraints", {})
    return constraints if isinstance(constraints, dict) else {}


def _confidence(base: float, passed: int, failed: int, sample_count: int, violations: bool, fallback: bool) -> float:
    if violations:
        return 0.0
    if fallback:
        return min(base, 0.1)
    if sample_count <= 0:
        return _clamp(base)
    total = passed + failed
    ratio = passed / total if total else 0.0
    if failed == 0:
        return _clamp(base)
    if passed == 0:
        return min(base, 0.1)
    return min(base, ratio, 0.35)


def _result_from_code(source: str, code: str, entry: str, cases: list[dict], constraints: dict, rationale: str, base_conf: float, sample_count: int, extra_errors: list[str] | None = None) -> CandidateResult:
    loc = _sloc(code)
    forbidden = constraints.get("imports_forbidden", [])
    forbidden = forbidden if isinstance(forbidden, list) else []
    import_violations, sandbox_violations = _static_checks(code, forbidden)
    import_violations = sorted(set(import_violations) | set(_allowed_import_violations(code, constraints)))
    passed, failed, errors = _run_cases(code, entry, cases)
    errors = (extra_errors or []) + errors
    try:
        limit = int(constraints.get("max_loc", 500))
    except (TypeError, ValueError):
        limit = 500
    loc_violation = loc > limit
    entry_missing = not _contains_entry(code, entry)
    if import_violations or sandbox_violations or loc_violation or entry_missing:
        failed += 1
    violations = bool(import_violations or sandbox_violations or loc_violation or entry_missing)
    return CandidateResult(
        source=source,
        code=code,
        loc=loc,
        passed=passed,
        failed=failed,
        errors=_limit_errors(errors),
        import_violations=import_violations,
        sandbox_violations=sandbox_violations,
        loc_violation=loc_violation,
        entry_missing=entry_missing,
        confidence=_confidence(base_conf, passed, failed, sample_count, violations, source == "fallback"),
        rationale=rationale,
    )


def _template_result(payload: dict, entry: str, desc: str, sample_cases: list[dict], constraints: dict) -> CandidateResult:
    template = _select_template(entry, desc, sample_cases)
    code = _render(entry, template.body)
    cases = sample_cases or list(template.tests)
    extra_errors: list[str] = []
    source = "template"
    if template is FALLBACK_TEMPLATE:
        source = "fallback"
        extra_errors.append("no deterministic template matched")
    result = _result_from_code(source, code, entry, cases, constraints, f"deterministic template: {template.name}", template.confidence, len(sample_cases), extra_errors)
    if template is FALLBACK_TEMPLATE and result.failed < 1:
        result = CandidateResult(**{**result.__dict__, "failed": 1})
    return result


def _llm_candidate_result(candidate_code: str, entry: str, sample_cases: list[dict], constraints: dict) -> CandidateResult | None:
    validation = _validate_candidate(candidate_code, entry, constraints)
    if not validation["ok"]:
        return CandidateResult(
            source="llm_invalid",
            code=validation["code"] or _fallback_code(),
            loc=validation["loc"] or 2,
            passed=0,
            failed=1,
            errors=_limit_errors(["llm candidate rejected"] + validation["errors"]),
            import_violations=validation["import_violations"],
            sandbox_violations=validation["sandbox_violations"],
            loc_violation=False,
            entry_missing=True,
            confidence=0.0,
            rationale="llm_candidate rejected by validation",
        )
    hardcode_warnings = _sample_hardcode_warnings(validation["code"], sample_cases)
    if hardcode_warnings:
        return CandidateResult(
            source="llm_invalid",
            code=validation["code"],
            loc=validation["loc"],
            passed=0,
            failed=1,
            errors=_limit_errors(["llm candidate rejected"] + hardcode_warnings),
            import_violations=[],
            sandbox_violations=[],
            loc_violation=False,
            entry_missing=False,
            confidence=0.0,
            rationale="llm_candidate rejected by validation",
        )
    cases = sample_cases or []
    if cases:
        passed, failed, errors = _run_cases(validation["code"], entry, cases)
        if failed == 0:
            conf = 0.78
            rationale = "llm_candidate validated by static checks and samples"
        elif passed == 0:
            conf = 0.1
            rationale = "llm_candidate failed public samples"
        else:
            conf = min(0.35, passed / (passed + failed))
            rationale = "llm_candidate partially passed samples"
    else:
        passed, failed, errors = _run_cases(validation["code"], entry, [])
        if errors:
            return CandidateResult(
                source="llm_invalid",
                code=validation["code"],
                loc=validation["loc"],
                passed=0,
                failed=1,
                errors=_limit_errors(["llm candidate rejected"] + errors),
                import_violations=[],
                sandbox_violations=[],
                loc_violation=False,
                entry_missing=False,
                confidence=0.0,
                rationale="llm_candidate rejected by validation",
            )
        conf = 0.5
        rationale = "llm_candidate valid; no public samples"
    return CandidateResult(
        source="llm",
        code=validation["code"],
        loc=validation["loc"],
        passed=passed,
        failed=failed,
        errors=_limit_errors(errors),
        import_violations=[],
        sandbox_violations=[],
        loc_violation=False,
        entry_missing=False,
        confidence=conf,
        rationale=rationale,
    )


def _violation_count(result: CandidateResult) -> int:
    return len(result.import_violations) + len(result.sandbox_violations) + int(result.loc_violation) + int(result.entry_missing)


def _choose_result(template: CandidateResult, llm: CandidateResult | None, entry: str, sample_count: int) -> CandidateResult:
    if llm is None or llm.source != "llm":
        return template
    if _violation_count(llm) > 0:
        return template
    if sample_count:
        if llm.failed == 0:
            return llm
        if template.failed == 0 and llm.failed > 0:
            return template
        template_key = (template.passed, -template.failed, -_violation_count(template))
        llm_key = (llm.passed, -llm.failed, -_violation_count(llm))
        return llm if llm_key >= template_key else template
    return llm


def _contract_from_result(payload: dict, result: CandidateResult) -> dict:
    return {
        "task_id": str(payload.get("task_id", "")),
        "code": result.code,
        "loc": result.loc,
        "self_test_results": {
            "passed": result.passed,
            "failed": result.failed,
            "errors": _limit_errors(result.errors),
            "sloc": result.loc,
            "loc_violation": result.loc_violation,
            "import_violations": result.import_violations,
            "sandbox_violations": result.sandbox_violations,
        },
        "rationale": result.rationale,
        "confidence": _clamp(result.confidence),
    }


def _build_contract(payload: dict, candidate_code: str = "") -> dict:
    constraints = _constraints(payload)
    entry = _safe_entry(constraints.get("entry_function") or payload.get("entry_function"))
    desc = str(payload.get("task_description") or payload.get("description") or "").lower()
    sample_cases = _cases(payload)
    template = _template_result(payload, entry, desc, sample_cases, constraints)
    llm = _llm_candidate_result(candidate_code, entry, sample_cases, constraints) if candidate_code.strip() else None
    chosen = _choose_result(template, llm, entry, len(sample_cases))
    if chosen.source != "llm" and llm is not None and llm.source == "llm_invalid":
        chosen = CandidateResult(**{
            **chosen.__dict__,
            "errors": _limit_errors(chosen.errors + llm.errors),
            "import_violations": sorted(set(chosen.import_violations) | set(llm.import_violations)),
            "sandbox_violations": sorted(set(chosen.sandbox_violations) | set(llm.sandbox_violations)),
        })
    return _contract_from_result(payload, chosen)


def main(argv: list[str]) -> int:
    payload: dict | None = None
    cli_args = _parse_cli_args(argv)
    if cli_args is not None:
        if cli_args.task_id is not None and cli_args.code is not None:
            return _emit(_contract_from_cli_args(cli_args))
        if cli_args.payload and cli_args.candidate_code:
            try:
                payload, candidate_code = _payload_candidate_from_cli(cli_args)
            except Exception as exc:
                return _emit(_invalid_input_contract(str(exc)))
            try:
                return _emit(_build_contract(payload, candidate_code))
            except Exception as exc:
                return _emit(_internal_error_contract(payload, str(exc)))
    try:
        payload, candidate_code = _read_input(argv)
    except Exception as exc:
        return _emit(_invalid_input_contract(str(exc)))
    try:
        return _emit(_build_contract(payload, candidate_code))
    except Exception as exc:
        return _emit(_internal_error_contract(payload, str(exc)))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
