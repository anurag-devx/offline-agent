"""
engine/audit.py: the activity log. One JSON line per thing that happened
(agent saved, run started, approval given, model imported...), in logs/activity.jsonl.
"""
import json
from datetime import datetime

from .config import ROOT

LOG_FILE = ROOT / "logs" / "activity.jsonl"


def log(action, **details):
    LOG_FILE.parent.mkdir(exist_ok=True)
    entry = {"time": datetime.now().isoformat(timespec="seconds"), "action": action, **details}
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def read_activity(limit=300):
    if not LOG_FILE.exists():
        return []
    lines = LOG_FILE.read_text(encoding="utf-8").splitlines()[-limit:]
    return [json.loads(line) for line in reversed(lines) if line.strip()]
