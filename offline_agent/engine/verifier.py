"""
engine/verifier.py: a second, read-only agent that checks whether the task is really done.

Why a separate agent? The worker agent can be wrong or confused about its own work
(it may *say* it moved files when it didn't). The verifier:
  - gets the task + success criteria,
  - gets the evidence OUR CODE recorded (file changes, errors, denials), not the worker's claims,
  - can only look (read-only tools, same folders the worker had),
  - returns a structured verdict: complete yes/no, reason, what's missing.
"""
import json

from . import llm
from .agent import Agent
from .config import AgentConfig
from .findings import SCHEMA as FINDINGS_SCHEMA
from .permissions import ALLOW, OFF, Policy

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {"complete": {"type": "boolean"}, "reason": {"type": "string"},
                   "missing": {"type": "string"}, "findings": FINDINGS_SCHEMA},
    "required": ["complete", "reason", "missing", "findings"],
}

PROMPT = """You are a strict verifier. You check whether another agent really completed a task.
Rules:
- Trust the RECORDED EVIDENCE and what you see with your own tools. Do not trust the agent's claims.
- Check the real current state (e.g. list the folders involved, using filters like extensions=".pdf").
- A task is complete only if every part of it is done. Summaries or plans are not completion.
- Be concrete: name what is missing (e.g. "23 .pdf files are still in ~/Downloads").
- Look at files with read_lines (it shows line numbers), so you can point at the exact line of
  each problem. Something missing entirely: give the line it should go after.
You cannot change anything; you can only look."""


def evidence(events):
    """Summarize what the code recorded during the run."""
    ops = [e for e in events if e["type"] == "file_op"]
    counts = {}
    for e in ops:
        counts[e["op"]] = counts.get(e["op"], 0) + 1
    lines = ["File changes recorded: " + (", ".join(f"{n} {k}" for k, n in counts.items()) or "none")]
    for e in ops[-40:]:
        lines.append(f"  {e['op']}: {e.get('src', '')} -> {e.get('dst', '')}".replace(" -> ", " -> " if e.get("src") else ""))
    errors = [e for e in events if e["type"] == "tool_result" and str(e["result"]).startswith("Error")]
    lines.append(f"Tool errors: {len(errors)}")
    lines += [f"  {e['name']}: {str(e['result'])[:200]}" for e in errors[-10:]]
    denied = [e for e in events if e["type"] == "approval" and not e["approved"]]
    lines.append(f"Actions the user denied: {len(denied)}" + "".join(f"\n  {e['name']}" for e in denied[-10:]))
    warns = [e["content"] for e in events if e["type"] == "warning"]
    if warns:
        lines.append("Warnings: " + " | ".join(warns[-3:]))
    return "\n".join(lines)


def _readonly_policy(worker):
    pol = Policy()
    pol.interaction.ask_user = OFF
    wp = worker.permissions
    if any(wp.mode(f"files.{a}") != OFF for a in ("read", "create", "modify", "move", "delete")):
        pol.files.read = ALLOW
        pol.files.folders = list(wp.files.folders)
    if wp.mode("email.read") != OFF or wp.mode("email.organize") != OFF:
        pol.email.read = ALLOW
        pol.email.folders = list(wp.email.folders)
    return pol


def verify(cfg, task, events, granted_folders=(), should_stop=None, notes=""):
    """Generator: yields the verifier's own steps, then {"type": "verdict", ...}."""
    v = cfg.verify
    vcfg = AgentConfig(name=f"{cfg.name} (verifier)", model=v.model or cfg.model, system_prompt=PROMPT,
                       permissions=_readonly_policy(cfg), max_steps=8, temperature=0,
                       context_length=cfg.context_length, plan_steps=False, terse=True,
                       max_reply_tokens=cfg.max_reply_tokens)
    checker = Agent(vcfg, approver=None, asker=None, should_stop=should_stop)
    checker.state["granted_folders"] = list(granted_folders)  # same folders the worker was granted
    answer = next((e["content"] for e in reversed(events) if e["type"] == "answer"), "")
    prompt = (f"TASK:\n{task}\n\nSUCCESS CRITERIA:\n{v.criteria.strip() or 'Decide from the task.'}\n\n"
              f"RECORDED EVIDENCE (from the system, reliable):\n{evidence(events)}\n\n"
              + (f"JOB NOTES (steps: agent's claims + code's evidence):\n{notes}\n\n" if notes else "") +
              f"AGENT'S FINAL MESSAGE (may be wrong):\n{answer[:1500]}\n\n"
              "Check the real state with your tools, then say whether the task is complete.")
    for e in checker.run(prompt):
        yield e
    try:
        resp = llm.chat(vcfg.model, checker.messages + [{"role": "user", "content":
                        "Now give your verdict as JSON: complete (true/false), reason, missing, and "
                        "findings: one per problem with file, line (from read_lines; 0 if unknown), "
                        "problem and fix. Empty findings if complete."}],
                        temperature=0, think=False, format=VERDICT_SCHEMA, num_ctx=cfg.context_length,
                        num_predict=900)  # Word Limit: a verdict with findings is still short
        verdict = json.loads(resp.message.content)
    except Exception as ex:
        verdict = {"complete": False, "reason": f"Verifier failed: {ex}", "missing": "unknown"}
    found = verdict.get("findings") if isinstance(verdict.get("findings"), list) else []
    yield {"type": "verdict", "complete": bool(verdict.get("complete")),
           "reason": str(verdict.get("reason", "")), "missing": str(verdict.get("missing", "")),
           "findings": [] if verdict.get("complete") else found}
