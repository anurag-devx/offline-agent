# offline-agent

**AI agents that run on a normal laptop. The model decides, code does the work.**

Build, preview, validate, run and track agents on local models with [Ollama](https://ollama.com).
No cloud, no API keys, no accounts. Your prompts and data never go to an AI company.

[![tests](https://github.com/anurag-devx/offline-agent/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/anurag-devx/offline-agent/actions/workflows/tests.yml)
![license](https://img.shields.io/badge/license-MIT-blue)
![python](https://img.shields.io/badge/python-3.10%2B-blue)

<!-- Add a GIF here: docs/demo.gif (File Sorter run: approve rule -> DONE ✓) -->

## Why it's different

Most agent frameworks let the model do everything, one tool call at a time. On a laptop that's
slow, and small models lose track. offline-agent uses the model only for judgment:

Same task, same model (`qwen3.5:9b`, MacBook Air M2, 16 GB): *"move the PDFs in Downloads to a new folder"*

| | Classic agent loop | **Rule mode** |
|---|---|---|
| Model calls | 7 | **1** |
| Tokens | 15,705 | **532** (30× fewer) |
| Files moved | 0 (the model lost its instructions) | **110, verified ✓** |
| Time | 16 min 52 s | **89 s**, including the human approval |

And when the model does do the work, it's kept honest: permissions enforced in code, job notes
with evidence from code (not the model's claims), and a verifier that checks the real result.

An agent is a small YAML file:

```yaml
name: File Sorter
model: gemma4:e4b
system_prompt: |
  1. Ask the user which folder to sort...
permissions:
  files:
    folders: []                  # none fixed...
    ask_for_other_folders: true  # ...so it asks you to grant one at run time
    read: allow
    create: allow
    move: ask                    # pauses for your OK (once, or "all this run")
    delete: ask
  interaction: {ask_user: allow}
max_steps: 80
```

## What you get

| | |
|---|---|
| **Studio** | Design → Preview → Validate → Run → Deploy, all in the browser |
| **Permission policy** | 10 capabilities, each *Off / Allow / Ask first*: files (read, create, modify, move, delete), internet (read pages, search), email (read, organize), asking you questions. Plus scopes: folders, file types, max changes per run, sites, mail folders. Grant extra folders/sites during a run |
| **Preview before running** | What the agent can/can't do, a workflow diagram, and a step-by-step plan for your task with nothing executed |
| **AI-generated agents** | Describe an agent in plain English; your local model drafts the config |
| **Run tracking** | Background runs, live status, approve once / approve all this run / deny, answer the agent's questions, stop runs |
| **Two modes** | *Agent*: the model does the work with tools. *Rule*: the model writes one rule (`~/Downloads · .pdf → all_pdf`), you approve it with the exact file list, code executes and checks it. One model call, exact, seconds |
| **Job notes** | Every task gets a job ID, a plan and a checklist (`runs/<job>/notes.md`). The agent closes steps with a one-line note; code attaches evidence, refuses "done" on failed steps, flags mismatches. Finished steps' messages are dropped, so the context stays small |
| **Telegram style** | Compact tool output (`OK moved 138/140 ~/Downloads → all_pdf`), short replies, capped reply length: fewer tokens, faster on laptops |
| **Email rule mode** | Same idea for Gmail: `INBOX · from "amazon" → Receipts`. The mail server does the matching; code moves and checks |
| **News feeds** | `read_feed` parses RSS/Atom in code: one line per headline, filtered by keyword and date |
| **Memory** | Notes and run summaries stored on your computer, searched by meaning (local `nomic-embed-text`). Recall/Remember permissions; notes are shown as information, never instructions |
| **Schedules** | Run agents every day at a time or every N minutes, in the app or headless (`offline-agent scheduler`) |
| **Triage + Relay** | Triage sends simple tasks to the main agent and big ones to Relay: a PM agent splits the job into small chunks with a shared contract, a fresh worker builds each chunk, code checks every chunk, and the PM pulls it back together and has it reviewed. Long jobs save their progress and resume after a stop or restart |
| **Test Bench** | Sandboxed tests for every agent, checked in code and scored; compare models and settings side by side |
| **Speed features** | Stopwatch (where the time goes), Token Meter, Telegram style for machine talk, Full Voice for answers you read |
| **Verification** | Optional read-only verifier checks the real state when the agent says "done". Not done → the agent is told what's missing and continues (up to N rounds, or until you press Stop) |
| **File safety** | Never overwrites (clashes get `_1`), delete goes to the Trash, every file change logged (CSV), **Undo** for moves |
| **Everything recorded** | Each run's config, every step, tool call, web request and approval in `runs/`; app activity in `logs/` |
| **Models** | See installed models and their capabilities, download new ones, import `.gguf` files from your computer (e.g. Unsloth fine-tunes) |
| **Workspace** | The only folder file tools can touch. Preview websites agents build, upload/download files |

**What does each agent and tool do?** See the **[Catalog](docs/CATALOG.md)**: plain-words cards for every agent
(good for / not for / what it needs / examples) and every tool (inputs, safety, example output). In the app: the
📖 Catalog page; in the terminal: `offline-agent info file_sorter`.

Templates (in `offline_agent/templates/`): General Assistant, Math Helper, File Helper, Note Taker, **File Sorter**,
**Website Builder**, **Gmail Sorter**, **Web Researcher**, **News Collector**.

## Speed features

Every token costs time on a laptop: the model re-reads everything it's sent, on every call.
These features keep that small. All are measured in each run's **⚡ Speed** panel.

| Feature | What it does |
|---|---|
| **Clerk** (rule mode) | The model writes one rule; code does the work and checks it. 1 model call |
| **Ledger** (job notes) | Plan + checklist with code evidence; finished steps' messages are dropped |
| **Inspector** (verifier) | A read-only checker confirms the real result before "done" |
| **Morse** | Tools answer in compact one-liners: `OK moved 138/140 ~/Downloads → all_pdf` |
| **Page Turner** | Long files, pages and emails come one page at a time (`+N more chars, offset=…`) |
| **Slim Schemas** | Tool descriptions are sent in short form |
| **Ghost Chatter** | The model's narration between tool calls is dropped from history |
| **No Echo** | The model's hidden thinking is never sent back to it |
| **Fade Out** | Tool results older than two turns shrink to a one-line receipt |
| **Word Limit** | Reply caps per call type (steps, plans, rules, verdicts) |
| **Stopwatch** | Per call: load / read / write time, tokens and tokens per second |
| **Token Meter** | What each call sent (instructions, tools, history, notes) and what was saved |
| **Full Voice** | Compact while working, complete final answers; a cut-off answer is continued automatically |

Telegram style is for the machine side (what the model reads); **Full Voice** keeps the human side
(final answers, summaries, analysis) as detailed as needed. Both are toggles in
Design → ⚙️ How it works, so you can compare.

## Big jobs: Triage and Relay

Small local models do well on one focused piece of work and get lost in a 40-step job.
So big jobs are split up:

- **🚦 Triage** looks at each task first. Code counts the files it names, the listed requirements and
  its length; only when that's unclear does the model rate it. Simple tasks go to the main agent,
  complex ones to Relay.
- **🏃 Relay**: a **PM agent** writes a plan: a shared *contract* (file names, ids, class names, data that
  every piece must use) and small *chunks*, one output each. Then, one after another:
  1. a fresh **worker** builds each chunk, seeing only the brief, the contract, its chunk and the files it
     depends on, so its context stays small;
  2. **code checks** each chunk (file exists, must-have texts, no placeholders); a failed chunk is retried
     with the reason, and only that chunk;
  3. an **integration** worker checks the pieces fit together and fixes mismatches;
  4. the **Inspector** reviews the whole result; the PM sends the chunks that need work back, up to 2 rounds.

Code runs this loop, not a model. Relay jobs can take hours on a laptop, so their state is saved in
the run: **▶ Resume** in the run view (or `offline-agent resume`) continues where it stopped, even
after a restart. Per agent: **How big tasks run** = Triage decides / Main agent / Relay, plus a time limit.

```bash
offline-agent bench --agents "Website Builder" --route main,relay --timeout 180
```

## Test Bench

Run every agent on a built-in test, check the result in code, and compare settings and models:

```bash
offline-agent bench --telegram on,off --full-voice on,off
offline-agent bench --agents "File Sorter,Math Helper" --models gemma4:e4b,qwen3.5:9b
```

Or use the **🧪 Test Bench** page. Each test runs in its own sandbox folder (`workspace/_bench/`),
so your files are never touched; email tests are dry (the rule is checked, nothing is moved).
You get a comparison (pass rate, time, model calls, tokens) and a report in `bench/`.
Your own agents can add a test to their YAML:

```yaml
bench:
  task: Move all pdf files in {sandbox} to all_pdf
  checks:
    - {no_files: {folder: ".", extensions: [".pdf"]}}
    - {count_files: {folder: all_pdf, at_least: 1}}
```

## Requirements

**The framework** is small (about 200 MB with its Python packages) and has no hardware limit of its own:
- Python 3.10+
- [Ollama](https://ollama.com), running
- Any OS that runs Ollama (macOS, Linux, Windows; CI runs the tests on all three)

**The model** decides what your machine needs. Pick any Ollama model with **tool calling**
(`ollama show <model>` lists `tools` under Capabilities; the Models page shows it too).
Rule of thumb: a model needs about its download size in RAM, plus room for the context window.
Bigger models are more reliable, smaller ones faster.

Measured with the [Test Bench](#test-bench) on a MacBook Air M2, 16 GB, macOS (Telegram style + Full Voice on):

| Model | 4 quick agents* | Avg time | Website Builder | Verdict |
|---|---|---|---|---|
| **`gemma4:e4b`** (default) | ✅ 4/4 | **15s** | ✅ ~12 min, best page | Fastest on quick tasks, best quality |
| `qwen3.5:9b` | ✅ 4/4 | 19.5s | ✅ ~7 min | Reliable all-rounder |
| `gpt-oss:20b` | 3/4 | 48s | ✅ ~29.5 min, thinnest page | Too slow / memory-tight on 16 GB |
| *your model here* | | | | [Share your result](https://github.com/anurag-devx/offline-agent/issues/new?template=tested_on.md) |

\* General Assistant, File Helper, File Sorter, Math Helper.

## Quick start

```bash
# 1. Install (needs Python 3.10+ and Ollama)
pip install git+https://github.com/anurag-devx/offline-agent.git

# 2. Get a model with tool calling
ollama pull gemma4:e4b

# 3. Open the Studio
offline-agent studio
```

Your agents, runs, memory and workspace are stored in `~/OfflineAgent`
(`offline-agent where` shows it; set `OFFLINE_AGENT_HOME` to move it).

**From source** (to change the code):

```bash
git clone https://github.com/anurag-devx/offline-agent.git
cd offline-agent
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
offline-agent studio            # data stays in the project folder
python -m pytest -q             # tests, no Ollama needed
```

**Terminal:**

```bash
offline-agent list                     # your agents and the templates
offline-agent run file_sorter          # chat with an agent (approvals asked as y/n)
offline-agent check news_collector     # validate an agent
offline-agent scheduler                # run schedules without the app
offline-agent bench                    # test agents and compare settings/models
offline-agent info move_files          # what an agent or tool does
offline-agent catalog --write          # regenerate docs/CATALOG.md
```

**Python:**

```python
from offline_agent.engine import Agent, load_agent
agent = Agent(load_agent("agents/math_helper.yaml"))
print(agent.ask("What is 18% of 1240?"))
```

## Privacy model

| Data | Where it goes |
|---|---|
| Prompts, files, email content | Only to the model on your machine |
| Web requests | Only to the agent's sites (or ones you approve during a run); redirects elsewhere are blocked; every request is logged |
| Email | Only between your machine and your IMAP server, only the mail folders allowed. No send or delete tools exist |
| Files | Only the agent's folders (or ones you grant during a run). `~/.ssh`, `~/.aws`, Keychains and this app's own code/records are always blocked |
| Email password | `~/.offline-agent/credentials.json` (chmod 600), outside the repo |

One honest limit: anything an agent puts *in* a web address (e.g. a search query) reaches
that site. For agents that read private data, set Internet to **Ask first**. The validator warns you.

## Gmail setup

Turn on 2-Step Verification, create an app password at
https://myaccount.google.com/apppasswords, and add it on the **Settings** page.

## Context length (important)

Ollama's default context window is small and it **silently drops the start of longer
conversations**, which is where the agent's instructions are. Symptoms: the agent ignores its
task and just summarizes the last tool output. Each agent has a `context_length` (default 16k);
the run shows a warning if it fills up. Tool filters (e.g. `list_folder` with `extensions=".pdf"`)
keep tool output small.

## Choosing a model

Agents need **tool calling** (`ollama show <model>`, look for `tools`). The Models page shows this.
Rough guide: 1–3B fast but unreliable with tools; 4B fine for simple agents; 7–9B reliable.
Long outputs (whole web pages) and many-step tasks (sorting 30 emails) work better on larger models.

## Add a tool or template

See [CONTRIBUTING.md](CONTRIBUTING.md). A tool is a decorated Python function (about 10 lines);
a template is a YAML file. Tests run without Ollama: `python -m pytest -q`.

## Project layout

```
offline_agent/
  engine/            no UI code; everything works without Streamlit
    llm.py           the only file that talks to Ollama
    agent.py         the agent loop (approvals, job notes, compaction)
    rules.py         rule mode for files and email: model writes a rule, code executes it
    ledger.py        job notes: plan, checklist, evidence, notes.md
    verifier.py      read-only checker for "is the task really done?"
    triage.py        decides: main agent or Relay
    relay.py         Relay: PM plan, one worker per chunk, checks, integration, review
    memory.py        long-term memory (SQLite + local embeddings)
    scheduler.py     scheduled runs
    bench.py         Test Bench: sandboxed tests, code checks, comparisons
    speed.py         Stopwatch + Token Meter numbers
    telegram.py      Page Turner, Slim Schemas, Fade Out helpers
    runs.py          background runs, tracking, recording
    permissions.py   the permission policy (capabilities, modes, scopes)
    tools.py         tool registry (@tool)
    toolkits/        built-in tools: files, web, feeds, mail, memory, interaction, basic
    planner.py       capabilities, workflow diagram, plans, agent generator
    validate.py      checks + dry run
    paths.py         where data lives + always-blocked locations
    models.py        list / pull / delete / import models
  ui/                Streamlit pages
  templates/         starter agents (shipped with the package)
  app.py             Studio entry point
  cli.py             the offline-agent command
tests/               pytest suite with a fake model (no Ollama needed)
```

New to agents? Read [docs/WALKTHROUGH.md](docs/WALKTHROUGH.md).

## Roadmap

- Real-browser click tests for websites the agents build (cart, forms, filters)
- Cascade: a small model first, a bigger one only when a check fails
- Offline Coder: a coding agent (edit a repo, run tests, git checkpoints) on the same engine
- Template gallery and tool plugins
- More models and machines in the "tested on" table
- Publish to PyPI (`pip install offline-agent`)
- Fine-tuning small models on verified runs (Unsloth → GGUF → Models page)

## License

MIT · see [CHANGELOG.md](CHANGELOG.md) for what's new · security: [SECURITY.md](SECURITY.md)
