"""
engine/relay.py: Relay. A PM agent splits a complex job into small chunks, small worker agents
do one chunk each (one after another), and the PM pulls everything back together.

    1. Plan       the PM writes the plan: a shared CONTRACT (names, ids, data every piece must use),
                  small CHUNKS (one file, or ONE feature of a file) and, for web pages, browser
                  CHECKS of what the page must do
    2. Design     for visual work, the lead writes a concrete style guide every worker follows
    3. Build      one fresh worker per chunk. It sees only the brief, the contract, the style guide,
                  its chunk and the files it depends on. Code checks the output (and that it didn't
                  break another chunk's part of a shared file); a failed chunk is retried with the reason
    4. Integrate  a worker reads all outputs and fixes anything that doesn't fit together
    5. Test       code opens the page in a real browser and runs the checks; JavaScript errors and
                  failed checks go back to the chunk that owns them, as patch fixes
    6. Look       the lead looks at screenshots (desktop + phone) against the style guide; its
                  findings go back to the chunk that owns the file
    7. Review     the read-only Inspector checks the whole result against the task; the PM maps
                  anything missing to the chunks that must be redone
    8. Done       the PM writes the answer; code writes the report

Code runs this loop, not a model: small models are poor managers. The lead model (optional, e.g.
a bigger model) plans, designs, looks and writes the answer; workers use the agent's model.
Everything is saved in the run (run.relay), so a long job can stop and resume where it was.
"""
import copy
import json
import time
from pathlib import Path

from . import browser, llm
from .config import VerifyConfig
from .findings import PATCH_RULE, as_text, locate
from .speed import timing
from .tools import tools_for

MAX_CHUNKS = 16
CHUNK_TRIES = 3      # tries per chunk per round
REVIEW_ROUNDS = 2    # how many times the PM may send chunks back after the final review
TEST_ROUNDS = 3      # browser test runs (each failed run sends chunks back)
LOOK_ROUNDS = 1      # visual reviews
WORKER_STEPS = 15
LEAD_CTX = 16384     # the lead's prompts are short; a smaller context leaves memory for a bigger model
VISUAL = (".html", ".htm", ".css", ".svg")

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
        "page": {"type": "string"},
        "checks": {"type": "array", "items": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "owner": {"type": "string"},
                           "steps": {"type": "array", "items": {"type": "string"}}},
            "required": ["name", "owner", "steps"]}},
    },
    "required": ["understanding", "contract", "chunks", "page", "checks"],
}

REDO_SCHEMA = {
    "type": "object",
    "properties": {"redo": {"type": "array", "items": {
        "type": "object", "properties": {"id": {"type": "string"}, "fix": {"type": "string"}},
        "required": ["id", "fix"]}}},
    "required": ["redo"],
}

LOOK_SCHEMA = {
    "type": "object",
    "properties": {"looks_good": {"type": "boolean"}, "findings": {"type": "array", "items": {
        "type": "object", "properties": {"file": {"type": "string"}, "problem": {"type": "string"},
                                         "fix": {"type": "string"}},
        "required": ["file", "problem", "fix"]}}},
    "required": ["looks_good", "findings"],
}

PM_PLAN = """You are the PM (project manager) of a team of small AI workers. You do not do the work.
You split the job into small CHUNKS that one worker can finish alone in a few tool calls.

Rules:
- Keep chunks SMALL: one file, or ONE feature of a file. A file with several features gets several
  chunks with the same `output`: the first creates the file with its base (structure, data, shared
  helpers, a comment per section); each later chunk adds ONE feature to it. Example for script.js:
  "data + helpers", "cart", "menu filters", "form checks", "theme + open badge". Images: one chunk each.
- Order chunks so that what others depend on comes first. At most {max} chunks.
- `output`: the file the chunk creates or extends, as a path the worker can write: keep the folder
  the task names (e.g. "site/index.html", or the full path if the task gives one).
- `goal`: everything this chunk must do, in detail. Copy exact texts, names, numbers, prices,
  addresses from the task. A worker sees only its own goal, the contract and the style guide.
- `must_contain`: 2-10 short exact strings this chunk adds to the output (ids, names, function
  names, key texts).
- `contract`: the shared agreement every chunk must follow: file names and paths, ids, class names,
  function and variable names, data (e.g. the full list of items with prices). Be exact: this is
  how separate workers' pieces fit together.
- `understanding`: one sentence restating the job.
- Questions and analysis that need no file: `output` "" (the worker's reply is the result).
{files_rule}{web_rules}
The team's role:
{role}

The team's tools: {tools}"""

WEB_RULES = """
- If the job makes a web page: `page` = the path of the main HTML file, and `checks` = 4-10 browser
  tests of what the page must DO. Each: name, owner (the id of the chunk that builds that feature)
  and steps. Steps use only: click SEL | fill SEL TEXT | select SEL VALUE | expect_text SEL TEXT
  ("a|b" = either) | expect_no_text SEL TEXT | expect_visible SEL | expect_hidden SEL |
  expect_count SEL N | expect_at_least SEL N | expect_class SEL TEXT | reload | phone | desktop.
  SEL is CSS (#id, .class, [attr]) or text=Label; put it in double quotes if it has spaces. Use the
  ids and classes from the contract. Example:
  {{"name": "add to cart", "owner": "c5", "steps": ["click \\"text=Add to cart\\"", "expect_text #cart ₹"]}}
  Not a web page: page "" and checks []."""

PM_DESIGN = """You are the design lead. Write a concrete STYLE GUIDE for this job that several developers
will follow exactly. Decide; don't offer options. Short lines with exact values, no code:
- Colours (hex): background, surface/card, text, muted text, primary, primary hover, accent, border,
  error, success; and the dark theme versions if the job has a dark mode.
- Typography: font stack (system fonts only), sizes for h1/h2/h3/body/small, weights, line height.
- Spacing scale, max content width, section padding.
- Shapes: border radius, shadows, borders.
- Components: header and nav (desktop and phone), buttons (primary, secondary, hover, focus), cards,
  form fields (labels, inputs, error messages), tables, badges.
- Layout of each section, and how it changes on a phone (one breakpoint).
- Images and illustrations: style, colours, size.
Aim for a clean, modern, professional look with generous spacing and clear hierarchy."""

PM_REDO = """You are the PM. A reviewer checked the finished job and found problems.
Decide which chunks must be redone to fix them. For each, give the chunk id and `fix`: exactly what
the worker must change or add. Only chunks that need changes. Chunks:
{chunks}"""

PM_LOOK = """You are the design lead. The first image is the page on a desktop (full length), the second
on a phone. Compare them with the style guide and the task. List the most important visual problems
(at most 6): layout, alignment, spacing, readability, contrast, anything that looks broken, unfinished
or cramped, and the phone layout. For each: file (the .css or .html file to change), problem, and a
concrete fix (the CSS or HTML change). If it looks good and matches the guide, looks_good = true and
an empty list.

STYLE GUIDE:
{design}"""

WORKER_NOTE = """

You are one worker in a team. A PM split a bigger job into chunks; you do ONLY your chunk.
Follow the CONTRACT and the STYLE GUIDE exactly so your piece fits the others. Write a NEW output
completely with write_file. If the file already exists, change only what's needed with edit_file /
insert_lines (read_lines shows the exact text); never remove parts other workers made. No placeholders.
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


def _call(model, ctx, system, user, schema, num_predict, images=None):
    started = time.time()
    msg = {"role": "user", "content": user}
    if images:
        msg["images"] = list(images)
    resp = llm.chat(model, [{"role": "system", "content": system}, msg],
                    temperature=0, think=False, format=schema, num_ctx=ctx, num_predict=num_predict)
    return (_parse(resp) if schema else (resp.message.content or "")), \
        {"type": "model_call", "seconds": round(time.time() - started, 1), **timing(resp), "thinking": "", "content": ""}


def _chunk(cid, title, output="", goal="", must=(), deps=()):
    return {"id": cid, "title": title, "output": output, "goal": goal, "must_contain": list(must),
            "depends_on": list(deps), "status": "todo", "tries": 0, "problems": [], "note": "", "path": "",
            "fix": "", "facts": ""}


def clean_plan(plan, task):
    """Make the PM's plan safe to run: unique ids, known dependencies, sane sizes, valid checks."""
    chunks, seen = [], set()
    for i, c in enumerate((plan.get("chunks") or [])[:MAX_CHUNKS], 1):
        cid = str(c.get("id") or f"c{i}").strip() or f"c{i}"
        if cid in seen:
            cid = f"c{i}"
        seen.add(cid)
        must = [str(m).strip() for m in (c.get("must_contain") or []) if 0 < len(str(m).strip()) <= 60][:10]
        chunks.append(_chunk(cid, str(c.get("title") or cid)[:80], str(c.get("output") or "").strip(),
                             str(c.get("goal") or "").strip(), must,
                             [d for d in (c.get("depends_on") or []) if d in seen and d != cid]))
    if not chunks:
        chunks = [_chunk("c1", "Do the whole task", goal=task)]
    checks = browser.clean_checks(plan.get("checks"))
    for c in checks:  # a check belongs to a chunk; unknown owner -> the last chunk that makes a script or page
        if c["owner"] not in seen:
            c["owner"] = next((x["id"] for x in reversed(chunks) if x["output"].endswith(".js")), None) or \
                next((x["id"] for x in reversed(chunks) if x["output"].endswith(VISUAL)), chunks[-1]["id"])
    return {"understanding": str(plan.get("understanding") or "")[:300], "contract": str(plan.get("contract") or ""),
            "chunks": chunks, "page": str(plan.get("page") or "").strip(), "checks": checks}


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
           f"**Phase:** {state['phase']} · review round {state.get('round', 0)}/{REVIEW_ROUNDS} · {mins} min"
           + (f" · lead model {state['lead']}" if state.get("lead") else ""), "",
           f"**PM's understanding:** {state.get('understanding', '')}", "", "**Contract:**", "",
           "```", state.get("contract", ""), "```", ""]
    if state.get("design"):
        out += ["**Style guide:**", "", "```", state["design"], "```", ""]
    for c in state["chunks"]:
        out.append(f"- {icon.get(c['status'], '[ ]')} **{c['id']}. {c['title']}**"
                   + (f" → `{c['output']}`" if c["output"] else "") + f" · tries {c['tries']}")
        if c.get("fix"):
            out.append(f"  - sent back to fix: {c['fix'][:400]}")
        if c["problems"]:
            out.append(f"  - code saw: {'; '.join(c['problems'])}")
        if c["note"]:
            out.append(f"  - worker says: {c['note'][:300]}")
    if state.get("checks"):
        out += ["", "**Browser checks:** " + ", ".join(f"{c['name']} ({c['owner']})" for c in state["checks"])]
    if state.get("integrate"):
        out += ["", f"**Integration:** {state['integrate']}"]
    if state.get("test"):
        t = state["test"]
        out += ["", f"**Browser test (round {state.get('test_round', 0)}):** "
                + ("all passed" if t["ok"] else "; ".join(t["lines"][:6]))]
    if state.get("look"):
        out += ["", f"**Visual review:** {state['look']}"]
    if state.get("review"):
        r = state["review"]
        out += ["", f"**Review:** {'passed' if r['complete'] else 'not passed'}: {r['reason']}"
                + (f" · missing: {r['missing']}" if r.get("missing") and not r["complete"] else "")]
    return "\n".join(out) + "\n"


class Relay:
    """Runs one Relay job inside a RunManager run. Code drives; models only plan, design and build."""

    def __init__(self, manager, run, cfg, task):
        self.m, self.run, self.cfg = manager, run, cfg
        self.stop = manager._stops[run.id]
        if not run.relay:
            run.relay = {"task": task, "phase": "plan", "round": 0, "elapsed_s": 0.0, "chunks": []}
        self.state = run.relay
        self.t0, self.e0 = time.time(), self.state.get("elapsed_s", 0.0)
        self.lead, self.lead_ctx = cfg.model, cfg.context_length
        if getattr(cfg, "lead_model", "") and cfg.lead_model != cfg.model:
            if cfg.lead_model in llm.list_models():
                self.lead, self.lead_ctx = cfg.lead_model, min(cfg.context_length, LEAD_CTX)
                self.state["lead"] = cfg.lead_model
            elif not self.state.get("lead_missing"):
                self.state["lead_missing"] = True
                self._event(phase="plan", content=f"Lead model {cfg.lead_model} isn't installed "
                                                  f"(ollama pull {cfg.lead_model}); the PM uses {cfg.model}.")

    # ------------------------------------------------------------ helpers
    def _event(self, **e):
        self.m._record(self.run, {"type": "relay", **e})

    def _model(self, call, purpose):
        self.run.steps += 1
        self.run.prompt_tokens += call.get("prompt_tokens", 0)
        self.run.output_tokens += call.get("output_tokens", 0)
        self.m._record(self.run, {**call, "purpose": purpose, "step": 0})

    def _lead(self, system, user, schema, num_predict, purpose, images=None):
        out, call = _call(self.lead, self.lead_ctx, system, user, schema, num_predict, images)
        self._model(call, purpose)
        return out

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

    def _known(self):
        return [e.get("dst") for e in self.run.events if e["type"] == "file_op" and e.get("dst")] + \
            [c["path"] for c in self.state["chunks"] if c.get("path")]

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

    def _owner(self, file_name, prefer=None):
        """The chunk that owns a file: the preferred chunk if it makes that file, else the first one that does."""
        name = Path(str(file_name)).name.lower()
        same = [c for c in self.state["chunks"] if c["output"] and Path(c["path"] or c["output"]).name.lower() == name]
        return next((c for c in same if c["id"] == prefer), None) or (same[0] if same else None)

    def _page(self):
        st = self.state
        if st.get("page"):
            from .findings import find_file
            p = find_file(st["page"], self.m.worker_roots(self.run.id), self._known())
            if p:
                return str(p)
        return next((c["path"] for c in st["chunks"] if c["path"].lower().endswith((".html", ".htm"))
                     and Path(c["path"]).is_file()), "")

    def _send(self, items_by_chunk, why):
        """Send fixes back to chunks (code chooses the chunk), then rebuild."""
        for cid, text in items_by_chunk.items():
            c = next(c for c in self.state["chunks"] if c["id"] == cid)
            c.update(status="todo", tries=0, fix=text[:3500], problems=[])
        self._event(phase=self.state["phase"], content=f"{why}: sent back " + ", ".join(items_by_chunk))
        self.state["phase"] = "build"

    # ------------------------------------------------------------ phases
    def run_job(self):
        try:
            if self.state["phase"] == "plan":
                self.plan()
            while self.state["phase"] in ("design", "build", "integrate", "test", "look", "review"):
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
        names = [n for n in tools_for(self.cfg) if not n.startswith("_")]
        can_write = "write_file" in names
        system = PM_PLAN.format(
            max=MAX_CHUNKS, role=self.cfg.system_prompt[:2000], tools=", ".join(names) or "none",
            files_rule="" if can_write else "- This team CANNOT create files: every chunk's `output` must be \"\".",
            web_rules=WEB_RULES.format() if can_write else "")
        plan = None
        for attempt in range(2):
            try:
                plan = clean_plan(self._lead(system, task, PLAN_SCHEMA, 5000, "relay plan"), task)
                if not can_write:  # code enforces it: no file outputs the team can't make
                    for c in plan["chunks"]:
                        c["output"], c["must_contain"] = "", []
                    plan["page"], plan["checks"] = "", []
                break
            except Exception as e:
                self._event(phase="plan", content=f"PM plan failed ({e}); {'retrying' if not attempt else 'one chunk'}.")
        plan = plan or clean_plan({}, task)
        self.state.update(plan)
        visual = any(c["output"].lower().endswith(VISUAL) for c in plan["chunks"])
        self.state["phase"] = "design" if visual else "build"
        self._event(phase="plan", content=f"PM split the job into {len(plan['chunks'])} chunks"
                                          + (f" and {len(plan['checks'])} browser checks." if plan["checks"] else "."),
                    chunks=[{"id": c["id"], "title": c["title"], "output": c["output"]} for c in plan["chunks"]])
        self._save()

    def design(self):
        st = self.state
        try:
            st["design"] = str(self._lead(PM_DESIGN, f"TASK:\n{st['task'][:4000]}\n\nCONTRACT:\n{st.get('contract', '')}",
                                          None, 1500, "relay design")).strip()[:6000]
            self._event(phase="design", content="Lead wrote the style guide.")
        except Exception as e:
            self._event(phase="design", content=f"No style guide ({e}).")
        st["phase"] = "build"
        self._save()

    def build(self):
        for chunk in self.state["chunks"]:
            if chunk["status"] != "todo":
                continue
            while chunk["status"] == "todo":
                if self.stop.is_set() or self._out_of_time():
                    return
                self.build_chunk(chunk)
        multi = sum(1 for c in self.state["chunks"] if c["output"]) > 1
        self.state["phase"] = "integrate" if multi and not self.state.get("integrated") else "test"
        self._save()

    def build_chunk(self, chunk):
        chunk["tries"] += 1
        self._event(phase="build", chunk=chunk["id"], content=f"{chunk['id']} {chunk['title']} · try {chunk['tries']}")
        since = len(self.run.events)
        final = self.m._worker_turn(self.run, self._worker_cfg(), self.worker_message(chunk))
        if final == "stopped":
            chunk["tries"] -= 1
            return
        chunk["note"] = (self.run.answer or "")[:1500]
        before = list(chunk["problems"])
        results = [e for e in self.run.events[since:] if e["type"] == "tool_result"]
        errors = sorted({str(e["result"])[:160] for e in results
                         if str(e["result"]).startswith(("Error", "The user denied"))})
        # facts from code: what the worker's tools really returned (the PM answers from these too)
        chunk["facts"] = "\n".join(f"{e['name']}: {str(e['result'])[:600]}" for e in results
                                   if not str(e["result"]).startswith(("Error", "The user denied")))[:2000]
        if chunk["output"]:
            chunk["path"] = self._find(chunk, since)
            chunk["problems"] = check_output(chunk, chunk["path"])
            for other in self.state["chunks"]:  # a shared file: did this worker break another chunk's part?
                if other is not chunk and other["status"] == "done" and other["output"] == chunk["output"]:
                    lost = [p for p in check_output(other, chunk["path"]) if p.startswith("missing")]
                    if lost:
                        chunk["problems"].append(f"you removed {other['id']}'s part ({lost[0]}); put it back")
            if chunk["problems"] and errors:
                chunk["problems"] += [f"tool error: {x}" for x in errors[:3]]
        else:
            chunk["problems"] = [] if final == "completed" and chunk["note"].strip() else ["the worker gave no result"]
            if any("no permission" in x for x in errors):  # e.g. tried to save a file it can't make
                chunk["problems"].append("you used a tool you don't have; put the result in your reply instead")
        fatal = chunk["output"] and any("no permission" in x for x in errors)
        if not chunk["problems"]:
            chunk["status"] = "done"
        elif chunk["tries"] >= CHUNK_TRIES or (chunk["tries"] > 1 and chunk["problems"] == before) or fatal:
            chunk["status"] = "failed"  # out of tries, the same failure again, or not allowed: retrying won't help
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
        if st.get("design") and chunk["output"].lower().endswith(VISUAL + (".js",)):
            lines.append(f"STYLE GUIDE (follow it exactly):\n{st['design']}")
        if others:
            lines.append("ALREADY DONE BY OTHERS (exists now):\n" + "\n".join(others))
        lines.append(f"YOUR CHUNK {chunk['id']}: {chunk['title']}")
        if chunk["output"]:
            sharing = [c for c in st["chunks"] if c is not chunk and c["output"] == chunk["output"]
                       and c["status"] == "done"]
            lines.append(f"Output file: {chunk['output']}")
            if sharing:
                lines.append("This file already exists (" + ", ".join(f"{c['id']} {c['title']}" for c in sharing)
                             + " made parts of it). ADD only your part with insert_lines or edit_file (read_lines "
                             "first). Do not rewrite the file or remove anything others made.")
        else:
            lines.append("Output: YOUR REPLY. Write the complete result in your reply (every fact, number, name and "
                         "date it needs), not a description of what you did. Do not create files.")
        lines.append(f"Goal:\n{chunk['goal']}")
        if chunk["must_contain"]:
            lines.append("Must contain exactly: " + ", ".join(f'"{m}"' for m in chunk["must_contain"]))
        mine = [c for c in st.get("checks", []) if c["owner"] == chunk["id"]]
        if mine:
            lines.append("A browser will test your part like this (make these pass):\n" + "\n".join(
                f"- {c['name']}: " + " → ".join(c["steps"]) for c in mine))
        if deps:
            lines.append("Read first (you depend on them): " + ", ".join(
                (d["path"] or d["output"]) if d["output"] else f"{d['id']} result: {d['note'][:200]}" for d in deps))
        if chunk.get("fix"):
            lines.append(f"PROBLEMS FOUND IN YOUR PART. FIX THEM:\n{chunk['fix']}\n\n{PATCH_RULE}")
        if chunk["problems"] and chunk["tries"] > 1:
            missing_file = any("was not created" in x for x in chunk["problems"])
            lines.append("YOUR LAST TRY FAILED THE CHECK: " + "; ".join(chunk["problems"]) + ". "
                         + ("Create the file with write_file." if missing_file else
                            "The file exists: fix it in place with edit_file / insert_lines (read_lines first)."))
        return "\n\n".join(lines)

    def integrate(self):
        st = self.state
        files = sorted({c["path"] or c["output"] for c in st["chunks"] if c["output"] and c["status"] == "done"})
        self._event(phase="integrate", content=f"PM: checking that {len(files)} files fit together.")
        msg = (f"WHOLE JOB:\n{st['task'][:4000]}\n\nCONTRACT:\n{st.get('contract') or '(none)'}\n\n"
               "YOUR CHUNK: integration. Separate workers made these files:\n" + "\n".join(f"- {f}" for f in files)
               + "\n\nRead each file. Check they fit together and follow the contract: links and file names "
               "between files, every id/class/function one file uses exists in the other, the same data and "
               "names everywhere, nothing from the job left out. Fix any mismatch with edit_file or "
               "insert_lines (change only what is needed). Reply with one line: what you fixed, or 'all fits'.")
        final = self.m._worker_turn(self.run, self._worker_cfg(), msg)
        if final == "stopped":
            return
        st["integrate"], st["integrated"] = (self.run.answer or "")[:300], True
        st["phase"] = "test"
        self._save()

    def test(self):
        """Open the page in a real browser and run the PM's checks; failures go back as patch fixes."""
        st = self.state
        page = self._page()
        if not page or st.get("test_round", 0) >= TEST_ROUNDS:
            st["phase"] = "look"
            return
        if not browser.available():
            if not st.get("test_skipped"):
                st["test_skipped"] = True
                self._event(phase="test", content=f"Browser checks skipped: install them with `{browser.INSTALL}`.")
            st["phase"] = "look"
            return
        st["test_round"] = st.get("test_round", 0) + 1
        try:
            result = browser.run(page, st.get("checks"), shots_dir=self.m.run_dir(self.run.id) / "shots")
        except Exception as e:
            self._event(phase="test", content=f"Browser test could not run ({e}).")
            st["phase"] = "look"
            return
        lines = browser.summary(result)
        passed = sum(c["ok"] for c in result["checks"])
        st["test"] = {"ok": result["ok"], "lines": lines, "passed": passed, "total": len(result["checks"]),
                      "shots": result["shots"]}
        self._event(phase="test", status="done" if result["ok"] else "failed", problems=lines,
                    content=f"Browser test {st['test_round']}: {passed}/{len(result['checks'])} checks passed"
                            + ("" if result["ok"] else " · " + "; ".join(lines[:4])))
        if result["ok"] or st["test_round"] >= TEST_ROUNDS:
            st["phase"] = "look"
            self._save()
            return
        roots, known = self.m.worker_roots(self.run.id), self._known()
        fixes = {}
        failed = [c for c in result["checks"] if not c["ok"]]
        for f in locate(browser.error_findings(result), roots, known):
            prefer = next((c["owner"] for c in failed if c.get("where")), None)
            owner = self._owner(f["path"] or f["file"], prefer)
            if owner:
                fixes.setdefault(owner["id"], []).append(as_text([f]))
        for c in failed:
            if c["owner"] in {x["id"] for x in st["chunks"]}:
                fixes.setdefault(c["owner"], []).append(
                    f"Browser check '{c['name']}' failed at `{c['failed_step']}`: {c['detail']}\n"
                    f"   The whole check: {' → '.join(next((x['steps'] for x in st['checks'] if x['name'] == c['name']), []))}")
        for problem in result["smoke"]:
            owner = None
            if problem.startswith(("broken images", "no <meta charset")):
                owner = next((x for x in st["chunks"] if x["output"].lower().endswith(".html")), None)
            elif "sideways" in problem:
                owner = next((x for x in st["chunks"] if x["output"].lower().endswith(".css")), None)
            if owner:
                fixes.setdefault(owner["id"], []).append(problem)
        if not fixes:
            st["phase"] = "look"
            self._save()
            return
        self._send({k: "\n".join(v) for k, v in fixes.items()}, f"Browser test {st['test_round']}")
        self._save()

    def look(self):
        """The lead looks at screenshots of the page and sends visual fixes to the chunk that owns the file."""
        st = self.state
        page = self._page()
        if st.get("look_round", 0) >= LOOK_ROUNDS or not page or not browser.available():
            st["phase"] = "review"
            return
        if "vision" not in llm.capabilities(self.lead):
            if not st.get("look_skipped"):
                st["look_skipped"] = True
                self._event(phase="look", content=f"Visual review skipped: {self.lead} can't read images.")
            st["phase"] = "review"
            return
        st["look_round"] = st.get("look_round", 0) + 1
        try:
            shots = browser.run(page, [], shots_dir=self.m.run_dir(self.run.id) / "shots")["shots"]
            out = self._lead(PM_LOOK.format(design=st.get("design") or "(none: judge by the task)"),
                             f"TASK:\n{st['task'][:3000]}", LOOK_SCHEMA, 1200, "relay look",
                             images=[shots["desktop"], shots["phone"]])
        except Exception as e:
            self._event(phase="look", content=f"Visual review could not run ({e}).")
            st["phase"] = "review"
            return
        items = locate([{**f, "line": 0} for f in (out.get("findings") or [])][:6],
                       self.m.worker_roots(self.run.id), self._known())
        st["look"] = "looks good" if out.get("looks_good") or not items else "; ".join(f["problem"] for f in items)
        fixes = {}
        for f in items:
            owner = self._owner(f["path"] or f["file"])
            if owner:
                fixes.setdefault(owner["id"], []).append(f)
        if out.get("looks_good") or not fixes:
            self._event(phase="look", status="done", content=f"Visual review: {st['look']}")
            st["phase"] = "review"
        else:
            self._send({k: "Visual review of the page (screenshots):\n" + as_text(v) for k, v in fixes.items()},
                       "Visual review")
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
            self.answer()
            st["phase"] = "done"
        elif st["round"] > REVIEW_ROUNDS:
            st["phase"] = "failed"
        else:
            self.send_back(verdict)
        self._save()

    def answer(self):
        """The PM pulls the results together into the answer for the user (when there's text to give)."""
        st = self.state
        texts = [c for c in st["chunks"] if not c["output"] and c["status"] == "done" and c["note"].strip()]
        if not texts:
            return
        results = "\n\n".join(f"[{c['title']}]\n{c['note']}"
                                + (f"\nWhat the tools returned (facts):\n{c['facts']}" if c.get("facts") else "")
                                for c in texts)
        files = [c["path"] or c["output"] for c in st["chunks"] if c["output"] and c["status"] == "done"]
        prompt = ("You are the PM. Your team finished the user's task. Write the final answer to the user from "
                  "the team's results: complete and well organised, in plain words. Use only facts from the "
                  "results and what the tools returned; never invent dates or numbers. Do not mention chunks, "
                  "workers or the PM." + (f" Files made: {', '.join(files)}." if files else ""))
        try:
            st["final"] = str(self._lead(prompt, f"TASK:\n{st['task'][:3000]}\n\nRESULTS:\n{results[:12000]}",
                                         None, 3000, "relay answer")).strip()
        except Exception as e:
            self._event(phase="review", content=f"PM could not write the final answer ({e}).")

    def send_back(self, verdict):
        """Findings that name a chunk's file go straight back to that chunk (code, no model call).
        The PM maps whatever is left to chunks to redo."""
        st = self.state
        direct, rest = {}, []
        for f in verdict.get("findings") or []:
            owner = self._owner(f["path"]) if f.get("path") else None
            if owner:
                direct.setdefault(owner["id"], []).append(f)
            else:
                rest.append(f)
        for cid, items in direct.items():
            c = next(c for c in st["chunks"] if c["id"] == cid)
            c.update(status="todo", tries=0, fix=as_text(items)[:3000], problems=[])
        if direct and not rest:
            self._event(phase="review", content="Review pointed at: " + ", ".join(
                f"{cid} ({len(v)} fix{'es' if len(v) > 1 else ''})" for cid, v in direct.items()))
            st["phase"] = "build"
            return
        if rest:
            verdict = {**verdict, "missing": f"{verdict.get('missing', '')}\n{as_text(rest)}".strip()}
        listing = "\n".join(f"- {c['id']} {c['title']}" + (f" ({c['output']})" if c["output"] else "")
                            for c in st["chunks"])
        user = f"TASK:\n{st['task'][:3000]}\n\nREVIEW: {verdict['reason']}\nMISSING: {verdict.get('missing', '')}"
        redo = []
        try:
            raw = self._lead(PM_REDO.format(chunks=listing), user, REDO_SCHEMA, 800, "relay redo")
            redo = [r for r in raw.get("redo", []) if any(c["id"] == r.get("id") for c in st["chunks"])]
        except Exception as e:
            self._event(phase="review", content=f"PM could not map the findings ({e}).")
        if not redo:  # nothing mapped: one extra chunk that fixes what's missing
            n = sum(1 for c in st["chunks"] if c["id"].startswith("fix")) + 1
            st["chunks"].append(_chunk(f"fix{n}", "Fix what the review found",
                                       goal=f"{verdict['reason']}\nMissing: {verdict.get('missing', '')}"))
        for r in redo:
            c = next(c for c in st["chunks"] if c["id"] == r["id"])
            earlier = c["fix"] if c["id"] in direct else ""
            c.update(status="todo", tries=0, fix=(earlier + "\n" + str(r.get("fix", ""))[:500]).strip(), problems=[])
        self._event(phase="review", content="PM sent back: " + (", ".join(r["id"] for r in redo) or "a fix chunk"))
        st["phase"] = "build"

    def report(self):
        st = self.state
        done = [c for c in st["chunks"] if c["status"] == "done"]
        lines = ([st["final"], "", "---", ""] if st.get("final") else []) + [
                 f"Relay: {len(done)}/{len(st['chunks'])} chunks done · review "
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
        if st.get("test"):
            t = st["test"]
            lines += ["", f"Browser test: {t['passed']}/{t['total']} checks passed"
                      + ("" if t["ok"] else " · still failing: " + "; ".join(t["lines"][:4]))]
        if st.get("look"):
            lines += [f"Visual review: {st['look']}"]
        if st.get("review"):
            lines += ["", f"Review: {st['review']['reason']}"]
            if not st["review"]["complete"] and st["review"].get("missing"):
                lines.append(f"Still missing: {st['review']['missing']}")
        return "\n".join(lines)
