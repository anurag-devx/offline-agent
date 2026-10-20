"""
engine/agent.py: the agent loop. This is the heart of the framework.

    task -> plan (job notes) -> ask the model <-------------------------------+
                                  |                                           |
                             wants a tool? -- yes --> "ask"? wait for your OK |
                                  |                       |                   |
                                  no                      run tool, attach evidence to notes
                                  |                       step closed? drop its old messages
                             open steps left? -- yes --> remind it (max 2x) --+
                                  |
                                  no -> final answer

The model never runs anything itself. It only *asks* for a tool; our code decides.
Every call sends: [system prompt] [task] [current step's messages] [NOTES]  (notes last = never cut off)
"""
import json
import time
import uuid

from .context import ToolContext, set_context
from .ledger import Ledger
from .llm import chat
from .permissions import ASK
from .tools import (get_schemas, internal_tools, is_internal, permission_of, preview_tool, run_tool,
                    tools_for)

DENIED = "The user denied this action. Do not try it again; continue without it or explain what you could not do."
TERSE = ("\n\nSTYLE (telegram): keep every reply short and factual. No essays, no restating lists or "
         "file names. Act with tools; write only to report. Final answer: at most 8 short lines.")
PLAN_SCHEMA = {"type": "object", "properties": {"steps": {"type": "array", "items": {"type": "string"}}},
               "required": ["steps"]}


def _normalize(decision):
    if decision is True:
        return "yes"
    return decision if decision in ("yes", "all") else "no"


class Agent:
    def __init__(self, config, approver=None, asker=None, should_stop=None, job_id=None):
        """
        approver(name, args) -> "yes" | "all" | "no"   for "ask" capabilities (None = deny)
        asker(question) -> str                         for the ask_user tool
        should_stop() -> bool                          checked between steps
        job_id                                         shown in the job notes
        """
        self.config = config
        self.approver = approver
        self.asker = asker
        self.should_stop = should_stop or (lambda: False)
        self.job_id = job_id or uuid.uuid4().hex[:4]
        self.reset()

    def reset(self):
        """Forget the conversation, notes and any access granted during it."""
        prompt = self.config.system_prompt + (TERSE if self.config.terse else "")
        self.messages = [{"role": "system", "content": prompt}]
        self.tags = [None]          # which step each message belongs to (None = keep forever)
        self.state = {"granted_folders": [], "granted_domains": [], "changes": 0}
        self.auto_approved = set()  # tools you chose "approve all" for, this run only
        self.ledger = None

    # ------------------------------------------------------------ helpers
    def _add(self, message, tag):
        self.messages.append(message)
        self.tags.append(tag)

    def _approve(self, name, args):
        decision = _normalize(self.approver(name, args) if self.approver else "no")
        if decision == "all":
            self.auto_approved.add(name)
        return decision

    def _call(self, messages, tools):
        cfg = self.config
        return chat(cfg.model, messages, tools=tools, temperature=cfg.temperature, think=cfg.think,
                    num_ctx=cfg.context_length, num_predict=cfg.max_reply_tokens or None)

    def _plan(self, task, names):
        """One model call: break the task into short steps (telegram style)."""
        cfg = self.config
        prompt = ("Break the task into 2-6 steps, max 8 words each, telegram style. Only steps that must be "
                  "done, in order. The last step checks the result.\n\n"
                  f"Agent role:\n{cfg.system_prompt[:1500]}\n\nTools: {', '.join(n for n in names if not is_internal(n))}")
        started = time.time()
        resp = chat(cfg.model, [{"role": "system", "content": prompt}, {"role": "user", "content": task}],
                    temperature=0, think=False, format=PLAN_SCHEMA, num_ctx=cfg.context_length, num_predict=300)
        steps = [str(s).strip() for s in json.loads(resp.message.content).get("steps", []) if str(s).strip()][:8]
        info = {"type": "model_call", "purpose": "plan", "seconds": round(time.time() - started, 1),
                "prompt_tokens": resp.prompt_eval_count or 0, "output_tokens": resp.eval_count or 0}
        return steps or [task[:80]], info

    def _compact(self):
        """Drop messages of closed steps. Their facts live on in the notes."""
        closed = {s.n for s in self.ledger.steps if s.status != "todo"}
        keep = [(m, t) for m, t in zip(self.messages, self.tags) if t is None or t not in closed]
        dropped = len(self.messages) - len(keep)
        self.messages, self.tags = [m for m, _ in keep], [t for _, t in keep]
        return dropped

    # ------------------------------------------------------------ the loop
    def run(self, user_input):
        """Work on one user message. Yields an event for every step."""
        cfg = self.config
        names = tools_for(cfg)
        notes_on = cfg.plan_steps
        if notes_on:
            names = names + internal_tools()
        schemas = get_schemas(names)
        ctx = ToolContext(cfg, self.state, approver=self._approve, asker=self.asker)
        set_context(ctx)
        self._add({"role": "user", "content": user_input}, None)

        if notes_on:
            if self.ledger is None:
                try:
                    steps, info = self._plan(user_input, names)
                    yield {**info, "step": 0, "thinking": "", "content": ""}
                except Exception as e:
                    steps = [user_input[:80]]
                    yield {"type": "warning", "step": 0, "content": f"Planning failed ({e}); using one step."}
                self.ledger = Ledger(job=self.job_id, task=user_input)
                for title in steps:
                    self.ledger.add(title)
                yield {"type": "plan", "steps": steps, "step": 0}
            elif not self.ledger.open_steps():
                self.ledger.add(f"Follow-up: {user_input[:70]}")
            ctx.ledger = self.ledger
            yield {"type": "ledger", "ledger": self.ledger.to_dict(), "step": 0}

        nudges = 0
        for step in range(1, cfg.max_steps + 1):
            if self.should_stop():
                yield {"type": "stopped", "content": "Stopped by user.", "step": step}
                return

            outgoing = self.messages + ([{"role": "user", "content": self.ledger.for_model()}] if notes_on else [])
            started = time.time()
            try:
                response = self._call(outgoing, schemas)
            except Exception as e:
                yield {"type": "error", "content": f"Model call failed: {e}", "step": step}
                return
            message = response.message
            tag = (self.ledger.current().n if self.ledger.current() else 0) if notes_on else None
            self._add(message, tag)
            yield {
                "type": "model_call", "step": step,
                "seconds": round(time.time() - started, 1),
                "prompt_tokens": response.prompt_eval_count or 0,
                "output_tokens": response.eval_count or 0,
                "thinking": (getattr(message, "thinking", None) or "")[:4000],
                "content": message.content or "",
            }
            used = response.prompt_eval_count or 0
            if cfg.context_length and used >= 0.95 * cfg.context_length:
                yield {"type": "warning", "step": step,
                       "content": f"The model's context window is full ({used:,} of {cfg.context_length:,} tokens). "
                                  "It may have lost its instructions. Raise Context length, or use tool filters."}

            if not message.tool_calls:
                open_steps = self.ledger.open_steps() if notes_on else []
                if open_steps and nudges < 2:
                    nudges += 1
                    text = (f"[status] Not finished: step(s) {', '.join(str(s.n) for s in open_steps)} still open. "
                            "Do them now with tools, or close each with update_step(step, \"skipped\", reason).")
                    self._add({"role": "user", "content": text}, tag)
                    yield {"type": "nudge", "content": text, "step": step}
                    continue
                yield {"type": "answer", "content": message.content or "", "step": step}
                return

            closed_before = sum(s.status != "todo" for s in self.ledger.steps) if notes_on else 0
            for call in message.tool_calls:
                if self.should_stop():
                    yield {"type": "stopped", "content": "Stopped by user.", "step": step}
                    return
                name, args = call.function.name, dict(call.function.arguments or {})
                yield {"type": "tool_call", "name": name, "args": args, "step": step}

                approved = True
                needs_ok = (name in names and cfg.permissions.mode(permission_of(name)) == ASK
                            and name not in self.auto_approved)
                if needs_ok:
                    shown = dict(args)
                    effect = preview_tool(name, args)
                    if effect:
                        shown["will_do"] = effect
                    for event in ctx.events:  # e.g. a folder grant needed by the preview
                        yield {**event, "step": step}
                    ctx.events.clear()
                    yield {"type": "approval_needed", "name": name, "args": shown, "step": step}
                    decision = self._approve(name, shown)
                    approved = decision != "no"
                    yield {"type": "approval", "name": name, "approved": approved,
                           "all": decision == "all", "step": step}
                result = run_tool(name, args, allowed=names) if approved else DENIED

                for event in ctx.events:  # side events: network, file changes, in-tool approvals
                    yield {**event, "step": step}
                ctx.events.clear()
                if notes_on and not is_internal(name):
                    self.ledger.attach(name, result)  # facts from code, not the model's claim
                yield {"type": "tool_result", "name": name, "result": result, "step": step}
                self._add({"role": "tool", "content": result, "tool_name": name}, tag)

            if notes_on:
                yield {"type": "ledger", "ledger": self.ledger.to_dict(), "step": step}
                if sum(s.status != "todo" for s in self.ledger.steps) > closed_before:
                    dropped = self._compact()
                    if dropped:
                        yield {"type": "compacted", "dropped": dropped, "step": step}

        yield {"type": "error", "step": cfg.max_steps,
               "content": f"Stopped after {cfg.max_steps} steps without a final answer. "
                          "Raise max steps, simplify the task, or try a bigger model."}

    def ask(self, user_input):
        """Simple version of run(): return only the final answer text."""
        for event in self.run(user_input):
            if event["type"] in ("answer", "error", "stopped"):
                return event["content"]
