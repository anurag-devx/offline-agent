"""
engine/runs.py: run agents in the background, track them, and record everything.

A Run is one task given to one agent (plus any follow-up messages).
Each run (job) gets a folder runs/<id>/ with:
    notes.md      the job notes: plan, checklist, agent's one-liners, code's evidence
    agent.yaml    the exact agent config used
    meta.json     status, counters, timings (updated live)
    events.jsonl  every step, one JSON line each

Statuses: running, waiting_approval, waiting_input (a question for you), verifying,
completed, failed, stopped, interrupted (the app closed while it was active).

If the agent has verification on, every time it says "done" a read-only verifier checks the
real state. Not done -> the agent is told what's missing and continues, until verified,
out of attempts, or you press Stop.
"""
import json
import shutil
import threading
import time
import uuid
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from . import audit
from .ledger import Ledger
from .rules import make_agent
from .config import ROOT
from .verifier import verify

RUNS_DIR = ROOT / "runs"
ACTIVE = ("running", "waiting_approval", "waiting_input", "verifying")
WAITING = ("waiting_approval", "waiting_input")


def _now():
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class Run:
    id: str
    agent: str
    model: str
    task: str
    status: str = "running"
    started: str = ""
    ended: str = ""
    steps: int = 0
    tool_calls: int = 0
    network_requests: int = 0
    file_changes: int = 0
    email_changes: int = 0
    prompt_tokens: int = 0
    output_tokens: int = 0
    turns: int = 1
    answer: str = ""
    pending: dict = None          # {"kind": "approval", name, args} or {"kind": "question", question}
    undone: bool = False
    wait_s: float = 0.0           # time spent waiting for your approvals / answers
    verify_s: float = 0.0         # model time spent by the verifier
    ledger: dict = None           # job notes (plan + checklist)
    attempts: int = 0             # verification rounds
    verified: bool = False
    config: dict = field(default_factory=dict)
    events: list = field(default_factory=list)

    @property
    def active(self):
        return self.status in ACTIVE

    def duration(self):
        try:
            end = datetime.fromisoformat(self.ended) if self.ended else datetime.now()
            return (end - datetime.fromisoformat(self.started)).total_seconds()
        except Exception:
            return 0.0


class RunManager:
    def __init__(self, unattended=False):
        self.unattended = unattended  # True = nobody is watching (headless scheduler)
        self.runs = {}
        self._lock = threading.Lock()
        self._agents, self._stops, self._decisions, self._auto = {}, {}, {}, {}
        self._load_history()

    # ---------------------------------------------------------------- public API
    def start(self, cfg, task, auto=None):
        """auto (Test Bench only): {"approve": "all"|"no", "answers": [...]} answers approvals and
        questions automatically, because the bench limits the agent to a sandbox folder."""
        rid = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
        run = Run(id=rid, agent=cfg.name, model=cfg.model, task=task,
                  started=_now(), config=cfg.to_dict())
        (RUNS_DIR / rid).mkdir(parents=True)
        (RUNS_DIR / rid / "agent.yaml").write_text(cfg.to_yaml(), encoding="utf-8")
        self.runs[rid] = run
        self._stops[rid] = threading.Event()
        if auto:
            self._auto[rid] = {"approve": auto.get("approve", "all"), "answers": list(auto.get("answers") or [])}
        self._agents[rid] = make_agent(
            cfg, job_id=rid,
            approver=lambda n, a: self._wait(rid, {"kind": "approval", "name": n, "args": a}, "no"),
            asker=lambda q: self._wait(rid, {"kind": "question", "question": q}, "(The run was stopped.)"),
            should_stop=self._stops[rid].is_set)
        audit.log("run_started", run=rid, agent=cfg.name, model=cfg.model, task=task)
        self._launch(rid, task)
        return run

    def send(self, rid, message):
        """Follow-up message in an existing run (the agent remembers the conversation)."""
        run = self.runs[rid]
        if not self.can_continue(rid):
            raise ValueError("This run can't take new messages.")
        run.turns += 1
        run.ended = ""
        self._stops[rid].clear()
        audit.log("run_message", run=rid, message=message)
        self._launch(rid, message)

    def decide(self, rid, choice):
        """Answer an approval request: "yes", "all" (rest of this run) or "no"."""
        self._resolve(rid, choice, "approval")

    def answer(self, rid, text):
        """Answer the agent's question."""
        self._resolve(rid, text, "answer")

    def _resolve(self, rid, value, action):
        decision = self._decisions.get(rid)
        if decision:
            audit.log(action, run=rid, value=value, request=self.runs[rid].pending)
            decision["value"] = value
            decision["event"].set()

    def undo_file_changes(self, rid):
        """Put moved files back and remove folders the run created (if still empty).
        New files, edits and Trash deletions are left as they are and reported."""
        run = self.runs[rid]
        results = []
        for e in reversed([e for e in run.events if e["type"] == "file_op"]):
            op = e["op"]
            try:
                if op == "move":
                    src, dst = Path(e["src"]), Path(e["dst"])
                    if dst.exists() and not src.exists():
                        src.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(dst), str(src))
                        results.append({"op": op, "file": e["src"], "result": "moved back"})
                    else:
                        results.append({"op": op, "file": e["src"], "result": "skipped (changed since)"})
                elif op == "create_folder":
                    p = Path(e["dst"])
                    if p.is_dir() and not any(p.iterdir()):
                        p.rmdir()
                        results.append({"op": op, "file": e["dst"], "result": "removed (empty)"})
                    else:
                        results.append({"op": op, "file": e["dst"], "result": "kept (not empty)"})
                elif op == "delete":
                    results.append({"op": op, "file": e["src"], "result": "restore it from the Trash"})
                else:
                    results.append({"op": op, "file": e.get("dst"), "result": "left as is"})
            except Exception as ex:
                results.append({"op": op, "file": e.get("src") or e.get("dst"), "result": f"failed: {ex}"})
        run.undone = True
        self._record(run, {"type": "undo", "results": results})
        audit.log("undo", run=rid, results=results)
        return results

    def stop(self, rid):
        if rid in self._stops:
            self._stops[rid].set()
            audit.log("run_stop_requested", run=rid)

    def can_continue(self, rid):
        """Only runs started in this session (agent still in memory) and not busy."""
        return rid in self._agents and not self.runs[rid].active

    def list(self):
        return sorted(self.runs.values(), key=lambda r: r.started, reverse=True)

    def counts(self):
        return Counter(r.status for r in self.runs.values())

    # ---------------------------------------------------------------- internals
    def _launch(self, rid, text):
        run = self.runs[rid]
        run.status = "running"
        self._record(run, {"type": "user", "content": text})
        threading.Thread(target=self._work, args=(rid, text), daemon=True).start()

    def _work(self, rid, text):
        run, agent = self.runs[rid], self._agents[rid]
        cfg, stop = agent.config, self._stops[rid]
        message = text
        while True:
            final = self._turn(run, agent, message)
            if final != "completed" or not cfg.verify.enabled or cfg.mode == "rules":  # rule mode checks itself
                break
            if stop.is_set():
                final = "stopped"
                break
            run.status, run.attempts = "verifying", run.attempts + 1
            self._save(run)
            verdict = self._verify(run, agent, cfg)
            if stop.is_set():
                final = "stopped"
                break
            if verdict["complete"]:
                run.verified = True
                break
            limit = cfg.verify.max_attempts
            if limit and run.attempts >= limit:
                final = "failed"
                run.answer = f"Not verified after {run.attempts} attempts. Last check: {verdict['reason']}"
                break
            message = ("A verifier checked the real state and the task is NOT complete yet.\n"
                       f"Reason: {verdict['reason']}\nStill missing: {verdict['missing']}\n"
                       "Continue now and finish the task with your tools. Do not just describe or summarize.")
            self._record(run, {"type": "user", "content": message, "auto": True})
            run.status = "running"
        run.status, run.pending, run.ended = final, None, _now()
        self._save(run)
        if cfg.permissions.memory.run_summaries:
            try:
                from .memory import get_store, run_summary, scope_of
                mid = get_store().add(scope_of(cfg), run_summary(run, Ledger.from_dict(run.ledger) if run.ledger
                                                                 else None), kind="episode", run=rid)
                self._record(run, {"type": "memory_op", "op": "summary", "id": mid})
            except Exception as ex:
                self._record(run, {"type": "warning", "content": f"Could not save the run summary: {ex}"})
        audit.log("run_finished", run=rid, status=final, steps=run.steps, tool_calls=run.tool_calls,
                  file_changes=run.file_changes, verified=run.verified, attempts=run.attempts)

    def _turn(self, run, agent, message):
        """One pass of the agent loop. Returns completed / failed / stopped."""
        final = "failed"
        try:
            for e in agent.run(message):
                kind = e["type"]
                if kind == "model_call":
                    run.steps += 1
                    run.prompt_tokens += e["prompt_tokens"]
                    run.output_tokens += e["output_tokens"]
                elif kind == "tool_call":
                    run.tool_calls += 1
                elif kind == "network":
                    run.network_requests += 1
                elif kind == "file_op":
                    run.file_changes += 1
                elif kind == "email_op":
                    run.email_changes += 1
                elif kind == "answer":
                    run.answer, final = e["content"], "completed"
                elif kind == "stopped":
                    final = "stopped"
                elif kind == "error":
                    run.answer, final = e["content"], "failed"
                elif kind == "ledger":
                    run.ledger = e["ledger"]
                    self._write_notes(run)
                    continue  # notes live in notes.md + run.ledger, not repeated in the log
                elif kind == "verification" and agent.config.mode == "rules":
                    run.attempts, run.verified = 1, bool(e["complete"])
                self._record(run, e)
        except Exception as ex:
            self._record(run, {"type": "error", "content": f"Run crashed: {ex}"})
        return final

    def _write_notes(self, run):
        counters = {"file changes": run.file_changes, "tool calls": run.tool_calls,
                    "web requests": run.network_requests, "steps": run.steps}
        try:
            (RUNS_DIR / run.id / "notes.md").write_text(Ledger.from_dict(run.ledger).to_markdown(counters),
                                                       encoding="utf-8")
        except Exception:
            pass
        self._save(run)

    def _verify(self, run, agent, cfg):
        """Run the read-only verifier and record its steps compactly."""
        task = "\n".join(e["content"] for e in run.events if e["type"] == "user" and not e.get("auto"))
        self._record(run, {"type": "verify_start", "attempt": run.attempts})
        verdict = {"complete": False, "reason": "Verifier gave no verdict.", "missing": ""}
        for e in verify(cfg, task, list(run.events), agent.state["granted_folders"], self._stops[run.id].is_set,
                        notes=Ledger.from_dict(run.ledger).for_model() if run.ledger else ""):
            if e["type"] == "model_call":
                run.prompt_tokens += e["prompt_tokens"]
                run.output_tokens += e["output_tokens"]
                run.verify_s = round(run.verify_s + e.get("load_s", 0) + e.get("read_s", 0) + e.get("write_s", 0), 2)
            elif e["type"] == "tool_call":
                self._record(run, {"type": "verify_step", "name": e["name"], "args": e["args"]})
            elif e["type"] == "verdict":
                verdict = e
        self._record(run, {"type": "verification", "attempt": run.attempts, **{k: verdict[k] for k in
                                                                                ("complete", "reason", "missing")}})
        audit.log("verification", run=run.id, attempt=run.attempts, complete=verdict["complete"],
                  reason=verdict["reason"])
        return verdict

    def _wait(self, rid, pending, default):
        """Called from the agent's thread. Blocks until you answer in the UI (or Stop).
        A threading.Event is a flag one thread waits on and another thread sets."""
        run = self.runs[rid]
        auto = self._auto.get(rid)
        if auto is not None:  # Test Bench: answer automatically and say so in the log
            if pending["kind"] == "question":
                answer = auto["answers"].pop(0) if auto["answers"] else "Use your best judgment."
                self._record(run, {"type": "warning", "content": f"Bench answered the question: {answer}"})
                return answer
            self._record(run, {"type": "warning", "content": f"Bench {'approved' if auto['approve'] != 'no' else 'denied'}"
                                                             f" '{pending.get('name')}' automatically (sandbox only)."})
            return auto["approve"]
        if self.unattended:  # nobody can answer: deny / no answer, and say so in the log
            self._record(run, {"type": "warning", "content": f"Unattended run: '{pending.get('name') or 'question'}' "
                                                             "was denied automatically (no one to approve)."})
            if pending["kind"] == "question":
                return "(No one is available to answer: this is an unattended scheduled run. Use your best judgment.)"
            return default
        decision = {"event": threading.Event(), "value": default}
        self._decisions[rid] = decision
        run.pending = pending
        run.status = "waiting_input" if pending["kind"] == "question" else "waiting_approval"
        self._save(run)
        waited = time.time()
        while not decision["event"].wait(0.5):
            if self._stops[rid].is_set():
                break
        run.wait_s = round(run.wait_s + time.time() - waited, 1)
        self._decisions.pop(rid, None)
        run.pending, run.status = None, "running"
        self._save(run)
        return decision["value"]

    def _record(self, run, event):
        event = {"time": _now(), **event}
        with self._lock:
            run.events.append(event)
            (RUNS_DIR / run.id).mkdir(parents=True, exist_ok=True)  # robust to late writes / moved folders
            with open(RUNS_DIR / run.id / "events.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(event, default=str) + "\n")
        self._save(run)

    def _save(self, run):
        meta = {k: v for k, v in asdict(run).items() if k != "events"}
        with self._lock:
            (RUNS_DIR / run.id).mkdir(parents=True, exist_ok=True)
            (RUNS_DIR / run.id / "meta.json").write_text(
                json.dumps(meta, indent=2, default=str), encoding="utf-8")

    def _load_history(self):
        RUNS_DIR.mkdir(exist_ok=True)
        for meta_path in RUNS_DIR.glob("*/meta.json"):
            try:
                data = json.loads(meta_path.read_text(encoding="utf-8"))
                run = Run(**{k: v for k, v in data.items() if k in Run.__dataclass_fields__})
                events_path = meta_path.parent / "events.jsonl"
                if events_path.exists():
                    run.events = [json.loads(line) for line in
                                  events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
                if run.status in ACTIVE:
                    run.status, run.pending = "interrupted", None
                self.runs[run.id] = run
            except Exception:
                continue


_manager = None
_manager_lock = threading.Lock()


def get_manager(unattended=False):
    """One RunManager per app process, shared by every page and browser tab."""
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = RunManager(unattended=unattended)
        return _manager
