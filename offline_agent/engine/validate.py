"""
engine/validate.py: check an agent before you run it.

Each check: {"check", "ok", "detail", "level"}. "error" blocks the agent, "warning" is advice.
"""
import time
from pathlib import Path

from . import audit, llm
from .rules import make_agent
from .credentials import email_configured
from .paths import HOME, is_protected, resolve_folder
from .permissions import ALLOW, OFF, cap_title
from .tools import tools_for


def _check(name, ok, detail, level="error"):
    """`detail` explains the problem; passing checks just say OK."""
    return {"check": name, "ok": bool(ok), "detail": "OK" if ok else detail, "level": level}


def validate(cfg):
    pol = cfg.permissions
    on = lambda cap: pol.mode(cap) != OFF  # noqa: E731
    checks = [
        _check("Name", cfg.name.strip(), "Give the agent a name."),
        _check("System prompt", cfg.system_prompt.strip(), "Tell the agent what it should do."),
    ]

    running = llm.is_running()
    checks.append(_check("Ollama running", running, "Open the Ollama app (or run `ollama serve`)."))
    if running:
        installed = cfg.model in llm.list_models()
        checks.append(_check("Model installed", installed, f"Run `ollama pull {cfg.model}` or pick another model."))
        if installed and tools_for(cfg):
            caps = llm.capabilities(cfg.model)
            if not caps:
                checks.append(_check("Model supports tools", False,
                                     "Could not read model capabilities. Update Ollama to be sure.", "warning"))
            else:
                checks.append(_check("Model supports tools", "tools" in caps,
                                     f"{cfg.model} can't call tools. Pick another model."))
        limit = llm.context_limit(cfg.model) if installed else 0
        if limit and cfg.context_length > limit:
            checks.append(_check("Context length", False, f"{cfg.model} supports at most {limit:,} tokens.", "warning"))
        if cfg.verify.enabled and cfg.verify.model:
            checks.append(_check("Verifier model installed", cfg.verify.model in llm.list_models(),
                                 f"Run `ollama pull {cfg.verify.model}` or leave it empty to use the agent's model."))
        if installed and cfg.think and "thinking" not in llm.capabilities(cfg.model):
            checks.append(_check("Thinking", False, f"{cfg.model} has no thinking mode; ignored.", "warning"))

    # ---- files
    file_caps = [f"files.{a}" for a in ("read", "create", "modify", "move", "delete")]
    if any(on(c) for c in file_caps):
        folders = [resolve_folder(f) for f in pol.files.folders]
        if not folders and not pol.files.ask_for_other_folders:
            checks.append(_check("Folders", False, "File access is on but no folders are listed. "
                                 "Add one, or tick 'Ask me before using other folders'."))
        missing = [str(p) for p in folders if not p.is_dir()]
        checks.append(_check("Folders exist", not missing, f"Not found: {', '.join(missing)}"))
        bad = [str(p) for p in folders if is_protected(p)]
        checks.append(_check("Folders allowed", not bad, f"Protected, agents can never use: {', '.join(bad)}"))
        broad = [str(p) for p in folders if p in (HOME, HOME.parent, Path("/"))]
        if broad:
            checks.append(_check("Folder scope", False, f"{', '.join(broad)} gives access to almost everything. "
                                 "Use a specific folder.", "warning"))
        if pol.files.ask_for_other_folders and not on("interaction.ask_user") and not folders:
            checks.append(_check("Choosing a folder", False, "No folders listed and the agent can't ask you "
                                 "questions. Turn on 'Ask you questions' so it can ask which folder.", "warning"))
    for cap in ("files.modify", "files.delete", "email.organize"):
        if pol.mode(cap) == ALLOW:
            checks.append(_check(f"{cap_title(cap)} without asking", False,
                                 "The agent can change things without your OK. Consider 'Ask first'.", "warning"))

    # ---- internet
    if on("internet.read") and not pol.internet.domains and pol.internet.other_domains == "block":
        checks.append(_check("Websites", False, "Reading web pages is on but no sites are listed and other "
                             "sites are blocked, so every page will be refused.", "warning"))

    # ---- email
    if on("email.read") or on("email.organize"):
        checks.append(_check("Email account", email_configured(), "Add your email on the Settings page."))
        if on("email.organize") and not on("email.read"):
            checks.append(_check("Email read", False, "Organizing without reading means the agent can't "
                                 "find emails.", "warning"))

    # ---- data leaving the machine
    private = on("email.read") or on("files.read")
    if private and (pol.mode("internet.read") == ALLOW or pol.mode("internet.search") == ALLOW):
        checks.append(_check("Private data + internet", False, "This agent reads your files/email AND can "
                             "contact websites freely. Set internet to 'Ask first' so nothing private can "
                             "leave without your OK.", "warning"))

    if on("memory.read") or on("memory.write") or pol.memory.run_summaries:
        from .memory import EMBED_MODEL
        has_embed = running and any(m.startswith(EMBED_MODEL) for m in _all_models())
        checks.append(_check("Memory search", has_embed, f"Keyword search only. For search by meaning: "
                             f"`ollama pull {EMBED_MODEL}`.", "warning"))
        if pol.mode("memory.write") == ALLOW and (on("internet.read") or on("email.read") or on("files.read")):
            checks.append(_check("Memory poisoning", False, "This agent reads outside content and can save notes "
                                 "without asking; a web page or file could plant a note. Set Remember to "
                                 "'Ask first'.", "warning"))
    if cfg.context_length < 8192 and tools_for(cfg):
        checks.append(_check("Context length", False, "Below 8,192 tokens, tool results (like a folder list) "
                             "can push the instructions out of the model's memory.", "warning"))
    if cfg.verify.enabled and cfg.verify.max_attempts == 0:
        checks.append(_check("Verification attempts", False, "Unlimited: the agent keeps retrying until it's "
                             "verified or you press Stop.", "warning"))
    if cfg.mode == "rules":
        from .rules import rule_target
        checks.append(_check("Rule mode", rule_target(cfg), "Rule mode organizes files or email: turn on Files "
                             "'Read' + 'Move', or Email 'Read' + 'Organize'."))
    if cfg.max_reply_tokens and cfg.max_reply_tokens < 256 and tools_for(cfg):
        checks.append(_check("Reply cap", False, "Below 256 tokens, tool calls with long arguments get cut off.",
                             "warning"))
    checks.append(_check("Max steps", 1 <= cfg.max_steps <= 100, "Should be between 1 and 100."))
    checks.append(_check("Temperature", 0 <= cfg.temperature <= 2, "Should be between 0 and 2."))
    return checks


def _all_models():
    """All installed models, including embedding models (list_models hides those)."""
    try:
        import ollama
        return [m.model for m in ollama.list().models]
    except Exception:
        return []


def is_valid(checks):
    return all(c["ok"] for c in checks if c["level"] == "error")


def dry_run(cfg, prompt):
    """Run one question right now. Approvals are denied and questions get no answer.
    Returns (ok, events, seconds)."""
    start = time.time()
    events = list(make_agent(cfg, approver=None, asker=None).run(prompt))
    ok = any(e["type"] == "answer" for e in events)
    audit.log("dry_run", agent=cfg.name, model=cfg.model, ok=ok)
    return ok, events, time.time() - start
