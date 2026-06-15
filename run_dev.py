#!/usr/bin/env python3
"""Local dev-set runner for file-based AIASE results.

Supports Basic Track and Pairwise Track roles while keeping compatibility helpers
used by the repository tests.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
import tempfile
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aiase_contract as contract


REPO_ROOT = Path(__file__).resolve().parent
RESULTS_DIR = REPO_ROOT / "dev_run_results"
HERMES_BASE = ["hermes", "chat", "--toolsets", "skills,terminal", "--yolo", "-Q"]
RUN_DEV_DEBUG_ENABLED = False


def log_progress(message: str) -> None:
    if not RUN_DEV_DEBUG_ENABLED:
        return
    timestamp = time.strftime("%H:%M:%S")
    print(f"[run_dev {timestamp}] {message}", file=sys.stderr, flush=True)


def make_debug_dir(debug: bool, debug_dir: str | None, skill: str | None) -> Path | None:
    global RUN_DEV_DEBUG_ENABLED
    RUN_DEV_DEBUG_ENABLED = bool(debug)
    if not debug:
        return None
    if debug_dir:
        path = Path(debug_dir)
    else:
        RESULTS_DIR.mkdir(exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        safe_skill = skill or "unknown"
        safe_skill = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in safe_skill)
        path = RESULTS_DIR / f"debug_{stamp}_{safe_skill}"
    path.mkdir(parents=True, exist_ok=True)
    print(f"[run_dev debug] debug_dir={path}")
    return path


@dataclass
class TaskResult:
    task_id: str
    passed: bool
    reason: str = ""
    sql_returned: str = ""
    elapsed_sec: float = 0.0
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass
class TrackReport:
    track: str
    skill: str
    role: str = ""
    total: int = 0
    passed: int = 0
    results: list[TaskResult] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict:
        obj = asdict(self)
        obj["pass_rate"] = self.passed / self.total if self.total else 0.0
        return obj


def bag_equal(rows_a, rows_b) -> bool:
    """Backward-compatible helper: row order ignored, column order significant."""
    return Counter(tuple(r) for r in rows_a) == Counter(tuple(r) for r in rows_b)


def run_sql(db_path: str, sql: str):
    return contract.run_sql(str(db_path), sql)


def is_read_only_sql(sql: str) -> tuple[bool, str]:
    text = str(sql or "").strip().rstrip(";").strip()
    if not text:
        return False, "empty sql"
    if ";" in text:
        return False, "multiple statements"
    upper = text.upper()
    if not upper.startswith("SELECT"):
        return False, "not a SELECT"
    forbidden = {
        "INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER", "ATTACH",
        "DETACH", "REPLACE", "TRUNCATE", "VACUUM", "PRAGMA",
    }
    for token in upper.replace("(", " ").replace(")", " ").split():
        if token in forbidden:
            return False, f"forbidden keyword: {token}"
    return True, ""


def extract_last_json_block(text):
    if not isinstance(text, str):
        return None
    import re
    matches = re.findall(r"```json\s*(.*?)\s*```", text, flags=re.IGNORECASE | re.DOTALL)
    for body in reversed(matches):
        try:
            obj = json.loads(body)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def _extract_first_json_object(text: str) -> dict | None:
    if not isinstance(text, str):
        return None
    decoder = json.JSONDecoder()
    for idx, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[idx:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def read_result_or_stdout(path: str, stdout_text: str) -> dict | None:
    obj = contract.read_result(path)
    if obj is not None:
        return obj
    # Local-dev compatibility for stale Hermes skill runners that still print JSON.
    return extract_last_json_block(stdout_text) or _extract_first_json_object(stdout_text)


def load_basic_tasks() -> list[dict]:
    base = REPO_ROOT / "dev_set" / "basic"
    tasks = []
    for path in sorted(base.glob("*.json")):
        with path.open(encoding="utf-8") as f:
            task = json.load(f)
        dbp = task.get("db_path", "")
        if dbp and not os.path.isabs(dbp) and not dbp.startswith("dev_set/"):
            task["db_path"] = os.path.join("dev_set", "basic", dbp)
        tasks.append(task)
    return tasks


def _infer_track(path: str, task: dict) -> str:
    if task.get("track"):
        return str(task["track"])
    parts = set(Path(path).parts)
    if "pairwise" in parts:
        return "pairwise"
    return "basic"


def load_tasks(dev_dir: str, track: str | None) -> list[dict]:
    root = os.path.dirname(os.path.abspath(dev_dir))
    tasks = []
    for path in sorted(glob.glob(os.path.join(dev_dir, "**", "*.json"), recursive=True)):
        if path.endswith("_GROUND_TRUTH.json"):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                task = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        file_track = _infer_track(path, task)
        if track and file_track != track:
            continue
        task["track"] = file_track
        task["_source_path"] = path
        dbp = task.get("db_path", "")
        if dbp and not os.path.isabs(dbp):
            task["db_path"] = os.path.join(root, dbp)
        tasks.append(task)
    return tasks


def load_reference_ground_truth(task_id: str, dev_dir: str) -> dict | None:
    base = Path(dev_dir) / "pairwise" / "reference_tasks"
    for path in (base / f"{task_id}_GROUND_TRUTH.json", base / f"{task_id}.json"):
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return None
            data.setdefault("bugs", data.get("bugs_in_buggy", []))
            return data
    return None


def build_skill_input(payload: dict) -> str:
    drop = {"gold_sql", "db_path", "seed_sql", "track", "_source_path"}
    return json.dumps({k: v for k, v in payload.items() if k not in drop}, ensure_ascii=False)


def invoke_skill(
    skill: str,
    payload: dict,
    result_path: str,
    model: str | None,
    debug_dir: Path | None = None,
    debug_name: str | None = None,
) -> tuple[int, str, float]:
    env = dict(os.environ)
    env["AIASE_RESULT_PATH"] = result_path
    query = f"/{skill} {build_skill_input(payload)}"
    cmd = list(HERMES_BASE)
    if model:
        cmd += ["-m", model]
    cmd += ["-q", query]
    task_id = payload.get("task_id", "<missing>")
    log_progress(f"invoke start skill={skill} task_id={task_id} result_path={result_path}")
    t0 = time.time()
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, encoding="utf-8")
    elapsed = time.time() - t0
    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    outerr = stdout + stderr
    log_progress(f"invoke done skill={skill} task_id={task_id} returncode={proc.returncode} elapsed={elapsed:.2f}s")

    if debug_dir is not None:
        safe = debug_name or str(payload.get("task_id", "unknown"))
        safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in safe)
        task_debug_dir = debug_dir / safe
        task_debug_dir.mkdir(parents=True, exist_ok=True)

        (task_debug_dir / "payload.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (task_debug_dir / "query.txt").write_text(query, encoding="utf-8")
        (task_debug_dir / "cmd.json").write_text(
            json.dumps(cmd, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (task_debug_dir / "env.txt").write_text(
            f"AIASE_RESULT_PATH={result_path}\n",
            encoding="utf-8",
        )
        (task_debug_dir / "stdout.log").write_text(stdout, encoding="utf-8")
        (task_debug_dir / "stderr.log").write_text(stderr, encoding="utf-8")
        (task_debug_dir / "combined.log").write_text(outerr, encoding="utf-8")
        (task_debug_dir / "result_path.txt").write_text(str(result_path) + "\n", encoding="utf-8")

        result_exists = os.path.exists(result_path)
        if result_exists:
            try:
                with open(result_path, encoding="utf-8") as f:
                    result_text = f.read()
            except OSError as exc:
                result_text = f"<failed to read result file: {exc}>"
        else:
            result_text = "<NO RESULT FILE>"

        (task_debug_dir / "result_file.txt").write_text(result_text, encoding="utf-8")
        (task_debug_dir / "summary.json").write_text(
            json.dumps(
                {
                    "skill": skill,
                    "task_id": payload.get("task_id"),
                    "returncode": proc.returncode,
                    "elapsed_sec": elapsed,
                    "result_path": result_path,
                    "result_exists": result_exists,
                    "stdout_len": len(stdout),
                    "stderr_len": len(stderr),
                    "combined_len": len(outerr),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    return proc.returncode, outerr, elapsed


def _debug_task_dir(debug_dir: Path | None, debug_name: str) -> str:
    if debug_dir is None:
        return ""
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in debug_name)
    return str(debug_dir / safe)


def _failure_extras(rc: int, result_path: str, debug_dir: Path | None, debug_name: str, outerr: str) -> dict[str, Any]:
    return {
        "returncode": rc,
        "result_path": result_path,
        "result_exists": os.path.exists(result_path),
        "debug_dir": _debug_task_dir(debug_dir, debug_name),
        "outerr_tail": outerr[-2000:],
    }


def grade_basic(skill_name: str, dev_dir: str, only_task: str | None, limit: int, model: str | None, debug_dir: Path | None = None) -> TrackReport:
    report = TrackReport(track="basic", skill=skill_name)
    tasks = load_tasks(dev_dir, "basic")
    tasks = [t for t in tasks if "gold_sql" in t and "db_path" in t]
    if only_task:
        tasks = [t for t in tasks if t.get("task_id") == only_task]
    if limit:
        tasks = tasks[:limit]
    report.total = len(tasks)
    log_progress(f"basic start skill={skill_name} tasks={report.total} dev_dir={dev_dir} limit={limit or 'all'}")
    if not tasks:
        report.note = "no basic tasks loaded"
        return report

    tmpdir = tempfile.mkdtemp(prefix="aiase_dev_basic_")
    log_progress(f"basic tempdir={tmpdir}")
    for idx, task in enumerate(tasks, 1):
        task_id = task.get("task_id", "<missing>")
        log_progress(f"basic task {idx}/{len(tasks)} start task_id={task_id}")
        result_path = os.path.join(tmpdir, f"{task_id}.json")
        payload = {
            "task_id": task_id,
            "question": task.get("question", ""),
            "db_schema": task.get("db_schema", ""),
            "dialect": task.get("dialect", "sqlite"),
        }
        debug_name = f"basic_{task_id}"
        rc, outerr, elapsed = invoke_skill(skill_name, payload, result_path, model, debug_dir, debug_name)
        obj = read_result_or_stdout(result_path, outerr)
        if obj is None:
            report.results.append(TaskResult(task_id, False, "no result file / invalid json", elapsed_sec=elapsed, extras=_failure_extras(rc, result_path, debug_dir, debug_name, outerr)))
            log_progress(f"basic task {idx}/{len(tasks)} done task_id={task_id} passed=False reason=no-result elapsed={elapsed:.2f}s")
            continue
        ok, reason = contract.validate_basic_schema(obj, task_id)
        if not ok:
            report.results.append(TaskResult(task_id, False, f"schema invalid: {reason}", elapsed_sec=elapsed, extras=_failure_extras(rc, result_path, debug_dir, debug_name, outerr)))
            log_progress(f"basic task {idx}/{len(tasks)} done task_id={task_id} passed=False reason=schema-invalid elapsed={elapsed:.2f}s")
            continue
        student_sql = obj.get("sql", "")
        try:
            got = contract.run_sql(str(task["db_path"]), student_sql)
            gold = contract.run_sql(str(task["db_path"]), task["gold_sql"])
        except Exception as exc:
            report.results.append(TaskResult(task_id, False, f"SQL execution failed: {exc}", student_sql, elapsed))
            log_progress(f"basic task {idx}/{len(tasks)} done task_id={task_id} passed=False reason=sql-exec elapsed={elapsed:.2f}s")
            continue
        passed = contract.bag_equal(got, gold)
        report.results.append(TaskResult(
            task_id,
            passed,
            "result set matches gold (bag-equal)" if passed else "result set differs from gold",
            student_sql,
            elapsed,
            {"student_rowcount": len(got), "gold_rowcount": len(gold)},
        ))
        log_progress(f"basic task {idx}/{len(tasks)} done task_id={task_id} passed={passed} elapsed={elapsed:.2f}s")
    report.passed = sum(1 for r in report.results if r.passed)
    log_progress(f"basic done skill={skill_name} passed={report.passed}/{report.total}")
    return report


def _bug_set_from_obj(obj: dict) -> set[tuple[int, str]]:
    out = set()
    for bug in obj.get("bugs", []) or []:
        try:
            out.add((int(bug.get("line_start")), str(bug.get("type", "")).strip()))
        except (TypeError, ValueError):
            continue
    return out


def _run_code_test_cases(code: str, constraints: dict, test_cases: list[dict]) -> tuple[int, int]:
    entry = constraints.get("entry_function", "")
    if not entry or not code:
        return 0, len(test_cases)
    ns: dict[str, Any] = {}
    try:
        exec(compile(code, "<student_code>", "exec"), ns)
    except Exception:
        return 0, len(test_cases)
    fn = ns.get(entry)
    if not callable(fn):
        return 0, len(test_cases)
    passed = 0
    for case in test_cases:
        args = case.get("input", [])
        expected = case.get("expected")
        try:
            got = fn(*args) if isinstance(args, list) else fn(args)
            if got == expected:
                passed += 1
        except Exception:
            pass
    return passed, len(test_cases) - passed


def _pairwise_tasks(dev_dir: str, only_task: str | None, limit: int) -> list[dict]:
    tasks = load_tasks(dev_dir, "pairwise")
    tasks = [t for t in tasks if "reference_tasks" in str(t.get("_source_path", ""))]
    if only_task:
        tasks = [t for t in tasks if t.get("task_id") == only_task]
    if limit:
        tasks = tasks[:limit]
    return tasks


def grade_pairwise(skill_name: str, role: str, dev_dir: str, only_task: str | None, limit: int, model: str | None, debug_dir: Path | None = None) -> TrackReport:
    report = TrackReport(track="pairwise", skill=skill_name, role=role)
    tasks = _pairwise_tasks(dev_dir, only_task, limit)
    report.total = len(tasks)
    log_progress(f"pairwise start skill={skill_name} role={role} tasks={report.total} dev_dir={dev_dir} limit={limit or 'all'}")
    if not tasks:
        report.note = "no pairwise reference tasks loaded"
        return report
    tmpdir = tempfile.mkdtemp(prefix="aiase_dev_pairwise_")
    log_progress(f"pairwise tempdir={tmpdir}")

    if role == "code-author":
        for idx, task in enumerate(tasks, 1):
            task_id = task["task_id"]
            log_progress(f"pairwise code-author task {idx}/{len(tasks)} start task_id={task_id}")
            result_path = os.path.join(tmpdir, f"{task_id}.json")
            payload = {
                "task_id": task_id,
                "task_description": task.get("task_description", ""),
                "constraints": task.get("constraints", {}),
                "samples": task.get("test_cases", [])[:3],
            }
            debug_name = f"pairwise_code_author_{task_id}"
            rc, outerr, elapsed = invoke_skill(skill_name, payload, result_path, model, debug_dir, debug_name)
            obj = read_result_or_stdout(result_path, outerr)
            if obj is None or obj.get("task_id") != task_id or "code" not in obj:
                if not os.path.exists(result_path):
                    reason = "contract violation: missing result file"
                elif obj is None:
                    reason = "contract violation: invalid json"
                elif obj.get("task_id") != task_id:
                    reason = "contract violation: task_id mismatch"
                else:
                    reason = "contract violation: missing code"
                report.results.append(TaskResult(task_id, False, reason, elapsed_sec=elapsed, extras=_failure_extras(rc, result_path, debug_dir, debug_name, outerr)))
                log_progress(f"pairwise code-author task {idx}/{len(tasks)} done task_id={task_id} passed=False reason=contract elapsed={elapsed:.2f}s")
                continue
            passed_cases, failed_cases = _run_code_test_cases(obj.get("code", ""), task.get("constraints", {}), task.get("test_cases", []))
            passed = failed_cases == 0 and passed_cases == len(task.get("test_cases", []))
            report.results.append(TaskResult(
                task_id,
                passed,
                "" if passed else f"{failed_cases}/{len(task.get('test_cases', []))} hidden-style cases failed",
                elapsed_sec=elapsed,
                extras={"passed_cases": passed_cases, "total_cases": len(task.get("test_cases", []))},
            ))
            log_progress(f"pairwise code-author task {idx}/{len(tasks)} done task_id={task_id} passed={passed} cases={passed_cases}/{len(task.get('test_cases', []))} elapsed={elapsed:.2f}s")
    elif role == "bug-hunter":
        for idx, task in enumerate(tasks, 1):
            task_id = task["task_id"]
            log_progress(f"pairwise bug-hunter task {idx}/{len(tasks)} start task_id={task_id}")
            gt_bugs = _bug_set_from_obj({"bugs": task.get("bugs_in_buggy", task.get("bugs", []))})
            buggy_code = task.get("buggy_code", "")
            clean_code = task.get("clean_code", "")
            if not buggy_code:
                report.results.append(TaskResult(task_id, False, "no ground-truth buggy_code"))
                log_progress(f"pairwise bug-hunter task {idx}/{len(tasks)} done task_id={task_id} passed=False reason=no-buggy-code")
                continue

            result_buggy = os.path.join(tmpdir, f"{task_id}_buggy.json")
            payload = {"task_id": task_id, "task_description": task.get("task_description", ""), "code": buggy_code}
            debug_name_buggy = f"pairwise_bug_hunter_{task_id}_buggy"
            rc_buggy, outerr_buggy, elapsed_buggy = invoke_skill(skill_name, payload, result_buggy, model, debug_dir, debug_name_buggy)
            obj_buggy = read_result_or_stdout(result_buggy, outerr_buggy)
            if obj_buggy is None or obj_buggy.get("task_id") != task_id:
                report.results.append(TaskResult(task_id, False, "contract violation on buggy code", elapsed_sec=elapsed_buggy, extras=_failure_extras(rc_buggy, result_buggy, debug_dir, debug_name_buggy, outerr_buggy)))
                log_progress(f"pairwise bug-hunter task {idx}/{len(tasks)} done task_id={task_id} passed=False reason=buggy-contract elapsed={elapsed_buggy:.2f}s")
                continue
            student_bugs = _bug_set_from_obj(obj_buggy)
            intersection = len(student_bugs & gt_bugs)
            union = len(student_bugs | gt_bugs) or 1
            recall_like = intersection / max(1, len(gt_bugs))

            clean_fp = 0
            elapsed_clean = 0.0
            if clean_code:
                result_clean = os.path.join(tmpdir, f"{task_id}_clean.json")
                clean_payload = dict(payload)
                clean_payload["code"] = clean_code
                debug_name_clean = f"pairwise_bug_hunter_{task_id}_clean"
                _, outerr_clean, elapsed_clean = invoke_skill(skill_name, clean_payload, result_clean, model, debug_dir, debug_name_clean)
                obj_clean = read_result_or_stdout(result_clean, outerr_clean) or {}
                if obj_clean.get("verdict") == "buggy" or obj_clean.get("bugs"):
                    clean_fp = 1
            passed = recall_like >= 0.5 and clean_fp == 0
            report.results.append(TaskResult(
                task_id,
                passed,
                "" if passed else f"recall={recall_like:.2f}, clean_fp={clean_fp}",
                elapsed_sec=elapsed_buggy + elapsed_clean,
                extras={"jaccard": intersection / union, "recall_like": recall_like, "clean_fp": clean_fp},
            ))
            log_progress(f"pairwise bug-hunter task {idx}/{len(tasks)} done task_id={task_id} passed={passed} recall={recall_like:.2f} clean_fp={clean_fp} elapsed={elapsed_buggy + elapsed_clean:.2f}s")
    else:
        report.note = "unknown pairwise role"
    report.passed = sum(1 for r in report.results if r.passed)
    log_progress(f"pairwise done skill={skill_name} role={role} passed={report.passed}/{report.total}")
    return report


def _write_report(report: TrackReport) -> Path:
    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    suffix = f"_{report.role}" if report.role else ""
    out = RESULTS_DIR / f"{report.track}{suffix}_{report.skill}_{stamp}.json"
    out.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def _print_summary(report: TrackReport) -> None:
    label = f"{report.track.upper()} :: {report.skill}"
    if report.role:
        label += f" ({report.role})"
    print(f"\n=== {label} ===")
    if report.note:
        print(f"  note: {report.note}")
    rate = report.passed / report.total * 100 if report.total else 0.0
    print(f"  total: {report.total}  passed: {report.passed}  rate: {rate:.1f}%")
    for item in report.results[:50]:
        mark = "[PASS]" if item.passed else "[FAIL]"
        print(f"   {mark} {item.task_id}  {item.reason}")
    if len(report.results) > 50:
        print(f"   ... ({len(report.results) - 50} more)")


def run(skill, dev_dir, only_task, track, limit, model, dry_run=False, dry_result_file=None, role="", invoke=invoke_skill, debug_dir: Path | None = None):
    # Compatibility entry point for older tests; non-dry normal runs use the richer graders.
    if dry_run:
        tasks = load_tasks(dev_dir, track)
        if only_task:
            tasks = [t for t in tasks if t["task_id"] == only_task]
        results = []
        for task in tasks[: limit or None]:
            obj = contract.read_result(dry_result_file)
            passed = obj is not None and obj.get("task_id") == task.get("task_id")
            results.append({"task_id": task.get("task_id"), "passed": passed, "detail": "dry-run result checked"})
        return {"total": len(results), "passed": sum(1 for r in results if r["passed"]), "results": results}
    if track == "pairwise":
        report = grade_pairwise(skill, role or "code-author", dev_dir, only_task, limit, model, debug_dir)
    else:
        report = grade_basic(skill, dev_dir, only_task, limit, model, debug_dir)
    _print_summary(report)
    return report.to_dict()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skill", help="skill name, e.g. text2sql-<GITHUBID>")
    parser.add_argument("--track", default="basic", choices=["basic", "pairwise"], help="basic | pairwise")
    parser.add_argument("--role", default="", choices=["", "code-author", "bug-hunter"], help="required when --track pairwise")
    parser.add_argument("--limit", type=int, default=0, help="only run the first N tasks")
    parser.add_argument("--task", dest="only_task", default=None)
    parser.add_argument("--model", default=None, help="override model")
    parser.add_argument("--dev-dir", default=str(REPO_ROOT / "dev_set"))
    parser.add_argument("--dry-run", action="store_true", help="do not invoke hermes; validate --result-file")
    parser.add_argument("--result-file", dest="dry_result_file", default=None)
    parser.add_argument("--debug", action="store_true", help="write per-task debug logs")
    parser.add_argument("--debug-dir", default=None, help="directory for debug logs")
    args = parser.parse_args()

    if not args.dry_run and not args.skill:
        parser.error("--skill is required unless --dry-run")
    if args.dry_run and not args.dry_result_file:
        parser.error("--dry-run requires --result-file")
    if args.track == "pairwise" and not args.role:
        parser.error("--role is required when --track pairwise")

    debug_dir = make_debug_dir(args.debug, args.debug_dir, args.skill)

    if args.dry_run:
        summary = run(args.skill or "", args.dev_dir, args.only_task, args.track, args.limit, args.model, True, args.dry_result_file, args.role)
        return 0 if summary["total"] and summary["passed"] == summary["total"] else 1
    if args.track == "basic":
        report = grade_basic(args.skill, args.dev_dir, args.only_task, args.limit, args.model, debug_dir)
    else:
        report = grade_pairwise(args.skill, args.role, args.dev_dir, args.only_task, args.limit, args.model, debug_dir)
    _print_summary(report)
    out = _write_report(report)
    print(f"\nreport written to: {out.relative_to(REPO_ROOT)}")
    return 0 if report.total and report.passed == report.total else 1


if __name__ == "__main__":
    sys.exit(main())
