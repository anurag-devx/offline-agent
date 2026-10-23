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
- `engine/permissions.py`: the **policy**. Twelve capabilities in five groups (files: read, create,
  modify, move, delete · internet: read, search · email: read, organize · memory: recall, remember ·
  asking you questions), each `off` / `allow` / `ask`, plus scopes (folders, file types, max changes,
  sites, mail folders). `off` means the model never even sees the tools.
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
  - Patch tools in `files.py`: `read_lines` shows line numbers (added by code, so the model never
    counts), `edit_file` replaces one exact piece of text (refused unless it appears exactly once),
    `insert_lines` adds lines. A one-line fix costs a few tokens, not a whole-file rewrite.
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
- `RunManager._single()` loops: worker turn → verify → not done? send the gap back → repeat.
- `engine/findings.py` (**Pinpoint**): the verdict includes findings (file, line, problem, fix). Code
  checks that the file and line exist and attaches the real lines around them, so the agent can patch
  that exact spot.

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

## Part 4e: measuring and trimming
- `engine/speed.py` (**Stopwatch**): Ollama reports load / prompt-read / reply-write time per call;
  `summarize()` adds tool time and waiting time and turns the numbers into tips.
- `engine/telegram.py`: **Page Turner** (`page()`), **Slim Schemas** (`slim_schema()`), **Fade Out**
  (`receipt()`), and a rough token counter for the **Token Meter**.
- `Agent._store()` (**Ghost Chatter**, **No Echo**) and `Agent._outgoing()` (**Fade Out**) change only
  what we *send* the model; the run log keeps everything.

## Part 4f: big jobs (Triage and Relay)
Small models do well on one focused piece and get lost in a 40-step job, so big jobs are split.
- `engine/triage.py`: decides per task. Code counts files, listed requirements and words first; only
  when that's unclear does the model rate the task. Simple → the normal loop; complex → Relay.
- `engine/relay.py`: read the module docstring, then `run_job()`. **Code runs the loop; models only
  plan, design and build.**
  1. **Plan:** a PM call writes a *contract* (names, ids, data every piece must use), small *chunks*
     (one file, or one feature of a file), and browser checks for web pages.
  2. **Design:** for visual work, the lead model writes a style guide.
  3. **Build:** `build_chunk()` gives one fresh worker one chunk (`RunManager._worker_turn()`); code
     checks the output with `check_output()`, including that no worker removed another's part of a
     shared file.
  4. **Integrate**, then **Test** (`engine/browser.py` opens the page in Playwright, runs the steps,
     and turns JavaScript errors into file + line findings), then **Look** (screenshots go to a
     vision-capable lead), then **Review** (the Inspector). Each sends problems straight back to the
     chunk that owns the file.
  5. Everything is in `run.relay`, saved with the run, so `RunManager.resume()` continues after a
     stop or restart.

## Part 4g: measuring agents
- `engine/bench.py` (**Test Bench**): runs agents on the cases in `bench_cases.yaml`, each in its own
  sandbox folder, with approvals answered automatically inside it. `run_checks()` checks the result in
  code (files, texts, counts, rules, and `browser:` click-throughs). The score is % of checks passed,
  minus 10 for each time the Inspector sent the agent back.

## Part 5: understanding before running
- `engine/planner.py`: capabilities summary and diagram need no model. `plan_task()` asks the
  model what it *would* do, using JSON output, and marks each step allowed / asks / blocked.
  `generate_agent()` lets the model write a config, then we sanitize it (it can't grant itself
  unasked email changes).
- `engine/validate.py`: catch problems early, including risky combinations like email + free internet.

## Part 6: the Studio
- `web/server.py`: a small HTTP server from Python's standard library. It serves the app and a JSON
  API over the engine (`ROUTES`), plus **Server-Sent Events**: `_stream_run()` keeps one request open
  and writes each new run event as it happens, so the page updates live without polling.
  - Safety: it listens on 127.0.0.1 only; requests that change something need the secret in the page's
    `<meta name="oa-token">` (new every start); other Host names are refused; workspace pages are
    served at `/ws/` with a sandbox policy.
- `web/static/`: the app itself, plain JavaScript modules with no build step and nothing from the
  internet. `js/core.js` has the tiny DOM helper `h()`, the API helper, icons and a safe Markdown
  renderer; `app.js` is the shell, router and Home; one module per page (`agents.js`, `activity.js`,
  `library.js`, `tests.js`, `settings.js`); `app.css` is one set of design tokens with light and dark
  themes.
- The Studio has no agent logic: like the CLI, it only calls `engine/`.
- The classic Streamlit Studio (`app.py` + `ui/`, `offline-agent studio --classic`) is still
  supported. Streamlit reruns the script on every click; `st.session_state` keeps values.

## Exercises
1. Open the Studio (`offline-agent studio`). On Home, pick File Sorter and sort a test folder with a
   few images and PDFs. Approve the rule, then use **Undo moves** in the run's Files tab.
2. On Home, pick Website Builder: "Build a one-page site for a bakery in bakery/". Watch Relay's
   phases in Activity, then preview the site in Library → Workspace.
3. Give the Web Researcher a site that's *not* allowed. Find the blocked request in the run's steps.
4. Open Gmail Sorter in Agents before setting up email. What do Checks and Plan say?
5. In Tests, run the same agents on a small and a bigger model. Compare pass rate, score and time.
6. Write a `word_count` tool (`@tool(...)` in a toolkit), then give it to a new agent in the editor.
