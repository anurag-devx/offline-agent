"""
offline-agent command line.

  offline-agent studio                 open the Studio in your browser
  offline-agent list                   list your agents and the templates
  offline-agent run <agent.yaml>       chat with an agent in the terminal
  offline-agent check <agent.yaml>     validate an agent
  offline-agent scheduler              run schedules without the app (Ctrl+C to stop)
  offline-agent bench                  test agents and compare settings/models
  offline-agent where                  show where your data is stored
"""
import argparse
import json
import time

from .engine import get_manager, is_valid, load_agent, validate
from .engine.config import AGENTS_DIR, TEMPLATES_DIR

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
        from .engine.speed import summarize
        sp = summarize(run)
        print(f"{GREY}{run.file_changes} file changes. Notes: runs/{run.id}/notes.md{RESET}")
        print(f"{GREY}Speed: {sp['total_s']:.0f}s total, {sp['model_s']:.0f}s in the model, {sp['calls']} calls · "
              + " · ".join(f"{k} {v:.0f}s" for k, v in sp["parts"].items() if v >= 1) + RESET)
        for tip in sp["tips"]:
            print(f"{YELLOW}  tip: {tip}{RESET}")


def headless_scheduler():
    """Run schedules in this terminal. Nobody is watching, so 'Ask first' actions are denied."""
    from .engine.scheduler import get_scheduler, load_schedules
    mgr = get_manager(unattended=True)
    sched = get_scheduler(mgr, owner="headless")
    if not sched.start():
        print(f"{RED}Schedules are already being run by another process ({sched.status()}).{RESET}")
        return
    items = [s for s in load_schedules() if s.enabled]
    print(f"Running {len(items)} schedule(s). 'Ask first' actions are denied automatically. Ctrl+C to stop.")
    for s in items:
        print(f"  {s.name}: {s.describe()} · next {s.next_run.replace('T', ' ')}")
    seen = {}
    try:
        while True:
            for run in mgr.list():
                if seen.get(run.id) != run.status:
                    seen[run.id] = run.status
                    print(f"{GREY}[{run.started[11:16]}] {run.agent}: {run.status}{RESET}"
                          + (f" · {run.answer.splitlines()[0][:80]}" if not run.active and run.answer else ""))
            time.sleep(2)
    except KeyboardInterrupt:
        sched.stop()
        print("\nStopped.")


def studio(extra=()):
    """Start the Streamlit Studio (same as: streamlit run offline_agent/app.py)."""
    import subprocess
    import sys
    from pathlib import Path
    app = Path(__file__).resolve().parent / "app.py"
    return subprocess.call([sys.executable, "-m", "streamlit", "run", str(app), *extra])


def list_agents():
    for label, folder in (("Your agents", AGENTS_DIR), ("Templates", TEMPLATES_DIR)):
        print(f"{label} ({folder}):")
        for path in sorted(folder.glob("*.yaml")):
            print(f"  {path.name}")


def resolve_agent(arg):
    """A path, or just a name found in your agents or the templates."""
    from pathlib import Path
    p = Path(arg).expanduser()
    if p.exists():
        return p
    for folder in (AGENTS_DIR, TEMPLATES_DIR):
        for cand in (folder / arg, folder / f"{arg}.yaml"):
            if cand.exists():
                return cand
    raise SystemExit(f"Agent not found: {arg}. Try: offline-agent list")


def run_agent(arg, check_only=False):
    cfg = load_agent(resolve_agent(arg))
    print(f"Checking {cfg.name}...")
    ok = show_checks(cfg)
    if check_only:
        return
    if not ok:
        print(f"\n{RED}Fix the failed checks first.{RESET}")
        return
    chat(cfg)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="offline-agent", description="AI agents on local models.")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("studio", help="open the Studio in your browser")
    sub.add_parser("list", help="list agents and templates")
    p_run = sub.add_parser("run", help="chat with an agent in the terminal")
    p_run.add_argument("agent", help="agent YAML path or name, e.g. file_sorter")
    p_check = sub.add_parser("check", help="validate an agent")
    p_check.add_argument("agent")
    sub.add_parser("scheduler", help="run schedules without the app")
    p_bench = sub.add_parser("bench", help="test agents and compare settings/models")
    p_bench.add_argument("--agents", default="", help="comma separated names (default: all offline tests)")
    p_bench.add_argument("--models", default="", help="comma separated models (default: each agent's own)")
    p_bench.add_argument("--telegram", default="on", help="on, off or on,off")
    p_bench.add_argument("--full-voice", default="on", help="on, off or on,off")
    p_bench.add_argument("--internet", action="store_true", help="include internet tests")
    p_bench.add_argument("--email", action="store_true", help="include email tests (dry)")
    sub.add_parser("where", help="show where your data is stored")
    args, extra = parser.parse_known_args(argv)

    if args.cmd == "studio":
        return studio(extra)
    if args.cmd == "run":
        return run_agent(args.agent)
    if args.cmd == "check":
        return run_agent(args.agent, check_only=True)
    if args.cmd == "scheduler":
        return headless_scheduler()
    if args.cmd == "bench":
        return bench(args)
    if args.cmd == "where":
        from .engine.paths import PKG_DIR, ROOT
        print(f"Your data: {ROOT}\nProgram:   {PKG_DIR}\n(set OFFLINE_AGENT_HOME to move your data)")
        return
    if args.cmd == "list":
        return list_agents()
    parser.print_help()


def bench(args):
    import itertools
    from .engine.bench import available_agents, case_for, start_job
    found = available_agents()
    names = [a.strip() for a in args.agents.split(",") if a.strip()] or \
        [a for a in found if not case_for(a, found[a]).get("needs") and not case_for(a, found[a]).get("smoke")]
    tel = [x.strip() for x in args.telegram.split(",") if x.strip()]
    voice = [x.strip() for x in args.full_voice.split(",") if x.strip()]
    variants = [f"Telegram {t} + Full Voice {v}" for t, v in itertools.product(tel, voice)]
    models = [m.strip() for m in args.models.split(",") if m.strip()] or [""]
    job = start_job(get_manager(), agents=names, models=models, variants=variants,
                    internet=args.internet, email=args.email)
    print(f"Bench {job.id}: {job.total} test runs. Ctrl+C to stop.")
    shown = 0
    try:
        while not job.done:
            for r in job.results[shown:]:
                res = "skipped" if r.get("passed") is None else ("PASS" if r["passed"] else "FAIL")
                print(f"  {res:7} {r['agent']} · {r['model']} · {r['variant']} · {r.get('seconds', '-')}s")
            shown = len(job.results)
            time.sleep(1)
    except KeyboardInterrupt:
        job.stop()
        while not job.done:
            time.sleep(0.5)
    for r in job.results[shown:]:
        res = "skipped" if r.get("passed") is None else ("PASS" if r["passed"] else "FAIL")
        print(f"  {res:7} {r['agent']} · {r['model']} · {r['variant']} · {r.get('seconds', '-')}s")
    print("\nComparison:")
    for s in job.summary():
        print(f"  {s['model']} · {s['variant']}: {s['passed']} passed · {s['avg_seconds']}s avg · "
              f"{s['avg_calls']} calls · {s['avg_tokens_in']:.0f} tokens in")
    from .engine.bench import BENCH_DIR
    print(f"Report: {BENCH_DIR / (job.id + '.md')}")


def legacy_main():
    """Old style: python run.py [agent.yaml] [--check] [--scheduler]."""
    import sys
    argv = sys.argv[1:]
    if "--scheduler" in argv:
        return main(["scheduler"])
    files = [a for a in argv if not a.startswith("-")]
    if not files:
        return main(["list"])
    return main(["check" if "--check" in argv else "run", files[0]])


if __name__ == "__main__":
    main()
