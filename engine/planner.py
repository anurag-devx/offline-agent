"""
engine/planner.py: understand an agent BEFORE running it.

    capabilities_summary  what it can / asks for / cannot do, and its scopes (no model needed)
    workflow_dot          a diagram of how the agent works (Graphviz)
    plan_task             ask the model for a step-by-step plan, without running any tool
    generate_agent        describe an agent in words; the local model drafts the config
"""
import json
import re

from . import llm
from .config import AgentConfig
from .paths import resolve_folder
from .permissions import ALLOW, ASK, CAPABILITIES, GROUPS, OFF, Policy, cap_title, group_of
from .tools import TOOLS, describe, permission_of, tools_for


def tools_of(cap):
    return [n for n, t in TOOLS.items() if t["permission"] == cap]


def capabilities_summary(cfg):
    """(allowed, asks_first, off, scope_notes) as lists of strings."""
    pol = cfg.permissions
    allowed, asks, off = ["Calculator and clock (always on, touch nothing)"], [], []
    for cap, info in CAPABILITIES.items():
        line = f"{cap_title(cap)}: {info['detail']}"
        {ALLOW: allowed, ASK: asks, OFF: off}[pol.mode(cap)].append(line)

    notes = [f"Model `{cfg.model}` runs on this computer; your data is not sent to any AI company.",
             f"At most {cfg.max_steps} model steps per pass; context window {cfg.context_length:,} tokens."]
    if cfg.mode == "rules":
        from .rules import rule_target
        what = "emails" if rule_target(cfg) == "email" else "files"
        notes.insert(0, f"Rule mode: the model is used once to write a rule; you approve it with the exact list "
                        f"of {what}; code moves them and checks the result exactly.")
    elif cfg.plan_steps:
        notes.append("Job notes: it plans steps and ticks them off; code attaches evidence; finished steps' "
                     "messages are dropped so the context stays small. Saved as notes.md per job.")
    if cfg.verify.enabled and cfg.mode == "agent":
        tries = "until it passes or you press Stop" if cfg.verify.max_attempts == 0 else \
            f"up to {cfg.verify.max_attempts} times"
        notes.append(f"When it says it's done, a read-only verifier checks the real state; if not done, "
                     f"it continues ({tries}). Criteria: {cfg.verify.criteria.strip() or 'judged from the task'}.")
    if any(pol.mode(f"files.{a}") != OFF for a in ("read", "create", "modify", "move", "delete")):
        folders = ", ".join(f"`{resolve_folder(f)}`" for f in pol.files.folders) or "none yet"
        notes.append(f"Folders (with subfolders): {folders}.")
        notes.append("Other folders: " + ("it asks you first." if pol.files.ask_for_other_folders else "blocked."))
        if pol.files.file_types:
            notes.append("Only file types: " + ", ".join(pol.files.file_types))
        notes.append(f"At most {pol.files.max_changes} file changes per run. Nothing is ever overwritten.")
    if pol.mode("internet.read") != OFF:
        notes.append("Websites: " + (", ".join(pol.internet.domains) or "none listed")
                     + ("; other sites: asks you." if pol.internet.other_domains == "ask" else "; other sites: blocked."))
        notes.append("Anything in a web address it opens reaches that site.")
    if pol.mode("internet.search") != OFF:
        notes.append("Web searches are sent to DuckDuckGo.")
    if pol.mode("internet.read") == OFF and pol.mode("internet.search") == OFF:
        notes.append("No internet access.")
    if pol.mode("memory.read") != OFF or pol.mode("memory.write") != OFF or pol.memory.run_summaries:
        notes.append("Memory: " + ("shared" if pol.memory.shared else "its own") + " notes on this computer"
                     + (f"; {pol.memory.recall} relevant notes recalled at the start" if pol.mode("memory.read") != OFF
                        and pol.memory.recall else "")
                     + ("; code saves a summary after each run" if pol.memory.run_summaries else "") + ".")
    if pol.mode("email.read") != OFF or pol.mode("email.organize") != OFF:
        notes.append("Mail folders: " + (", ".join(pol.email.folders) or "all")
                     + ". Mail goes only to your mail server; no send or delete tools exist.")
    return allowed, asks, off, notes


def workflow_dot(cfg):
    """Graphviz diagram: you -> model -> (your OK) -> capabilities -> what they touch."""
    pol = cfg.permissions
    lines = [
        "digraph G {",
        'rankdir=LR; bgcolor="transparent";',
        'node [shape=box, style="rounded,filled", fillcolor="#eef2f7", color="#94a3b8", fontname="Helvetica", fontsize=11];',
        'edge [color="#64748b", fontname="Helvetica", fontsize=9];',
        f'you [label="You\\n(task)", fillcolor="#fde68a"];',
        f'model [label="{cfg.name}\\n{cfg.model}\\non this computer", fillcolor="#bfdbfe"];',
        'answer [label="Answer", fillcolor="#bbf7d0"];',
        'you -> model;',
        ('verify [shape=diamond, label="verifier:\\ndone?", fillcolor="#c7d2fe"]; model -> verify [label="says done"]; '
         'verify -> answer [label="yes"]; verify -> model [label="no: continue", style=dashed];')
        if cfg.verify.enabled and cfg.mode == "agent" else 'model -> answer [label="done"];',
    ]
    targets = {
        "files": ("res_files", "folder", "Folders\\n" + "\\n".join(
            str(resolve_folder(f)).replace(str(resolve_folder("~")), "~") for f in pol.files.folders[:5])
            + ("\\n+ ones you grant" if pol.files.ask_for_other_folders else "")),
        "internet": ("res_web", "cylinder", "Sites\\n" + "\\n".join(pol.internet.domains[:5] or ["(none listed)"])
                     + ("\\n+ ones you allow" if pol.internet.other_domains == "ask" else "")),
        "email": ("res_mail", "cylinder", "Your mail server"),
        "memory": ("res_mem", "cylinder", "Memory\\n(on this computer)"),
        "interaction": ("you", None, None),
    }
    used = set()
    for cap in pol.enabled():
        node = cap.replace(".", "_")
        tools = "\\n".join(tools_of(cap))
        lines.append(f'{node} [label="{cap_title(cap)}\\n\\n{tools}"];')
        if pol.mode(cap) == ASK:
            lines.append(f'gate_{node} [shape=diamond, label="your\\nOK?", fillcolor="#fecaca"];')
            lines.append(f"model -> gate_{node}; gate_{node} -> {node};")
        else:
            lines.append(f"model -> {node};")
        lines.append(f'{node} -> model [style=dashed, label="result"];')
        res, shape, label = targets[group_of(cap)]
        if shape and res not in used:
            lines.append(f'{res} [shape={shape}, label="{label}", fillcolor="#fed7aa"];')
            used.add(res)
        lines.append(f"{node} -> {res};")
    lines.append("}")
    return "\n".join(lines)


PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "understanding": {"type": "string"},
        "steps": {"type": "array", "items": {
            "type": "object",
            "properties": {"action": {"type": "string"}, "tool": {"type": "string"}},
            "required": ["action", "tool"]}},
    },
    "required": ["understanding", "steps"],
}


def plan_task(cfg, task):
    """Ask the model how it WOULD do the task. No tools are run."""
    available = tools_for(cfg)
    blocked = [n for n in TOOLS if n not in available]
    prompt = (
        "You are planning, not doing. Do not perform the task.\n\n"
        f"Your instructions as an agent:\n{cfg.system_prompt}\n\n"
        "Tools you may use:\n" + "\n".join(f"- {n}: {describe(n)}" for n in available) + "\n\n"
        "Tools that exist but you are NOT allowed to use:\n"
        + ("\n".join(f"- {n}: {describe(n)}" for n in blocked) or "- none") + "\n\n"
        "Return: `understanding` = one sentence restating the task; `steps` = short ordered steps. "
        "For each step give the exact tool name you would use, or \"none\" if no tool is needed. "
        "If a step needs a tool you are not allowed to use, still name it.")
    response = llm.chat(cfg.model, [{"role": "system", "content": prompt},
                                    {"role": "user", "content": task}],
                        temperature=0, think=False, format=PLAN_SCHEMA)
    plan = json.loads(response.message.content)
    for s in plan.get("steps", []):
        tool = (s.get("tool") or "none").strip()
        if tool.lower() in ("none", ""):
            s["status"] = "reasoning"
        elif tool in available:
            s["status"] = "asks you" if cfg.permissions.mode(permission_of(tool)) == ASK else "allowed"
        elif tool in TOOLS:
            s["status"] = "blocked"
            s["needs"] = cap_title(permission_of(tool))
        else:
            s["status"] = "unknown tool"
    return plan


_MODE_ENUM = {"type": "string", "enum": [OFF, ALLOW, ASK]}
GENERATE_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "description": {"type": "string"},
        "system_prompt": {"type": "string"},
        "permissions": {"type": "object", "properties": {
            c.replace(".", "_"): _MODE_ENUM for c in CAPABILITIES}},
        "folders": {"type": "array", "items": {"type": "string"}},
        "ask_for_other_folders": {"type": "boolean"},
        "domains": {"type": "array", "items": {"type": "string"}},
        "max_steps": {"type": "integer"},
        "temperature": {"type": "number"},
    },
    "required": ["name", "description", "system_prompt", "permissions", "folders",
                 "ask_for_other_folders", "domains", "max_steps"],
}
_ALWAYS_ASK = ("files.modify", "files.delete", "email.organize")


def generate_agent(description, model):
    """Let the local model design an agent config from a plain-English description."""
    catalog = "\n".join(f"- {c.replace('.', '_')}: {i['detail']} Tools: {', '.join(tools_of(c))}"
                        for c, i in CAPABILITIES.items())
    prompt = (
        "You design AI agents for a framework. Output a config for the agent the user describes.\n"
        "Rules:\n"
        "- system_prompt: numbered step-by-step instructions in second person ('You ...'), "
        "naming exactly which tool to use for each step.\n"
        "- permissions: each is off, allow or ask. Turn on ONLY what the task needs. Use 'ask' for "
        "anything that changes or deletes files or email.\n"
        "- folders: folders the agent may use, like '~/Downloads' or 'workspace'. If the user "
        "should choose the folder at run time, leave it empty, set ask_for_other_folders true, "
        "turn on interaction_ask_user and tell the agent to ask with ask_user.\n"
        "- domains: only if internet is needed, bare domains like 'wikipedia.org'.\n"
        "- max_steps: 3-60 depending on task size.\n\n"
        f"Capabilities:\n{catalog}\nAlways available: calculator, current_datetime.")
    response = llm.chat(model, [{"role": "system", "content": prompt},
                                {"role": "user", "content": description}],
                        temperature=0.2, think=False, format=GENERATE_SCHEMA)
    data = json.loads(response.message.content)

    pol = Policy()
    pol.interaction.ask_user = OFF
    raw = data.get("permissions") or {}
    for cap in CAPABILITIES:
        mode = raw.get(cap.replace(".", "_"), OFF)
        mode = mode if mode in (OFF, ALLOW, ASK) else OFF
        if cap == "interaction.ask_user" and mode == ASK:
            mode = ALLOW
        if cap in _ALWAYS_ASK and mode == ALLOW:
            mode = ASK  # safety: generated agents never change/delete things unasked
        pol.set_mode(cap, mode)
    pol.files.folders = [f.strip() for f in data.get("folders") or [] if f.strip()]
    pol.files.ask_for_other_folders = bool(data.get("ask_for_other_folders"))
    pol.internet.domains = [re.sub(r"^https?://", "", d).split("/")[0].strip().lower()
                            for d in data.get("domains") or [] if d.strip()]
    return AgentConfig(
        name=(data.get("name") or "Generated Agent").strip()[:60],
        description=(data.get("description") or description).strip(),
        model=model,
        system_prompt=(data.get("system_prompt") or "").strip(),
        permissions=pol,
        max_steps=max(1, min(int(data.get("max_steps") or 8), 100)),
        temperature=max(0.0, min(float(data.get("temperature") or 0.2), 2.0)),
    )
