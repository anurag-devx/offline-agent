# Changelog

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
