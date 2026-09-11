"""Tests for run_dev output contract parsing and fallback recovery."""

import json
from pathlib import Path

import run_dev
from run_dev import extract_last_json_block, recover_fallback_result


def test_basic_single_block():
    s = '''some preface
```json
{"task_id": "x", "sql": "SELECT 1"}
```
'''
    obj = extract_last_json_block(s)
    assert obj == {"task_id": "x", "sql": "SELECT 1"}


def test_multiple_blocks_takes_last():
    s = '''first attempt:
```json
{"task_id": "x", "sql": "SELECT bad"}
```
revision:
```json
{"task_id": "x", "sql": "SELECT good"}
```
'''
    obj = extract_last_json_block(s)
    assert obj == {"task_id": "x", "sql": "SELECT good"}


def test_no_fence_returns_none():
    assert extract_last_json_block("just prose, no JSON") is None
    assert extract_last_json_block("```python\nprint(1)\n```") is None


def test_invalid_json_returns_none():
    s = "```json\n{not valid json,}\n```"
    assert extract_last_json_block(s) is None


def test_non_object_top_level_returns_none():
    # array at top-level violates spec §1.4 #1
    s = '```json\n[1, 2, 3]\n```'
    assert extract_last_json_block(s) is None
    # plain string also rejected
    s2 = '```json\n"hello"\n```'
    assert extract_last_json_block(s2) is None


def test_case_insensitive_fence():
    s = '```JSON\n{"ok": true}\n```'
    assert extract_last_json_block(s) == {"ok": True}


def test_crlf_line_endings():
    s = "preface\r\n```json\r\n{\"k\": 1}\r\n```\r\n"
    assert extract_last_json_block(s) == {"k": 1}


def test_unicode_content():
    s = '```json\n{"name": "陳小明", "rationale": "中文 OK"}\n```'
    obj = extract_last_json_block(s)
    assert obj["name"] == "陳小明"


def test_none_input():
    assert extract_last_json_block(None) is None  # type: ignore[arg-type]
    assert extract_last_json_block(123) is None  # type: ignore[arg-type]


def test_recover_fallback_result(tmp_path):
    fallback = tmp_path / "aiase_result.json"
    expected = tmp_path / "results" / "task_001.json"
    fallback.write_text(json.dumps({"task_id": "task_001", "ok": True}), encoding="utf-8")

    assert recover_fallback_result(str(expected), "task_001", tmp_path)
    assert json.loads(expected.read_text(encoding="utf-8"))["ok"] is True
    assert not fallback.exists()


def test_recover_fallback_ignores_other_tasks(tmp_path):
    fallback = tmp_path / "aiase_result.json"
    expected = tmp_path / "results" / "task_001.json"
    fallback.write_text(json.dumps({"task_id": "task_002"}), encoding="utf-8")

    assert not recover_fallback_result(str(expected), "task_001", tmp_path)
    assert fallback.exists()
    assert not expected.exists()


def test_invoke_skill_retries_once_on_missing_result(tmp_path, monkeypatch):
    result_path = tmp_path / "task_001.json"
    calls = []

    class FakeProcess:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, env):
        calls.append(cmd)
        if len(calls) == 2:
            Path(env["AIASE_RESULT_PATH"]).write_text(
                json.dumps({"task_id": "task_001", "ok": True}),
                encoding="utf-8",
            )
        return FakeProcess()

    monkeypatch.setattr(run_dev, "run_hermes", fake_run)

    returncode, _, _ = run_dev.invoke_skill("example-skill", {"task_id": "task_001"}, str(result_path), None)

    assert returncode == 0
    assert len(calls) == 2


def test_invoke_skill_does_not_retry_valid_result(tmp_path, monkeypatch):
    result_path = tmp_path / "task_001.json"
    calls = []

    class FakeProcess:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, env):
        calls.append(cmd)
        Path(env["AIASE_RESULT_PATH"]).write_text(
            json.dumps({"task_id": "task_001", "ok": True}),
            encoding="utf-8",
        )
        return FakeProcess()

    monkeypatch.setattr(run_dev, "run_hermes", fake_run)

    run_dev.invoke_skill("example-skill", {"task_id": "task_001"}, str(result_path), None)

    assert len(calls) == 1


def test_recover_fallback_rejects_stale_matching_result(tmp_path):
    fallback = tmp_path / "aiase_result.json"
    expected = tmp_path / "results" / "task_001.json"
    fallback.write_text(json.dumps({"task_id": "task_001"}), encoding="utf-8")
    cutoff = fallback.stat().st_mtime_ns + 1

    assert not recover_fallback_result(str(expected), "task_001", tmp_path, cutoff)
    assert fallback.exists()


def test_recover_fallback_replaces_wrong_destination(tmp_path):
    fallback = tmp_path / "aiase_result.json"
    expected = tmp_path / "task_001.json"
    fallback.write_text(json.dumps({"task_id": "task_001", "ok": True}), encoding="utf-8")
    expected.write_text(json.dumps({"task_id": "other"}), encoding="utf-8")

    assert recover_fallback_result(str(expected), "task_001", tmp_path)
    assert json.loads(expected.read_text(encoding="utf-8"))["task_id"] == "task_001"
