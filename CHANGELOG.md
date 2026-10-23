# Changelog

## Unreleased

- **New Studio**: a fast, minimal local web app replaces the Streamlit pages (still available with
  `offline-agent studio --classic`). Built on Python's own HTTP server and plain JavaScript: no new
  dependencies, nothing loaded from the internet.
  - **Home**: one box; type a task, pick an agent, Enter to run; recent runs below
  - **Agents**: cards with what each can touch; editor with access presets (Answers only, Workspace
    files, Organize a folder, Web research, Email, Custom), a compact permission table, Advanced closed
    by default, and a live panel of what it can do, checks and tools; Test, Plan, Run, Save, schedules
  - **Activity**: each run as a live conversation (streamed as it happens); tool steps fold into one line,
    approvals and questions are answered inline, Relay shows its phases and one line per chunk; Files,
    Speed and notes tabs; Stop, Resume, follow-ups, undo
  - **Library**: catalog, models (download with progress, remove, import .gguf), memory, workspace with
    a sandboxed website preview; **Tests**; **Settings**; light and dark
  - Safe by design: listens only on 127.0.0.1, accepts changes only from its own page (a secret that's
    new every start), refuses other Host names, previews workspace pages in a sandbox
- **Relay quality**:
  - **Feature chunks**: big files are split by feature (script.js → data, cart, filters, form checks…);
    workers sharing a file add their part, and code checks nobody removed another chunk's part
  - **Style guide**: for visual work the lead writes concrete colours, type, spacing, components and phone
    layout; every visual worker follows it
  - **🌐 Browser test** (`engine/browser.py`, Playwright, optional): the PM writes checks in a tiny step
    language (`click`, `fill`, `expect_text`, `expect_count`, `reload`, `phone`…); code runs them in a real
    browser, plus JavaScript errors (with file and line), broken images, missing charset and sideways
    scrolling on a phone. Failures go back to the owning chunk as patch fixes (3 rounds)
  - **👀 Visual review**: the lead looks at desktop + phone screenshots against the style guide and sends
    concrete CSS/HTML fixes to the chunk that owns the file
  - **Lead model** per agent (`lead_model`, optional): plans, designs, looks and writes the answer; workers
    use the agent's model. Off by default: on 16 GB a second model next to the worker swaps to disk
    (a bench run spent 71 of 80 minutes in two 12b calls)
  - **🔗 Joins** (`engine/joins.py`): code checks where the files meet. It finds names the script looks
    for that no element has, CSS and HTML that picked different class names, buttons with no style,
    a CSS block that is never closed, the same selector written several times, and duplicate ids,
    each with file and line. A script chunk is checked as soon as the HTML is done; integration gets
    code's list, finishes failed chunks, and code checks again (2 passes)
  - Workers see a **page map** (the ids, classes and data attributes the HTML really has) and the
    classes the CSS styles; the PM's contract lists every id, class, data attribute and function
  - A fix may change the other files it touches (where most bugs sit); code still checks that no
    other chunk's part was removed
  - The PM's browser checks are checked first: a selector naming an element HTML doesn't have is
    repaired (`#form submit` → `#form [type=submit]`) or the check is dropped; ids the checks use are
    given to the HTML chunk, so nothing is left unbuilt
  - A failed click says why: no element matches, hidden at this size, or covered by another element
  - `must_contain` understands selectors (`#menu-toggle` matches `id="menu-toggle"`); SVG drawings need
    at least 6 shapes; a text chunk that changed files counts as done
- Bench: `browser:` checks; the Website Builder test now clicks through the site (11 checks)
- **Pinpoint + Patch**: the Inspector returns findings (file, line, problem, fix); code checks them and
  attaches the real lines; agents fix just that spot with new tools `read_lines` (line numbers by code),
  `edit_file` (exact replace, refused unless the text appears once; tolerant of indentation and pasted
  line numbers) and `insert_lines`. Relay sends findings straight to the chunk that owns the file
- **Warm Start**: every model call keeps the model loaded (`keep_alive` 30 min,
  `OFFLINE_AGENT_KEEP_ALIVE` to change) and uses one context size, so Ollama doesn't reload;
  the Speed panel estimates how much of each prompt Ollama reused
- **Web Cache**: the same address twice in one job is downloaded once
- Relay: the PM sees the team's tools; a team that can't create files gets text chunks (code enforces
  it); questions get no output file; the PM writes the final answer from the results; a tool error is
  shown to the worker, and a chunk stops retrying when the same failure repeats or permission is missing
- Relay text chunks: the worker is told its reply is the result; what its tools really returned is kept
  as facts, and the PM writes the final answer from those facts (no invented dates or numbers)

## v0.3.1 (2026-10-23)

- Fix (Windows): the Test Bench, Relay checks, Workspace preview and scheduler now read and write
  files as UTF-8, so text like ₹ is no longer garbled and checks no longer miss it

## v0.3.0 (2026-10-23)

- **Triage**: rates each task (code signals first, the model only when unclear) and sends simple
  tasks to the main agent and complex ones to Relay. Per agent: `route: auto | single | relay`
- **Relay**: a PM agent splits a big job into small chunks with a shared contract; one fresh worker
  per chunk, code checks each chunk and retries only failed ones; an integration pass fits the pieces
  together; the Inspector reviews and the PM sends chunks back (2 rounds). State is saved, so jobs
  resume after a stop or restart (`offline-agent resume`, ▶ Resume in the run view); time limit per
  agent (`time_limit_min`, default 180)
- Bench: `--route main,relay,triage`
- Job notes: code keeps an "ALREADY MADE" list of files the job created, so the agent no longer
  redoes finished work after old messages are trimmed; duplicate open steps aren't added twice
- Bench checks can read several files together (e.g. a menu built by script.js counts)

- **Default model is now `gemma4:e4b`** (templates and new agents): in the Test Bench on a
  MacBook Air M2 it passed every test, was fastest on quick tasks and built the best website.
  `qwen3.5:9b` remains a tested alternative
- Test Bench **score**: % of checks passed, minus 10 for each time the Inspector sent the agent back
- Bench cases can switch the Inspector on with their own criteria; new checks `file_not_contains`,
  `count_text`, and `file_contains` with a list (names what's missing)
- Website Builder: the bench brief is now a fully interactive bakery site (cart saved in the browser,
  menu filters, form validation, open/closed badge, dark mode, mobile menu) with 5 SVG images and
  19 checks; the template draws SVG images, self-checks its work, has the Inspector on (2 attempts)
  and allows 40 steps and 8192-token replies

- **Stopwatch**: speed breakdown per model call (load / read / write, tokens/s) and per run
  (model, tools, waiting for you, verifier), with tips. Speed panel in every run
- **Telegram style everywhere**: Morse (compact tool output), Page Turner (paged reads for files,
  web pages, emails), Slim Schemas, Ghost Chatter, No Echo, Fade Out, Word Limit
- **Token Meter**: what each call sent and what the Telegram features saved
- **Full Voice**: Telegram style applies to working steps only; final answers are as detailed as needed
  and are continued automatically if cut off; readable Clerk summaries. Toggle per agent
- **Test Bench**: sandboxed tests for every agent, checks in code, comparison across Telegram /
  Full Voice / models; page, `offline-agent bench`, reports in `bench/`; agents can add a `bench:` test
- **Catalog**: plain-words cards for every agent (good for / not for / needs / examples / test result) and
  tool (inputs, safety, example output); Catalog page, card in Studio, `offline-agent info`, generated
  `docs/CATALOG.md`; a test keeps cards complete and the doc up to date
- Fix: Test Bench saved its report only after saying it was done
- Installs work with the setuptools already in a venv (`pip install -e . --no-build-isolation`)

## v0.2.0 (2026-10-20)

- **Rule mode for email**: the model writes sender/subject rules once; the mail server matches
  (IMAP SEARCH); code moves the emails and checks none are left. Gmail Sorter uses it.
- **read_feed**: RSS/Atom parsed in code, one line per headline, keyword/today/hours filters.
  News Collector uses it.
- **Memory**: local notes and code-written run summaries, searched by meaning
  (`nomic-embed-text`); Recall/Remember permissions; Memory page; poisoning warnings.
- **Schedules**: daily / chosen days / every N minutes; in the app or `offline-agent scheduler`;
  one scheduler at a time; unattended runs deny approvals.
- **Packaging**: `pip install git+https://github.com/anurag-devx/offline-agent.git`, the
  `offline-agent` command (studio, list, run, check, scheduler, where). Data lives in the project
  folder (git checkout) or `~/OfflineAgent` (installed). Code moved into `offline_agent/`.

## v0.1.1 (2026-10-20)

- Fix paths on macOS (symlinked home) and Windows (USERPROFILE, forward slashes)

## v0.1.0 (2026-10-20)

First public release.

- **Studio** (Streamlit): Design → Preview → Validate → Run → Deploy; Runs, Workspace, Models, Settings pages
- **Agents as YAML files**; 9 templates (File Sorter, Website Builder, Gmail Sorter, News Collector, ...)
- **Permission policy**: 10 capabilities (files, internet, email, asking you), each Off / Allow / Ask first;
  scopes for folders, file types, change limits, sites, mail folders; run-time folder/site grants;
  protected locations always blocked
- **Two modes**: Agent (model uses tools) and Rule (model writes one rule, code executes and checks it)
- **Job notes**: plan + checklist per job, agent's one-liners next to code evidence, old messages dropped
- **Verification**: read-only verifier checks the real state; sends the agent back until done
- **Telegram style**: compact tool output, capped replies, explicit context length
- **Runs**: background runs, live status, approvals (once / all / deny), questions, stop, file log, undo
- **Models**: list, download, delete, import `.gguf` (e.g. Unsloth exports)
- Everything recorded locally (`runs/`, `logs/`); nothing goes to an AI company
