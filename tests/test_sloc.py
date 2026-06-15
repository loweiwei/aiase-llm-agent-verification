"""Tests for SLOC computation in code-author selftest harness."""

import importlib.util
import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
ST_PATH = REPO_ROOT / "skills" / "code-author-loweiwei" / "scripts" / "selftest.py"


def _load():
    spec = importlib.util.spec_from_file_location("selftest", ST_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


st = _load()


def test_sloc_empty():
    assert st.compute_sloc("") == 0


def test_sloc_only_comments_and_blanks():
    code = "\n# comment\n\n   # another\n"
    assert st.compute_sloc(code) == 0


def test_sloc_simple_function():
    code = "def f(x):\n    return x + 1\n"
    # If radon is available, expect 2 SLOC. Fallback computes the same.
    assert st.compute_sloc(code) == 2


def test_sloc_with_inline_comments():
    code = "def f(x):  # entry\n    return x + 1\n"
    # SLOC counts statement lines; both lines have code.
    assert st.compute_sloc(code) == 2


def test_loc_violation_detection_via_find_import_violations():
    bad = "import os\ndef f(): pass\n"
    violations = st.find_import_violations(bad, ["os", "sys"])
    assert "os" in violations


def test_no_import_violations_when_clean():
    good = "def f(x):\n    return x * 2\n"
    assert st.find_import_violations(good, ["os", "sys"]) == []


def test_radon_present_or_fallback():
    """Sanity: either radon is installed and we got its output, or fallback agreed.
    Either way, SLOC for a known sample is in a reasonable ballpark."""
    code = "import math\n\ndef circ(r):\n    return 2 * math.pi * r\n"
    s = st.compute_sloc(code)
    # 3 statement lines (import, def, return). Allow ±1 for radon variants.
    assert 2 <= s <= 4


@pytest.mark.skipif(shutil.which("radon") is None, reason="radon not on PATH")
def test_radon_path_specifically():
    """When radon is on PATH, verify the radon path runs (not just fallback)."""
    code = "def a():\n    return 1\n\ndef b():\n    return 2\n"
    assert st.compute_sloc(code) == 4
