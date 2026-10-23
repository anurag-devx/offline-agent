"""Guard: personal data never gets committed. Runs in CI on every push."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PRIVATE = ("agents/", "runs/", "logs/", "memory/", "schedules/", "bench/", "build/", "docs/private/", "workspace/")
ALLOWED = {"agents/.gitkeep", "workspace/welcome.txt"}
SECRET_FILES = re.compile(r"(^|/)(\.env|credentials[^/]*\.json)$|\.(db|sqlite)$")
HOME_PATH = re.compile(r"(/Users/|/home/|C:\\\\Users\\\\)(?!you\b|runner|user\b|…)[a-z][\w.-]+/", re.I)


def tracked():
    if not shutil.which("git") or not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [f for f in out.splitlines() if f]


def test_no_personal_folders_are_tracked():
    bad = [f for f in tracked() if f.startswith(PRIVATE) and f not in ALLOWED]
    assert not bad, f"personal data is tracked by git (git rm --cached it): {bad}"


def test_no_secret_files_are_tracked():
    bad = [f for f in tracked() if SECRET_FILES.search(f)]
    assert not bad, f"secret-looking files are tracked: {bad}"


def test_no_real_home_paths_in_tracked_text():
    hits = []
    for f in tracked():
        p = ROOT / f
        if p.suffix.lower() in (".png", ".jpg", ".gif", ".ico", ".pdf") or not p.is_file():
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        hits += [f"{f}: {m.group(0)}" for m in HOME_PATH.finditer(text)]
    assert not hits, f"real home-folder paths in committed files: {hits[:10]}"
