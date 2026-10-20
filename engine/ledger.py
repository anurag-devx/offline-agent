"""
engine/ledger.py: the job's notes. A plan, a checklist, and evidence per step.

Code owns the notes; the model can only:
    update_step(step, status, note)  -> close a step with a one-line note
    add_step(title)                  -> add a step it discovered
Code attaches evidence (what each tool call really did) to the current step, refuses a "done"
whose tool calls all failed, and flags a "done" when code saw something the note doesn't say.

The notes are sent to the model at the END of every call (so they're never cut off), and
messages from closed steps are dropped: the notes replace them. That keeps the context small.
"""
from dataclasses import asdict, dataclass, field
from datetime import datetime

ICON = {"todo": "▢", "done": "✓", "skipped": "–", "blocked": "✗"}
BOX = {"todo": "[ ]", "done": "[x]", "skipped": "[-]", "blocked": "[!]"}
FAIL_PREFIXES = ("Error", "The user denied", "REFUSED", "ERR")


@dataclass
class Step:
    n: int
    title: str
    status: str = "todo"        # todo | done | skipped | blocked
    note: str = ""              # the agent's one-liner (a claim)
    evidence: list = field(default_factory=list)  # [{"tool", "ok", "warn", "text"}] (facts from code)
    flag: str = ""              # mismatch between the claim and what code saw
    unverified: bool = False    # closed without any tool evidence


@dataclass
class Ledger:
    job: str
    task: str
    steps: list = field(default_factory=list)
    updated: str = ""

    # ------------------------------------------------------------ changes
    def current(self):
        return next((s for s in self.steps if s.status == "todo"), None)

    def open_steps(self):
        return [s for s in self.steps if s.status == "todo"]

    def add(self, title):
        step = Step(n=len(self.steps) + 1, title=str(title).strip()[:80] or "step")
        self.steps.append(step)
        self._touch()
        return step

    def attach(self, tool, result):
        """Record what a tool call really did, on the current step."""
        step = self.current() or (self.steps[-1] if self.steps else None)
        if not step:
            return
        text = " / ".join(line.strip() for line in str(result).strip().splitlines()[:2])
        step.evidence.append({
            "tool": tool,
            "ok": not str(result).startswith(FAIL_PREFIXES),
            "warn": "not moved" in str(result).lower() or "skipped" in str(result).lower(),
            "text": text[:140],
        })
        step.evidence = step.evidence[-6:]
        self._touch()

    def update(self, n, status, note=""):
        """The model closes a step. Returns a short telegram-style reply."""
        try:
            n = int(n)
        except (TypeError, ValueError):
            return "ERR step must be a number"
        if not 1 <= n <= len(self.steps):
            return f"ERR no step {n}. Steps are 1-{len(self.steps)}"
        status = str(status).strip().lower()
        if status not in ("done", "skipped", "blocked"):
            return "ERR status must be done, skipped or blocked"
        step = self.steps[n - 1]
        if status == "done":
            ok = [e for e in step.evidence if e["ok"]]
            if step.evidence and not ok:
                return f"REFUSED step {n}: its tool calls failed. Fix it, or mark it blocked with a reason."
            step.unverified = not step.evidence
            warns = [e for e in step.evidence if e["warn"]]
            step.flag = f"code saw: {warns[-1]['text']}" if warns else ""
        elif not str(note).strip():
            return f"ERR give a reason in note when a step is {status}"
        step.status, step.note = status, str(note).strip()[:160]
        self._touch()
        nxt = self.current()
        return (f"OK step {n} {status}" + (f" ⚠ {step.flag}" if step.flag else "")
                + (f" · NOW step {nxt.n}: {nxt.title}" if nxt else " · all steps closed: give your final answer"))

    def _touch(self):
        self.updated = datetime.now().isoformat(timespec="seconds")

    # ------------------------------------------------------------ views
    def for_model(self):
        """Telegram-style notes for the model (~100-300 tokens)."""
        now = self.current()
        lines = [f"NOTES · JOB {self.job} · {self.task[:100]}"]
        for s in self.steps:
            line = f"{s.n} {ICON[s.status]} {s.title}"
            if s.note:
                line += f" · agent: {s.note}"
            if s.evidence:
                e = s.evidence[-1]
                line += f" · code: {'ok' if e['ok'] else 'ERR'} {e['tool']} {e['text'][:70]}"
            if s.flag:
                line += f" ⚠ {s.flag[:70]}"
            if s is now:
                line += "  ← NOW"
            lines.append(line)
        lines.append('Work on the NOW step. When it is finished: update_step(step, "done", "one line"). '
                     'Missing a step: add_step. Cannot do one: update_step(step, "skipped" or "blocked", reason).')
        return "\n".join(lines)

    def to_markdown(self, counters=None):
        done = sum(s.status != "todo" for s in self.steps)
        out = [f"# Job {self.job}", "", f"**Task:** {self.task}", "",
               f"**Progress:** {done}/{len(self.steps)} steps closed · updated {self.updated.replace('T', ' ')}"]
        if counters:
            out.append("**Recorded by code:** " + " · ".join(f"{k}: {v}" for k, v in counters.items()))
        out.append("")
        for s in self.steps:
            mark = " ⚠" if s.flag else (" (no evidence)" if s.unverified else "")
            out.append(f"- {BOX[s.status]} **{s.n}. {s.title}**{mark}")
            if s.note:
                out.append(f"  - agent says: {s.note}")
            for e in s.evidence[-3:]:
                out.append(f"  - code saw: {'✔' if e['ok'] else '✘'} `{e['tool']}` {e['text']}")
            if s.flag:
                out.append(f"  - ⚠ {s.flag}")
        return "\n".join(out) + "\n"

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(job=d["job"], task=d["task"], updated=d.get("updated", ""),
                   steps=[Step(**s) for s in d.get("steps", [])])
