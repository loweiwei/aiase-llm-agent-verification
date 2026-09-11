#!/usr/bin/env python3
"""Run offline checks and write one machine-readable evidence artifact."""

from __future__ import annotations

import datetime as dt
import json
import platform
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts" / "verification.json"
COMMANDS = [
    ("pytest", [sys.executable, "-m", "pytest", "-q"]),
    ("code_author_selftest", [sys.executable, "skills/code-author-loweiwei/scripts/selftest.py"]),
    ("bug_hunter_selftest", [sys.executable, "skills/bug-hunter-loweiwei/scripts/selftest.py"]),
    ("open_selftest", [sys.executable, "skills/open-test-killer-loweiwei/scripts/selftest.py"]),
    ("code_author_regression", [sys.executable, "skills/code-author-loweiwei/scripts/regression.py"]),
    ("bug_hunter_regression", [sys.executable, "skills/bug-hunter-loweiwei/scripts/regression.py"]),
    ("open_regression", [sys.executable, "skills/open-test-killer-loweiwei/scripts/regression.py"]),
    ("repository_verifier", [sys.executable, "verify_repo.py", "--github-id", "loweiwei"]),
]


def git_value(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()


def main() -> int:
    checks = []
    for name, command in COMMANDS:
        started = time.monotonic()
        process = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=300, check=False)
        checks.append({
            "name": name,
            "command": command,
            "returncode": process.returncode,
            "passed": process.returncode == 0,
            "elapsed_sec": time.monotonic() - started,
            "stdout": process.stdout,
            "stderr": process.stderr,
        })
    evidence = {
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "commit": git_value("rev-parse", "HEAD"),
        "branch": git_value("branch", "--show-current"),
        "dirty_worktree": bool(git_value("status", "--porcelain")),
        "passed": all(check["passed"] for check in checks),
        "checks": checks,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": evidence["passed"], "output": str(OUTPUT)}, ensure_ascii=False))
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
