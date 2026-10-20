"""
run.py: run any agent from the terminal. Runs are recorded in runs/ just like in the app.

  python run.py                              list agents and templates
  python run.py agents/math_helper.yaml      chat with an agent
  python run.py agents/x.yaml --check        validate only
"""
import argparse
import json
import time

from engine import get_manager, is_valid, load_agent, validate
from engine.config import AGENTS_DIR, TEMPLATES_DIR

GREY, GREEN, RED, YELLOW, RESET = "\033[90m", "\033[92m", "\033[91m", "\033[93m", "\033[0m"


def show_checks(cfg):
    checks = validate(cfg)
    for c in checks:
        mark = f"{GREEN}ok{RESET}" if c["ok"] else (f"{RED}FAIL{RESET}" if c["level"] == "error" else f"{YELLOW}warn{RESET}")
        print(f"  [{mark}] {c['check']}: {c['detail']}")
    return is_valid(checks)


def print_event(e):
    t = e["type"]
    if t == "tool_call":
        print(f"{GREY}  -> {e['name']}({json.dumps(e['args'], ensure_ascii=False)[:200]}){RESET}")
    elif t == "tool_result":
        print(f"{GREY}  <- {str(e['result'])[:200]}{RESET}")
    elif t == "plan":
        print(f"{GREY}  [plan] " + " → ".join(e["steps"]) + RESET)
    elif t == "rule":
        print(f"{YELLOW}  [rule] {e['text']}{RESET}")
    elif t == "verification":
        print(f"{GREEN if e['complete'] else RED}  [check] {'complete' if e['complete'] else 'NOT complete'}: {e['reason']}{RESET}")
    elif t in ("nudge", "compacted"):
        print(f"{GREY}  [{t}] {e.get('content') or str(e.get('dropped')) + ' old messages dropped'}{RESET}")
    elif t == "file_op":
        print(f"{GREY}  [file] {e['op']} {e.get('src', '')} -> {e.get('dst', '')}{RESET}")
    elif t == "network":
        print(f"{GREY}  [web] {'allowed' if e['allowed'] else 'BLOCKED'} {e['url'][:120]}{RESET}")
    elif t == "answer":
        print(f"agent > {e['content']}\n")
    elif t in ("error", "stopped"):
        print(f"{RED}{e['content']}{RESET}\n")


def follow(mgr, run, seen):
    """Print new events until the run finishes; ask y/n when approval is needed."""
    try:
        while True:
            for e in run.events[seen:]:
                print_event(e)
            seen = len(run.events)
            if run.pending:
                p = run.pending
                if p["kind"] == "question":
                    mgr.answer(run.id, input(f"{YELLOW}  Agent asks: {p['question']}\n  your answer > {RESET}"))
                else:
                    ans = input(f"{YELLOW}  Allow {p['name']}({json.dumps(p['args'], ensure_ascii=False)[:300]})?"
                                f" [y]es / [a]ll this run / [N]o {RESET}").strip().lower()
                    mgr.decide(run.id, "all" if ans.startswith("a") else ("yes" if ans.startswith("y") else "no"))
                while run.pending:
                    time.sleep(0.1)
            if not run.active:
                for e in run.events[seen:]:
                    print_event(e)
                return len(run.events)
            time.sleep(0.2)
    except KeyboardInterrupt:
        mgr.stop(run.id)
        print(f"\n{RED}Stopping...{RESET}")
        while run.active:
            time.sleep(0.2)
        return len(run.events)


def chat(cfg):
    mgr = get_manager()
    run, seen = None, 0
    print(f"\n{cfg.name} ({cfg.model}). Type 'exit' to quit, 'new' for a fresh run.\n")
    while True:
        try:
            text = input("you > ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if text in ("exit", "quit"):
            break
        if text == "new":
            run = None
            print(f"{GREY}(new run){RESET}")
            continue
        if not text:
            continue
        if run is None:
            run, seen = mgr.start(cfg, text), 0
        else:
            mgr.send(run.id, text)
        seen = follow(mgr, run, seen)
    if run:
        print(f"{GREY}{run.file_changes} file changes. Notes: runs/{run.id}/notes.md{RESET}")


def main():
    parser = argparse.ArgumentParser(description="Run an offline agent.")
    parser.add_argument("config", nargs="?", help="Path to an agent YAML file")
    parser.add_argument("--check", action="store_true", help="Only validate the agent")
    args = parser.parse_args()

    if not args.config:
        for label, folder in (("Agents", AGENTS_DIR), ("Templates", TEMPLATES_DIR)):
            print(f"{label}:")
            for path in sorted(folder.glob("*.yaml")):
                print(f"  {path.relative_to(folder.parent)}")
        print("\nUsage: python run.py <file.yaml>")
        return

    cfg = load_agent(args.config)
    print(f"Checking {cfg.name}...")
    ok = show_checks(cfg)
    if args.check:
        return
    if not ok:
        print(f"\n{RED}Fix the failed checks first.{RESET}")
        return
    chat(cfg)


if __name__ == "__main__":
    main()
