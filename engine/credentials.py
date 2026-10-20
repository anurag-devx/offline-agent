"""
engine/credentials.py: where account details (like your email app password) are kept.

Stored in ~/.offline-agent/credentials.json, outside the project folder so it can
never be committed to GitHub, readable only by your user account (chmod 600).
"""
import json
import os
from pathlib import Path

CRED_PATH = Path.home() / ".offline-agent" / "credentials.json"


def load_credentials():
    try:
        return json.loads(CRED_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_credentials(data):
    CRED_PATH.parent.mkdir(parents=True, exist_ok=True)
    CRED_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.chmod(CRED_PATH, 0o600)


def email_configured():
    e = load_credentials().get("email") or {}
    return bool(e.get("address") and e.get("password"))
