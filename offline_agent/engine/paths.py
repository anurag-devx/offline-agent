"""
engine/paths.py: where things live, and folders agents may never touch.

    PKG_DIR    the program itself (code + built-in templates)
    ROOT       your data: agents/, workspace/, runs/, logs/, memory/, schedules/
               - running from a git checkout: the project folder (same as before)
               - installed with pip: ~/OfflineAgent
               - override with the OFFLINE_AGENT_HOME environment variable
"""
import os
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent.parent           # .../offline_agent
_REPO = PKG_DIR.parent
_IS_CHECKOUT = (_REPO / "pyproject.toml").exists() and (_REPO / ".git").exists()

if os.environ.get("OFFLINE_AGENT_HOME"):
    ROOT = Path(os.environ["OFFLINE_AGENT_HOME"]).expanduser().resolve()
elif _IS_CHECKOUT:
    ROOT = _REPO
else:
    ROOT = (Path.home() / "OfflineAgent").resolve()

TEMPLATES_DIR = PKG_DIR / "templates"
AGENTS_DIR = ROOT / "agents"
WORKSPACE = ROOT / "workspace"
for _d in (ROOT, AGENTS_DIR, WORKSPACE):
    _d.mkdir(parents=True, exist_ok=True)

HOME = Path.home().resolve()  # resolved: on macOS /var is really /private/var
# Credentials and keys: blocked for every agent, whatever its permissions say.
PROTECTED = [HOME / p for p in (".ssh", ".gnupg", ".aws", ".kube", ".docker", ".config/gcloud",
                                "Library/Keychains", ".offline-agent")]


def resolve_folder(text):
    """'workspace' -> your workspace; '~/Downloads' or 'Downloads' -> /Users/you/Downloads."""
    t = str(text).strip()
    if t.rstrip("/") == "workspace":
        return WORKSPACE.resolve()
    p = Path(t).expanduser()
    return (p if p.is_absolute() else HOME / p).resolve()


def is_inside(path, root):
    return path == root or root in path.parents


def is_protected(path):
    """Credential folders, the program's code, and this app's own records (except workspace/)."""
    p = Path(path).resolve()
    if any(is_inside(p, q.resolve()) for q in PROTECTED):
        return True
    if is_inside(p, PKG_DIR):
        return True
    return is_inside(p, ROOT.resolve()) and not is_inside(p, WORKSPACE.resolve())
