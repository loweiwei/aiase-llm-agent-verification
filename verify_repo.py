#!/usr/bin/env python3
"""
verify_repo.py — 繳交前自我檢查

跑過規格書 §5.7「繳交前自我檢查清單」,輸出結構化報告 verify_report.json
+ 人類可讀摘要。回傳 exit code 0 全通過、非 0 有問題。

用法:
    python verify_repo.py --github-id <your_github_id>

不會呼叫 hermes(避免依賴外部安裝);但會檢查:
- skill folder name vs SKILL.md frontmatter name 一致、含 github_id
- 必交檔案存在
- OPEN_TRACK.md 七區塊齊全
- PAIRWISE_ROLE.md 格式合法、skill_path 存在
- 無疑似 token、無 hardcoded 絕對路徑
- scripts/requirements.txt 有 pin 版本
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent

# 七個 Open Track heading
OPEN_TRACK_HEADINGS = [
    "## 1. Skill 簡介",
    "## 2. Skill 名稱與目錄",
    "## 3. 呼叫方式",
    "## 4. 自定 Verifiable Scenario",
    "## 5. 預期失敗模式",
    "## 6. 互動對象",
    "## 7. Token Budget 估算",
]

REFERENCE_SKILL_PREFIXES = (
    "reference-bug-hunter-",
    "reference-author-",
    "hello-aiase",
)

ABSOLUTE_PATH_PATTERNS = [
    re.compile(r"\b/Users/[A-Za-z0-9_\-./]+"),
    re.compile(r"\b/home/[A-Za-z0-9_\-./]+"),
    re.compile(r"\b[Cc]:\\[A-Za-z0-9_\-.\\]+"),
]

TOKEN_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b"),
    re.compile(r"\baiase[_-]?litellm[_-]?key\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{16,}", re.IGNORECASE),
]

PINNED_REQ_RE = re.compile(r"^[A-Za-z0-9_\-]+==[0-9]")


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class Report:
    github_id: str
    checks: list[Check] = field(default_factory=list)

    def add(self, name: str, passed: bool, detail: str = "") -> None:
        self.checks.append(Check(name=name, passed=passed, detail=detail))

    def to_dict(self) -> dict:
        return {
            "github_id": self.github_id,
            "total": len(self.checks),
            "passed": sum(1 for c in self.checks if c.passed),
            "failed": sum(1 for c in self.checks if not c.passed),
            "checks": [asdict(c) for c in self.checks],
        }


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return ""


def _frontmatter_name(skill_md: Path) -> str:
    text = _read(skill_md)
    m = re.search(r"^---\s*\n(.*?)\n---", text, re.DOTALL | re.MULTILINE)
    if not m:
        return ""
    fm = m.group(1)
    nm = re.search(r"^\s*name:\s*(.+?)\s*$", fm, re.MULTILINE)
    return nm.group(1).strip() if nm else ""


def check_required_files(rep: Report) -> None:
    for rel in ["README.md", "run_dev.py", "PAIRWISE_ROLE.md", "OPEN_TRACK.md", "report.md"]:
        p = REPO_ROOT / rel
        rep.add(f"required-file:{rel}", p.exists(),
                "" if p.exists() else f"missing {rel}")


def check_skill_naming(rep: Report, github_id: str) -> None:
    skills_dir = REPO_ROOT / "skills"
    if not skills_dir.is_dir():
        rep.add("skills-dir", False, "skills/ not found")
        return
    rep.add("skills-dir", True)

    for sub in sorted(skills_dir.iterdir()):
        if not sub.is_dir():
            continue
        if sub.name.startswith(REFERENCE_SKILL_PREFIXES):
            continue  # reference skills 不需含 github_id
        skill_md = sub / "SKILL.md"
        if not skill_md.exists():
            rep.add(f"skill:{sub.name}/SKILL.md", False, "SKILL.md missing")
            continue
        fm_name = _frontmatter_name(skill_md)
        if not fm_name:
            rep.add(f"skill:{sub.name}/SKILL.md:name", False, "frontmatter name missing")
            continue
        if fm_name != sub.name:
            rep.add(f"skill:{sub.name}/SKILL.md:name", False,
                    f"frontmatter name '{fm_name}' != folder name '{sub.name}'")
            continue
        if "GITHUBID" in sub.name:
            rep.add(f"skill:{sub.name}:github_id", False,
                    f"placeholder 'GITHUBID' not replaced; rename to include github_id={github_id}")
            continue
        if github_id and github_id not in sub.name:
            rep.add(f"skill:{sub.name}:github_id", False,
                    f"github_id '{github_id}' not present in folder name")
            continue
        rep.add(f"skill:{sub.name}", True, f"name={fm_name}")


def check_open_track(rep: Report) -> None:
    p = REPO_ROOT / "OPEN_TRACK.md"
    if not p.exists():
        rep.add("open-track:exists", False, "OPEN_TRACK.md missing")
        return
    text = _read(p)
    missing = [h for h in OPEN_TRACK_HEADINGS if h not in text]
    rep.add("open-track:seven-headings", not missing,
            f"missing headings: {missing}" if missing else "")


def check_pairwise_role(rep: Report) -> None:
    p = REPO_ROOT / "PAIRWISE_ROLE.md"
    if not p.exists():
        rep.add("pairwise-role:exists", False, "PAIRWISE_ROLE.md missing")
        return
    text = _read(p)
    role_m = re.search(r"^role:\s*(code-author|bug-hunter)\s*$", text, re.MULTILINE)
    path_m = re.search(r"^skill_path:\s*(\S+)\s*$", text, re.MULTILINE)
    if not role_m:
        rep.add("pairwise-role:role", False, "role line missing or invalid")
        return
    rep.add("pairwise-role:role", True, role_m.group(1))
    if not path_m:
        rep.add("pairwise-role:skill_path", False, "skill_path line missing")
        return
    sp = path_m.group(1).rstrip("/")
    target = REPO_ROOT / sp
    if not target.is_dir():
        rep.add("pairwise-role:skill_path", False, f"path not a directory: {sp}")
        return
    rep.add("pairwise-role:skill_path", True, sp)


def check_no_absolute_paths(rep: Report) -> None:
    offenders: list[str] = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in (".git", "__pycache__", "dev_run_results", "node_modules", ".venv", "venv")
               for part in path.parts):
            continue
        if path.suffix in (".sqlite", ".sqlite3", ".db", ".png", ".jpg", ".pdf"):
            continue
        # 跳過自己 + 含路徑範例的檔案(verify_repo.py 內有 regex pattern;
        # hermes-config.example.yaml 與 README.md 有 placeholder 絕對路徑示例)
        if path.name in ("verify_repo.py", "hermes-config.example.yaml", "README.md"):
            continue
        text = _read(path)
        for pat in ABSOLUTE_PATH_PATTERNS:
            for m in pat.finditer(text):
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {m.group(0)}")
        if len(offenders) > 30:
            break
    rep.add("no-absolute-paths", not offenders,
            "" if not offenders else f"found {len(offenders)} hit(s); first: {offenders[0]}")


def check_no_tokens(rep: Report) -> None:
    offenders: list[str] = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in (".git", "__pycache__", "dev_run_results", "node_modules") for part in path.parts):
            continue
        if path.suffix in (".sqlite", ".sqlite3", ".db"):
            continue
        if path.name == "verify_repo.py":
            continue
        text = _read(path)
        for pat in TOKEN_PATTERNS:
            for m in pat.finditer(text):
                # hermes-env.example 用 <YOUR_TOKEN> 佔位,不應被誤判
                if "<YOUR_TOKEN>" in m.group(0):
                    continue
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {m.group(0)[:40]}...")
    rep.add("no-tokens", not offenders,
            "" if not offenders else f"found {len(offenders)} potential token(s); first: {offenders[0]}")


def check_requirements_pinned(rep: Report) -> None:
    bad: list[str] = []
    for req in REPO_ROOT.rglob("scripts/requirements.txt"):
        for line in _read(req).splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if not PINNED_REQ_RE.match(line):
                bad.append(f"{req.relative_to(REPO_ROOT)}: {line}")
    rep.add("requirements-pinned", not bad,
            "" if not bad else f"unpinned: {bad[:3]}")


def check_skill_md_required_fields(rep: Report) -> None:
    """Each SKILL.md 應有 name + description + version + 內文 sections。"""
    for skill_md in (REPO_ROOT / "skills").rglob("SKILL.md"):
        text = _read(skill_md)
        ok = True
        why = []
        if not re.search(r"^name:", text, re.MULTILINE):
            ok = False; why.append("missing name:")
        if not re.search(r"^description:", text, re.MULTILINE):
            ok = False; why.append("missing description:")
        if "## When to Use" not in text and "## When to use" not in text:
            ok = False; why.append("missing '## When to Use'")
        if "## Procedure" not in text:
            ok = False; why.append("missing '## Procedure'")
        if "## Verification" not in text:
            ok = False; why.append("missing '## Verification'")
        rel = skill_md.relative_to(REPO_ROOT)
        rep.add(f"skill-md:{rel}", ok, "; ".join(why))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--github-id", default="", help="your GitHub ID (for skill naming check)")
    p.add_argument("--report", default="verify_report.json")
    args = p.parse_args(argv)

    rep = Report(github_id=args.github_id)

    check_required_files(rep)
    check_skill_naming(rep, args.github_id)
    check_skill_md_required_fields(rep)
    check_open_track(rep)
    check_pairwise_role(rep)
    check_no_absolute_paths(rep)
    check_no_tokens(rep)
    check_requirements_pinned(rep)

    out = REPO_ROOT / args.report
    out.write_text(json.dumps(rep.to_dict(), ensure_ascii=False, indent=2))

    passed = sum(1 for c in rep.checks if c.passed)
    total = len(rep.checks)
    failed = [c for c in rep.checks if not c.passed]

    print(f"\n=== verify_repo summary ===")
    print(f"  passed: {passed}/{total}")
    if failed:
        print(f"  failed:")
        for c in failed:
            print(f"   ✗ {c.name}: {c.detail}")
    print(f"\nreport: {out.relative_to(REPO_ROOT)}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())