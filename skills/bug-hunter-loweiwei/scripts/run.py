#!/usr/bin/env python3
"""Pairwise Bug Hunter file-based validator.

In the official skill flow, Hermes privately prepares a candidate bug report.
This script validates and normalizes that report, then writes the final contract
JSON to AIASE_RESULT_PATH. A legacy deterministic audit path is retained only for
direct local fallback when no candidate-report delimiter is provided.
"""

from __future__ import annotations

import ast
import builtins
import contextlib
import copy
import inspect
import io
import json
import math
import os
import re
import signal
import sys
import tempfile
import traceback
from dataclasses import dataclass
from typing import Any, Callable


ALLOWED_TYPES = {
    "off_by_one", "null_deref", "type_error", "logic_error",
    "edge_case", "api_misuse", "inefficient", "unhandled_input",
}
ALLOWED_SEVERITIES = {"critical", "high", "medium", "low"}
TIME_LIMIT = 0.08
REPORT_DELIMITER = "__AIASE_BUG_REPORT_V1__"
_PLACEHOLDER_NAMES = {
    "arr", "array", "nums", "num", "numbers", "target",
    "line", "s", "str", "string", "text", "x", "y",
    "n", "m", "k", "value", "values", "input", "interval", "intervals",
}


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


@dataclass
class Probe:
    args: tuple[Any, ...]
    kwargs: dict[str, Any]
    expected: Any = None
    source: str = "generic"
    label: str = ""


@dataclass
class TaskSpec:
    name: str
    detectors: tuple[str, ...]
    oracle: Callable[[tuple[Any, ...], str], Any]
    probes: Callable[[str], list[Probe]]
    compare: Callable[[Any, Any, Probe], bool]
    bug_type_hint: str = "logic_error"
    line_hint_patterns: tuple[str, ...] = ()


@dataclass
class Finding:
    line: int
    line_end: int
    severity: str
    type: str
    description: str
    suggested_fix: str
    confidence: float
    evidence_rank: int
    probe: Probe | None = None
    status: str = "mismatch"


def _emit(obj: dict) -> int:
    write_result(obj)
    return 0


def _confidence(value: float) -> float:
    return max(0.0, min(1.0, round(float(value), 2)))


def _bug(line: int, severity: str, bug_type: str, description: str, fix: str, line_end: int | None = None) -> dict:
    if severity not in ALLOWED_SEVERITIES:
        severity = "medium"
    if bug_type not in ALLOWED_TYPES:
        bug_type = "logic_error"
    return {
        "line_start": max(1, int(line or 1)),
        "line_end": max(1, int(line if line_end is None else line_end)),
        "severity": severity,
        "type": bug_type,
        "description": description,
        "suggested_fix": fix,
    }


def _contract(task_id: str, bugs: dict | list[dict] | None, confidence: float) -> dict:
    if bugs is None:
        bug_list: list[dict] = []
    elif isinstance(bugs, list):
        bug_list = bugs[:2]
    else:
        bug_list = [bugs]
    return {
        "task_id": str(task_id),
        "verdict": "buggy" if bug_list else "clean",
        "bugs": bug_list,
        "confidence": _confidence(confidence),
    }


def _read_payload(argv: list[str]) -> dict:
    raw = argv[1] if len(argv) > 1 else sys.stdin.read()
    try:
        obj = json.loads(raw or "{}")
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    return {"task_id": "", "task_description": "", "code": ""}


def _read_raw(argv: list[str]) -> str:
    if len(argv) > 1 and argv[1] != "-":
        return argv[1]
    return sys.stdin.read()


def _extract_json_object(text: str) -> dict | None:
    raw = str(text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)\s*```", raw, re.I | re.S)
    if fence:
        raw = fence.group(1).strip()
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


def _parse_input(raw: str) -> tuple[dict, dict | None]:
    text = str(raw or "")
    if REPORT_DELIMITER in text:
        left, _, right = text.partition(REPORT_DELIMITER)
        payload = _extract_json_object(left) or {"task_id": "", "task_description": "", "code": ""}
        report = _extract_json_object(right)
        return payload, report
    payload = _extract_json_object(text) or {"task_id": "", "task_description": "", "code": ""}
    return payload, None


def _maybe_json_obj(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{") and text.endswith("}"):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                return value
    return value


def _nested_dicts(payload: dict) -> list[dict]:
    out = [payload]
    for key in ("code_author_output", "author_output", "candidate", "submission", "result"):
        value = _maybe_json_obj(payload.get(key))
        if isinstance(value, dict):
            out.append(value)
    return out


def _payload_value(payload: dict, keys: tuple[str, ...]) -> Any:
    for obj in _nested_dicts(payload):
        for key in keys:
            if obj.get(key) not in (None, ""):
                return obj.get(key)
    return None


def _extract_code(payload: dict) -> str:
    code = _payload_value(payload, ("code",))
    return str(code or "").replace("\r\n", "\n").replace("\r", "\n")


def _extract_description(payload: dict) -> str:
    return str(_payload_value(payload, ("task_description", "description", "prompt")) or "")


def _extract_constraints_text(payload: dict) -> str:
    value = _payload_value(payload, ("constraints",))
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value or "")


def _norm_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")


def _infer_entry(payload: dict, desc: str, tree: ast.AST | None) -> str:
    for obj in _nested_dicts(payload):
        for key in ("entry_point", "entry_function", "function_name"):
            if obj.get(key):
                return str(obj[key])
        constraints = obj.get("constraints")
        if isinstance(constraints, dict):
            for key in ("entry_point", "entry_function"):
                if constraints.get(key):
                    return str(constraints[key])
    for pat in (
        r"(?:function|method|implement|write)\s+([A-Za-z_]\w*)\s*\(",
        r"`([A-Za-z_]\w*)\s*\(`",
        r"\b([A-Za-z_]\w*)\s*\([^\n)]*\)\s*(?:->|should return|returns)",
    ):
        m = re.search(pat, desc, re.I)
        if m:
            return m.group(1)
    if tree is not None:
        funcs = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
        if funcs:
            return funcs[0]
    return ""


def _safe_builtins() -> dict[str, Any]:
    names = {
        "abs", "all", "any", "bool", "dict", "enumerate", "filter", "float",
        "int", "isinstance", "len", "list", "map", "max", "min", "ord", "pow",
        "range", "reversed", "round", "set", "sorted", "str", "sum", "tuple", "zip",
    }
    return {name: getattr(builtins, name) for name in names} | {
        "Exception": Exception,
        "ValueError": ValueError,
        "object": object,
        "List": list,
        "Dict": dict,
        "Tuple": tuple,
        "Set": set,
        "Optional": object,
        "Any": object,
    }


def _safe_import(name: str, globals_: Any = None, locals_: Any = None, fromlist: Any = (), level: int = 0) -> Any:
    allowed = {"math", "collections", "itertools", "functools", "bisect", "heapq", "re", "string", "typing"}
    root = name.split(".", 1)[0]
    if root not in allowed:
        raise ImportError(f"import not allowed: {name}")
    return __import__(name, globals_, locals_, fromlist, level)


def _exec_candidate(code: str) -> tuple[dict[str, Any] | None, BaseException | None, int]:
    ns: dict[str, Any] = {"__name__": "__candidate__", "__builtins__": _safe_builtins() | {"__import__": _safe_import}}
    try:
        with _time_limit(TIME_LIMIT), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            exec(compile(code, "<candidate>", "exec"), ns, ns)
        return ns, None, 1
    except BaseException as exc:
        return None, exc, _trace_line(exc)


@contextlib.contextmanager
def _time_limit(seconds: float):
    if not hasattr(signal, "SIGALRM"):
        yield
        return
    def handler(signum: int, frame: Any) -> None:
        raise _Timeout("probe timed out")
    old = signal.signal(signal.SIGALRM, handler)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


def _trace_line(exc: BaseException) -> int:
    tb = exc.__traceback__
    best = 1
    while tb:
        if tb.tb_frame.f_code.co_filename == "<candidate>":
            best = tb.tb_lineno
        tb = tb.tb_next
    return best


class LineLocator(ast.NodeVisitor):
    def __init__(self, entry: str):
        self.entry = entry
        self.nodes: list[ast.AST] = []
        self._in_entry = False

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        old = self._in_entry
        self._in_entry = node.name == self.entry or (not self.entry and not old)
        if self._in_entry:
            self.nodes.append(node)
            for child in node.body:
                self.visit(child)
        self._in_entry = old

    def generic_visit(self, node: ast.AST) -> Any:
        if self._in_entry and isinstance(node, (ast.Return, ast.If, ast.Compare, ast.For, ast.While, ast.Subscript, ast.BinOp, ast.Assign, ast.AugAssign)):
            self.nodes.append(node)
        super().generic_visit(node)

    def first(self, kinds: tuple[type, ...] = ()) -> ast.AST | None:
        for node in self.nodes:
            if not kinds or isinstance(node, kinds):
                return node
        return None

    def containing_name(self, names: tuple[str, ...]) -> ast.AST | None:
        for node in self.nodes:
            if isinstance(node, ast.FunctionDef):
                continue
            text = ""
            try:
                text = ast.unparse(node).lower()
            except Exception:
                pass
            if any(name in text for name in names):
                return node
        return None


def _node_span(node: ast.AST | None) -> tuple[int, int]:
    if node is None:
        return 1, 1
    start = int(getattr(node, "lineno", 1) or 1)
    end = int(getattr(node, "end_lineno", start) or start)
    return start, max(start, end)


def _run(fn: Callable[..., Any], probe: Probe) -> tuple[str, Any, BaseException | None, int]:
    args = copy.deepcopy(probe.args)
    kwargs = copy.deepcopy(probe.kwargs)
    try:
        with _time_limit(TIME_LIMIT), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            value = fn(*args, **kwargs)
        return "ok", {"return": value, "args": args, "kwargs": kwargs}, None, 1
    except _Timeout as exc:
        return "timeout", None, exc, _trace_line(exc)
    except BaseException as exc:
        return "crash", None, exc, _trace_line(exc)


def _normalize(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_normalize(x) for x in value]
    if isinstance(value, list):
        return [_normalize(x) for x in value]
    if isinstance(value, dict):
        return {k: _normalize(v) for k, v in value.items()}
    return value


def _default_compare(actual: Any, expected: Any, probe: Probe) -> bool:
    return _normalize(actual.get("return") if isinstance(actual, dict) else actual) == _normalize(expected)


def _interval_compare(actual: Any, expected: Any, probe: Probe) -> bool:
    return _normalize(actual.get("return")) == _normalize(expected)


def _two_sum_compare(actual: Any, expected: Any, probe: Probe) -> bool:
    ret = actual.get("return")
    if not isinstance(ret, (list, tuple)) or len(ret) != 2 or not all(isinstance(i, int) for i in ret):
        return False
    nums, target = probe.args[0], probe.args[1]
    i, j = ret
    return i != j and 0 <= i < len(nums) and 0 <= j < len(nums) and nums[i] + nums[j] == target


def _inplace_or_return_compare(actual: Any, expected: Any, probe: Probe) -> bool:
    ret = actual.get("return")
    args = actual.get("args", [])
    if isinstance(expected, dict) and expected.get("mode") == "inplace_len":
        return ret == expected["length"] and args and _normalize(args[0][:ret]) == _normalize(expected["list"])
    if isinstance(expected, dict) and expected.get("mode") == "inplace_list":
        return args and _normalize(args[0]) == _normalize(expected["list"])
    return _normalize(ret) == _normalize(expected)


def _contains_any(text: str, words: tuple[str, ...]) -> bool:
    norm = _norm_text(text)
    return any(w in norm for w in words)


def _is_inplace(desc: str) -> bool:
    d = desc.lower()
    return any(x in d for x in ("in-place", "in place", "modify nums", "modify the array", "return length"))


def _case_insensitive(desc: str) -> bool:
    return "case-insensitive" in desc.lower() or "case insensitive" in desc.lower()


def _ignore_non_alnum(desc: str) -> bool:
    d = desc.lower()
    return "non-alphanumeric" in d or "non alphanumeric" in d or "ignore punctuation" in d


def _p(*args: Any, source: str = "known", label: str = "") -> Probe:
    return Probe(tuple(args), {}, source=source, label=label)


def _summary_ranges(args: tuple[Any, ...], desc: str) -> list[str]:
    nums = args[0]
    out = []
    i = 0
    while i < len(nums):
        start = nums[i]
        while i + 1 < len(nums) and nums[i + 1] == nums[i] + 1:
            i += 1
        end = nums[i]
        out.append(str(start) if start == end else f"{start}->{end}")
        i += 1
    return out


def _merge_intervals(args: tuple[Any, ...], desc: str) -> list[list[int]]:
    intervals = sorted([list(x) for x in args[0]], key=lambda x: x[0])
    merged: list[list[int]] = []
    for start, end in intervals:
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return merged


def _two_sum(args: tuple[Any, ...], desc: str) -> list[int] | None:
    nums, target = args[0], args[1]
    seen: dict[int, int] = {}
    for i, n in enumerate(nums):
        if target - n in seen:
            return [seen[target - n], i]
        seen[n] = i
    return None


def _remove_duplicates(args: tuple[Any, ...], desc: str) -> Any:
    out = []
    for x in args[0]:
        if x not in out:
            out.append(x)
    return {"mode": "inplace_len", "length": len(out), "list": out} if _is_inplace(desc) else out


def _move_zeroes(args: tuple[Any, ...], desc: str) -> list[int]:
    nums = list(args[0])
    nz = [x for x in nums if x != 0]
    return nz + [0] * (len(nums) - len(nz))


def _rotate_array(args: tuple[Any, ...], desc: str) -> Any:
    nums, k = list(args[0]), args[1]
    if nums:
        k %= len(nums)
        nums = nums[-k:] + nums[:-k] if k else nums
    return {"mode": "inplace_list", "list": nums} if _is_inplace(desc) else nums


def _plus_one(args: tuple[Any, ...], desc: str) -> list[int]:
    digits = list(args[0])
    carry = 1
    for i in range(len(digits) - 1, -1, -1):
        val = digits[i] + carry
        digits[i] = val % 10
        carry = val // 10
    return [1] + digits if carry else digits


def _majority(args: tuple[Any, ...], desc: str) -> Any:
    nums = args[0]
    for x in nums:
        if nums.count(x) > len(nums) // 2:
            return x
    return None


def _max_subarray(args: tuple[Any, ...], desc: str) -> int:
    nums = args[0]
    best = cur = nums[0]
    for x in nums[1:]:
        cur = max(x, cur + x)
        best = max(best, cur)
    return best


def _max_profit(args: tuple[Any, ...], desc: str) -> int:
    low = 10**18
    best = 0
    for p in args[0]:
        low = min(low, p)
        best = max(best, p - low)
    return best


def _search_insert(args: tuple[Any, ...], desc: str) -> int:
    nums, target = args[0], args[1]
    lo, hi = 0, len(nums)
    while lo < hi:
        mid = (lo + hi) // 2
        if nums[mid] < target:
            lo = mid + 1
        else:
            hi = mid
    return lo


def _kth_smallest(args: tuple[Any, ...], desc: str) -> Any:
    nums, k = args[0], args[1]
    if not nums or k < 1 or k > len(nums):
        return None
    return sorted(nums)[k - 1]


def _valid_parentheses(args: tuple[Any, ...], desc: str) -> bool:
    stack = []
    pairs = {")": "(", "]": "[", "}": "{"}
    for ch in args[0]:
        if ch in pairs.values():
            stack.append(ch)
        elif ch in pairs:
            if not stack or stack.pop() != pairs[ch]:
                return False
    return not stack


def _is_palindrome(args: tuple[Any, ...], desc: str) -> bool:
    s = str(args[0])
    if _ignore_non_alnum(desc):
        s = "".join(c for c in s if c.isalnum())
    if _case_insensitive(desc):
        s = s.lower()
    return s == s[::-1]


def _valid_anagram(args: tuple[Any, ...], desc: str) -> bool:
    a, b = str(args[0]), str(args[1])
    if _case_insensitive(desc):
        a, b = a.lower(), b.lower()
    return sorted(a) == sorted(b)


def _roman_to_int(args: tuple[Any, ...], desc: str) -> int:
    vals = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    prev = 0
    for ch in reversed(args[0]):
        val = vals[ch]
        total += -val if val < prev else val
        prev = max(prev, val)
    return total


def _parse_csv_line(args: tuple[Any, ...], desc: str) -> list[str]:
    s = args[0]
    out, cur, i, quoted = [], [], 0, False
    while i < len(s):
        ch = s[i]
        if ch == '"':
            if quoted and i + 1 < len(s) and s[i + 1] == '"':
                cur.append('"'); i += 2; continue
            quoted = not quoted
        elif ch == "," and not quoted:
            out.append("".join(cur)); cur = []
        else:
            cur.append(ch)
        i += 1
    out.append("".join(cur))
    return out


def _binary_search(args: tuple[Any, ...], desc: str) -> int:
    arr, target = args[0], args[1]
    try:
        return arr.index(target)
    except ValueError:
        return -1


def _simple_oracles(name: str) -> Callable[[tuple[Any, ...], str], Any]:
    def oracle(args: tuple[Any, ...], desc: str) -> Any:
        if name == "contains_duplicate": return len(set(args[0])) != len(args[0])
        if name == "missing_number": return sum(range(len(args[0]) + 1)) - sum(args[0])
        if name == "single_number":
            x = 0
            for n in args[0]: x ^= n
            return x
        if name == "longest_common_prefix":
            strs = args[0]
            if not strs: return ""
            pref = strs[0]
            for s in strs[1:]:
                while not s.startswith(pref): pref = pref[:-1]
            return pref
        if name == "reverse_string": return args[0][::-1]
        if name == "reverse_words": return " ".join(reversed(str(args[0]).split()))
        if name == "first_unique_char":
            s = args[0]
            for i, ch in enumerate(s):
                if s.count(ch) == 1: return i
            return -1
        if name == "length_of_last_word": return len(str(args[0]).rstrip().split(" ")[-1]) if str(args[0]).strip() else 0
        if name == "count_vowels": return sum(1 for c in str(args[0]).lower() if c in "aeiou")
        if name == "fizz_buzz": return ["FizzBuzz" if i % 15 == 0 else "Fizz" if i % 3 == 0 else "Buzz" if i % 5 == 0 else str(i) for i in range(1, args[0] + 1)]
        if name == "unique_paths": return 0 if args[0] <= 0 or args[1] <= 0 else math.comb(args[0] + args[1] - 2, args[0] - 1)
        if name in {"climb_stairs", "fibonacci", "fib"}:
            n = args[0]
            if n < 0: return None
            a, b = (1, 1) if name == "climb_stairs" else (0, 1)
            for _ in range(n): a, b = b, a + b
            return a
        if name == "factorial": return None if args[0] < 0 else math.factorial(args[0])
        if name == "gcd": return math.gcd(args[0], args[1])
        if name == "is_prime":
            n = args[0]
            if n < 2: return False
            return all(n % d for d in range(2, int(n ** 0.5) + 1))
        if name in {"power", "pow"}: return args[0] ** args[1]
        if name in {"sqrt", "integer_sqrt"}: return math.isqrt(args[0]) if args[0] >= 0 else None
        raise AssertionError(name)
    return oracle


def _boundary_allowed(desc: str) -> bool:
    text = str(desc or "").lower()
    return any(phrase in text for phrase in (
        "empty", "blank", "zero", "negative", "invalid", "null", "none",
        "out of range", "out-of-range", "duplicate", "boundary", "edge case",
    ))


def _is_boundary_probe(name: str, args: tuple[Any, ...]) -> bool:
    if name == "unique_paths":
        return bool(len(args) >= 2 and (args[0] <= 0 or args[1] <= 0))
    if name == "kth_smallest":
        nums = args[0] if args else []
        k = args[1] if len(args) > 1 else 1
        return not nums or not isinstance(k, int) or k < 1 or k > len(nums)
    if name == "search_insert":
        return bool(args and args[0] == [])
    if name == "factorial":
        return bool(args and isinstance(args[0], int) and args[0] < 0)
    if name in {"sqrt", "integer_sqrt"}:
        return bool(args and isinstance(args[0], int) and args[0] < 0)
    for arg in args:
        if arg in ([], "", None):
            return True
        if isinstance(arg, int) and arg < 0:
            return True
    return False


def _probes_for(name: str) -> Callable[[str], list[Probe]]:
    def f(desc: str) -> list[Probe]:
        base: dict[str, list[tuple[Any, ...]]] = {
            "summary_ranges": [([],), ([0],), ([0, 1, 2, 4],), ([0, 2, 3, 4, 6, 8, 9],), ([-1, 0, 1],)],
            "merge_intervals": [([],), ([[1, 3]],), ([[1, 3], [2, 6]],), ([[1, 4], [4, 5]],), ([[5, 6], [1, 3]],)],
            "two_sum": [([2, 7, 11, 15], 9), ([3, 2, 4], 6), ([3, 3], 6), ([1, 2, 3], 4)],
            "remove_duplicates": [([],), ([1],), ([1, 1, 2],), ([0, 0, 1, 1, 2],)],
            "move_zeroes": [([],), ([0],), ([0, 1, 0, 3, 12],), ([1, 2],)],
            "rotate_array": [([], 3), ([1], 2), ([1, 2, 3, 4], 1), ([1, 2, 3, 4, 5, 6, 7], 3)],
            "plus_one": [([1, 2, 3],), ([9],), ([9, 9],), ([0],)],
            "contains_duplicate": [([],), ([1],), ([1, 2, 3],), ([1, 2, 1],)],
            "majority_element": [([3, 2, 3],), ([2, 2, 1, 1, 1, 2, 2],), ([1],)],
            "missing_number": [([3, 0, 1],), ([0, 1],), ([9,6,4,2,3,5,7,0,1],)],
            "single_number": [([2, 2, 1],), ([4, 1, 2, 1, 2],), ([1],)],
            "max_subarray": [([-2,1,-3,4,-1,2,1,-5,4],), ([-1],), ([-2, -3],), ([5, -1, 2],)],
            "max_profit": [([7,1,5,3,6,4],), ([7,6,4,3,1],), ([1,2],)],
            "search_insert": [([1,3,5,6], 5), ([1,3,5,6], 2), ([1,3,5,6], 7), ([], 1)],
            "binary_search": [([1,2,3], 3), ([1,2,3], 1), ([1,2,3], 4), ([1], 1)],
            "kth_smallest": [([3,1,2], 1), ([3,1,2], 2), ([1,1,2], 2), ([], 1)],
            "valid_parentheses": [("()",), (")",), ("([{}])",), ("(]",), ("",)],
            "is_palindrome": [("",), ("aba",), ("ab",), ("A man, a plan, a canal: Panama",)],
            "valid_anagram": [("", ""), ("anagram", "nagaram"), ("rat", "car"), ("aacc", "ccac")],
            "longest_common_prefix": [(["flower","flow","flight"],), (["dog","racecar"],), ([],), (["a"],)],
            "reverse_string": [("abc",), ("",), (["h","i"],)],
            "reverse_words": [("hello world",), ("  a good   example ",), ("",)],
            "first_unique_char": [("leetcode",), ("aabb",), ("",)],
            "length_of_last_word": [("Hello World",), ("a ",), ("",)],
            "count_vowels": [("hello",), ("",), ("AEIOU",)],
            "roman_to_int": [("III",), ("IV",), ("MCMXCIV",)],
            "fizz_buzz": [(1,), (3,), (5,), (15,)],
            "unique_paths": [(1, 1), (3, 2), (3, 7), (0, 2)],
            "climb_stairs": [(0,), (1,), (2,), (5,)],
            "fibonacci": [(0,), (1,), (2,), (7,)],
            "fib": [(0,), (1,), (2,), (7,)],
            "factorial": [(0,), (1,), (5,), (-1,)],
            "gcd": [(0, 5), (12, 8), (17, 13), (-4, 6)],
            "is_prime": [(0,), (1,), (2,), (9,), (17,)],
            "power": [(2, 3), (5, 0), (2, -1)],
            "pow": [(2, 3), (5, 0), (2, -1)],
            "sqrt": [(0,), (1,), (8,), (16,)],
            "integer_sqrt": [(0,), (1,), (8,), (16,)],
            "parse_csv_line": [("a,b",), ('"a,b",c',), ('"a""b",c',), ("",)],
        }
        allow_boundary = _boundary_allowed(desc)
        probes = [args for args in base.get(name, []) if allow_boundary or not _is_boundary_probe(name, args)]
        return [_p(*args, label=name) for args in probes[:8]]
    return f


def _build_registry() -> list[TaskSpec]:
    names = {
        "summary_ranges": _summary_ranges, "merge_intervals": _merge_intervals, "two_sum": _two_sum,
        "remove_duplicates": _remove_duplicates, "move_zeroes": _move_zeroes, "rotate_array": _rotate_array,
        "plus_one": _plus_one, "majority_element": _majority, "max_subarray": _max_subarray,
        "max_profit": _max_profit, "search_insert": _search_insert, "kth_smallest": _kth_smallest,
        "valid_parentheses": _valid_parentheses, "is_palindrome": _is_palindrome, "valid_anagram": _valid_anagram,
        "roman_to_int": _roman_to_int, "parse_csv_line": _parse_csv_line, "binary_search": _binary_search,
    }
    for n in ("contains_duplicate missing_number single_number longest_common_prefix reverse_string reverse_words "
              "first_unique_char length_of_last_word count_vowels fizz_buzz unique_paths climb_stairs fibonacci fib "
              "factorial gcd is_prime power pow sqrt integer_sqrt").split():
        names[n] = _simple_oracles(n)
    hints = {
        "summary_ranges": ("summary_ranges", "summary ranges"), "merge_intervals": ("merge_intervals", "merge intervals", "overlapping intervals"),
        "two_sum": ("two_sum", "two sum"), "valid_parentheses": ("valid_parentheses", "valid parentheses"),
        "parse_csv_line": ("parse_csv_line", "csv"), "binary_search": ("binary_search", "binary search"),
    }
    specs = []
    for name, oracle in names.items():
        detectors = hints.get(name, (name, name.replace("_", " ")))
        compare = _two_sum_compare if name == "two_sum" else _interval_compare if name == "merge_intervals" else _inplace_or_return_compare if name in {"remove_duplicates", "rotate_array"} else _default_compare
        specs.append(TaskSpec(name, tuple(detectors), oracle, _probes_for(name), compare, "logic_error", tuple()))
    return specs


TASKS = _build_registry()


def _classify(desc: str, entry: str, params: list[str]) -> TaskSpec | None:
    text = f"{entry} {desc} {' '.join(params)}".lower()
    norm = _norm_text(text)
    for spec in TASKS:
        if any(_norm_text(d) in norm for d in spec.detectors):
            return spec
    if "search" in norm and "insert" in norm:
        return next(s for s in TASKS if s.name == "search_insert")
    if "palindrome" in norm:
        return next(s for s in TASKS if s.name == "is_palindrome")
    if "anagram" in norm:
        return next(s for s in TASKS if s.name == "valid_anagram")
    if "duplicate" in norm and "remove" not in norm:
        return next(s for s in TASKS if s.name == "contains_duplicate")
    if "fib" in norm:
        return next(s for s in TASKS if s.name == "fibonacci")
    if "sqrt" in norm or "square_root" in norm:
        return next(s for s in TASKS if s.name == "sqrt")
    return None


def _split_top_level(text: str) -> list[str]:
    out, start, depth, quote = [], 0, 0, ""
    for i, ch in enumerate(text):
        if quote:
            if ch == quote and (i == 0 or text[i - 1] != "\\"):
                quote = ""
        elif ch in "'\"":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            out.append(text[start:i].strip()); start = i + 1
    last = text[start:].strip()
    if last:
        out.append(last)
    return out


def _literal(text: str) -> Any:
    raw = str(text).strip()
    lower = raw.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    if lower in {"null", "none"}:
        return None
    try:
        return ast.literal_eval(raw)
    except Exception:
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {'"', "'"}:
            return raw[1:-1]
        return raw


def _looks_like_placeholder_value(value: Any) -> bool:
    if isinstance(value, str):
        text = value.strip()
        return bool(text and text.isidentifier() and text.lower() in _PLACEHOLDER_NAMES)
    if isinstance(value, (list, tuple)):
        return bool(value) and all(_looks_like_placeholder_value(item) for item in value)
    if isinstance(value, dict):
        return bool(value) and all(_looks_like_placeholder_value(k) and _looks_like_placeholder_value(v) for k, v in value.items())
    return False


def _valid_example_probe(args: tuple[Any, ...], expected: Any, params: list[str]) -> bool:
    if params and len(args) != len(params):
        return False
    if args and all(_looks_like_placeholder_value(arg) for arg in args):
        return False
    if any(_looks_like_placeholder_value(arg) for arg in args):
        return False
    if _looks_like_placeholder_value(expected):
        return False
    return True


def _extract_examples(desc: str, entry: str, params: list[str]) -> list[Probe]:
    probes: list[Probe] = []
    text = desc or ""
    for m in re.finditer(r"([A-Za-z_]\w*)\s*\(([^()\n]*)\)\s*(?:->|=>|should return|returns?)\s*([^\n]+)", text, re.I):
        try:
            args = tuple(_literal(x) for x in _split_top_level(m.group(2))) if m.group(2).strip() else tuple()
            expected = _literal(m.group(3).strip().rstrip("."))
            if _valid_example_probe(args, expected, params):
                probes.append(Probe(args, {}, expected, "example", "call example"))
        except Exception:
            pass
    blocks = re.finditer(r"Input\s*:\s*(.*?)\n\s*Output\s*:\s*([^\n]+)", text, re.I | re.S)
    for m in blocks:
        try:
            assigns: dict[str, Any] = {}
            for part in _split_top_level(m.group(1)):
                if "=" in part:
                    k, v = part.split("=", 1)
                    assigns[_norm_text(k)] = _literal(v)
            args = tuple(assigns[_norm_text(p)] for p in params if _norm_text(p) in assigns)
            expected = _literal(m.group(2).strip().rstrip("."))
            if args and _valid_example_probe(args, expected, params):
                probes.append(Probe(args, {}, expected, "example", "input/output example"))
        except Exception:
            pass
    for m in re.finditer(r"([A-Za-z_]\w*)\s*\(([^()\n]*)\)[^\n]*(?:should return|returns?)\s+([^\n]+)", text, re.I):
        try:
            args = tuple(_literal(x) for x in _split_top_level(m.group(2))) if m.group(2).strip() else tuple()
            expected = _literal(m.group(3).strip().rstrip("."))
            if _valid_example_probe(args, expected, params):
                probes.append(Probe(args, {}, expected, "example", "should return example"))
        except Exception:
            pass
    return probes[:5]


def _param_kind(name: str) -> str:
    n = _norm_text(name)
    if "intervals" in n: return "intervals"
    if any(x in n for x in ("grid", "matrix", "board")): return "matrix"
    if any(x in n for x in ("nums", "arr", "array", "list", "items", "values", "heights", "prices")): return "list"
    if any(x in n for x in ("string", "text", "word", "sentence", "line", "path")) or n == "s": return "string"
    if any(x in n for x in ("target", "num")) or n in {"n", "k", "x", "m"}: return "int"
    return "int"


def _generic_probes(params: list[str], desc: str) -> list[Probe]:
    values = {
        "list": [[], [0], [1], [1, 2], [2, 1], [1, 1], [-1, 0, 1], [0, 1, 2, 4]],
        "string": ["", "a", "aa", "ab", "aba", "A man, a plan, a canal: Panama", "hello world"],
        "int": [0, 1, 2, 3, 5, -1, 10],
        "matrix": [[], [[]], [[1]], [[1, 2], [3, 4]], [[0, 1], [1, 0]]],
        "intervals": [[], [[1, 3]], [[1, 3], [2, 6]], [[1, 4], [4, 5]], [[5, 6], [1, 3]]],
    }
    kinds = [_param_kind(p) for p in params]
    probes: list[Probe] = []
    for i in range(8):
        args = tuple(values[k][min(i, len(values[k]) - 1)] for k in kinds)
        probes.append(Probe(args, {}, source="generic", label="signature boundary"))
    return probes


def _metamorphic_probes(fn: Callable[..., Any], desc: str, entry: str, params: list[str]) -> list[dict]:
    text = _norm_text(f"{entry} {desc}")
    fails: list[dict] = []
    if "sort" in text or "sorted" in text:
        p = Probe(([3, 1, 2, 1],), {}, source="metamorphic", label="sort property")
        st, actual, exc, line = _run(fn, p)
        if st == "ok":
            ret = actual["return"] if actual["return"] is not None else actual["args"][0]
            if isinstance(ret, list) and (ret != sorted(ret) or sorted(ret) != [1, 1, 2, 3]):
                fails.append({"kind": "metamorphic", "line": line, "message": "Sort output is not non-decreasing permutation of input."})
    if "reverse" in text:
        p = Probe(("abc",), {}, source="metamorphic", label="reverse twice")
        st, actual, exc, line = _run(fn, p)
        if st == "ok":
            first = actual["return"]
            st2, actual2, exc2, line2 = _run(fn, Probe((first,), {}, source="metamorphic"))
            if st2 == "ok" and actual2["return"] != "abc":
                fails.append({"kind": "metamorphic", "line": line2, "message": "Reversing twice should recover the original value."})
    if "palindrome" in text:
        for s in ("ab", "ba"):
            pass
        p1, p2 = Probe(("ab",), {}, source="metamorphic"), Probe(("ba",), {}, source="metamorphic")
        st1, a1, e1, l1 = _run(fn, p1); st2, a2, e2, l2 = _run(fn, p2)
        if st1 == st2 == "ok" and bool(a1["return"]) != bool(a2["return"]):
            fails.append({"kind": "metamorphic", "line": l1, "message": "Palindrome result should match for s and reversed s."})
    return fails[:1]


def _description_mentions_boundary(desc: str, probe: Probe, exc: BaseException | None) -> bool:
    d = desc.lower()
    words = ("empty", "blank", "zero", "negative", "duplicate", "case-insensitive", "case insensitive", "none", "invalid", "null")
    return any(x in d for x in words)


def _line_matching(lines: list[str], pattern: str) -> int:
    rx = re.compile(pattern)
    for i, line in enumerate(lines, 1):
        if rx.search(line):
            return i
    return 0


def _locate_line(task_kind: str, failure: dict, lines: list[str], tree: ast.AST | None, entry: str = "") -> tuple[int, int]:
    if failure.get("line"):
        line = int(failure["line"])
        return line, line
    if failure.get("syntax_line"):
        line = int(failure["syntax_line"])
        return line, line
    if tree is not None:
        locator = LineLocator(entry)
        locator.visit(tree)
        hints = {
            "merge_intervals": (("merged", "start", "end"), (ast.If, ast.Assign, ast.AugAssign)),
            "summary_ranges": (("append", "->", "while"), (ast.While, ast.Return, ast.If)),
            "two_sum": (("target", "seen", "return"), (ast.If, ast.Return, ast.Assign)),
            "max_subarray": (("best", "cur"), (ast.Assign, ast.AugAssign, ast.Return)),
            "search_insert": (("lo", "hi", "mid", "target"), (ast.If, ast.While, ast.Return)),
            "binary_search": (("lo", "hi", "mid", "target"), (ast.If, ast.While, ast.Return)),
            "plus_one": (("carry", "digit", "return"), (ast.Assign, ast.AugAssign, ast.Return)),
            "kth_smallest": (("sorted", "k"), (ast.Return, ast.Subscript)),
            "unique_paths": (("dp", "j"), (ast.Assign, ast.Return)),
        }
        if task_kind == "merge_intervals":
            for node in locator.nodes:
                if isinstance(node, ast.If):
                    try:
                        text = ast.unparse(node.test).lower()
                    except Exception:
                        text = ""
                    if "merged" in text and any(token in text for token in ("start", "cur", "interval", "[0]")):
                        return _node_span(node)
        if task_kind in {"binary_search", "search_insert"}:
            uses_exclusive_hi = False
            has_strict_loop = False
            for line in lines:
                compact = line.replace(" ", "")
                if compact.startswith("while") and "lo<hi" in compact:
                    has_strict_loop = True
                if re.search(r"(?:^|,)hi=len\([^)]*\)$", compact):
                    uses_exclusive_hi = True
            if uses_exclusive_hi:
                for node in locator.nodes:
                    try:
                        text = ast.unparse(node).replace(" ", "")
                    except Exception:
                        text = ""
                    if has_strict_loop and isinstance(node, (ast.Assign, ast.AugAssign)) and "hi=mid-1" in text:
                        return _node_span(node)
            node = locator.first((ast.While,))
            if node is not None:
                line, _ = _node_span(node)
                return line, line
        if task_kind == "unique_paths":
            for node in locator.nodes:
                try:
                    text = ast.unparse(node).replace(" ", "")
                except Exception:
                    text = ""
                if isinstance(node, (ast.Assign, ast.AugAssign)) and "dp[i][j]" in text:
                    return _node_span(node)
        if task_kind == "kth_smallest":
            for node in locator.nodes:
                try:
                    text = ast.unparse(node).replace(" ", "")
                except Exception:
                    text = ""
                if "set(" in text:
                    return _node_span(node)
                if "sorted(" in text and "[k]" in text:
                    return _node_span(node)
        if task_kind in hints:
            names, kinds = hints[task_kind]
            return _node_span(locator.containing_name(names) or locator.first(kinds))
        status = failure.get("status")
        if status == "crash":
            return _node_span(locator.first((ast.Subscript, ast.BinOp, ast.Call if hasattr(ast, "Call") else ast.AST)))
        return _node_span(locator.first((ast.Return, ast.If, ast.Compare, ast.For, ast.While)))
    return 1, 1


def _classify_failure(kind: str, status: str, exc: BaseException | None, probe: Probe) -> tuple[str, str, float]:
    if status == "timeout":
        return "inefficient", "medium", 0.75
    if status == "crash":
        name = type(exc).__name__ if exc else "Exception"
        boundary = any(arg in ([], "", 0) for arg in probe.args)
        if name == "IndexError" and boundary: return "edge_case", "medium", 0.72 if kind == "generic" else 0.90
        if name == "ZeroDivisionError": return "edge_case", "medium", 0.72 if kind == "generic" else 0.90
        if name == "TypeError": return "type_error", "medium" if boundary else "high", 0.82 if kind == "generic" else 0.90
        if name in {"KeyError", "ValueError"}: return "unhandled_input", "medium", 0.72 if kind == "generic" else 0.90
        return "logic_error", "medium" if boundary else "high", 0.82 if kind == "generic" else 0.90
    if kind == "known" and probe.label in {"search_insert", "binary_search", "kth_smallest"}:
        return "off_by_one", "medium", 0.88
    if kind == "known" and probe.label == "merge_intervals" and status == "mismatch":
        intervals = probe.args[0] if probe.args else []
        touches = any(a[1] == b[0] or b[1] == a[0] for a in intervals for b in intervals if a is not b)
        if touches:
            return "off_by_one", "high", 0.88
    if kind == "known" and probe.label == "unique_paths":
        return "logic_error", "high", 0.88
    boundary = any(arg in ([], "", 0) or arg == [0] or arg == [1] for arg in probe.args)
    return ("edge_case", "medium", 0.84) if boundary else ("logic_error", "high", 0.88)


def _format_args(probe: Probe) -> str:
    try:
        return repr(list(probe.args) if not probe.kwargs else {"args": list(probe.args), "kwargs": probe.kwargs})[:120]
    except Exception:
        return "the failing input"


def _suggest_fix(kind: str, status: str, exc: BaseException | None, probe: Probe, expected: Any = None) -> str:
    if kind == "example" and status == "mismatch":
        return f"Update the condition/return logic so input {_format_args(probe)} returns {expected!r}."
    if status == "crash" and isinstance(exc, IndexError):
        if any(arg == [] or arg == "" for arg in probe.args):
            return "Add an empty-input guard before indexing the sequence."
        return "Check bounds before indexing the sequence."
    if status == "crash" and isinstance(exc, TypeError):
        return "Convert or validate the value before applying this operation."
    if status == "timeout":
        return "Replace the unbounded loop or quadratic scan with a bounded algorithm."
    if kind == "known" and probe.label in {"search_insert", "binary_search"}:
        return "Adjust the comparison or loop bound so the returned index is correct."
    if kind == "known" and probe.label == "max_subarray":
        return "Initialize and update the running/best sum from the first element."
    if kind == "known" and probe.label == "merge_intervals":
        return "Update the overlap condition and merged end update for touching intervals."
    if kind == "known" and probe.label == "summary_ranges":
        return "Append the final range after scanning each consecutive run."
    return f"Update the branch or return logic for input {_format_args(probe)}."


def _make_finding(task_id: str, desc: str, lines: list[str], tree: ast.AST | None, entry: str, failure: dict) -> Finding:
    kind = failure.get("kind", "known")
    status = failure.get("status", "mismatch")
    exc = failure.get("exc")
    probe = failure.get("probe", Probe((), {}))
    bug_type, severity, conf = _classify_failure(kind, status, exc, probe)
    if kind == "syntax":
        line = int(failure.get("line", 1) or 1)
        return Finding(line, line, "critical", "api_misuse", "Code has a syntax error.", "Fix the syntax error before submission.", 0.95, 1, None, "syntax")
    if kind == "missing_entry":
        return Finding(1, 1, "critical", "api_misuse", "The required entry function is missing.", "Define the function named by the task.", 0.95, 1, None, "missing_entry")
    if kind == "exec":
        line = int(failure.get("line", 1) or 1)
        return Finding(line, line, "critical", "api_misuse", "Candidate fails during compile or module execution.", "Move work into the entry function and avoid top-level failures.", 0.90, 1, None, "exec")
    if kind == "example":
        conf = 0.92
        msg = "Candidate does not match an explicit task_description example." if status == "mismatch" else "Candidate crashes on an explicit task_description example."
    elif kind == "metamorphic":
        conf = 0.74
        msg = failure.get("message", "Candidate violates a task-derived metamorphic property.")
    elif kind == "generic":
        msg = f"Candidate crashes on a signature-appropriate small input: {type(exc).__name__ if exc else status}."
    else:
        msg = "Candidate result disagrees with a deterministic task oracle." if status == "mismatch" else f"Candidate crashes on a known valid probe: {type(exc).__name__ if exc else status}."
    rank = {"syntax": 1, "missing_entry": 1, "exec": 1, "example": 2, "known": 3, "metamorphic": 4, "generic": 5}.get(kind, 5)
    if kind == "known" and status == "crash" and probe is not None and _is_boundary_probe(str(failure.get("task", probe.label)), probe.args):
        # Prefer valid-domain oracle mismatches over boundary crashes when both are present.
        rank = 4
    line, line_end = _locate_line(str(failure.get("task", probe.label if probe else "")), failure, lines, tree, entry)
    fix = _suggest_fix(kind, status, exc, probe, getattr(probe, "expected", None))
    return Finding(line, line_end, severity, bug_type, msg, fix, conf, rank, probe, status)


def _finding_bug(finding: Finding) -> dict:
    return _bug(finding.line, finding.severity, finding.type, finding.description, finding.suggested_fix, finding.line_end)


def _dedupe_findings(findings: list[Finding]) -> list[Finding]:
    seen: set[tuple[int, str, str]] = set()
    out: list[Finding] = []
    for item in sorted(findings, key=lambda f: (f.evidence_rank, -f.confidence, f.line, f.type)):
        key = (item.line, item.type, item.description)
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _csv_source_findings(code: str, entry: str, desc: str, lines: list[str], tree: ast.AST | None) -> list[Finding]:
    text = _norm_text(f"{entry} {desc}")
    if entry != "parse_csv_line" and "csv" not in text:
        return []
    code_lower = code.lower()
    quote_state = "in_quotes" in code_lower or "in_quote" in code_lower or "quoted" in code_lower
    split_comma = ".split(',')" in code or '.split(",")' in code
    comma_separator = bool(re.search(r"if\s+\w+\s*==\s*['\"]\s*,\s*['\"]", code))
    doubled_quote = bool(re.search(r"\+\s*1\s*<\s*len\([^)]*\).*==\s*['\"]\"['\"]", code, re.S)) or '""' in code or "''" in code
    if (split_comma or comma_separator) and not quote_state:
        line = _line_matching(lines, r"\.split\(\s*['\"]\s*,\s*['\"]\s*\)") or _line_matching(lines, r"if\s+\w+\s*==\s*['\"]\s*,\s*['\"]") or 1
        return [Finding(
            line,
            line,
            "high",
            "unhandled_input",
            "Quoted CSV fields containing commas will be mis-split.",
            "Track quote state and only split on commas outside quotes.",
            0.90,
            3,
            Probe((), {}, source="known", label="parse_csv_line"),
            "mismatch",
        )]
    if quote_state and not doubled_quote:
        line = _line_matching(lines, r"in_quotes|in_quote|quoted") or _line_matching(lines, r"['\"]\"['\"]") or 1
        return [Finding(
            line,
            line,
            "medium",
            "edge_case",
            "Escaped doubled quote convention is not handled.",
            "When inside quotes and the next character is a quote, append a literal quote and advance by 2.",
            0.86,
            3,
            Probe((), {}, source="known", label="parse_csv_line"),
            "mismatch",
        )]
    return []


def _final_contract(task_id: str, findings: list[Finding], default_confidence: float) -> dict:
    findings = _dedupe_findings(findings)
    if not findings:
        return _contract(task_id, None, default_confidence)
    best = findings[0]
    if best.evidence_rank >= 4 and best.confidence < 0.80:
        return _contract(task_id, None, 0.55)
    return _contract(task_id, _finding_bug(best), best.confidence)


def _line_count_from_payload(payload: dict) -> int:
    code = _extract_code(payload)
    return max(1, len(code.splitlines()))


def _clamp_int(value: Any, lo: int, hi: int) -> int:
    try:
        num = int(value)
    except (TypeError, ValueError):
        num = lo
    return max(lo, min(hi, num))


def _looks_placeholder_false_positive(text: str) -> bool:
    raw = str(text or "").lower()
    if re.search(r"\[\s*['\"](?:arr|array|nums|target|line|s|x|y|n|m|k)['\"]\s*(?:,\s*['\"](?:arr|array|nums|target|line|s|x|y|n|m|k)['\"]\s*)*\]", raw):
        return True
    if "placeholder" in raw and "input" in raw:
        return True
    tokens = set(re.findall(r"[a-z_]+", raw))
    meaningful = tokens - {"the", "a", "an", "to", "for", "input", "argument", "parameter", "value", "values", "bug", "fix", "returns", "return"}
    return bool(meaningful) and meaningful <= _PLACEHOLDER_NAMES


def _looks_self_negating_bug(text: str) -> bool:
    raw = str(text or "").lower()
    negating_phrases = (
        "cannot find a concrete bug",
        "can't find a concrete bug",
        "cannot find a bug",
        "can't find a bug",
        "could not find a bug",
        "no concrete bug",
        "no bug",
        "no fix needed",
        "return clean",
        "verdict clean",
        "i will return clean",
        "i would return clean",
    )
    return any(phrase in raw for phrase in negating_phrases)


def _looks_speculative_bug(text: str) -> bool:
    raw = str(text or "").lower()
    speculative = (
        "potentially",
        "might",
        "may ",
        "could ",
        "or similar",
        "depending on",
        "unclear",
        "not sure",
    )
    if not any(token in raw for token in speculative):
        return False
    has_concrete_evidence = any(token in raw for token in ("expected", "instead", "actual", "returns", "raises", "for example"))
    return not has_concrete_evidence or "or similar" in raw or "depending on" in raw


def _looks_impossible_continue_claim(text: str) -> bool:
    raw = str(text or "").lower()
    mentions_continue = "continue" in raw
    claims_later_increment = any(
        phrase in raw
        for phrase in (
            "outer loop also increments",
            "also increments at the end",
            "outer loop's i += 1 also executes",
            "bottom of the loop also executes",
            "incremented by 1 at the end of the loop",
            "incremented by 1 at end of the loop",
            "total increment of 3 instead of 2",
            "increment of 3 instead of 2",
            "advancing by 3",
            "advances 3 total",
            "final i += 1",
            "double-increment",
            "double increment",
        )
    )
    return mentions_continue and claims_later_increment


def _parser_delimiter_hint(code: str, bug_text: str) -> tuple[int, int, str | None] | None:
    text = str(bug_text or "").lower()
    if not any(word in text for word in ("quoted", "quote", "delimiter", "comma", "split", "separator")):
        return None
    lines = code.splitlines() or [""]
    for idx, line in enumerate(lines, start=1):
        compact = line.replace(" ", "")
        lower = line.lower()
        delimiter_branch = (
            "==','" in compact
            or '==","' in compact
            or "split(" in lower
            or "separator" in lower
            or "delimiter" in lower
        )
        if not delimiter_branch:
            continue
        if "quote" in lower or "in_quotes" in lower or "inquote" in lower:
            continue
        end = idx
        for j in range(idx + 1, min(len(lines), idx + 4) + 1):
            stripped = lines[j - 1].strip()
            if not stripped:
                continue
            end = j
            if stripped.startswith("else"):
                continue
            if "append" in stripped or "+=" in stripped or "=" in stripped:
                continue
            break
        return idx, max(idx, min(end, len(lines))), "unhandled_input"
    return None


def _ordinal_index_hint(code: str, bug_text: str) -> tuple[int, int, str | None] | None:
    text = str(bug_text or "").lower()
    if not any(word in text for word in ("1-based", "0-based", "off-by-one", "off by one", "k=1", "k=len", "index")):
        return None
    if not any(word in text for word in ("k", "kth", "nth", "smallest", "largest", "rank", "ordinal", "position")):
        return None
    lines = code.splitlines() or [""]
    for idx, line in enumerate(lines, start=1):
        compact = line.replace(" ", "")
        if re.search(r"\[k\]", compact) or re.search(r"\[\s*k\s*\]", line):
            return idx, idx, "off_by_one"
    return None


def _binary_search_boundary_hint(payload: dict, code: str, bug_text: str) -> tuple[int, int, str | None] | None:
    task_text = _norm_text(f"{_extract_description(payload)} {_extract_constraints_text(payload)}")
    if "binary_search" not in task_text and not ("binary" in task_text and "search" in task_text):
        return None
    text = str(bug_text or "").lower()
    boundary_words = ("lo == hi", "lo==hi", "final candidate", "single-element", "single element", "skips", "off-by-one", "off by one")
    if not any(word in text for word in boundary_words):
        return None
    lines = code.splitlines() or [""]
    for idx, line in enumerate(lines, start=1):
        compact = line.replace(" ", "")
        if compact.startswith("while") and "lo<hi" in compact:
            return idx, idx, "off_by_one"
    return None


def _dp_recurrence_hint(code: str, bug_text: str) -> tuple[int, int, str | None] | None:
    text = str(bug_text or "").lower().replace(" ", "")
    if "dp[i][j]" not in text and "recurrence" not in text:
        return None
    lines = code.splitlines() or [""]
    for idx, line in enumerate(lines, start=1):
        compact = line.replace(" ", "")
        if "dp[i][j]" in compact and "=" in compact:
            return idx, idx, "logic_error"
    return None


def _sanitize_bug(bug: Any, payload: dict, code_line_count: int) -> dict | None:
    if not isinstance(bug, dict):
        return None
    desc = str(bug.get("description", "")).strip()
    fix = str(bug.get("suggested_fix", "")).strip()
    if not desc or not fix:
        return None
    if _looks_placeholder_false_positive(desc) or _looks_placeholder_false_positive(fix):
        return None
    if _looks_self_negating_bug(desc) or _looks_self_negating_bug(fix):
        return None
    if _looks_speculative_bug(desc):
        return None
    if _looks_impossible_continue_claim(f"{desc} {fix}"):
        return None
    if desc.lower() in {"bug", "fix bug", "wrong", "incorrect"}:
        return None
    if fix.lower() in {"fix", "fix bug", "handle edge case", "fix the bug"}:
        return None
    line_start = _clamp_int(bug.get("line_start", 1), 1, code_line_count)
    line_end = _clamp_int(bug.get("line_end", line_start), 1, code_line_count)
    if line_end < line_start:
        line_end = line_start
    severity = str(bug.get("severity", "medium")).strip().lower()
    if severity not in ALLOWED_SEVERITIES:
        severity = "medium"
    bug_type = str(bug.get("type", "logic_error")).strip().lower()
    if bug_type not in ALLOWED_TYPES:
        bug_type = "logic_error"
    code = _extract_code(payload)
    for hint in (
        _parser_delimiter_hint(code, f"{desc} {fix}"),
        _ordinal_index_hint(code, f"{desc} {fix}"),
        _binary_search_boundary_hint(payload, code, f"{desc} {fix}"),
        _dp_recurrence_hint(code, f"{desc} {fix}"),
    ):
        if hint is not None:
            line_start, line_end, type_hint = hint
            if type_hint is not None:
                bug_type = type_hint
            break
    return {
        "line_start": line_start,
        "line_end": line_end,
        "severity": severity,
        "type": bug_type,
        "description": desc,
        "suggested_fix": fix,
    }


def _normalize_candidate_report(payload: dict, report: dict | None) -> dict:
    task_id = str(_payload_value(payload, ("task_id", "id")) or "")
    if not isinstance(report, dict):
        return _contract(task_id, None, 0.55)
    confidence = _clamp_confidence(report.get("confidence", 0.75))
    verdict = str(report.get("verdict", "")).strip().lower()
    if verdict == "clean":
        return _contract(task_id, None, min(0.70, max(0.55, confidence)))
    raw_bugs = report.get("bugs", [])
    if not isinstance(raw_bugs, list):
        raw_bugs = []
    code_line_count = _line_count_from_payload(payload)
    bugs: list[dict] = []
    for item in raw_bugs:
        clean = _sanitize_bug(item, payload, code_line_count)
        if clean is not None:
            bugs.append(clean)
        if len(bugs) >= 2:
            break
    if not bugs:
        return _contract(task_id, None, 0.55)
    return _contract(task_id, bugs, confidence if confidence > 0 else 0.75)


def _normalize_with_audit(payload: dict, report: dict | None) -> dict:
    candidate = _normalize_candidate_report(payload, report)
    if candidate.get("bugs"):
        first = candidate["bugs"][0]
        broad_from_def = int(first.get("line_start", 1) or 1) == 1 and int(first.get("line_end", 1) or 1) - 1 >= 3
        broad_range = int(first.get("line_end", 1) or 1) - int(first.get("line_start", 1) or 1) >= 2
        if broad_from_def or broad_range:
            audit = _audit_payload(payload)
            audit_bugs = audit.get("bugs") or []
            if audit_bugs and int(audit_bugs[0].get("line_end", 1) or 1) == int(audit_bugs[0].get("line_start", 1) or 1):
                return audit
        return candidate
    if not isinstance(report, dict) or str(report.get("verdict", "")).strip().lower() != "clean":
        return candidate
    raw_confidence = _clamp_confidence(report.get("confidence", 0.0)) if isinstance(report, dict) else 0.0
    if raw_confidence > 0.70:
        return candidate
    audit = _audit_payload(payload)
    if audit.get("bugs"):
        return audit
    return candidate


def _clamp_confidence(value: Any) -> float:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return 0.75
    return max(0.0, min(1.0, num))


def _parse_cli_args(argv: list[str]) -> Any | None:
    if not any(arg.startswith("--") for arg in argv[1:]):
        return None
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--task_id")
    parser.add_argument("--verdict")
    parser.add_argument("--confidence", default=0.75)
    parser.add_argument("--bugs")
    parser.add_argument("--payload", default="")
    parser.add_argument("--report", default="")
    parser.add_argument("--code", default="")
    parser.add_argument("--task_description", default="")
    return parser.parse_args(argv[1:])


def _parse_bug_array(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _sanitize_cli_bug(bug: Any) -> dict | None:
    if not isinstance(bug, dict):
        return None
    desc = str(bug.get("description", "")).strip()
    fix = str(bug.get("suggested_fix", "")).strip()
    line_start = _clamp_int(bug.get("line_start", 1), 1, 10**9)
    line_end = _clamp_int(bug.get("line_end", line_start), 1, 10**9)
    if line_end < line_start:
        line_end = line_start
    severity = str(bug.get("severity", "medium")).strip().lower()
    if severity not in ALLOWED_SEVERITIES:
        severity = "medium"
    bug_type = str(bug.get("type", "logic_error")).strip().lower()
    if bug_type not in ALLOWED_TYPES:
        bug_type = "logic_error"
    return {
        "line_start": line_start,
        "line_end": line_end,
        "severity": severity,
        "type": bug_type,
        "description": desc,
        "suggested_fix": fix,
    }


def _direct_cli_contract(args: Any) -> dict:
    verdict = str(args.verdict or "").strip().lower()
    raw_bugs = _parse_bug_array(args.bugs)
    bugs = [clean for item in raw_bugs if (clean := _sanitize_cli_bug(item)) is not None]
    if verdict == "clean":
        bugs = []
    elif bugs:
        verdict = "buggy"
    elif verdict not in {"buggy", "clean"}:
        verdict = "clean"
    return {
        "task_id": str(args.task_id or ""),
        "verdict": verdict,
        "bugs": bugs,
        "confidence": _clamp_confidence(args.confidence),
    }


def _payload_report_from_cli(args: Any) -> tuple[dict, dict | None]:
    payload = _extract_json_object(str(args.payload or ""))
    if not isinstance(payload, dict):
        raise ValueError("payload not an object")
    report = _extract_json_object(str(args.report or ""))
    return payload, report


def _audit_payload(payload: dict) -> dict:
    task_id = str(_payload_value(payload, ("task_id", "id")) or "")
    desc = _extract_description(payload)
    probe_desc = f"{desc} {_extract_constraints_text(payload)}"
    code = _extract_code(payload)
    lines = code.splitlines() or [""]
    if not code.strip():
        return _contract(task_id, _bug(1, "critical", "api_misuse", "No code was provided.", "Provide Python source code to audit."), 0.95)
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        finding = _make_finding(task_id, desc, lines, None, "", {"kind": "syntax", "line": exc.lineno or 1})
        return _final_contract(task_id, [finding], 0.95)
    entry = _infer_entry(payload, desc, tree)
    ns, exec_exc, exec_line = _exec_candidate(code)
    if exec_exc is not None or ns is None:
        finding = _make_finding(task_id, desc, lines, tree, entry, {"kind": "exec", "line": exec_line, "exc": exec_exc})
        return _final_contract(task_id, [finding], 0.90)
    fn = ns.get(entry) if entry else None
    if not callable(fn):
        finding = _make_finding(task_id, desc, lines, tree, entry, {"kind": "missing_entry"})
        return _final_contract(task_id, [finding], 0.95)
    try:
        sig = inspect.signature(fn)
        params = [p.name for p in sig.parameters.values() if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    except Exception:
        params = []
    spec = _classify(desc, entry, params)
    findings: list[Finding] = []
    findings.extend(_csv_source_findings(code, entry, desc, lines, tree))

    for probe in _extract_examples(desc, entry, params):
        st, actual, exc, line = _run(fn, probe)
        if st in {"crash", "timeout"}:
            findings.append(_make_finding(task_id, desc, lines, tree, entry, {"kind": "example", "status": st, "line": line, "exc": exc, "probe": probe}))
            continue
        if not _default_compare(actual, probe.expected, probe):
            findings.append(_make_finding(task_id, desc, lines, tree, entry, {"kind": "example", "status": "mismatch", "probe": probe}))

    if spec is not None:
        for probe in spec.probes(probe_desc):
            probe.expected = spec.oracle(probe.args, desc)
            st, actual, exc, line = _run(fn, probe)
            if st in {"crash", "timeout"}:
                findings.append(_make_finding(task_id, desc, lines, tree, entry, {"kind": "known", "task": spec.name, "status": st, "line": line, "exc": exc, "probe": probe}))
                continue
            if not spec.compare(actual, probe.expected, probe):
                findings.append(_make_finding(task_id, desc, lines, tree, entry, {"kind": "known", "task": spec.name, "status": "mismatch", "probe": probe}))
        return _final_contract(task_id, findings, 0.82)

    meta = _metamorphic_probes(fn, desc, entry, params)
    for failure in meta:
        findings.append(_make_finding(task_id, desc, lines, tree, entry, failure))

    for probe in _generic_probes(params, desc)[:8]:
        st, actual, exc, line = _run(fn, probe)
        if st in {"crash", "timeout"} and _description_mentions_boundary(desc, probe, exc):
            # Ignore likely harness arity mismatches; probes match positional arity by construction.
            findings.append(_make_finding(task_id, desc, lines, tree, entry, {"kind": "generic", "status": st, "line": line, "exc": exc, "probe": probe}))
    return _final_contract(task_id, findings, 0.55)


def main(argv: list[str]) -> int:
    cli_args = _parse_cli_args(argv)
    if cli_args is not None:
        if cli_args.task_id is not None and cli_args.verdict is not None and cli_args.bugs is not None:
            return _emit(_direct_cli_contract(cli_args))
        if cli_args.payload and cli_args.report:
            try:
                payload, report = _payload_report_from_cli(cli_args)
            except Exception:
                return _emit(_contract("", None, 0.0))
            return _emit(_normalize_candidate_report(payload, report))
    raw = _read_raw(argv)
    payload, report = _parse_input(raw)
    if report is not None or REPORT_DELIMITER in raw:
        return _emit(_normalize_with_audit(payload, report))
    return _emit(_audit_payload(payload))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
