# offline-agent

**AI agents that run on a normal laptop. The model decides, code does the work.**

Build, preview, validate, run and track agents on local models with [Ollama](https://ollama.com).
No cloud, no API keys, no accounts. Your prompts and data never go to an AI company.

[![tests](https://github.com/crazzzyann/offline-agent/actions/workflows/tests.yml/badge.svg)](https://github.com/crazzzyann/offline-agent/actions/workflows/tests.yml)
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
model: qwen3.5:9b
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
| **Verification** | Optional read-only verifier checks the real state when the agent says "done". Not done → the agent is told what's missing and continues (up to N rounds, or until you press Stop) |
| **File safety** | Never overwrites (clashes get `_1`), delete goes to the Trash, every file change logged (CSV), **Undo** for moves |
| **Everything recorded** | Each run's config, every step, tool call, web request and approval in `runs/`; app activity in `logs/` |
| **Models** | See installed models and their capabilities, download new ones, import `.gguf` files from your computer (e.g. Unsloth fine-tunes) |
| **Workspace** | The only folder file tools can touch. Preview websites agents build, upload/download files |

Templates: General Assistant, Math Helper, File Helper, Note Taker, **File Sorter**,
**Website Builder**, **Gmail Sorter**, **Web Researcher**, **News Collector**.

## Requirements

**The framework** is small (about 200 MB with its Python packages) and has no hardware limit of its own:
- Python 3.10+
- [Ollama](https://ollama.com), running
- Any OS that runs Ollama (macOS, Linux, Windows; CI runs the tests on all three)

**The model** decides what your machine needs. Pick any Ollama model with **tool calling**
(`ollama show <model>` lists `tools` under Capabilities; the Models page shows it too).
Rule of thumb: a model needs about its download size in RAM, plus room for the context window.
Bigger models are more reliable, smaller ones faster.

| Model | Size | Tested on | Result |
|---|---|---|---|
| `qwen3.5:9b` | 6.6 GB | MacBook Air M2, 16 GB, macOS | ✅ All templates |
| *your model here* | | | [Share your result](https://github.com/crazzzyann/offline-agent/issues/new?template=tested_on.md) |

## Quick start

```bash
git clone https://github.com/crazzzyann/offline-agent.git
cd offline-agent
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
ollama pull qwen3.5:9b           # or any model with tool support
streamlit run app.py
```

Terminal (approvals asked as y/n, runs recorded the same way):

```bash
python run.py                              # list agents
python run.py templates/file_helper.yaml
```

Python:

```python
from engine import Agent, load_agent
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
engine/            no UI code; everything works without Streamlit
  llm.py           the only file that talks to Ollama
  tools.py         tool registry (@tool), permission checks
  toolkits/        built-in tools: basic, files, web, mail, interaction
  permissions.py   the permission policy (capabilities, modes, scopes)
  paths.py         project folders + always-blocked locations
  context.py       what a running tool knows (config, grants, approvals)
  agent.py         the agent loop (with approvals)
  runs.py          background runs, tracking, recording
  planner.py       capabilities, workflow diagram, plans, agent generator
  validate.py      checks + dry run
  verifier.py      read-only checker for "is the task really done?"
  ledger.py        job notes: plan, checklist, evidence, notes.md
  rules.py         rule mode: model writes a rule, code executes it
  models.py        list / pull / delete / import models
  config.py        AgentConfig + YAML
  audit.py         activity log
  credentials.py   local credential storage
ui/                Streamlit pages
app.py             entry point
run.py             terminal runner
templates/         starter agents
agents/            your agents
workspace/         the only folder file tools can touch
tests/             pytest suite with a fake model (no Ollama needed)
```

New to agents? Read [docs/WALKTHROUGH.md](docs/WALKTHROUGH.md).

## Roadmap

- Long-term memory (facts + run summaries, local embeddings)
- RSS/news parsing in code (lighter news agents)
- Rule mode for email (sort by sender/subject with code)
- Scheduled runs
- `pip install offline-agent`

## License

MIT · see [CHANGELOG.md](CHANGELOG.md) for what's new · security: [SECURITY.md](SECURITY.md)
