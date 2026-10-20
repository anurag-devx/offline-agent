"""
engine/context.py: what a running tool knows about the agent that called it.

Tools are plain functions, so the agent stores a ToolContext for the current thread
before running them. Through it a tool can:
    read the agent's config (permissions, scopes)
    record events for the run log (network requests, file changes...)
    ask you for approval mid-tool (e.g. "grant access to ~/Pictures?")
    ask you a question
`state` lives on the Agent, so grants and counters last for the whole run.
"""
import threading
from datetime import datetime

_local = threading.local()


class ToolContext:
    def __init__(self, config, state, approver=None, asker=None):
        self.config = config
        self.state = state          # {"granted_folders": [], "granted_domains": [], "changes": 0}
        self.approver = approver
        self.asker = asker
        self.events = []
        self.ledger = None          # job notes, when the agent uses them
        self.job = ""               # job id, so memory notes can point back to their run

    def record(self, kind, **data):
        self.events.append({"type": kind, "time": datetime.now().isoformat(timespec="seconds"), **data})

    def approve(self, name, args):
        self.record("approval_needed", name=name, args=args)
        decision = self.approver(name, args) if self.approver else "no"
        ok = decision in ("yes", "all", True)
        self.record("approval", name=name, approved=ok)
        return ok

    def ask(self, question):
        self.record("question", question=question)
        answer = self.asker(question) if self.asker else "(No answer available: this is a test run.)"
        self.record("answer_given", answer=answer)
        return answer


def set_context(ctx):
    _local.ctx = ctx


def get_context():
    ctx = getattr(_local, "ctx", None)
    if ctx is None:
        raise RuntimeError("This tool must be run by an agent.")
    return ctx
