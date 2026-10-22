"""
engine/relay.py: Relay. A PM agent splits a complex job into small chunks, small worker agents
do one chunk each (one after another), and the PM pulls everything back together.

    1. Plan       the PM writes the plan: a shared CONTRACT (names, ids, data every piece must use)
                  and small CHUNKS (one output each, with what it must contain)
    2. Build      one fresh worker per chunk. It sees only the brief, the contract, its chunk and
                  the files it depends on, so its context stays small. Code checks the output;
                  a failed chunk is retried with the reason (only that chunk)
    3. Integrate  a worker reads all outputs and fixes anything that doesn't fit together
    4. Review     the read-only Inspector checks the whole result against the task. The PM maps
                  anything missing to the chunks that must be redone, and they are rebuilt
    5. Done       code writes the final report

Code runs this loop, not a model: small models are poor managers. Everything is saved in the
run (run.relay), so a long job can stop and resume where it was.
"""
import copy
import json
import time
from pathlib import Path

from . import llm
from .config import VerifyConfig
from .speed import timing

MAX_CHUNKS = 12
CHUNK_TRIES = 3      # tries per chunk per round
REVIEW_ROUNDS = 2    # how many times the PM may send chunks back after the final review
WORKER_STEPS = 15

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "understanding": {"type": "string"},
        "contract": {"type": "string"},
        "chunks": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "id": {"type": "string"}, "title": {"type": "string"}, "output": {"type": "string"},
                "goal": {"type": "string"},
                "depends_on": {"type": "array", "items": {"type": "string"}},
                "must_contain": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["id", "title", "output", "goal", "depends_on", "must_contain"]}},
    },
    "required": ["understanding", "contract", "chunks"],
}

REDO_SCHEMA = {
    "type": "object",
    "properties": {"redo": {"type": "array", "items": {
        "type": "object", "properties": {"id": {"type": "string"}, "fix": {"type": "string"}},
        "required": ["id", "fix"]}}},
    "required": ["redo"],
}

PM_PLAN = """You are the PM (project manager) of a team of small AI workers. You do not do the work.
You split the job into small CHUNKS that one worker can finish alone in a few tool calls.

Rules:
- One chunk = one output file (or one clearly separate piece of work with output ""). A big file
  that has several parts (e.g. HTML, CSS, JS) gets one chunk per file. Small images/icons: one chunk each.
- Order chunks so that what others depend on comes first. At most {max} chunks.
- `output`: the file the chunk creates, as a path the worker can write: keep the folder the task
  names (e.g. "site/index.html", or the full path if the task gives one).
- `goal`: everything this chunk must contain, in detail. Copy exact texts, names, numbers, prices,
  addresses from the task. A worker sees only its own goal and the contract.
- `must_contain`: 2-10 short exact strings that must appear in the output (ids, names, key texts).
- `contract`: the shared agreement every chunk must follow: file names and paths, ids, class names,
  function and variable names, data (e.g. the full list of items with prices), colours. Be exact:
  this is how separate workers' pieces fit together.
- `understanding`: one sentence restating the job.

The team's role and tools:
{role}"""

PM_REDO = """You are the PM. A reviewer checked the finished job and found problems.
Decide which chunks must be redone to fix them. For each, give the chunk id and `fix`: exactly what
the worker must change or add. Only chunks that need changes. Chunks:
{chunks}"""

WORKER_NOTE = """

You are one worker in a team. A PM split a bigger job into chunks; you do ONLY your chunk.
Follow the CONTRACT exactly so your piece fits the others. Write your output completely with
write_file (if the file already exists, read it and use overwrite_file). No placeholders.
When your chunk is done, reply with one short line saying what you made."""


def _parse(resp):
    text = resp.message.content or ""
    try:
        return json.loads(text)
    except ValueError:
        found = llm._json_in(text)
        if not found:
            raise
        return json.loads(found)


def _call(cfg, system, user, schema, num_predict):
    started = time.time()
    resp = llm.chat(cfg.model, [{"role": "system", "content": system}, {"role": "user", "content": user}],
                    temperature=0, think=False, format=schema, num_ctx=cfg.context_length, num_predict=num_predict)
    return _parse(resp), {"type": "model_call", "seconds": round(time.time() - started, 1), **timing(resp),
                          "thinking": "", "content": ""}


def clean_plan(plan, task):
    """Make the PM's plan safe to run: unique ids, known dependencies, sane sizes."""
    chunks, seen = [], set()
    for i, c in enumerate((plan.get("chunks") or [])[:MAX_CHUNKS], 1):
        cid = str(c.get("id") or f"c{i}").strip() or f"c{i}"
        if cid in seen:
            cid = f"c{i}"
        seen.add(cid)
        must = [str(m).strip() for m in (c.get("must_contain") or []) if 0 < len(str(m).strip()) <= 60][:10]
        chunks.append({"id": cid, "title": str(c.get("title") or cid)[:80], "output": str(c.get("output") or "").strip(),
                       "goal": str(c.get("goal") or "").strip(), "must_contain": must,
                       "depends_on": [d for d in (c.get("depends_on") or []) if d in seen and d != cid],
                       "status": "todo", "tries": 0, "problems": [], "note": "", "path": "", "fix": ""})
    if not chunks:
        chunks = [{"id": "c1", "title": "Do the whole task", "output": "", "goal": task, "must_contain": [],
                   "depends_on": [], "status": "todo", "tries": 0, "problems": [], "note": "", "path": "", "fix": ""}]
    return {"understanding": str(plan.get("understanding") or "")[:300], "contract": str(plan.get("contract") or ""),
            "chunks": chunks}


def check_output(chunk, path):
    """Code's check of one chunk's file. Returns a list of problems (empty = passed)."""
    if not path or not Path(path).is_file():
        return [f"output file {chunk['output']} was not created"]
    body = Path(path).read_text(encoding="utf-8", errors="replace")
    low, problems = body.lower(), []
    if len(body.strip()) < 20:
        problems.append("the file is (almost) empty")
    missing = [m for m in chunk["must_contain"] if m.lower() not in low]
    if missing:
        problems.append("missing: " + ", ".join(missing))
    holders = [x for x in ("lorem ipsum", "your text here") if x in low] + (["TODO"] if "TODO" in body else [])
    if holders:
        problems.append("placeholder text: " + ", ".join(holders))
    return problems


def markdown(job_id, state):
    icon = {"todo": "[ ]", "done": "[x]", "failed": "[!]"}
    mins = round(state.get("elapsed_s", 0) / 60)
    out = [f"# Relay job {job_id}", "", f"**Task:** {state['task']}", "",
           f"**Phase:** {state['phase']} · review round {state.get('round', 0)}/{REVIEW_ROUNDS} · {mins} min", "",
           f"**PM's understanding:** {state.get('understanding', '')}", "", "**Contract:**", "",
           "```", state.get("contract", ""), "```", ""]
    for c in state["chunks"]:
        out.append(f"- {icon.get(c['status'], '[ ]')} **{c['id']}. {c['title']}**"
                   + (f" → `{c['output']}`" if c["output"] else "") + f" · tries {c['tries']}")
        if c.get("fix"):
            out.append(f"  - PM asked to fix: {c['fix']}")
        if c["problems"]:
            out.append(f"  - code saw: {'; '.join(c['problems'])}")
        if c["note"]:
            out.append(f"  - worker says: {c['note']}")
    if state.get("integrate"):
        out += ["", f"**Integration:** {state['integrate']}"]
    if state.get("review"):
        r = state["review"]
        out += ["", f"**Review:** {'passed' if r['complete'] else 'not passed'}: {r['reason']}"
                + (f" · missing: {r['missing']}" if r.get("missing") and not r["complete"] else "")]
    return "\n".join(out) + "\n"


class Relay:
    """Runs one Relay job inside a RunManager run. Code drives; models only plan and build."""

    def __init__(self, manager, run, cfg, task):
        self.m, self.run, self.cfg = manager, run, cfg
        self.stop = manager._stops[run.id]
        if not run.relay:
            run.relay = {"task": task, "phase": "plan", "round": 0, "elapsed_s": 0.0, "chunks": []}
        self.state = run.relay
        self.t0, self.e0 = time.time(), self.state.get("elapsed_s", 0.0)

    # ------------------------------------------------------------ helpers
    def _event(self, **e):
        self.m._record(self.run, {"type": "relay", **e})

    def _model(self, call, purpose):
        self.run.steps += 1
        self.run.prompt_tokens += call.get("prompt_tokens", 0)
        self.run.output_tokens += call.get("output_tokens", 0)
        self.m._record(self.run, {**call, "purpose": purpose, "step": 0})

    def _save(self):
        self.state["elapsed_s"] = round(self.e0 + time.time() - self.t0, 1)
        self.m._write_relay_notes(self.run)

    def _out_of_time(self):
        limit = self.cfg.time_limit_min * 60
        return bool(limit) and self.e0 + time.time() - self.t0 > limit

    def _worker_cfg(self):
        w = copy.deepcopy(self.cfg)
        w.system_prompt = self.cfg.system_prompt + WORKER_NOTE
        w.plan_steps, w.full_voice, w.route = False, False, "single"
        w.verify = VerifyConfig()
        w.max_steps = max(8, min(self.cfg.max_steps, WORKER_STEPS))
        return w

    def _find(self, chunk, since):
        """Where the chunk's output really is: the file the worker wrote (from code's log)."""
        want = chunk["output"].replace("\\", "/").lstrip("./").lower()
        if not want:
            return ""
        name = want.rsplit("/", 1)[-1]
        hits = [e.get("dst") or "" for e in self.run.events[since:] if e["type"] == "file_op"]
        hits += [c.get("path", "") for c in self.state["chunks"] if c["output"] == chunk["output"]]
        for h in reversed([h for h in hits if h]):
            p = str(h).replace("\\", "/").lower()
            if (p.endswith("/" + want) or p.endswith("/" + name)) and Path(h).is_file():
                return h
        for f in self.m.worker_roots(self.run.id):  # not written this time: look for it on disk
            for cand in (Path(f) / chunk["output"], Path(chunk["output"]).expanduser()):
                if cand.is_file():
                    return str(cand)
        return ""

    # ------------------------------------------------------------ phases
    def run_job(self):
        try:
            if self.state["phase"] == "plan":
                self.plan()
            while self.state["phase"] in ("build", "integrate", "review"):
                if self.stop.is_set():
                    return "stopped"
                if self._out_of_time():
                    self._event(phase=self.state["phase"], content=f"Time limit reached ({self.cfg.time_limit_min} min).")
                    return "stopped"
                getattr(self, self.state["phase"])()
            return "completed" if self.state["phase"] == "done" else "failed"
        finally:
            self._save()

    def plan(self):
        task = self.state["task"]
        system = PM_PLAN.format(max=MAX_CHUNKS, role=self.cfg.system_prompt[:2000])
        plan = None
        for attempt in range(2):
            try:
                raw, call = _call(self.cfg, system, task, PLAN_SCHEMA, 4000)
                self._model(call, "relay plan")
                plan = clean_plan(raw, task)
                break
            except Exception as e:
                self._event(phase="plan", content=f"PM plan failed ({e}); {'retrying' if not attempt else 'one chunk'}.")
        plan = plan or clean_plan({}, task)
        self.state.update(plan)
        self.state["phase"] = "build"
        self._event(phase="plan", content=f"PM split the job into {len(plan['chunks'])} chunks.",
                    chunks=[{"id": c["id"], "title": c["title"], "output": c["output"]} for c in plan["chunks"]])
        self._save()

    def build(self):
        for chunk in self.state["chunks"]:
            if chunk["status"] != "todo":
                continue
            while chunk["status"] == "todo":
                if self.stop.is_set() or self._out_of_time():
                    return
                self.build_chunk(chunk)
        self.state["phase"] = "integrate" if sum(1 for c in self.state["chunks"] if c["output"]) > 1 else "review"
        self._save()

    def build_chunk(self, chunk):
        chunk["tries"] += 1
        self._event(phase="build", chunk=chunk["id"], content=f"{chunk['id']} {chunk['title']} · try {chunk['tries']}")
        since = len(self.run.events)
        final = self.m._worker_turn(self.run, self._worker_cfg(), self.worker_message(chunk))
        if final == "stopped":
            chunk["tries"] -= 1
            return
        chunk["note"] = (self.run.answer or "")[:300]
        if chunk["output"]:
            chunk["path"] = self._find(chunk, since)
            chunk["problems"] = check_output(chunk, chunk["path"])
        else:
            chunk["problems"] = [] if final == "completed" and chunk["note"].strip() else ["the worker gave no result"]
        if not chunk["problems"]:
            chunk["status"] = "done"
        elif chunk["tries"] >= CHUNK_TRIES:
            chunk["status"] = "failed"
        self._event(phase="build", chunk=chunk["id"], status=chunk["status"], problems=chunk["problems"],
                    content=f"{chunk['id']} " + ("passed" if chunk["status"] == "done" else
                                                 "failed: " + "; ".join(chunk["problems"])))
        self._save()

    def worker_message(self, chunk):
        st = self.state
        by_id = {c["id"]: c for c in st["chunks"]}
        others = [f"- {c['id']} {c['title']}" + (f": {c['path'] or c['output']}" if c["output"] else
                                                f": {c['note'][:200]}")
                  for c in st["chunks"] if c["status"] == "done" and c["id"] != chunk["id"]]
        deps = [by_id[d] for d in chunk["depends_on"] if d in by_id]
        lines = [f"WHOLE JOB (context only, do not do all of it):\n{st['task'][:4000]}",
                 f"CONTRACT (use exactly these names):\n{st.get('contract') or '(none)'}"]
        if others:
            lines.append("ALREADY DONE BY OTHERS (exists now):\n" + "\n".join(others))
        lines.append(f"YOUR CHUNK {chunk['id']}: {chunk['title']}")
        if chunk["output"]:
            lines.append(f"Output file: {chunk['output']}")
        lines.append(f"Goal:\n{chunk['goal']}")
        if chunk["must_contain"]:
            lines.append("Must contain exactly: " + ", ".join(f'"{m}"' for m in chunk["must_contain"]))
        if deps:
            lines.append("Read first (you depend on them): " + ", ".join(
                (d["path"] or d["output"]) if d["output"] else f"{d['id']} result: {d['note'][:200]}" for d in deps))
        if chunk.get("fix"):
            lines.append(f"THE PM ASKS YOU TO FIX: {chunk['fix']}")
        if chunk["problems"] and chunk["tries"] > 1:
            lines.append("YOUR LAST TRY FAILED THE CHECK: " + "; ".join(chunk["problems"])
                         + ". Read the file and fix it with overwrite_file.")
        return "\n\n".join(lines)

    def integrate(self):
        st = self.state
        files = [c["path"] or c["output"] for c in st["chunks"] if c["output"] and c["status"] == "done"]
        self._event(phase="integrate", content=f"PM: checking that {len(files)} pieces fit together.")
        msg = (f"WHOLE JOB:\n{st['task'][:4000]}\n\nCONTRACT:\n{st.get('contract') or '(none)'}\n\n"
               "YOUR CHUNK: integration. Separate workers made these files:\n" + "\n".join(f"- {f}" for f in files)
               + "\n\nRead each file. Check they fit together and follow the contract: links and file names "
               "between files, every id/class/function one file uses exists in the other, the same data and "
               "names everywhere, nothing from the job left out. Fix any mismatch with overwrite_file "
               "(change only what is needed). Reply with one line: what you fixed, or 'all fits'.")
        final = self.m._worker_turn(self.run, self._worker_cfg(), msg)
        if final == "stopped":
            return
        st["integrate"] = (self.run.answer or "")[:300]
        st["phase"] = "review"
        self._save()

    def review(self):
        st = self.state
        st["round"] = st.get("round", 0) + 1
        self.run.attempts = st["round"]
        self._event(phase="review", content=f"Final review, round {st['round']}.")
        verdict = self.m._review(self.run, self.cfg, st["task"], markdown(self.run.id, st))
        st["review"] = {k: verdict.get(k, "") for k in ("complete", "reason", "missing")}
        if self.stop.is_set():
            st["round"] -= 1
            return
        if verdict["complete"]:
            self.run.verified = True
            st["phase"] = "done"
        elif st["round"] > REVIEW_ROUNDS:
            st["phase"] = "failed"
        else:
            self.send_back(verdict)
        self._save()

    def send_back(self, verdict):
        """The PM maps the review's findings to chunks to redo."""
        st = self.state
        listing = "\n".join(f"- {c['id']} {c['title']}" + (f" ({c['output']})" if c["output"] else "")
                            for c in st["chunks"])
        user = f"TASK:\n{st['task'][:3000]}\n\nREVIEW: {verdict['reason']}\nMISSING: {verdict.get('missing', '')}"
        redo = []
        try:
            raw, call = _call(self.cfg, PM_REDO.format(chunks=listing), user, REDO_SCHEMA, 800)
            self._model(call, "relay redo")
            redo = [r for r in raw.get("redo", []) if any(c["id"] == r.get("id") for c in st["chunks"])]
        except Exception as e:
            self._event(phase="review", content=f"PM could not map the findings ({e}).")
        if not redo:  # nothing mapped: one extra chunk that fixes what's missing
            n = sum(1 for c in st["chunks"] if c["id"].startswith("fix")) + 1
            st["chunks"].append({**clean_plan({}, "")["chunks"][0], "id": f"fix{n}", "title": "Fix what the review found",
                                 "goal": f"{verdict['reason']}\nMissing: {verdict.get('missing', '')}"})
        for r in redo:
            c = next(c for c in st["chunks"] if c["id"] == r["id"])
            c.update(status="todo", tries=0, fix=str(r.get("fix", ""))[:500], problems=[])
        self._event(phase="review", content="PM sent back: " + (", ".join(r["id"] for r in redo) or "a fix chunk"))
        st["phase"] = "build"

    def report(self):
        st = self.state
        done = [c for c in st["chunks"] if c["status"] == "done"]
        lines = [f"Relay: {len(done)}/{len(st['chunks'])} chunks done · review "
                 + ("passed" if self.run.verified else "not passed")
                 + f" · {round(st.get('elapsed_s', 0) / 60)} min", ""]
        if st.get("understanding"):
            lines += [st["understanding"], ""]
        lines.append("What was made:")
        for c in st["chunks"]:
            mark = "✓" if c["status"] == "done" else ("✗" if c["status"] == "failed" else "…")
            lines.append(f"- {mark} {c['title']}" + (f" → {c['path'] or c['output']}" if c["output"] else
                                                     (f": {c['note']}" if c["note"] else "")))
        if st.get("integrate"):
            lines += ["", f"Fitting it together: {st['integrate']}"]
        if st.get("review"):
            lines += ["", f"Review: {st['review']['reason']}"]
            if not st["review"]["complete"] and st["review"].get("missing"):
                lines.append(f"Still missing: {st['review']['missing']}")
        return "\n".join(lines)
