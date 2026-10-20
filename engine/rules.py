"""
engine/rules.py: Rule mode. The model decides, code does the work.

For routine jobs (organizing files) the model is used ONCE: it turns your words into a rule,
    RULE ~/Downloads · .pdf → ~/Downloads/all_pdf
you approve it (with the exact file list), and plain code moves the files and checks the
result exactly. No model in the loop = fast, exact, nothing to hallucinate.

RuleAgent has the same interface as Agent (run() yields events), so runs, approvals,
notes, the file log and Undo all work the same.
"""
import json
import time
import uuid

from . import llm
from .context import ToolContext, set_context
from .ledger import Ledger
from .memory import recall_block
from .permissions import ASK, OFF
from .toolkits import files

KINDS = list(files.KINDS) + ["other"]
RULE_SCHEMA = {
    "type": "object",
    "properties": {
        "source_folder": {"type": "string"},
        "rules": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "extensions": {"type": "array", "items": {"type": "string"}},
                "kinds": {"type": "array", "items": {"type": "string", "enum": KINDS}},
                "name_contains": {"type": "string"},
                "destination": {"type": "string"},
            },
            "required": ["extensions", "kinds", "name_contains", "destination"]}},
        "question": {"type": "string"},
    },
    "required": ["source_folder", "rules", "question"],
}
PROMPT = """Turn the user's file-organizing task into rules. Do NOT do the task.
- source_folder: the folder to organize, like "~/Downloads". If neither the task nor the defaults
  say which folder, use "" and write a short question in `question`. Otherwise question = "".
- rules: one rule per destination. Match files by extensions (like ".pdf"), kinds ({kinds})
  and/or name_contains. Use extensions when the user names a file type.
- destination: a folder path. A bare name like "all_pdf" means a subfolder of source_folder.
- Only what the user asked. If the user gives no specifics, use the default instructions.

Default instructions:
{defaults}"""


def rule_target(cfg):
    """What rule mode organizes for this agent: "email", "files", or None."""
    p = cfg.permissions
    if p.mode("email.read") != OFF and p.mode("email.organize") != OFF:
        return "email"
    if p.mode("files.read") != OFF and p.mode("files.move") != OFF:
        return "files"
    return None


def make_agent(cfg, **kwargs):
    """The right engine for the agent's mode."""
    if cfg.mode == "rules":
        return EmailRuleAgent(cfg, **kwargs) if rule_target(cfg) == "email" else RuleAgent(cfg, **kwargs)
    from .agent import Agent
    return Agent(cfg, **kwargs)


def rule_text(source, r):
    match = [",".join(r["extensions"]), ",".join(r["kinds"]),
             f'name has "{r["name_contains"]}"' if r["name_contains"] else ""]
    return f"{files.short(source)} · {' '.join(m for m in match if m)} → {files.short(r['destination'])}"


class RuleAgent:
    def __init__(self, config, approver=None, asker=None, should_stop=None, job_id=None):
        self.config = config
        self.approver = approver
        self.asker = asker
        self.should_stop = should_stop or (lambda: False)
        self.job_id = job_id or uuid.uuid4().hex[:4]
        self.reset()

    def reset(self):
        self.messages = []
        self.state = {"granted_folders": [], "granted_domains": [], "changes": 0}
        self.auto_approved = set()
        self.ledger = None

    def _ask_model(self, messages):
        cfg = self.config
        started = time.time()
        resp = llm.chat(cfg.model, messages, temperature=0, think=False, format=RULE_SCHEMA,
                        num_ctx=cfg.context_length, num_predict=600)
        event = {"type": "model_call", "purpose": "rule", "step": 1, "seconds": round(time.time() - started, 1),
                 "prompt_tokens": resp.prompt_eval_count or 0, "output_tokens": resp.eval_count or 0,
                 "thinking": "", "content": resp.message.content or ""}
        return json.loads(resp.message.content), event

    def _drain(self, ctx):
        events = list(ctx.events)
        ctx.events.clear()
        return events

    def run(self, user_input):
        cfg = self.config
        ctx = ToolContext(cfg, self.state, approver=self.approver, asker=self.asker)
        set_context(ctx)
        led = Ledger(job=self.job_id, task=user_input)
        for t in ("Turn task into a rule", "You approve the rule", "Move files (code)", "Check result (code)"):
            led.add(t)
        self.ledger = led
        yield {"type": "plan", "steps": [s.title for s in led.steps], "step": 0}
        yield {"type": "ledger", "ledger": led.to_dict(), "step": 0}

        if cfg.permissions.mode("files.read") == OFF or cfg.permissions.mode("files.move") == OFF:
            yield {"type": "error", "content": "Rule mode needs the Files 'Read' and 'Move' permissions.", "step": 1}
            return

        # ---- 1. the model writes the rule (the only model call)
        memory, hits = recall_block(cfg, user_input)
        if hits:
            yield {"type": "recalled", "items": [{"id": h["id"], "text": h["text"][:120], "score": h["score"]}
                                                 for h in hits], "step": 1}
        messages = [{"role": "system", "content": PROMPT.format(kinds=", ".join(KINDS), defaults=cfg.system_prompt)
                     + (f"\n\n{memory}" if memory else "")},
                    {"role": "user", "content": user_input}]
        answer = ""
        try:
            rule, event = self._ask_model(messages)
            yield event
            if not rule.get("source_folder", "").strip() and rule.get("question", "").strip():
                answer = ctx.ask(rule["question"])
                yield from ({**e, "step": 1} for e in self._drain(ctx))
                messages += [{"role": "assistant", "content": json.dumps(rule)},
                             {"role": "user", "content": f"Answer: {answer}"}]
                rule, event = self._ask_model(messages)
                yield event
        except Exception as e:
            yield {"type": "error", "content": f"Could not turn the task into a rule: {e}", "step": 1}
            return

        source = rule.get("source_folder", "").strip()
        if not source and answer.strip():
            source = answer.strip()  # the user's answer to "which folder?" IS the folder
        rules = []
        for r in rule.get("rules") or []:
            r = {"extensions": [x.strip().lower() if x.strip().startswith(".") else "." + x.strip().lower()
                                for x in r.get("extensions") or [] if x.strip()],
                 "kinds": [k for k in r.get("kinds") or [] if k in KINDS],
                 "name_contains": str(r.get("name_contains") or "").strip(),
                 "destination": str(r.get("destination") or "").strip()}
            if r["destination"] and (r["extensions"] or r["kinds"] or r["name_contains"]):
                if "/" not in r["destination"] and not r["destination"].startswith("~"):
                    r["destination"] = f"{source.rstrip('/')}/{r['destination']}"
                rules.append(r)
        if not source or not rules:
            led.update(1, "blocked", "task did not give a folder and a file type")
            yield {"type": "ledger", "ledger": led.to_dict(), "step": 1}
            yield {"type": "error", "step": 1, "content": "Could not make a rule: name the folder and what to move "
                                                          "where, e.g. 'move .pdf in ~/Downloads to all_pdf'."}
            return
        text = "\n".join(f"RULE {rule_text(source, r)}" for r in rules)
        led.attach("rule", "ok " + text.replace("\n", " | "))
        led.update(1, "done", text.replace("\n", " | ")[:150])
        yield {"type": "rule", "rules": rules, "source": source, "text": text, "step": 1}
        yield {"type": "ledger", "ledger": led.to_dict(), "step": 1}

        # ---- 2. preview + your approval
        try:
            previews = [files._preview_move_files(source, r["destination"], ",".join(r["extensions"]),
                                                  ",".join(r["kinds"]), r["name_contains"]) for r in rules]
        except Exception as e:
            yield from ({**ev, "step": 2} for ev in self._drain(ctx))
            led.update(2, "blocked", str(e)[:120])
            yield {"type": "ledger", "ledger": led.to_dict(), "step": 2}
            yield {"type": "error", "content": f"Rule can't run: {e}", "step": 2}
            return
        yield from ({**ev, "step": 2} for ev in self._drain(ctx))
        if self.should_stop():
            yield {"type": "stopped", "content": "Stopped by user.", "step": 2}
            return
        args = {"rule": text, "will_do": " | ".join(previews)}
        if cfg.permissions.mode("files.move") == ASK:
            yield {"type": "approval_needed", "name": "apply_rule", "args": args, "step": 2}
            decision = self.approver("apply_rule", args) if self.approver else "no"
            ok = decision in ("yes", "all", True)
            yield {"type": "approval", "name": "apply_rule", "approved": ok, "step": 2}
            if not ok:
                led.update(2, "blocked", "you did not approve the rule")
                yield {"type": "ledger", "ledger": led.to_dict(), "step": 2}
                yield {"type": "answer", "content": f"NOT APPLIED · rule denied\n{text}", "step": 2}
                return
        led.attach("approval", "ok approved")
        led.update(2, "done", "rule approved")
        yield {"type": "ledger", "ledger": led.to_dict(), "step": 2}

        # ---- 3. code moves the files
        problems = []
        for r in rules:
            if self.should_stop():
                yield {"type": "stopped", "content": "Stopped by user.", "step": 3}
                return
            call = {"folder": source, "destination_folder": r["destination"], "extensions": ",".join(r["extensions"]),
                    "kinds": ",".join(r["kinds"]), "name_contains": r["name_contains"]}
            yield {"type": "tool_call", "name": "move_files", "args": call, "step": 3}
            try:
                result = files.move_files(**call)
            except Exception as e:
                result = f"Error: {e}"
            yield from ({**ev, "step": 3} for ev in self._drain(ctx))
            if "NOT MOVED" in result or result.startswith("Error"):
                problems.append(result)
            led.attach("move_files", result)
            yield {"type": "tool_result", "name": "move_files", "result": result, "step": 3}
        led.update(3, "done", "code ran the rule")
        yield {"type": "ledger", "ledger": led.to_dict(), "step": 3}

        # ---- 4. code checks the result exactly (no model)
        left = []
        for r in rules:
            _, remaining = files._batch(source, ",".join(r["extensions"]), ",".join(r["kinds"]),
                                        r["name_contains"], r["destination"])
            left += [p.name for p in remaining]
        moved = self.state["changes"]
        complete = not left
        reason = (f"no matching files left in {files.short(source)}" if complete
                  else f"{len(left)} matching files still in {files.short(source)}")
        yield {"type": "verification", "attempt": 1, "complete": complete, "reason": reason,
               "missing": ", ".join(left[:20]), "step": 4}
        led.attach("check", ("ok " if complete else "ERR ") + reason)
        led.update(4, "done" if complete else "blocked", reason)
        yield {"type": "ledger", "ledger": led.to_dict(), "step": 4}

        lines = [("DONE ✓" if complete else "PARTLY DONE ⚠"), text,
                 f"changes {moved} · left {len(left)}" + (f" · problems {len(problems)}" if problems else "")]
        if left:
            lines.append("left: " + ", ".join(left[:10]) + (" …" if len(left) > 10 else ""))
        yield {"type": "answer", "content": "\n".join(lines), "step": 4}


# ====================================================================== email rule mode

EMAIL_RULE_SCHEMA = {
    "type": "object",
    "properties": {
        "folder": {"type": "string"},
        "unread_only": {"type": "boolean"},
        "rules": {"type": "array", "items": {
            "type": "object",
            "properties": {"from_contains": {"type": "string"}, "subject_contains": {"type": "string"},
                           "destination": {"type": "string"}},
            "required": ["from_contains", "subject_contains", "destination"]}},
        "question": {"type": "string"},
    },
    "required": ["folder", "unread_only", "rules", "question"],
}
EMAIL_PROMPT = """Turn the user's email-organizing task into rules. Do NOT do the task.
- folder: the mail folder to organize, usually "INBOX".
- unread_only: true only if the user said unread/new emails.
- rules: one per destination. Match by from_contains (part of the sender, e.g. "amazon" or
  "@swiggy.in") and/or subject_contains (e.g. "invoice"). Leave a field "" if not used.
  destination: the folder/label to move them to, e.g. "Receipts".
- Only what the user asked; if unclear, use the default instructions. If you can't tell what to
  move where, put a short question in `question` (otherwise "").

Default instructions:
{defaults}"""


def email_rule_text(folder, r, unread):
    match = " ".join(x for x in [f'from "{r["from_contains"]}"' if r["from_contains"] else "",
                                 f'subject "{r["subject_contains"]}"' if r["subject_contains"] else "",
                                 "unread" if unread else ""] if x)
    return f"{folder} · {match} → {r['destination']}"


class EmailRuleAgent(RuleAgent):
    """Same flow as file rules: the model writes rules once; code searches, moves and checks."""

    def _ask_email_model(self, messages):
        cfg = self.config
        started = time.time()
        resp = llm.chat(cfg.model, messages, temperature=0, think=False, format=EMAIL_RULE_SCHEMA,
                        num_ctx=cfg.context_length, num_predict=600)
        event = {"type": "model_call", "purpose": "rule", "step": 1, "seconds": round(time.time() - started, 1),
                 "prompt_tokens": resp.prompt_eval_count or 0, "output_tokens": resp.eval_count or 0,
                 "thinking": "", "content": resp.message.content or ""}
        return json.loads(resp.message.content), event

    def run(self, user_input):
        from .toolkits import mail
        cfg = self.config
        ctx = ToolContext(cfg, self.state, approver=self.approver, asker=self.asker)
        set_context(ctx)
        led = Ledger(job=self.job_id, task=user_input)
        for t in ("Turn task into email rules", "You approve the rules", "Move emails (code)", "Check result (code)"):
            led.add(t)
        self.ledger = led
        yield {"type": "plan", "steps": [s.title for s in led.steps], "step": 0}
        yield {"type": "ledger", "ledger": led.to_dict(), "step": 0}

        # ---- 1. the model writes the rules (the only model call)
        memory, hits = recall_block(cfg, user_input)
        if hits:
            yield {"type": "recalled", "items": [{"id": h["id"], "text": h["text"][:120], "score": h["score"]}
                                                 for h in hits], "step": 1}
        messages = [{"role": "system", "content": EMAIL_PROMPT.format(defaults=cfg.system_prompt)
                     + (f"\n\n{memory}" if memory else "")},
                    {"role": "user", "content": user_input}]
        try:
            spec, event = self._ask_email_model(messages)
            yield event
            if not spec.get("rules") and spec.get("question", "").strip():
                answer = ctx.ask(spec["question"])
                yield from ({**e, "step": 1} for e in self._drain(ctx))
                messages += [{"role": "assistant", "content": json.dumps(spec)},
                             {"role": "user", "content": f"Answer: {answer}"}]
                spec, event = self._ask_email_model(messages)
                yield event
        except Exception as e:
            yield {"type": "error", "content": f"Could not turn the task into email rules: {e}", "step": 1}
            return
        folder = (spec.get("folder") or "INBOX").strip()
        unread = bool(spec.get("unread_only"))
        rules = [{"from_contains": str(r.get("from_contains") or "").strip(),
                  "subject_contains": str(r.get("subject_contains") or "").strip(),
                  "destination": str(r.get("destination") or "").strip()}
                 for r in spec.get("rules") or []]
        rules = [r for r in rules if r["destination"] and (r["from_contains"] or r["subject_contains"])]
        if not rules:
            led.update(1, "blocked", "no usable rule")
            yield {"type": "ledger", "ledger": led.to_dict(), "step": 1}
            yield {"type": "error", "step": 1, "content": "Could not make a rule: say which emails go where, e.g. "
                                                          "'move emails from amazon to Receipts'."}
            return
        text = "\n".join(f"RULE {email_rule_text(folder, r, unread)}" for r in rules)
        led.attach("rule", "ok " + text.replace("\n", " | "))
        led.update(1, "done", text.replace("\n", " | ")[:150])
        yield {"type": "rule", "rules": rules, "source": folder, "text": text, "step": 1}
        yield {"type": "ledger", "ledger": led.to_dict(), "step": 1}

        # ---- 2. preview (server-side search) + your approval
        try:
            conn = mail._connect()
        except Exception as e:
            yield from ({**ev, "step": 2} for ev in self._drain(ctx))
            yield {"type": "error", "content": f"Could not connect to email: {e}", "step": 2}
            return
        try:
            matches, previews = [], []
            for r in rules:
                uids = mail.search_uids(conn, folder, r["from_contains"], r["subject_contains"], unread)
                sample = mail.headers(conn, uids[-5:])
                matches.append(uids)
                previews.append(f"{len(uids)} emails → {r['destination']}"
                                + (": " + "; ".join(f"{s[:50]} ({f[:30]})" for _, f, s in sample) if sample else ""))
            yield from ({**ev, "step": 2} for ev in self._drain(ctx))
            args = {"rule": text, "will_do": " | ".join(previews)}
            if cfg.permissions.mode("email.organize") == ASK:
                yield {"type": "approval_needed", "name": "apply_rule", "args": args, "step": 2}
                decision = self.approver("apply_rule", args) if self.approver else "no"
                if decision not in ("yes", "all", True):
                    yield {"type": "approval", "name": "apply_rule", "approved": False, "step": 2}
                    led.update(2, "blocked", "you did not approve the rules")
                    yield {"type": "ledger", "ledger": led.to_dict(), "step": 2}
                    yield {"type": "answer", "content": f"NOT APPLIED · rules denied\n{text}", "step": 2}
                    return
                yield {"type": "approval", "name": "apply_rule", "approved": True, "step": 2}
            led.attach("approval", "ok approved")
            led.update(2, "done", "rules approved")
            yield {"type": "ledger", "ledger": led.to_dict(), "step": 2}

            # ---- 3. code moves the emails
            moved, problems = 0, []
            for r, uids in zip(rules, matches):
                if self.should_stop():
                    yield {"type": "stopped", "content": "Stopped by user.", "step": 3}
                    return
                call = {"from_folder": folder, "to_folder": r["destination"], "emails": len(uids)}
                yield {"type": "tool_call", "name": "move_emails", "args": call, "step": 3}
                if not uids:
                    result = f"OK nothing matches · moved 0 → {r['destination']}"
                else:
                    try:
                        n = mail.move_uids(conn, uids, folder, r["destination"])
                        moved += n
                        for uid in uids:
                            yield {"type": "email_op", "op": "move", "uid": uid, "from_folder": folder,
                                   "to_folder": r["destination"], "step": 3}
                        result = f"OK moved {n} emails {folder} → {r['destination']}"
                    except Exception as e:
                        result = f"Error: {e}"
                        problems.append(result)
                led.attach("move_emails", result)
                yield {"type": "tool_result", "name": "move_emails", "result": result, "step": 3}
            led.update(3, "done", f"code moved {moved} emails")
            yield {"type": "ledger", "ledger": led.to_dict(), "step": 3}

            # ---- 4. code checks: nothing matching is left in the source folder
            left = sum(len(mail.search_uids(conn, folder, r["from_contains"], r["subject_contains"], unread))
                       for r in rules)
        finally:
            try:
                conn.logout()
            except Exception:
                pass
        complete = left == 0 and not problems
        reason = f"no matching emails left in {folder}" if complete else f"{left} matching emails still in {folder}"
        yield {"type": "verification", "attempt": 1, "complete": complete, "reason": reason,
               "missing": "" if complete else reason, "step": 4}
        led.attach("check", ("ok " if complete else "ERR ") + reason)
        led.update(4, "done" if complete else "blocked", reason)
        yield {"type": "ledger", "ledger": led.to_dict(), "step": 4}
        yield {"type": "answer", "step": 4, "content": "\n".join(
            [("DONE ✓" if complete else "PARTLY DONE ⚠"), text,
             f"moved {moved} emails · left {left}" + (f" · problems {len(problems)}" if problems else "")])}
