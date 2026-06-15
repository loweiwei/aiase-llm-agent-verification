#!/usr/bin/env python3
"""Local regression tests for code-author-loweiwei.

This module is not used by run.py or the skill hot path.
"""

from __future__ import annotations

import ast
import importlib.util
import io
import json
import math
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RUN = ROOT / "run.py"
SKILL = ROOT.parent / "SKILL.md"


def _load_runner():
    spec = importlib.util.spec_from_file_location("code_author_run", RUN)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


runner = _load_runner()


def compute_sloc(code: str) -> int:
    return runner._sloc(code)


def find_import_violations(code: str, forbidden: list[str]) -> list[str]:
    imports, _ = runner._static_checks(code, forbidden)
    return imports


def _call(raw: str, *args: str) -> dict:
    old_stdin, old_stdout = sys.stdin, sys.stdout
    old_result = os.environ.get("AIASE_RESULT_PATH")
    fd, result_path = tempfile.mkstemp(prefix="code_author_selftest_", suffix=".json")
    os.close(fd)
    os.remove(result_path)
    try:
        os.environ["AIASE_RESULT_PATH"] = result_path
        sys.stdin = io.StringIO(raw)
        buf = io.StringIO()
        sys.stdout = buf
        rc = runner.main(["run.py", *args])
        assert rc == 0
        assert buf.getvalue() == ""
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


def _hybrid(payload: dict, code: str) -> dict:
    raw = json.dumps(payload, ensure_ascii=False) + "\n" + runner.CANDIDATE_MARKER + "\n" + code
    return _call(raw, "-")


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def test_invalid_json() -> None:
    obj = _call("{bad", "-")
    _assert(obj["confidence"] == 0.0, "invalid JSON confidence")
    _assert(obj["self_test_results"]["failed"] == 1, "invalid JSON failed")


def test_skill_pitfalls_no_contradiction() -> None:
    text = SKILL.read_text(encoding="utf-8")
    _assert("REPO_ROOT" not in text, "legacy REPO_ROOT remains")
    _assert("git rev-parse" not in text, "legacy git rev-parse remains")
    _assert("$REPO_ROOT/skills/code-author-loweiwei/scripts/run.py" not in text, "legacy repo-root run.py path remains")
    _assert("<skill_dir>/scripts/run.py" in text, "missing skill_dir run.py path")
    _assert(runner.CANDIDATE_MARKER in text, "missing candidate marker")
    _assert("Do not analyze the task." not in text, "contradictory analyze pitfall")
    _assert("Do not hand-write Python code." not in text, "contradictory hand-write pitfall")
    _assert("Do not hand-write the final JSON contract." in text, "missing final JSON pitfall")
    _assert("The only allowed visible action is one terminal call." in text, "missing terminal-only wording")
    _assert("Do not output the JSON contract in chat or stdout." in text, "missing stdout/chat pitfall")
    _assert("After the terminal call completes, stop." in text, "missing stop wording")
    _assert("The grader reads the result file, not stdout or chat text." in text, "missing file-contract wording")


def test_no_legacy_fenced_json_renderer() -> None:
    text = RUN.read_text(encoding="utf-8")
    _assert("_render_fenced_json" not in text, "legacy fenced JSON renderer remains")
    _assert("_sanitize_fences" not in text, "legacy fence sanitizer remains")
    _assert("```json" not in text, "fenced JSON output remains")


def test_cli_direct_contract() -> None:
    code = "def f(x):\n    return x\n"
    obj = _call(
        "",
        "--task_id", "cli",
        "--code", code,
        "--loc", "2",
        "--self_test_passed", "1",
        "--self_test_failed", "0",
        "--rationale", "Identity function.",
        "--confidence", "0.9",
    )
    _assert(obj == {
        "task_id": "cli",
        "code": code,
        "loc": 2,
        "self_test_results": {"passed": 1, "failed": 0},
        "rationale": "Identity function.",
        "confidence": 0.9,
    }, "direct CLI contract normalization")


def test_cli_self_test_results_json() -> None:
    obj = _call(
        "",
        "--task_id", "cli2",
        "--code", "def f(x):\n    return x\n",
        "--loc", "2",
        "--self_test_results", '{"passed":1,"failed":0,"errors":[]}',
        "--rationale", "Identity function.",
        "--confidence", "2.5",
    )
    _assert(obj["self_test_results"] == {"passed": 1, "failed": 0, "errors": []}, "self_test_results JSON parsed")
    _assert(obj["confidence"] == 1.0, "CLI confidence clamped")


def test_cli_payload_candidate_code() -> None:
    payload = {
        "task_id": "cli_payload",
        "task_description": "Implement f(x): return x.",
        "constraints": {"entry_function": "f", "max_loc": 500, "imports_forbidden": ["os", "sys"]},
        "samples": [{"input": [5], "expected": 5}],
    }
    obj = _call(
        "",
        "--payload", json.dumps(payload, ensure_ascii=False),
        "--candidate_code", "def f(x):\n    return x\n",
    )
    _assert(obj["task_id"] == "cli_payload", "payload CLI task id")
    _assert("def f" in obj["code"], "payload CLI candidate selected")
    _assert(obj["self_test_results"]["passed"] == 1, "payload CLI sample passed")


def test_keyword_entry() -> None:
    payload = {"task_id": "kw", "task_description": "Implement two sum.", "constraints": {"entry_function": "class"}}
    obj = _call(json.dumps(payload), "-")
    ast.parse(obj["code"])
    _assert("def solution" in obj["code"], "keyword entry must fall back to solution")


def test_fallback_honest() -> None:
    payload = {"task_id": "fb", "task_description": "invent unknown frobnicator", "constraints": {"entry_function": "frobnicate"}}
    obj = _call(json.dumps(payload), "-")
    _assert(obj["self_test_results"]["failed"] >= 1, "fallback failed count")
    _assert(obj["confidence"] <= 0.1, "fallback confidence")
    _assert("no deterministic template matched" in obj["self_test_results"]["errors"], "fallback error")


def test_unique_paths_large() -> None:
    payload = {
        "task_id": "up",
        "task_description": "Implement unique_paths.",
        "constraints": {"entry_function": "unique_paths"},
    }
    obj = _call(json.dumps(payload), "-")
    _assert("def unique_paths" in obj["code"], "unique_paths selected")
    passed, failed, errors = runner._run_cases(
        obj["code"], "unique_paths", [{"input": [1000, 1000], "expected": math.comb(1998, 999)}]
    )
    _assert(passed == 1 and failed == 0, "unique_paths large correctness")
    _assert(not any("timeout" in e for e in errors), "unique_paths large timed out")


def test_samples_key() -> None:
    payload = {
        "task_id": "samples",
        "task_description": "Implement two sum.",
        "constraints": {"entry_function": "two_sum"},
        "samples": [{"args": [[2, 7], 9], "output": [0, 1]}],
    }
    obj = _call(json.dumps(payload), "-")
    _assert(obj["self_test_results"]["passed"] == 1, "samples key passed")


def test_backward_compatible_template_only() -> None:
    payload = {"task_id": "plain", "task_description": "Implement two sum.", "constraints": {"entry_function": "two_sum"}}
    obj = _call(json.dumps(payload), "-")
    _assert(obj["rationale"] == "deterministic template: two_sum", "template-only compatibility")


def test_candidate_unknown_gcd() -> None:
    payload = {
        "task_id": "unknown_gcd",
        "task_description": "Return the greatest common divisor of two integers.",
        "constraints": {"entry_function": "gcd"},
        "samples": [{"input": [12, 18], "expected": 6}, {"input": [7, 5], "expected": 1}],
    }
    code = "def gcd(a, b):\n    a, b = abs(a), abs(b)\n    while b:\n        a, b = b, a % b\n    return a\n"
    obj = _hybrid(payload, code)
    _assert(obj["rationale"] == "llm_candidate validated by static checks and samples", "gcd candidate selected")
    _assert(obj["self_test_results"]["passed"] == 2, "gcd samples passed")


def test_candidate_without_marker_after_json() -> None:
    payload = {
        "task_id": "unknown_gcd_no_marker",
        "task_description": "Return the greatest common divisor of two integers.",
        "constraints": {"entry_function": "gcd"},
        "samples": [{"input": [12, 18], "expected": 6}],
    }
    raw = json.dumps(payload, ensure_ascii=False) + "\ndef gcd(a, b):\n    a, b = abs(a), abs(b)\n    while b:\n        a, b = b, a % b\n    return a\n"
    obj = _call(raw, "-")
    _assert(obj["task_id"] == "unknown_gcd_no_marker", "task id parsed without marker")
    _assert(obj["rationale"] == "llm_candidate validated by static checks and samples", "candidate without marker selected")
    _assert(obj["self_test_results"]["passed"] == 1, "candidate without marker sample passed")


def test_candidate_beats_fallback_solution() -> None:
    payload = {
        "task_id": "unknown_solution",
        "task_description": "Return x squared plus one.",
        "constraints": {"entry_function": "solution"},
        "samples": [{"input": [3], "expected": 10}],
    }
    obj = _hybrid(payload, "def solution(x):\n    return x * x + 1\n")
    _assert(obj["rationale"] == "llm_candidate validated by static checks and samples", "candidate beats fallback")
    _assert(obj["self_test_results"]["passed"] == 1, "solution candidate sample")


def test_no_sample_ambiguous_search_prefers_llm() -> None:
    payload = {
        "task_id": "ambiguous_search",
        "task_description": "Implement a custom search-like function that returns 42.",
        "constraints": {"entry_function": "search"},
    }
    obj = _hybrid(payload, "def search(x):\n    return 42\n")
    _assert(obj["rationale"].startswith("llm_candidate"), "ambiguous search should prefer llm")
    _assert("return 42" in obj["code"], "ambiguous search code should be candidate")


def test_no_sample_ambiguous_insert_prefers_llm() -> None:
    payload = {
        "task_id": "ambiguous_insert",
        "task_description": "Implement a custom insert-like function.",
        "constraints": {"entry_function": "insert"},
    }
    obj = _hybrid(payload, "def insert(x):\n    return x\n")
    _assert(obj["rationale"].startswith("llm_candidate"), "ambiguous insert should prefer llm")
    _assert("def insert" in obj["code"] and "return x" in obj["code"], "ambiguous insert code should be candidate")


def test_no_sample_valid_candidate_preferred() -> None:
    payload = {
        "task_id": "two_sum_no_sample",
        "task_description": "Implement two sum.",
        "constraints": {"entry_function": "two_sum"},
    }
    obj = _hybrid(payload, "def two_sum(nums, target):\n    return []\n")
    _assert(obj["rationale"].startswith("llm_candidate"), "no-sample valid candidate should be preferred")
    _assert("return []" in obj["code"], "candidate code selected over template")


def test_candidate_first_known_function_modified_semantics() -> None:
    payload = {
        "task_id": "summary_perturb",
        "task_description": "Implement summary_ranges(nums): consecutive range format must be x..y, not x->y.",
        "constraints": {"entry_function": "summary_ranges"},
        "samples": [{"input": [[0, 1, 2, 4, 5, 7]], "expected": ["0..2", "4..5", "7"]}],
    }
    code = "def summary_ranges(nums):\n    out = []\n    i = 0\n    while i < len(nums):\n        start = nums[i]\n        while i + 1 < len(nums) and nums[i + 1] == nums[i] + 1:\n            i += 1\n        end = nums[i]\n        out.append(str(start) if start == end else f'{start}..{end}')\n        i += 1\n    return out\n"
    obj = _hybrid(payload, code)
    _assert(obj["rationale"].startswith("llm_candidate"), "modified semantics candidate should be selected")
    _assert(".." in obj["code"], "candidate dots format preserved")
    _assert(obj["self_test_results"]["passed"] == 1, "modified semantics sample passed")
    _assert(obj["rationale"] != "deterministic template: summary_ranges", "template must not win modified semantics")


def test_candidate_first_known_function_conflicting_template() -> None:
    payload = {
        "task_id": "two_sum_values",
        "task_description": "Implement two_sum(nums, target): return the two values, not indices, whose sum is target.",
        "constraints": {"entry_function": "two_sum"},
        "samples": [{"input": [[2, 7, 11], 9], "expected": [2, 7]}],
    }
    obj = _hybrid(payload, "def two_sum(nums, target):\n    seen = set()\n    for x in nums:\n        if target - x in seen:\n            return [target - x, x]\n        seen.add(x)\n    return []\n")
    _assert(obj["rationale"].startswith("llm_candidate"), "conflicting template candidate should win")
    _assert("seen = set" in obj["code"], "candidate value-return code selected")


def test_template_fallback_when_candidate_invalid() -> None:
    payload = {
        "task_id": "summary_bad_candidate",
        "task_description": "Implement summary_ranges(nums).",
        "constraints": {"entry_function": "summary_ranges"},
        "samples": [{"input": [[0, 1, 2]], "expected": ["0->2"]}],
    }
    obj = _hybrid(payload, "def summary_ranges(nums):\n    return [\n")
    _assert(not obj["rationale"].startswith("llm_candidate validated"), "invalid candidate should not be selected")
    _assert(any("candidate rejected" in e or "syntax" in e for e in obj["self_test_results"]["errors"]), "candidate rejection surfaced")


def test_public_sample_hardcode_rejected_or_warned() -> None:
    payload = {
        "task_id": "hardcode_sample",
        "task_description": "Implement summary_ranges(nums).",
        "constraints": {"entry_function": "summary_ranges"},
        "samples": [{"input": [[0, 1, 2, 4, 5, 7]], "expected": ["0->2", "4->5", "7"]}],
    }
    code = "def summary_ranges(nums):\n    if nums == [0, 1, 2, 4, 5, 7]:\n        return ['0->2', '4->5', '7']\n    return []\n"
    obj = _hybrid(payload, code)
    _assert(not obj["rationale"].startswith("llm_candidate validated"), "hardcoded sample candidate should be rejected or not preferred")
    _assert(any("public sample" in e or "candidate rejected" in e for e in obj["self_test_results"]["errors"]), "hardcode warning surfaced")


def test_cases_key_used_for_template_selection() -> None:
    payload = {
        "task_id": "custom_remove_duplicates_inplace",
        "task_description": "Implement remove_duplicates(nums): remove duplicates from a sorted list in-place and return the number of unique values.",
        "constraints": {"entry_function": "remove_duplicates"},
        "test_cases": [
            {"input": [[]], "expected": 0},
            {"input": [[1]], "expected": 1},
            {"input": [[1, 1, 2]], "expected": 2},
            {"input": [[0, 0, 1, 1, 2]], "expected": 3},
        ],
    }
    obj = _call(json.dumps(payload), "-")
    _assert(obj["rationale"] != "deterministic template: merge_intervals", "merge_intervals template must not be selected")
    _assert(obj["self_test_results"]["failed"] == 0, f"test_cases should pass: {obj}")
    ns = {}
    exec(obj["code"], ns)
    nums = [1, 1, 2]
    got = ns["remove_duplicates"](nums)
    _assert(got == 2, "remove_duplicates returns unique count")
    _assert(nums[:got] == [1, 2], "remove_duplicates mutates prefix in-place")


def test_unrelated_template_not_selected_when_entry_in_desc() -> None:
    score = runner._match_score(runner.TEMPLATES[0], "remove_duplicates", "implement remove duplicates in-place and return count")
    _assert(score == 0, f"unrelated merge_intervals should not score from entry in desc: {score}")


def test_remove_duplicates_inplace_template() -> None:
    payload = {
        "task_id": "remove_dup_invalid_candidate",
        "task_description": "Implement remove_duplicates(nums): remove duplicates from sorted nums in-place and return number of unique values.",
        "constraints": {"entry_function": "remove_duplicates"},
        "test_cases": [
            {"input": [[]], "expected": 0},
            {"input": [[1]], "expected": 1},
            {"input": [[1, 1, 2]], "expected": 2},
            {"input": [[0, 0, 1, 1, 2]], "expected": 3},
        ],
    }
    obj = _hybrid(payload, "def remove_duplicates(nums):\n    return [\n")
    _assert(obj["rationale"] == "deterministic template: remove_duplicates", f"remove_duplicates fallback template selected: {obj['rationale']}")
    _assert(obj["self_test_results"]["failed"] == 0, "remove_duplicates fallback passes test_cases")


def test_no_sample_candidate_compile_exec_error_rejected() -> None:
    payload = {
        "task_id": "no_sample_bad_import",
        "task_description": "Implement an unknown frobnicator.",
        "constraints": {"entry_function": "frobnicate"},
    }
    obj = _hybrid(payload, "import not_a_real_module\ndef frobnicate(x):\n    return x\n")
    _assert(obj["rationale"] != "llm_candidate valid; no public samples", "bad no-sample candidate selected")
    _assert(obj["self_test_results"]["failed"] >= 1, "bad no-sample candidate failed count")
    _assert(any("candidate rejected" in e or "compile/exec" in e for e in obj["self_test_results"]["errors"]), "bad no-sample candidate error surfaced")


def test_imports_allowed_enforced() -> None:
    payload = {"task_id": "allowed0", "task_description": "identity", "constraints": {"entry_function": "solution", "imports_allowed": []}, "samples": [{"input": [9], "expected": 9}]}
    obj = _hybrid(payload, "import math\ndef solution(x):\n    return x\n")
    _assert(obj["rationale"] != "llm_candidate validated by static checks and samples", "disallowed import candidate selected")
    _assert(obj["self_test_results"]["import_violations"], "allowed import violation surfaced")


def test_imports_allowed_permits_math() -> None:
    payload = {"task_id": "allowed_math", "task_description": "sqrt", "constraints": {"entry_function": "solution", "imports_allowed": ["math"]}, "samples": [{"input": [9], "expected": 3.0}]}
    obj = _hybrid(payload, "import math\ndef solution(x):\n    return math.sqrt(x)\n")
    _assert(obj["rationale"] == "llm_candidate validated by static checks and samples", "allowed math candidate rejected")
    _assert(obj["self_test_results"]["passed"] == 1, "allowed math sample")


def test_invalid_candidate_rejected() -> None:
    payload = {"task_id": "badcand", "task_description": "unknown", "constraints": {"entry_function": "solution"}, "samples": [{"input": [1], "expected": 1}]}
    obj = _hybrid(payload, "import os\ndef solution(x):\n    return x\n")
    _assert(obj["rationale"] != "llm_candidate validated by static checks and samples", "bad candidate not selected")
    _assert(any("candidate rejected" in e or "forbidden import" in e or "sandbox" in e for e in obj["self_test_results"]["errors"]), "bad candidate error surfaced")


def test_candidate_print_not_pollute_stdout() -> None:
    payload = {"task_id": "print", "task_description": "identity", "constraints": {"entry_function": "solution"}, "samples": [{"input": [2], "expected": 2}]}
    raw = json.dumps(payload) + "\n" + runner.CANDIDATE_MARKER + "\ndef solution(x):\n    print('bad')\n    return x\n"
    old_stdin, old_stdout = sys.stdin, sys.stdout
    old_result = os.environ.get("AIASE_RESULT_PATH")
    fd, result_path = tempfile.mkstemp(prefix="code_author_selftest_", suffix=".json")
    os.close(fd)
    os.remove(result_path)
    try:
        os.environ["AIASE_RESULT_PATH"] = result_path
        sys.stdin = io.StringIO(raw)
        buf = io.StringIO()
        sys.stdout = buf
        rc = runner.main(["run.py", "-"])
        assert rc == 0
        _assert(buf.getvalue() == "", "print candidate stdout must be empty")
        with open(result_path, encoding="utf-8") as f:
            json.load(f)
    finally:
        sys.stdin = old_stdin
        sys.stdout = old_stdout
        if old_result is None:
            os.environ.pop("AIASE_RESULT_PATH", None)
        else:
            os.environ["AIASE_RESULT_PATH"] = old_result
        if os.path.exists(result_path):
            os.remove(result_path)


def test_top_level_print_rejected() -> None:
    payload = {"task_id": "topprint", "task_description": "identity", "constraints": {"entry_function": "solution"}, "samples": [{"input": [1], "expected": 1}]}
    obj = _hybrid(payload, "print('bad')\ndef solution(x):\n    return x\n")
    _assert(obj["rationale"] != "llm_candidate validated by static checks and samples", "top-level print rejected")
    _assert(any("top-level" in e or "candidate rejected" in e for e in obj["self_test_results"]["errors"]), "top-level rejection error")


def test_top_level_class_rejected() -> None:
    payload = {"task_id": "class", "task_description": "identity", "constraints": {"entry_function": "solution"}, "samples": [{"input": [1], "expected": 1}]}
    obj = _hybrid(payload, "class Bad:\n    while True:\n        pass\ndef solution(x):\n    return x\n")
    _assert(obj["rationale"] != "llm_candidate validated by static checks and samples", "top-level class selected")
    _assert(any("ClassDef" in e or "top-level" in e or "candidate rejected" in e for e in obj["self_test_results"]["errors"]), "class rejection error")


def test_top_level_binop_memory_style_rejected() -> None:
    payload = {"task_id": "binop", "task_description": "identity", "constraints": {"entry_function": "solution"}, "samples": [{"input": [1], "expected": 1}]}
    obj = _hybrid(payload, "BIG = 'x' * 1000000000\ndef solution(x):\n    return x\n")
    _assert(obj["rationale"] != "llm_candidate validated by static checks and samples", "top-level binop selected")
    _assert(any("Assign" in e or "top-level" in e or "candidate rejected" in e for e in obj["self_test_results"]["errors"]), "binop rejection error")


def test_print_rejected() -> None:
    payload = {"task_id": "print_reject", "task_description": "identity", "constraints": {"entry_function": "solution"}, "samples": [{"input": [1], "expected": 1}]}
    obj = _hybrid(payload, "def solution(x):\n    print('bad')\n    return x\n")
    _assert(obj["rationale"] != "llm_candidate validated by static checks and samples", "print candidate selected")
    _assert(any("print" in e or "sandbox" in e or "candidate rejected" in e for e in obj["self_test_results"]["errors"]), "print rejection error")


def test_candidate_infinite_loop_timeout() -> None:
    payload = {"task_id": "loop", "task_description": "identity", "constraints": {"entry_function": "solution"}, "samples": [{"input": [1], "expected": 1}]}
    obj = _hybrid(payload, "def solution(x):\n    while True:\n        pass\n")
    _assert(obj["self_test_results"]["failed"] >= 1, "loop failed")
    _assert(any("timeout" in e for e in obj["self_test_results"]["errors"]), "loop timeout error")


def test_code_fences_stripped() -> None:
    payload = {"task_id": "add", "task_description": "add two numbers", "constraints": {"entry_function": "add"}, "samples": [{"input": [2, 3], "expected": 5}]}
    obj = _hybrid(payload, "```python\ndef add(a, b):\n    return a + b\n")
    _assert(obj["self_test_results"]["passed"] == 1, "code fence stripped")


def test_candidate_triple_backticks_preserved_in_file_json() -> None:
    payload = {"task_id": "ticks", "task_description": "return ticks", "constraints": {"entry_function": "solution"}, "samples": [{"input": [], "expected": "```"}]}
    raw = json.dumps(payload) + "\n" + runner.CANDIDATE_MARKER + "\ndef solution():\n    return '```'\n"
    old_stdin, old_stdout = sys.stdin, sys.stdout
    old_result = os.environ.get("AIASE_RESULT_PATH")
    fd, result_path = tempfile.mkstemp(prefix="code_author_selftest_", suffix=".json")
    os.close(fd)
    os.remove(result_path)
    try:
        os.environ["AIASE_RESULT_PATH"] = result_path
        sys.stdin = io.StringIO(raw)
        buf = io.StringIO()
        sys.stdout = buf
        rc = runner.main(["run.py", "-"])
        assert rc == 0
        _assert(buf.getvalue() == "", "ticks stdout must be empty")
        with open(result_path, encoding="utf-8") as f:
            text = f.read()
        _assert("```" in text, "result JSON preserves code string content")
        json.loads(text)
    finally:
        sys.stdin = old_stdin
        sys.stdout = old_stdout
        if old_result is None:
            os.environ.pop("AIASE_RESULT_PATH", None)
        else:
            os.environ["AIASE_RESULT_PATH"] = old_result
        if os.path.exists(result_path):
            os.remove(result_path)


def test_sample_cases_not_mutated_by_selection() -> None:
    samples = [{"input": [[0, 1, 0, 3, 12]], "expected": [1, 3, 12, 0, 0]}]
    before = json.dumps(samples, sort_keys=True)
    runner._select_template("solution", "move zeroes", samples)
    after = json.dumps(samples, sort_keys=True)
    _assert(before == after, "sample cases mutated during selection")


def test_search_rotated_not_binary_search() -> None:
    payload = {
        "task_id": "rotated",
        "task_description": "Search target in rotated sorted array",
        "constraints": {"entry_function": "search"},
        "samples": [{"input": [[4,5,6,7,0,1,2], 0], "expected": 4}],
    }
    obj = _call(json.dumps(payload), "-")
    _assert("deterministic template: search_rotated" == obj["rationale"], "rotated search selection")
    _assert(obj["self_test_results"]["passed"] == 1, "rotated sample passed")


def test_binary_search_still_selected() -> None:
    payload = {
        "task_id": "binary",
        "task_description": "Binary search sorted array target in log n",
        "constraints": {"entry_function": "binary_search"},
    }
    obj = _call(json.dumps(payload), "-")
    _assert(obj["rationale"] == "deterministic template: binary_search", "binary search selection")


def test_num_islands_int_grid() -> None:
    payload = {
        "task_id": "islands",
        "task_description": "number of islands",
        "constraints": {"entry_function": "num_islands"},
        "samples": [{"input": [[[1,1,0],[0,1,0],[1,0,1]]], "expected": 3}],
    }
    obj = _call(json.dumps(payload), "-")
    _assert(obj["self_test_results"]["passed"] == 1, "int grid islands passed")


def test_valid_palindrome_ii() -> None:
    payload = {
        "task_id": "vp2",
        "task_description": "valid palindrome II delete one character",
        "constraints": {"entry_function": "validPalindrome"},
        "samples": [{"input": ["abca"], "expected": True}, {"input": ["abc"], "expected": False}],
    }
    obj = _call(json.dumps(payload), "-")
    _assert(obj["rationale"] == "deterministic template: valid_palindrome_ii", "validPalindrome II selected")
    _assert(obj["self_test_results"]["passed"] == 2, "validPalindrome II samples")


def test_no_subprocess_import_in_selftest() -> None:
    names = {name for name in globals()}
    _assert("subprocess" not in names, "selftest imported subprocess")


def test_timeout() -> None:
    code = "def spin(x):\n    while True:\n        pass\n"
    passed, failed, errors = runner._run_cases(code, "spin", [{"input": [1], "expected": 1}])
    _assert(passed == 0 and failed == 1, "timeout failed count")
    _assert(any("timeout" in err for err in errors), "timeout error")


def test_templates() -> None:
    for template in runner.TEMPLATES:
        entry = template.aliases[0]
        code = runner._render(entry, template.body)
        passed, failed, errors = runner._run_cases(code, entry, list(template.tests))
        _assert(failed == 0, f"template {template.name} failed: {errors}")
        _assert(runner._sloc(code) <= 500, f"template {template.name} too large")
        imports, sandbox = runner._static_checks(code, [])
        _assert(not imports and not sandbox, f"template {template.name} static violations")


def test_static_checks() -> None:
    imports, sandbox = runner._static_checks("import os\ndef f():\n    open('x')\n", ["os"])
    _assert("os" in imports, "forbidden import")
    _assert("os" in sandbox and "open" in sandbox, "sandbox calls")
    _, sandbox2 = runner._static_checks("def f(x):\n    importlib.import_module('os')\n", [])
    _assert("importlib.import_module" in sandbox2 or "import_module" in sandbox2, "importlib call")


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
