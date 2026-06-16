#!/usr/bin/env python3
"""Local smoke tests for bug-hunter-loweiwei."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
RUN = ROOT / "run.py"
SKILL = ROOT.parent / "SKILL.md"


def _load_runner():
    spec = importlib.util.spec_from_file_location("bug_hunter_run", RUN)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


runner = _load_runner()


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def _call(payload: dict) -> dict:
    return _call_raw(json.dumps(payload, ensure_ascii=False))


def _call_raw(raw: str, *args: str) -> dict:
    old_stdin, old_stdout = sys.stdin, sys.stdout
    old_result = os.environ.get("AIASE_RESULT_PATH")
    fd, result_path = tempfile.mkstemp(prefix="bug_hunter_selftest_", suffix=".json")
    os.close(fd)
    os.remove(result_path)
    try:
        os.environ["AIASE_RESULT_PATH"] = result_path
        sys.stdin = io.StringIO(raw)
        buf = io.StringIO()
        sys.stdout = buf
        rc = runner.main(["run.py", *args])
        _assert(rc == 0, "run.py return code")
        _assert(buf.getvalue() == "", "stdout must be empty")
        with open(result_path, encoding="utf-8") as f:
            return json.load(f)
    finally:
        sys.stdin = old_stdin
        sys.stdout = old_stdout
        if old_result is None:
            os.environ.pop("AIASE_RESULT_PATH", None)
        else:
            os.environ["AIASE_RESULT_PATH"] = old_result
        if os.path.exists(result_path):
            os.remove(result_path)


def _mixed(payload: dict, report: str | dict) -> dict:
    report_text = json.dumps(report, ensure_ascii=False) if isinstance(report, dict) else str(report)
    raw = json.dumps(payload, ensure_ascii=False) + "\n" + runner.REPORT_DELIMITER + "\n" + report_text
    return _call_raw(raw)


def _schema(obj: dict) -> None:
    _assert({"task_id", "verdict", "bugs", "confidence"} <= set(obj), "contract fields")
    _assert(obj["verdict"] in {"clean", "buggy"}, "verdict enum")
    for bug in obj["bugs"]:
        _assert({"line_start", "line_end", "severity", "type", "description", "suggested_fix"} <= set(bug), "bug fields")
        _assert(bug["type"] in runner.ALLOWED_TYPES, "bug type enum")
        _assert(bug["severity"] in runner.ALLOWED_SEVERITIES, "severity enum")
        _assert(isinstance(bug["line_start"], int) and bug["line_start"] >= 1, "line_start")
        _assert(isinstance(bug["line_end"], int) and bug["line_end"] >= bug["line_start"], "line_end")


def _payload(task_id: str, desc: str, entry: str, code: str) -> dict:
    return {"task_id": task_id, "task_description": desc, "constraints": {"entry_function": entry}, "code": code}


def test_skill_filebased_template_text() -> None:
    text = SKILL.read_text(encoding="utf-8")
    _assert("REPO_ROOT" not in text, "legacy REPO_ROOT remains")
    _assert("git rev-parse" not in text, "legacy git rev-parse remains")
    _assert("$REPO_ROOT/skills/bug-hunter-loweiwei/scripts/run.py" not in text, "legacy repo-root run.py path remains")
    _assert("<skill_dir>/scripts/run.py" in text, "missing skill_dir run.py path")
    _assert(runner.REPORT_DELIMITER in text, "missing report delimiter")
    _assert("The only allowed visible action is one terminal call." in text, "missing terminal-only wording")
    _assert("The grader reads the result file, not stdout or chat text." in text, "missing file-contract wording")


def test_cli_clean_contract() -> None:
    obj = _call_raw("", "--task_id", "cli_clean", "--verdict", "clean", "--confidence", "0.8", "--bugs", "[]")
    _assert(obj == {"task_id": "cli_clean", "verdict": "clean", "bugs": [], "confidence": 0.8}, "CLI clean contract")


def test_cli_buggy_contract() -> None:
    bugs = '[{"line_start":2,"line_end":2,"severity":"severe","type":"bad","description":"Returns x plus one instead of x.","suggested_fix":"Return x unchanged."}]'
    obj = _call_raw("", "--task_id", "cli_buggy", "--verdict", "buggy", "--confidence", "2", "--bugs", bugs)
    _schema(obj)
    _assert(obj["task_id"] == "cli_buggy", "CLI buggy task id")
    _assert(obj["verdict"] == "buggy" and len(obj["bugs"]) == 1, "CLI buggy verdict")
    _assert(obj["bugs"][0]["severity"] == "medium", "CLI invalid severity normalized")
    _assert(obj["bugs"][0]["type"] == "logic_error", "CLI invalid type normalized")
    _assert(obj["confidence"] == 1.0, "CLI confidence clamped")


def test_cli_payload_report_contract() -> None:
    payload = _payload("cli_payload", "identity", "solution", "def solution(x):\n    return x + 1\n")
    report = {"verdict": "buggy", "bugs": [{"line_start": 2, "line_end": 2, "severity": "high", "type": "logic_error", "description": "Returns x plus one instead of x.", "suggested_fix": "Return x unchanged."}], "confidence": 0.8}
    obj = _call_raw("", "--payload", json.dumps(payload, ensure_ascii=False), "--report", json.dumps(report, ensure_ascii=False))
    _schema(obj)
    _assert(obj["task_id"] == "cli_payload", "payload report task id")
    _assert(obj["verdict"] == "buggy" and len(obj["bugs"]) == 1, "payload report normalized")


def test_clean_known_tasks() -> None:
    cases = [
        _payload("clean_merge", "merge intervals", "merge_intervals", "def merge_intervals(intervals):\n    intervals = sorted(intervals, key=lambda x: x[0])\n    out = []\n    for s, e in intervals:\n        if not out or s > out[-1][1]:\n            out.append([s, e])\n        else:\n            out[-1][1] = max(out[-1][1], e)\n    return out\n"),
        _payload("clean_summary", "summary ranges", "summary_ranges", "def summary_ranges(nums):\n    out = []\n    i = 0\n    while i < len(nums):\n        start = nums[i]\n        while i + 1 < len(nums) and nums[i + 1] == nums[i] + 1:\n            i += 1\n        end = nums[i]\n        out.append(str(start) if start == end else str(start) + '->' + str(end))\n        i += 1\n    return out\n"),
        _payload("clean_two_sum", "two sum", "two_sum", "def two_sum(nums, target):\n    seen = {}\n    for i, n in enumerate(nums):\n        if target - n in seen:\n            return [seen[target - n], i]\n        seen[n] = i\n    return None\n"),
        _payload("clean_parens", "valid parentheses", "valid_parentheses", "def valid_parentheses(s):\n    stack = []\n    pairs = {')':'(', ']':'[', '}':'{'}\n    for ch in s:\n        if ch in pairs.values():\n            stack.append(ch)\n        elif ch in pairs:\n            if not stack or stack.pop() != pairs[ch]:\n                return False\n    return not stack\n"),
    ]
    for payload in cases:
        obj = _call(payload)
        _schema(obj)
        _assert(obj["verdict"] == "clean", f"false positive: {payload['task_id']} {obj}")


def test_buggy_merge_intervals_touching_line() -> None:
    code = "def merge_intervals(intervals):\n    intervals = sorted(intervals, key=lambda x: x[0])\n    merged = []\n    for start, end in intervals:\n        if not merged or start >= merged[-1][1]:\n            merged.append([start, end])\n        else:\n            merged[-1][1] = max(merged[-1][1], end)\n    return merged\n"
    obj = _call(_payload("bug_merge", "merge intervals", "merge_intervals", code))
    _schema(obj)
    _assert(obj["verdict"] == "buggy", "merge bug detected")
    _assert(obj["bugs"][0]["line_start"] == 5, f"merge line from code string: {obj}")


def test_buggy_summary_ranges_missing_last() -> None:
    code = "def summary_ranges(nums):\n    out = []\n    for i in range(len(nums) - 1):\n        if nums[i + 1] != nums[i] + 1:\n            out.append(str(nums[i]))\n    return out\n"
    obj = _call(_payload("bug_summary", "summary ranges", "summary_ranges", code))
    _schema(obj)
    _assert(obj["verdict"] == "buggy", "summary bug detected")


def test_buggy_max_subarray_all_negative() -> None:
    code = "def max_subarray(nums):\n    best = 0\n    cur = 0\n    for x in nums:\n        cur = max(0, cur + x)\n        best = max(best, cur)\n    return best\n"
    obj = _call(_payload("bug_max", "max subarray", "max_subarray", code))
    _schema(obj)
    _assert(obj["verdict"] == "buggy", "max_subarray bug detected")
    _assert(obj["bugs"][0]["line_start"] in {2, 3, 5, 6, 7}, "max_subarray suspicious line")


def test_buggy_search_insert_empty_or_insert() -> None:
    code = "def search_insert(nums, target):\n    lo, hi = 0, len(nums) - 1\n    while lo < hi:\n        mid = (lo + hi) // 2\n        if nums[mid] < target:\n            lo = mid + 1\n        else:\n            hi = mid - 1\n    return lo\n"
    obj = _call(_payload("bug_insert", "search insert position", "search_insert", code))
    _schema(obj)
    _assert(obj["verdict"] == "buggy", "search_insert bug detected")
    _assert(obj["bugs"][0]["line_start"] in {2, 3, 5, 8, 9}, "search_insert code line")


def test_nested_json_string_payload() -> None:
    nested = {"code": "def two_sum(nums, target):\n    return [0, 1]\n", "constraints": {"entry_point": "two_sum"}}
    obj = _call({"task_id": "nested", "task_description": "two sum", "code_author_output": json.dumps(nested)})
    _schema(obj)
    _assert(obj["task_id"] == "nested", "task id preserved")


def test_clean_typing_import_list() -> None:
    code = "from typing import List\ndef two_sum(nums: List[int], target: int) -> List[int]:\n    seen = {}\n    for i, n in enumerate(nums):\n        if target - n in seen:\n            return [seen[target - n], i]\n        seen[n] = i\n    return None\n"
    obj = _call(_payload("typing_clean", "two sum", "two_sum", code))
    _schema(obj)
    _assert(obj["verdict"] == "clean", f"typing import false positive: {obj}")


def test_clean_name_main_guard() -> None:
    code = "def valid_parentheses(s):\n    stack = []\n    pairs = {')':'(', ']':'[', '}':'{'}\n    for ch in s:\n        if ch in pairs.values():\n            stack.append(ch)\n        elif ch in pairs:\n            if not stack or stack.pop() != pairs[ch]:\n                return False\n    return not stack\n\nif __name__ == '__main__':\n    print(valid_parentheses('()'))\n"
    obj = _call(_payload("main_guard_clean", "valid parentheses", "valid_parentheses", code))
    _schema(obj)
    _assert(obj["verdict"] == "clean", f"__name__ guard false positive: {obj}")


def test_explicit_boolean_examples_true_false() -> None:
    code = "def is_even(n):\n    return n % 2 == 1\n"
    payload = _payload("bool_examples", "is_even(2) -> true\nis_even(3) -> false", "is_even", code)
    obj = _call(payload)
    _schema(obj)
    _assert(obj["verdict"] == "buggy", "boolean explicit example detected")
    _assert(obj["bugs"][0]["type"] in runner.ALLOWED_TYPES, "boolean example bug type")


def test_nested_only_task_id() -> None:
    nested = {
        "task_id": "nested_only_id",
        "code": "def valid_parentheses(s):\n    return s == '' or s == '()'\n",
        "constraints": {"entry_function": "valid_parentheses"},
    }
    obj = _call({"task_description": "valid parentheses", "code_author_output": json.dumps(nested)})
    _schema(obj)
    _assert(obj["task_id"] == "nested_only_id", "nested-only task_id preserved")


def test_clean_kth_smallest_valid_constraints_no_empty_probe() -> None:
    code = "def kth_smallest(nums, k):\n    return sorted(nums)[k - 1]\n"
    payload = _payload("kth_clean", "kth smallest", "kth_smallest", code)
    payload["constraints"] = {"entry_function": "kth_smallest", "precondition": "1 <= k <= len(nums)"}
    obj = _call(payload)
    _schema(obj)
    _assert(obj["verdict"] == "clean", f"kth_smallest invalid empty probe false positive: {obj}")


def test_clean_factorial_nonnegative_constraints_no_negative_probe() -> None:
    code = "import math\ndef factorial(n):\n    return math.factorial(n)\n"
    payload = _payload("fact_clean", "factorial", "factorial", code)
    payload["constraints"] = {"entry_function": "factorial", "precondition": "n >= 0"}
    obj = _call(payload)
    _schema(obj)
    _assert(obj["verdict"] == "clean", f"factorial negative probe false positive: {obj}")


def test_factorial_negative_allowed_can_report_bug() -> None:
    code = "import math\ndef factorial(n):\n    return math.factorial(n)\n"
    obj = _call(_payload("fact_negative", "factorial should handle negative input", "factorial", code))
    _schema(obj)
    _assert(obj["verdict"] == "buggy", "negative input bug should be reportable when requested")


def test_mixed_clean_preserved() -> None:
    payload = _payload("cand_clean", "identity", "solution", "def solution(x):\n    return x\n")
    obj = _mixed(payload, {"verdict": "clean", "bugs": [], "confidence": 0.66})
    _schema(obj)
    _assert(obj["task_id"] == "cand_clean", "candidate clean task_id")
    _assert(obj["verdict"] == "clean" and obj["bugs"] == [], "candidate clean normalized")


def test_mixed_bug_preserved_and_sanitized() -> None:
    payload = _payload("cand_bug", "identity", "solution", "def solution(x):\n    return x + 1\n")
    report = {"task_id": "wrong", "verdict": "buggy", "bugs": [{"line_start": 2, "line_end": 2, "severity": "high", "type": "logic_error", "description": "Returns x plus one instead of x.", "suggested_fix": "Return x unchanged."}], "confidence": 0.8}
    obj = _mixed(payload, report)
    _schema(obj)
    _assert(obj["task_id"] == "cand_bug", "candidate bug task_id from payload")
    _assert(obj["verdict"] == "buggy" and len(obj["bugs"]) == 1, "candidate bug normalized")
    _assert(obj["bugs"][0]["line_start"] == 2 and obj["bugs"][0]["line_end"] == 2, "candidate bug line preserved")
    _assert(obj["bugs"][0]["type"] == "logic_error" and obj["bugs"][0]["severity"] == "high", "candidate enum preserved")


def test_mixed_invalid_enum_normalized() -> None:
    payload = _payload("cand_enum", "identity", "solution", "def solution(x):\n    return x + 1\n")
    report = {"verdict": "buggy", "bugs": [{"line_start": 2, "line_end": 2, "severity": "severe", "type": "bad_type", "description": "Returns the wrong value for normal input.", "suggested_fix": "Return the input value."}], "confidence": 0.8}
    obj = _mixed(payload, report)
    _schema(obj)
    _assert(obj["bugs"][0]["type"] == "logic_error", "invalid type normalized")
    _assert(obj["bugs"][0]["severity"] == "medium", "invalid severity normalized")


def test_mixed_line_clamp() -> None:
    payload = _payload("cand_lines", "identity", "solution", "def solution(x):\n    return x\n")
    report = {"verdict": "buggy", "bugs": [{"line_start": 99, "line_end": 120, "severity": "high", "type": "logic_error", "description": "Concrete wrong return behavior.", "suggested_fix": "Change the return expression."}], "confidence": 0.8}
    obj = _mixed(payload, report)
    _schema(obj)
    _assert(obj["bugs"][0]["line_start"] == 2 and obj["bugs"][0]["line_end"] == 2, "line clamp upper")


def test_mixed_placeholder_filtered() -> None:
    payload = _payload("cand_placeholder", "binary search", "binary_search", "def binary_search(arr, target):\n    return -1\n")
    report = {"verdict": "buggy", "bugs": [{"line_start": 1, "line_end": 1, "severity": "high", "type": "logic_error", "description": "Fails for ['arr', 'target'] placeholder input.", "suggested_fix": "Handle ['arr', 'target']."}], "confidence": 0.9}
    obj = _mixed(payload, report)
    _schema(obj)
    _assert(obj["verdict"] == "clean" and obj["bugs"] == [], "placeholder report filtered")


def test_mixed_self_negating_bug_filtered() -> None:
    payload = _payload("cand_self_negating", "identity", "solution", "def solution(x):\n    return x\n")
    report = {"verdict": "buggy", "bugs": [{"line_start": 2, "line_end": 2, "severity": "high", "type": "logic_error", "description": "I cannot find a concrete bug, so I will return clean.", "suggested_fix": "No fix needed."}], "confidence": 0.8}
    obj = _mixed(payload, report)
    _schema(obj)
    _assert(obj["verdict"] == "clean" and obj["bugs"] == [], "self-negating bug report filtered")


def test_mixed_speculative_bug_filtered() -> None:
    payload = _payload("cand_speculative", "identity", "solution", "def solution(x):\n    return x\n")
    report = {"verdict": "buggy", "bugs": [{"line_start": 2, "line_end": 2, "severity": "medium", "type": "logic_error", "description": "This might potentially parse incorrectly or similar depending on the characters.", "suggested_fix": "Make the implementation more robust."}], "confidence": 0.7}
    obj = _mixed(payload, report)
    _schema(obj)
    _assert(obj["verdict"] == "clean" and obj["bugs"] == [], "speculative report filtered")


def test_mixed_parser_delimiter_hint_normalized() -> None:
    code = "def split_record(line):\n    fields = []\n    cur = ''\n    for c in line:\n        if c == ',':\n            fields.append(cur)\n            cur = ''\n        else:\n            cur += c\n    fields.append(cur)\n    return fields\n"
    payload = _payload("parser_delimiter", "Parse quoted records where commas inside quotes are data, not separators.", "split_record", code)
    report = {"verdict": "buggy", "bugs": [{"line_start": 4, "line_end": 4, "severity": "high", "type": "logic_error", "description": "The parser treats commas inside quoted fields as delimiters and splits them incorrectly.", "suggested_fix": "Track quote state and only split on comma delimiters outside quotes."}], "confidence": 0.9}
    obj = _mixed(payload, report)
    _schema(obj)
    _assert(obj["verdict"] == "buggy", "parser delimiter bug preserved")
    _assert(obj["bugs"][0]["line_start"] == 5 and obj["bugs"][0]["line_end"] == 9, f"parser delimiter line range normalized: {obj}")
    _assert(obj["bugs"][0]["type"] == "unhandled_input", "parser delimiter type normalized")


def test_mixed_ordinal_index_hint_normalized() -> None:
    code = "def nth_item(items, k):\n    if not items:\n        return None\n    return sorted(items)[k]\n"
    payload = _payload("ordinal_index", "Return the k-th item using 1-based k; k=1 returns the first item.", "nth_item", code)
    report = {"verdict": "buggy", "bugs": [{"line_start": 3, "line_end": 3, "severity": "high", "type": "logic_error", "description": "This treats 1-based k as a 0-based index. For k=1 it returns index 1 instead of index 0, and k=len(items) is out of range.", "suggested_fix": "Use sorted(items)[k-1]."}], "confidence": 0.9}
    obj = _mixed(payload, report)
    _schema(obj)
    _assert(obj["verdict"] == "buggy", "ordinal indexing bug preserved")
    _assert(obj["bugs"][0]["line_start"] == 4 and obj["bugs"][0]["line_end"] == 4, f"ordinal index line normalized: {obj}")
    _assert(obj["bugs"][0]["type"] == "off_by_one", "ordinal index type normalized")


def test_mixed_impossible_continue_claim_filtered() -> None:
    payload = _payload("cand_continue", "loop parser", "solution", "def solution(s):\n    i = 0\n    while i < len(s):\n        if s[i] == 'x':\n            i += 2\n            continue\n        i += 1\n    return s\n")
    report = {"verdict": "buggy", "bugs": [{"line_start": 5, "line_end": 5, "severity": "high", "type": "logic_error", "description": "When continue executes, the outer loop also increments at the end, causing a double-increment.", "suggested_fix": "Avoid the double increment."}], "confidence": 0.8}
    obj = _mixed(payload, report)
    _schema(obj)
    _assert(obj["verdict"] == "clean" and obj["bugs"] == [], "impossible continue claim filtered")


def test_candidate_report_parse_fail_clean_fallback() -> None:
    payload = _payload("cand_parse_fail", "identity", "solution", "def solution(x):\n    return x\n")
    obj = _mixed(payload, "not valid json")
    _schema(obj)
    _assert(obj["verdict"] == "clean" and obj["bugs"] == [], "parse fail clean fallback")
    _assert(0.5 <= obj["confidence"] <= 0.6, "parse fail confidence")


def test_mixed_clean_not_overridden_by_deterministic_oracle() -> None:
    code = "def merge_intervals(intervals):\n    intervals = sorted(intervals, key=lambda x: x[0])\n    merged = []\n    for start, end in intervals:\n        if not merged or start >= merged[-1][1]:\n            merged.append([start, end])\n        else:\n            merged[-1][1] = max(merged[-1][1], end)\n    return merged\n"
    payload = _payload(
        "mixed_clean_not_overridden",
        "Implement merge_intervals(intervals): merge overlapping intervals. Touching intervals such as [1,4] and [4,5] should be merged.",
        "merge_intervals",
        code,
    )
    obj = _mixed(payload, {"verdict": "clean", "bugs": [], "confidence": 0.75})
    _schema(obj)
    _assert(obj["task_id"] == "mixed_clean_not_overridden", "task id preserved")
    _assert(obj["verdict"] == "clean" and obj["bugs"] == [], "mixed clean must not be overridden by legacy oracle")


def test_legacy_payload_only_still_works() -> None:
    code = "def merge_intervals(intervals):\n    intervals = sorted(intervals, key=lambda x: x[0])\n    merged = []\n    for start, end in intervals:\n        if not merged or start >= merged[-1][1]:\n            merged.append([start, end])\n        else:\n            merged[-1][1] = max(merged[-1][1], end)\n    return merged\n"
    payload = _payload(
        "legacy_payload_only",
        "Implement merge_intervals(intervals): merge overlapping intervals. Touching intervals such as [1,4] and [4,5] should be merged.",
        "merge_intervals",
        code,
    )
    obj = _call(payload)
    _schema(obj)
    _assert(obj["task_id"] == "legacy_payload_only", "legacy task id preserved")
    _assert(obj["verdict"] == "buggy", "legacy payload-only deterministic fallback still works")


def main() -> int:
    tests = [name for name in globals() if name.startswith("test_")]
    failures = []
    for name in sorted(tests):
        try:
            globals()[name]()
        except Exception as exc:
            failures.append({"name": name, "error": f"{type(exc).__name__}: {exc}"})
    out = {"ok": not failures, "passed": len(tests) - len(failures), "failed": len(failures), "failures": failures}
    sys.stdout.write(json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
