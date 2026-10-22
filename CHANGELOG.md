# Changelog

## Unreleased

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
