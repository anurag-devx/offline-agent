"""engine/paths.py: important locations, and folders agents may never touch."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = ROOT / "agents"
TEMPLATES_DIR = ROOT / "templates"
WORKSPACE = ROOT / "workspace"
for _d in (AGENTS_DIR, WORKSPACE):
    _d.mkdir(exist_ok=True)

HOME = Path.home()
# Credentials and keys: blocked for every agent, whatever its permissions say.
PROTECTED = [HOME / p for p in (".ssh", ".gnupg", ".aws", ".kube", ".docker", ".config/gcloud",
                                "Library/Keychains", ".offline-agent")]


def resolve_folder(text):
    """'workspace' -> project workspace; '~/Downloads' or 'Downloads' -> /Users/you/Downloads."""
    t = str(text).strip()
    if t.rstrip("/") == "workspace":
        return WORKSPACE.resolve()
    p = Path(t).expanduser()
    return (p if p.is_absolute() else HOME / p).resolve()


def is_inside(path, root):
    return path == root or root in path.parents


def is_protected(path):
    """Credential folders, and this project's own code and records (except workspace/)."""
    p = Path(path).resolve()
    if any(is_inside(p, q.resolve()) for q in PROTECTED):
        return True
    return is_inside(p, ROOT.resolve()) and not is_inside(p, WORKSPACE.resolve())
