"""
engine/bench.py: the Test Bench. Run agents one by one, check their results in code, compare.

Each test (a "case") runs in its own sandbox folder inside the workspace, and the agent is
limited to that folder, so approvals can be answered automatically. Email tests are dry: the
agent writes its rule, the move is denied, and only the rule is checked.

A bench "job" = agents × models × variants (e.g. Telegram on/off, Full Voice on/off).
Results are saved in bench/ as JSON + a Markdown report.
"""
import copy
import glob
import json
import threading
import time
from datetime import datetime
from pathlib import Path

import yaml

from . import audit
from .config import AGENTS_DIR, ROOT, TEMPLATES_DIR, WORKSPACE, list_configs, load_agent
from .credentials import email_configured
from .paths import PKG_DIR
from .permissions import OFF
from .speed import summarize

BENCH_DIR = ROOT / "bench"
SANDBOX_DIR = WORKSPACE / "_bench"
CASES_FILE = PKG_DIR / "bench_cases.yaml"
SMOKE = {"task": "In one or two sentences, what can you help me with?", "checks": [{"answer_not_empty": True}]}
TIMEOUT = 900  # seconds per case

VARIANTS = {  # name -> config overrides
    "Telegram on": {"terse": True}, "Telegram off": {"terse": False},
    "Full Voice on": {"full_voice": True}, "Full Voice off": {"full_voice": False},
}


def load_cases():
    try:
        return {c["agent"]: c for c in yaml.safe_load(CASES_FILE.read_text(encoding="utf-8"))["cases"]}
    except Exception:
        return {}


def available_agents():
    """{display name: path} for templates and your agents (yours win on name clashes)."""
    found = {}
    for name, path in list_configs(TEMPLATES_DIR).items():
        found[name] = path
    for name, path in list_configs(AGENTS_DIR).items():
        found[f"{name} (yours)" if name in found else name] = path
    return found


def case_for(name, cfg_path):
    """The test for an agent: its own `bench:` section, a built-in case, or the smoke test."""
    try:
        own = (yaml.safe_load(Path(cfg_path).read_text(encoding="utf-8")) or {}).get("bench")
    except Exception:
        own = None
    base = name.replace(" (yours)", "")
    return own or load_cases().get(base) or {**SMOKE, "smoke": True}


# ---------------------------------------------------------------- checks (all done by code)

def _files(folder, extensions=(), kinds=()):
    from .toolkits.files import kind_of
    exts = [e.lower() for e in extensions]
    return [p for p in Path(folder).iterdir() if p.is_file() and not p.name.startswith(".")
            and (not exts or p.suffix.lower() in exts) and (not kinds or kind_of(p) in kinds)] \
        if Path(folder).is_dir() else []


def run_checks(checks, run, sandbox):
    answer = (run.answer or "").lower()
    out = []
    for c in checks or []:
        (kind, arg), = c.items()
        try:
            if kind == "answer_contains":
                words = arg if isinstance(arg, list) else [arg]
                ok = any(str(w).lower() in answer for w in words)
                out.append((f"answer mentions {' / '.join(map(str, words))}", ok, ""))
            elif kind == "answer_not_empty":
                out.append(("answer is not empty", bool(answer.strip()), ""))
            elif kind == "file_exists":
                out.append((f"{arg} exists", (sandbox / arg).exists(), ""))
            elif kind == "file_contains":
                p = sandbox / arg["path"]
                ok = p.is_file() and str(arg["text"]).lower() in p.read_text(errors="replace").lower()
                out.append((f"{arg['path']} contains \"{arg['text']}\"", ok, "" if p.exists() else "file missing"))
            elif kind == "file_glob":
                hits = [Path(h) for h in glob.glob(str(sandbox / arg["pattern"]))]
                lines = max((len([x for x in h.read_text(errors="replace").splitlines() if x.strip()])
                             for h in hits if h.is_file()), default=0)
                ok = bool(hits) and lines >= arg.get("min_lines", 1)
                out.append((f"{arg['pattern']} with ≥{arg.get('min_lines', 1)} lines", ok, f"{lines} lines"))
            elif kind == "no_files":
                left = _files(sandbox / arg["folder"], arg.get("extensions", ()), arg.get("kinds", ()))
                out.append((f"no {','.join(arg.get('extensions', []) + arg.get('kinds', []))} left in "
                            f"{arg['folder']}", not left, f"{len(left)} left"))
            elif kind == "count_files":
                n = len(_files(sandbox / arg["folder"], arg.get("extensions", ()), arg.get("kinds", ())))
                want = arg.get("equals")
                ok = n == want if want is not None else n >= arg.get("at_least", 1)
                out.append((f"{arg['folder']} has {want if want is not None else '≥' + str(arg.get('at_least', 1))} "
                            f"files", ok, f"found {n}"))
            elif kind == "rule_written":
                rules = [e for e in run.events if e["type"] == "rule"]
                ok = bool(rules) and str(arg).lower() in json.dumps(rules[-1].get("rules", "")).lower()
                out.append((f"rule mentions {arg}", ok, ""))
            elif kind == "max_calls":
                n = sum(e["type"] == "model_call" for e in run.events)
                out.append((f"at most {arg} model calls", n <= arg, f"{n} calls"))
            else:
                out.append((f"unknown check {kind}", False, ""))
        except Exception as e:
            out.append((kind, False, f"check failed: {e}"))
    return out


# ---------------------------------------------------------------- one case

def prepare(cfg, case, sandbox):
    """A copy of the agent that can only touch the sandbox, saves no memory, and never wanders."""
    cfg = copy.deepcopy(cfg)
    sandbox.mkdir(parents=True, exist_ok=True)
    for rel, content in (case.get("setup") or {}).items():
        p = sandbox / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(str(content), encoding="utf-8")
    pol = cfg.permissions
    pol.files.folders = [str(sandbox)]
    pol.files.ask_for_other_folders = False
    pol.internet.other_domains = "block"
    pol.memory.write, pol.memory.run_summaries = OFF, False
    return cfg


def run_case(manager, cfg, case, sandbox, should_stop=lambda: False, timeout=TIMEOUT):
    cfg = prepare(cfg, case, sandbox)
    task = str(case["task"]).replace("{sandbox}", str(sandbox))
    answers = list(case.get("answers") or [str(sandbox)])
    run = manager.start(cfg, f"[bench] {task}", auto={"approve": "no" if case.get("dry") else "all",
                                                      "answers": answers})
    end = time.time() + timeout
    while run.active:
        if should_stop() or time.time() > end:
            manager.stop(run.id)
        time.sleep(0.2)
    checks = run_checks(case.get("checks"), run, sandbox)
    if not case.get("dry"):
        checks.insert(0, ("run completed", run.status == "completed", run.status))
    sp = summarize(run)
    return {"run_id": run.id, "status": run.status, "passed": all(ok for _, ok, _ in checks),
            "checks": [{"check": n, "ok": ok, "detail": d} for n, ok, d in checks],
            "seconds": round(run.duration(), 1), "model_s": sp["model_s"], "calls": sp["calls"],
            "prompt_tokens": sp["prompt_tokens"], "output_tokens": sp["output_tokens"],
            "saved_pct": sp["saved_pct"], "answer": (run.answer or "")[:300]}


# ---------------------------------------------------------------- a job: many cases

class BenchJob:
    def __init__(self, manager, agents, models=("",), variants=("Telegram on",), internet=False, email=False):
        self.manager = manager
        self.id = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.agents, self.models, self.variants = list(agents), list(models) or [""], list(variants) or [""]
        self.internet, self.email = internet, email
        self.results, self.current, self.done = [], "", False
        self.total = len(self.agents) * len(self.models) * len(self.variants)
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        found = available_agents()
        n = 0
        for name in self.agents:
            path = found.get(name)
            if not path:
                continue
            base_cfg = load_agent(path)
            case = case_for(name, path)
            for model in self.models:
                for variant in self.variants:
                    n += 1
                    if self._stop.is_set():
                        break
                    cfg = copy.deepcopy(base_cfg)
                    if model:
                        cfg.model = model
                    for part in [v.strip() for v in variant.split("+") if v.strip()]:
                        for k, v in VARIANTS.get(part, {}).items():
                            setattr(cfg, k, v)
                    row = {"agent": name, "model": cfg.model, "variant": variant or "as saved", "case": case["task"][:80]}
                    self.current = f"{n}/{self.total}: {name} · {cfg.model} · {row['variant']}"
                    needs = case.get("needs")
                    if needs == "internet" and not self.internet:
                        self.results.append({**row, "status": "skipped", "passed": None, "why": "internet tests off"})
                        continue
                    if needs == "email" and (not self.email or not email_configured()):
                        self.results.append({**row, "status": "skipped", "passed": None,
                                             "why": "email tests off" if not self.email else "email not set up"})
                        continue
                    sandbox = SANDBOX_DIR / self.id / f"{n:02d}"
                    try:
                        self.results.append({**row, **run_case(self.manager, cfg, case, sandbox, self._stop.is_set)})
                    except Exception as e:
                        self.results.append({**row, "status": "error", "passed": False, "why": str(e)})
        self.current, self.done = "", True
        self.save()
        audit.log("bench_finished", job=self.id, cases=len(self.results),
                  passed=sum(1 for r in self.results if r.get("passed")))

    def start(self):
        threading.Thread(target=self.run, daemon=True).start()
        audit.log("bench_started", job=self.id, total=self.total)
        return self

    # ---- comparison
    def summary(self):
        return compare(self.results)

    def save(self):
        BENCH_DIR.mkdir(exist_ok=True)
        data = {"id": self.id, "results": self.results, "summary": self.summary()}
        (BENCH_DIR / f"{self.id}.json").write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        (BENCH_DIR / f"{self.id}.md").write_text(report_markdown(data), encoding="utf-8")


def compare(results):
    """One row per model × variant: pass rate and averages."""
    groups = {}
    for r in results:
        if r.get("passed") is None:
            continue
        g = groups.setdefault((r["model"], r["variant"]), [])
        g.append(r)
    rows = []
    for (model, variant), rs in groups.items():
        ran = [r for r in rs if "seconds" in r]
        avg = (lambda k: round(sum(r[k] for r in ran) / len(ran), 1)) if ran else (lambda k: 0)
        rows.append({"model": model, "variant": variant, "passed": f"{sum(1 for r in rs if r['passed'])}/{len(rs)}",
                     "pass_rate": round(100 * sum(1 for r in rs if r["passed"]) / len(rs)),
                     "avg_seconds": avg("seconds"), "avg_model_s": avg("model_s"), "avg_calls": avg("calls"),
                     "avg_tokens_in": avg("prompt_tokens"), "avg_tokens_out": avg("output_tokens"),
                     "avg_saved_pct": avg("saved_pct")})
    return sorted(rows, key=lambda x: (-x["pass_rate"], x["avg_seconds"]))


def report_markdown(data):
    lines = [f"# Test Bench {data['id']}", "", "## Comparison", "",
             "| Model | Variant | Passed | Avg time | Avg model time | Avg calls | Avg tokens in/out | Saved |",
             "|---|---|---|---|---|---|---|---|"]
    for s in data["summary"]:
        lines.append(f"| {s['model']} | {s['variant']} | {s['passed']} | {s['avg_seconds']}s | {s['avg_model_s']}s | "
                     f"{s['avg_calls']} | {s['avg_tokens_in']:.0f}/{s['avg_tokens_out']:.0f} | {s['avg_saved_pct']:.0f}% |")
    lines += ["", "## Every test", "", "| Agent | Model | Variant | Result | Time | Calls | Failed checks |",
              "|---|---|---|---|---|---|---|"]
    for r in data["results"]:
        res = "skipped" if r.get("passed") is None else ("✅ pass" if r["passed"] else "❌ fail")
        failed = "; ".join(c["check"] + (f" ({c['detail']})" if c["detail"] else "")
                           for c in r.get("checks", []) if not c["ok"]) or r.get("why", "")
        lines.append(f"| {r['agent']} | {r['model']} | {r['variant']} | {res} | {r.get('seconds', '')}s | "
                     f"{r.get('calls', '')} | {failed} |")
    return "\n".join(lines) + "\n"


def past_reports():
    return sorted(BENCH_DIR.glob("*.json"), reverse=True) if BENCH_DIR.exists() else []


_job = None


def current_job():
    return _job


def start_job(manager, **kw):
    global _job
    if _job and not _job.done:
        raise RuntimeError("A bench is already running.")
    _job = BenchJob(manager, **kw).start()
    return _job
