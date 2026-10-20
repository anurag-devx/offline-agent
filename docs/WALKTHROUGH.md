# Walkthrough: how offline-agent works

All code is in `offline_agent/`. Paths below like `engine/agent.py` mean `offline_agent/engine/agent.py`.

Read in this order. Each part builds on the one before.

## 0. The big idea

An agent is a **loop around a normal model**:
1. Send the conversation + a list of tools to the model.
2. If it replies with a *tool call*, our code checks permission, runs the function, and adds the result.
3. Repeat until it replies with plain text, which is the answer.

The model only produces text. **Our code does all the work and enforces all the rules.**
That's why safety lives in our code, not in the prompt.

## Part 1: talking to a model
- `examples/01_hello.py`: messages, roles, streaming.
- `engine/llm.py`: the one door to Ollama. `capabilities()` tells us if a model supports tools.
  `format=` forces JSON output (used by the planner and agent generator).

## Part 2: tools and permissions
- `engine/permissions.py`: the **policy**. Ten capabilities (`files.read`, `files.move`,
  `internet.search`, ...), each `off` / `allow` / `ask`, plus scopes (folders, file types,
  max changes, sites, mail folders). `off` means the model never even sees the tools.
- `engine/tools.py`: `@tool("files.move")` turns a function into a schema the model understands
  and ties it to a capability. `run_tool()` always returns text; errors go back to the model.
- `engine/context.py`: how a tool knows which agent called it, and how it can ask you for
  approval mid-tool (e.g. "grant ~/Pictures for this run?") or ask you a question.
- `engine/paths.py`: locations no agent may ever touch, whatever its policy says.
- `engine/toolkits/`:
  - `files.py`: `resolve()` is the gatekeeper: scope check, protected check, run-time grants.
    `_unique()` means nothing is overwritten. `_count_change()` enforces the limit and records
    every change (that record powers the file log and Undo). Delete uses the Trash.
  - `web.py`: site allow-list, "ask me" for other sites, redirect guard, request logging.
  - `mail.py`: IMAP, mail-folder scope, `BODY.PEEK` so reading doesn't mark mail read.
  - `interaction.py`: `ask_user`, so an agent can ask you which folder to use.
- Key idea: **the prompt says what the agent should do; the policy, enforced in code, decides
  what it can do.** A model can ignore its prompt; it can't get around `resolve()`.

## Part 3: the loop
- `engine/config.py`: an agent is data (`AgentConfig` ⇄ YAML).
- `engine/agent.py`: read `run()` slowly. It *yields events* so anything (UI, terminal, logs)
  can watch each step. For `ask` tools it calls `approver()` and waits.

## Part 4: running many agents
- `engine/runs.py`: each run is a background **thread**. Approvals and questions use a
  `threading.Event`: the agent thread waits on it; your click sets it. Every event goes to
  `runs/<id>/events.jsonl` the moment it happens, so a crash loses nothing.
  `undo_file_changes()` replays the file log backwards.

## Part 4b: verification
- `engine/verifier.py`: a *second* agent with read-only permissions. It gets the task, the
  evidence our code recorded (file changes, errors, denials), and the worker's claim, then
  checks the real state and returns a JSON verdict. Rule: **trust recorded evidence, not claims.**
- `RunManager._work()` loops: worker turn → verify → not done? send the gap back → repeat.

## Lesson: the context window
Every model call sends the whole conversation. If it's longer than `num_ctx`, Ollama cuts the
**beginning**: your system prompt. The model then "forgets" its job. That's why agents set
`context_length`, why tools return compact output with filters, and why the agent warns when
`prompt_eval_count` gets close to the limit.

## Part 4c: spending fewer tokens (the "telegram" idea)
Every token costs time on a laptop, so the framework is frugal at three levels:
1. **Telegram style**: tools answer in one compact line (`OK moved 3/3 ~/Downloads → ~/Downloads/all_pdf`),
   replies are capped (`max_reply_tokens`), and the prompt asks for short answers.
2. **Job notes** (`engine/ledger.py`): the plan + checklist is the agent's working memory.
   - Facts come from code (`attach()`); the model only adds one-line claims (`update_step`).
   - "Done" is refused if the step's tool calls all failed; a claim that code contradicts gets ⚠.
   - The notes are sent LAST in every call (never cut off), and messages of closed steps are
     dropped (`Agent._compact`). Context stays roughly constant however long the job runs.
3. **Rule mode** (`engine/rules.py`): for routine jobs the model is called once, to turn words into a
   rule. Code does the rest. Principle: **the model decides, code does the work.**

## Part 4d: memory and schedules
- `engine/memory.py`: notes in SQLite; search by meaning with embeddings (numbers that represent
  meaning; similar meaning = similar numbers). Recalled notes are framed as information, never
  instructions. Run summaries are built by code (`run_summary`), so nothing is invented.
- `engine/scheduler.py`: one background thread per process, a lock file so only one process runs
  schedules, and `RunManager(unattended=True)` so nobody-is-watching runs deny approvals.
- `engine/rules.py` → `EmailRuleAgent`: rule mode for email; IMAP `SEARCH` lets the mail server
  do the matching, so no mail is downloaded to decide what moves.

## Part 5: understanding before running
- `engine/planner.py`: capabilities summary and diagram need no model. `plan_task()` asks the
  model what it *would* do, using JSON output, and marks each step allowed / asks / blocked.
  `generate_agent()` lets the model write a config, then we sanitize it (it can't grant itself
  unasked email changes).
- `engine/validate.py`: catch problems early, including risky combinations like email + free internet.

## Part 6: the UI
- `app.py` + `ui/`: Streamlit reruns the script on every click; `st.session_state` keeps values.
  `@st.fragment(run_every=…)` refreshes only the live part of a page. The UI has no agent logic;
  it only calls `engine/`.

## Exercises
1. Run File Sorter on a test folder with a few images and PDFs. Use "Approve all", then Undo.
2. Run Website Builder: "Build a one-page site for a bakery in bakery/". Preview it on the Workspace page.
3. Give the Web Researcher a site that's *not* allowed. Find the BLOCKED line in the run.
4. Plan a task with Gmail Sorter before setting up email. What does Validate say?
5. Compare the same task on a 4B and a 9B model on the Runs page: steps, tokens, time.
6. Write a `word_count` tool and use it in a new agent.
