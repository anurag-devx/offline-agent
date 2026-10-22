"""
engine/triage.py: Triage decides how a task runs.

    simple / medium  -> the main agent (one loop, as before)
    complex          -> Relay: a PM agent splits the job into small chunks, one small agent per
                        chunk, and the PM pulls the pieces back together (engine/relay.py)

Code looks first (cheap, no model call): how long the brief is, how many files it names, how
many separate requirements it lists. Only when that is unclear does the model rate the task.
An agent can skip Triage with `route: single` or `route: relay`.
"""
import json
import re
import time

from . import llm
from .speed import timing

FILE_RE = re.compile(r"\b[\w./-]+\.(?:html|css|js|ts|py|md|txt|svg|json|csv|yaml|yml|xml|sql)\b", re.I)
REQ_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+\S", re.M)

SCHEMA = {
    "type": "object",
    "properties": {
        "complexity": {"type": "string", "enum": ["simple", "medium", "complex"]},
        "parts": {"type": "integer"},
        "reason": {"type": "string"},
    },
    "required": ["complexity", "parts", "reason"],
}

PROMPT = """Rate how complex a task is for a small local AI agent working alone.
simple: one or two actions (answer, read a file, one small file).
medium: a few steps on one thing.
complex: many separate parts or files that must fit together (e.g. a website with several files,
a multi-section report, several features), too much for one long session.
parts = how many separate pieces of work it has. reason = one short line."""


def signals(task):
    text = str(task)
    return {"words": len(text.split()), "files": len({m.lower() for m in FILE_RE.findall(text)}),
            "requirements": len(REQ_RE.findall(text))}


def by_code(sig):
    """'simple', 'complex', or None when code can't tell."""
    if sig["files"] >= 3 or sig["requirements"] >= 8 or sig["words"] >= 250:
        return "complex"
    if sig["words"] <= 40 and sig["files"] <= 1 and sig["requirements"] <= 2:
        return "simple"
    return None


def triage(cfg, task):
    """{"route", "complexity", "reason", "parts", "by", "signals", "call"} — call = model_call event or None."""
    sig = signals(task)
    out = {"signals": sig, "call": None, "parts": 0}
    if cfg.mode == "rules":
        return {**out, "route": "single", "complexity": "-", "by": "mode", "reason": "rule mode runs as one agent"}
    if cfg.route in ("single", "relay"):
        return {**out, "route": cfg.route, "complexity": "-", "by": "setting",
                "reason": f"this agent is set to route: {cfg.route}"}
    level = by_code(sig)
    if level:
        why = (f"{sig['files']} files, {sig['requirements']} listed requirements, {sig['words']} words")
        return {**out, "route": "relay" if level == "complex" else "single", "complexity": level, "by": "code",
                "reason": why}
    try:
        started = time.time()
        resp = llm.chat(cfg.model, [{"role": "system", "content": PROMPT}, {"role": "user", "content": task}],
                        temperature=0, think=False, format=SCHEMA, num_ctx=cfg.context_length, num_predict=200)
        rating = json.loads(resp.message.content)
        level, parts = rating.get("complexity", "medium"), int(rating.get("parts") or 0)
        call = {"type": "model_call", "purpose": "triage", "seconds": round(time.time() - started, 1), **timing(resp)}
        route = "relay" if level == "complex" or (level == "medium" and parts >= 5) else "single"
        return {**out, "route": route, "complexity": level, "parts": parts, "by": "model",
                "reason": str(rating.get("reason", ""))[:200], "call": call}
    except Exception as e:
        return {**out, "route": "single", "complexity": "medium", "by": "fallback",
                "reason": f"could not rate the task ({e}); using the main agent"}
