"""Linux child-process isolation regression tests."""

from __future__ import annotations

import importlib.util
import os
import sys
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CODE_AUTHOR_RUN = ROOT / "skills" / "code-author-loweiwei" / "scripts" / "run.py"


def load_runner():
    spec = importlib.util.spec_from_file_location("isolated_code_author_run", CODE_AUTHOR_RUN)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


runner = load_runner()


pytestmark = pytest.mark.skipif("fork" not in runner.mp.get_all_start_methods(), reason="requires POSIX fork")


def test_worker_does_not_inherit_secret_environment(monkeypatch):
    monkeypatch.setenv("AIASE_TEST_SECRET", "must-not-leak")
    code = "def inspect_env():\n    return __builtins__['__import__']('os').environ.get('AIASE_TEST_SECRET')\n"

    passed, failed, errors = runner._run_cases(code, "inspect_env", [{"args": [], "expected": None}])

    assert (passed, failed, errors) == (1, 0, [])


def test_worker_uses_disposable_working_directory():
    code = "def current_dir():\n    return __builtins__['__import__']('os').getcwd()\n"
    passed, failed, errors = runner._run_cases(code, "current_dir", [{"args": [], "expected": "unmatchable"}])

    assert passed == 0 and failed == 1
    worker_dir = errors[0].split("got ", 1)[1].split(", expected", 1)[0].strip("'")
    assert "aiase_code_author_" in worker_dir
    assert not Path(worker_dir).exists()


def test_worker_process_group_kills_descendants(tmp_path):
    marker = tmp_path / "orphan_wrote.txt"
    code = (
        "def spawn():\n"
        "    os = __builtins__['__import__']('os')\n"
        "    time = __builtins__['__import__']('time')\n"
        "    pid = os.fork()\n"
        "    if pid == 0:\n"
        "        time.sleep(0.5)\n"
        f"        __builtins__['open']({str(marker)!r}, 'w').write('orphan')\n"
        "        os._exit(0)\n"
        "    return None\n"
    )

    passed, failed, errors = runner._run_cases(code, "spawn", [{"args": [], "expected": None}])
    time.sleep(0.7)

    assert passed + failed == 1
    if failed:
        assert errors
    assert not marker.exists()


def test_worker_memory_limit_preserves_parent():
    code = "def allocate():\n    return bytearray(1024 * 1024 * 1024)\n"

    passed, failed, errors = runner._run_cases(code, "allocate", [{"args": [], "expected": None}])

    assert passed == 0 and failed == 1
    assert errors


def test_static_policy_rejects_file_network_and_process_modules():
    code = "import os\nimport socket\nimport subprocess\ndef solution():\n    return 1\n"

    imports, sandbox = runner._static_checks(code, [])

    assert imports == []
    assert all(any(module in violation for violation in sandbox) for module in ("os", "socket", "subprocess"))
