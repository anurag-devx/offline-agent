"""
web/server.py: the Studio's local web server. A JSON API over the engine, plus the app's files.

    offline-agent studio            -> http://127.0.0.1:8765

Only this computer can reach it (it listens on 127.0.0.1). Because agents can move files and
read email, requests that change something must come from the Studio page itself: they need the
X-Offline-Agent header (a web page on another site can't add it without the browser asking this
server first, and this server never says yes) carrying a secret that only the Studio page knows (a new
one each start), and the Host must be localhost (blocks DNS tricks).

Live updates use Server-Sent Events: the browser keeps one request open and the server writes
each new run event to it as it happens.
"""
import base64
import io
import json
import mimetypes
import secrets
import threading
import time
import traceback
import webbrowser
import zipfile
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .. import __version__
from ..engine import audit, llm
from ..engine.config import AGENTS_DIR, ROOT, TEMPLATES_DIR, WORKSPACE, AgentConfig, load_agent, save_agent
from ..engine.permissions import CAPABILITIES, GROUPS, MODE_LABEL
from ..engine.runs import get_manager

STATIC = Path(__file__).resolve().parent / "static"
HEADER = "X-Offline-Agent"
TOKEN = secrets.token_urlsafe(18)  # new every start; only the Studio page gets it
LOCAL_HOSTS = ("127.0.0.1", "localhost", "[::1]")
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("image/svg+xml", ".svg")


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


# ------------------------------------------------------------------ agents

def _agent_files():
    """{id: path}: t-<name> for templates, a-<name> for your agents."""
    out = {}
    for prefix, folder in (("t", TEMPLATES_DIR), ("a", AGENTS_DIR)):
        for path in sorted(Path(folder).glob("*.yaml")):
            out[f"{prefix}-{path.stem}"] = path
    return out


def _agent_path(aid):
    path = _agent_files().get(aid)
    if not path:
        raise ApiError(404, f"No agent {aid}.")
    return path


def _card(aid, path):
    from ..engine.catalog import agent_card, latest_bench
    try:
        cfg = load_agent(path)
    except Exception as e:
        return {"id": aid, "name": path.stem, "what": f"(unreadable: {e})", "error": True}
    card = agent_card(cfg, latest_bench(cfg.name))
    return {"id": aid, "kind": "template" if aid.startswith("t-") else "mine", **card,
            "route": cfg.route, "mode_key": cfg.mode}


def list_agents(_q, _b):
    cards = [_card(aid, p) for aid, p in _agent_files().items()]
    return {"templates": [c for c in cards if c.get("kind") == "template"],
            "mine": [c for c in cards if c.get("kind") == "mine"]}


def get_agent(aid):
    path = _agent_path(aid)
    cfg = load_agent(path)
    return {"id": aid, "kind": "template" if aid.startswith("t-") else "mine", **inspect_config(cfg)}


def inspect_config(cfg):
    """Everything the editor shows next to the form: checks, summary, tools, card, YAML."""
    from ..engine import is_valid, validate
    from ..engine.catalog import agent_card
    from ..engine.planner import capabilities_summary
    from ..engine.tools import tools_for
    checks = validate(cfg)
    allowed, asks, off, notes = capabilities_summary(cfg)
    saved = AGENTS_DIR / f"{cfg.slug}.yaml"
    return {"config": cfg.to_dict(), "checks": checks, "valid": is_valid(checks), "tools": tools_for(cfg),
            "summary": {"allowed": allowed, "asks": asks, "off": off, "notes": notes},
            "card": agent_card(cfg), "yaml": cfg.to_yaml(),
            "saved_as": f"a-{cfg.slug}" if saved.exists() else "",
            "unsaved": not (saved.exists() and saved.read_text(encoding="utf-8") == cfg.to_yaml())}


def _cfg(body):
    data = (body or {}).get("config")
    if not isinstance(data, dict):
        raise ApiError(400, "Send the agent as {config: {...}}.")
    return AgentConfig.from_dict(data)


def check_agent(_q, body):
    return inspect_config(_cfg(body))


def save(_q, body):
    cfg = _cfg(body)
    path = save_agent(cfg, AGENTS_DIR)
    audit.log("agent_saved", agent=cfg.name, path=str(path))
    return {"id": f"a-{path.stem}", "path": str(path), **inspect_config(cfg)}


def delete_agent(aid):
    if not aid.startswith("a-"):
        raise ApiError(400, "Templates can't be deleted.")
    path = _agent_path(aid)
    trash = AGENTS_DIR / ".deleted"
    trash.mkdir(exist_ok=True)
    dest = trash / f"{path.stem}-{time.strftime('%Y%m%d-%H%M%S')}.yaml"
    path.rename(dest)
    audit.log("agent_deleted", agent=path.stem, kept_in=str(dest))
    return {"ok": True, "kept_in": str(dest)}


def blank(_q, _b):
    return inspect_config(AgentConfig(name="New agent", description=""))


def generate(_q, body):
    from ..engine.planner import generate_agent
    desc, model = str(body.get("description") or "").strip(), str(body.get("model") or "")
    if not desc:
        raise ApiError(400, "Describe the agent first.")
    cfg = generate_agent(desc, model or (llm.list_models() or ["gemma4:e4b"])[0])
    audit.log("agent_generated", description=desc, model=model, name=cfg.name)
    return inspect_config(cfg)


def plan(_q, body):
    from ..engine.planner import plan_task
    task = str(body.get("task") or "").strip()
    if not task:
        raise ApiError(400, "Give it a task.")
    return plan_task(_cfg(body), task)


def dry(_q, body):
    from ..engine import dry_run
    ok, events, secs = dry_run(_cfg(body), str(body.get("task") or "What can you help me with?"))
    return {"ok": ok, "events": events, "seconds": round(secs, 1)}


def meta(_q, _b):
    """Static facts the editor needs: capabilities and their wording."""
    from ..engine.tools import TOOLS, is_internal
    return {"capabilities": CAPABILITIES, "groups": {k: v.split(" ", 1)[1] for k, v in GROUPS.items()},
            "modes": MODE_LABEL, "version": __version__,
            "tools": {n: t["permission"] for n, t in TOOLS.items() if not is_internal(n)}}


# ------------------------------------------------------------------ runs

def run_row(r):
    from ..engine.speed import summarize
    return {"id": r.id, "agent": r.agent, "model": r.model, "task": r.task, "status": r.status,
            "active": r.active, "started": r.started, "ended": r.ended, "seconds": round(r.duration(), 1),
            "steps": r.steps, "tool_calls": r.tool_calls, "file_changes": r.file_changes,
            "tokens": r.prompt_tokens + r.output_tokens, "route": r.route, "verified": r.verified,
            "answer": (r.answer or "")[:400], "model_s": summarize(r)["model_s"]}


def list_runs(q, _b):
    mgr = get_manager()
    limit = int((q.get("limit") or ["100"])[0])
    agent = (q.get("agent") or [""])[0]
    runs = [r for r in mgr.list() if not agent or r.agent == agent][:limit]
    return {"runs": [run_row(r) for r in runs], "counts": dict(mgr.counts())}


def _run(rid):
    run = get_manager().runs.get(rid)
    if not run:
        raise ApiError(404, f"No run {rid}.")
    return run


def run_detail(rid):
    from ..engine.relay import markdown as relay_markdown
    from ..engine.speed import summarize
    mgr, run = get_manager(), _run(rid)
    data = {k: v for k, v in asdict(run).items() if k not in ("events", "config")}
    data.update(seconds=round(run.duration(), 1), active=run.active, events=run.events, speed=summarize(run),
                can_continue=mgr.can_continue(rid), can_resume=mgr.can_resume(rid),
                notes=relay_markdown(run.id, run.relay) if run.relay and run.relay.get("chunks") else "",
                shots=bool((run.relay or {}).get("test", {}).get("shots")))
    if run.ledger and not data["notes"]:
        from ..engine.ledger import Ledger
        data["notes"] = Ledger.from_dict(run.ledger).to_markdown({"file changes": run.file_changes,
                                                                   "tool calls": run.tool_calls})
    return data


def start_run(_q, body):
    task = str(body.get("task") or "").strip()
    if not task:
        raise ApiError(400, "What should the agent do?")
    if body.get("agent"):
        cfg = load_agent(_agent_path(body["agent"]))
    else:
        cfg = _cfg(body)
    run = get_manager().start(cfg, task)
    return {"id": run.id}


def run_action(rid, action, body):
    mgr = get_manager()
    _run(rid)
    if action == "decide":
        mgr.decide(rid, str(body.get("choice") or "no"))
    elif action == "answer":
        mgr.answer(rid, str(body.get("text") or ""))
    elif action == "stop":
        mgr.stop(rid)
    elif action == "send":
        text = str(body.get("message") or "").strip()
        if not text:
            raise ApiError(400, "Write a message.")
        try:
            mgr.send(rid, text)
        except ValueError as e:
            raise ApiError(409, str(e)) from None
    elif action == "resume":
        try:
            mgr.resume(rid)
        except ValueError as e:
            raise ApiError(409, str(e)) from None
    elif action == "undo":
        return {"results": mgr.undo_file_changes(rid)}
    else:
        raise ApiError(404, f"Unknown action {action}.")
    return {"ok": True}


def run_shot(rid, which):
    run = _run(rid)
    path = ((run.relay or {}).get("test") or {}).get("shots", {}).get(which)
    if not path or not Path(path).is_file():
        raise ApiError(404, "No screenshot.")
    return Path(path)


# ------------------------------------------------------------------ library

def catalog(_q, _b):
    from ..engine.catalog import all_tool_cards
    return {"agents": list_agents(None, None), "tools": all_tool_cards(include_internal=False)}


def models_list(_q, _b):
    from ..engine import models
    if not llm.is_running():
        return {"running": False, "models": []}
    return {"running": True, "models": models.installed()}


def model_delete(name):
    from ..engine import models
    models.delete(name)
    return {"ok": True}


def model_find(_q, body):
    from ..engine import models
    try:
        return {"files": models.find_gguf(str(body.get("folder") or "~/Downloads"))}
    except Exception as e:
        raise ApiError(400, str(e)) from None


def model_import(_q, body):
    from ..engine import models
    name = str(body.get("name") or "")
    if not models.valid_model_name(name):
        raise ApiError(400, "Use lowercase letters, numbers, - . _ and optionally :tag")
    ok, out = models.import_gguf(str(body.get("path") or ""), name)
    return {"ok": ok, "output": out, "capabilities": list(llm.capabilities(name)) if ok else []}


def memory_get(q, _b):
    from ..engine.memory import EMBED_MODEL, get_store
    store = get_store()
    scopes = store.scopes()
    scope = (q.get("scope") or [""])[0] or (scopes[0] if scopes else "shared")
    query = (q.get("q") or [""])[0].strip()
    rows = store.search(scope, query, k=50, min_score=0.2) if query else store.rows(scope)
    semantic = any(m.startswith(EMBED_MODEL) for m in _all_model_names())
    return {"scopes": scopes or ["shared"], "scope": scope, "semantic": semantic, "embed_model": EMBED_MODEL,
            "rows": [{k: v for k, v in r.items() if k != "embedding"} for r in rows]}


def _all_model_names():
    try:
        import ollama
        return [m.model for m in ollama.list().models]
    except Exception:
        return []


def memory_add(_q, body):
    from ..engine.memory import get_store
    text = str(body.get("text") or "").strip()
    if not text:
        raise ApiError(400, "Write the note.")
    return {"id": get_store().add(str(body.get("scope") or "shared"), text, kind="fact", run="manual")}


def memory_change(mid, body, delete=False):
    from ..engine.memory import get_store
    store = get_store()
    ok = store.delete(int(mid)) if delete else store.update(int(mid), str(body.get("text") or ""))
    return {"ok": bool(ok)}


def _ws_path(rel):
    p = (WORKSPACE / unquote(str(rel or ""))).resolve()
    if not (p == WORKSPACE.resolve() or WORKSPACE.resolve() in p.parents):
        raise ApiError(403, "Outside the workspace.")
    return p


def workspace_list(_q, _b):
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    root = WORKSPACE.resolve()
    files = []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if p.is_file() and not any(x.startswith(".") for x in rel.parts):
            files.append({"path": rel.as_posix(), "size": p.stat().st_size, "modified": p.stat().st_mtime})
    return {"root": str(root), "files": files[:5000]}


def workspace_text(q, _b):
    p = _ws_path((q.get("path") or [""])[0])
    if not p.is_file():
        raise ApiError(404, "No such file.")
    return {"path": str(p.relative_to(WORKSPACE.resolve()).as_posix()),
            "text": p.read_text(encoding="utf-8", errors="replace")[:200000]}


def workspace_upload(_q, body):
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    saved = []
    for f in body.get("files") or []:
        name = Path(str(f.get("name") or "")).name  # never trust a path from the browser
        if not name or name.startswith("."):
            continue
        (WORKSPACE / name).write_bytes(base64.b64decode(f.get("data") or ""))
        audit.log("workspace_upload", file=name)
        saved.append(name)
    return {"saved": saved}


def workspace_zip():
    buf = io.BytesIO()
    root = WORKSPACE.resolve()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(root.rglob("*")):
            if p.is_file() and not any(x.startswith(".") for x in p.relative_to(root).parts):
                z.write(p, p.relative_to(root).as_posix())
    return buf.getvalue()


# ------------------------------------------------------------------ schedules, tests, settings

def schedules_get(_q, _b):
    from ..engine.scheduler import get_scheduler, load_schedules
    mgr = get_manager()
    items = []
    for s in load_schedules():
        d = asdict(s)
        d["when"] = s.describe()
        last = mgr.runs.get(s.last_run_id)
        d["last_status"] = last.status if last else ""
        items.append(d)
    return {"status": get_scheduler(mgr).status(), "schedules": items}


def schedule_add(_q, body):
    from ..engine.scheduler import add_schedule
    path = _agent_path(str(body.get("agent") or ""))
    task = str(body.get("task") or "").strip()
    if not task:
        raise ApiError(400, "Give the schedule a task.")
    s = add_schedule(str(body.get("name") or f"{path.stem} schedule"), str(path.relative_to(ROOT)) if
                     ROOT in path.parents else str(path), task, kind=body.get("kind", "daily"),
                     time_=str(body.get("time") or "09:00"), weekdays=body.get("weekdays") or (),
                     every_minutes=int(body.get("every_minutes") or 60))
    return {"id": getattr(s, "id", "")}


def schedule_change(sid, body, delete=False):
    from ..engine.scheduler import delete_schedule, load_schedules, update_schedule
    if delete:
        delete_schedule(sid)
        return {"ok": True}
    if body.get("run_now"):
        s = next((x for x in load_schedules() if x.id == sid), None)
        if not s:
            raise ApiError(404, "No such schedule.")
        run = get_manager().start(load_agent(ROOT / s.agent), s.task)
        update_schedule(sid, last_run_id=run.id, last_result="started (manual)")
        return {"run": run.id}
    update_schedule(sid, **{k: v for k, v in body.items() if k in ("enabled", "task", "name", "time",
                                                                   "every_minutes", "weekdays", "kind")})
    return {"ok": True}


def bench_get(_q, _b):
    from ..engine import bench
    agents = bench.available_agents()
    job = bench.current_job()
    reports = []
    for p in bench.past_reports()[:30]:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            reports.append({"id": data["id"], "summary": data.get("summary", []), "count": len(data.get("results", []))})
        except Exception:
            continue
    cases = {name: {"needs": bench.case_for(name, path).get("needs"), "smoke": bool(bench.case_for(name, path).get("smoke")),
                    "task": str(bench.case_for(name, path).get("task", ""))[:200]} for name, path in agents.items()}
    return {"agents": cases, "variants": list(bench.VARIANTS), "models": llm.list_models(), "reports": reports,
            "job": None if not job else {"id": job.id, "done": job.done, "current": job.current, "total": job.total,
                                         "results": job.results, "summary": job.summary()}}


def bench_start(_q, body):
    from ..engine import bench
    try:
        job = bench.start_job(get_manager(), agents=list(body.get("agents") or []), models=list(body.get("models") or [""]),
                              variants=list(body.get("variants") or [""]), internet=bool(body.get("internet")),
                              email=bool(body.get("email")), timeout=int(body.get("timeout_min") or 15) * 60)
    except RuntimeError as e:
        raise ApiError(409, str(e)) from None
    return {"id": job.id, "total": job.total}


def bench_stop(_q, _b):
    from ..engine import bench
    job = bench.current_job()
    if job:
        job.stop()
    return {"ok": True}


def bench_report(rid):
    from ..engine import bench
    p = bench.BENCH_DIR / f"{Path(rid).name}.json"
    if not p.is_file():
        raise ApiError(404, "No such report.")
    return json.loads(p.read_text(encoding="utf-8"))


def settings_get(_q, _b):
    from ..engine.credentials import CRED_PATH, load_credentials
    e = load_credentials().get("email") or {}
    return {"email": {"imap_host": e.get("imap_host", "imap.gmail.com"), "address": e.get("address", ""),
                      "saved": bool(e.get("password"))}, "cred_path": str(CRED_PATH), "root": str(ROOT),
            "workspace": str(WORKSPACE), "version": __version__}


def settings_email(_q, body):
    from ..engine.credentials import load_credentials, save_credentials
    creds = load_credentials()
    old = creds.get("email") or {}
    creds["email"] = {"imap_host": str(body.get("imap_host") or "").strip(), "address": str(body.get("address") or "").strip(),
                      "password": str(body.get("password") or "").replace(" ", "") or old.get("password", "")}
    save_credentials(creds)
    audit.log("email_settings_saved", address=creds["email"]["address"], host=creds["email"]["imap_host"])
    return {"ok": True}


def settings_email_test(_q, _b):
    try:
        from ..engine.toolkits.mail import _connect, list_folder_names
        conn = _connect()
        names = list_folder_names(conn)
        conn.logout()
        return {"ok": True, "folders": len(names)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def status(_q, _b):
    mgr = get_manager()
    c = mgr.counts()
    return {"ollama": llm.is_running(), "models": llm.list_models(), "version": __version__,
            "running": c.get("running", 0) + c.get("verifying", 0),
            "waiting": c.get("waiting_approval", 0) + c.get("waiting_input", 0)}


def activity(_q, _b):
    from ..engine.audit import read_activity
    return {"items": read_activity(300)}


# ------------------------------------------------------------------ routing

ROUTES = {
    ("GET", "/api/status"): status,
    ("GET", "/api/meta"): meta,
    ("GET", "/api/agents"): list_agents,
    ("POST", "/api/agents"): save,
    ("POST", "/api/agents/check"): check_agent,
    ("POST", "/api/agents/generate"): generate,
    ("GET", "/api/agents/blank"): blank,
    ("POST", "/api/agents/plan"): plan,
    ("POST", "/api/agents/dry-run"): dry,
    ("GET", "/api/runs"): list_runs,
    ("POST", "/api/runs"): start_run,
    ("GET", "/api/catalog"): catalog,
    ("GET", "/api/models"): models_list,
    ("POST", "/api/models/find"): model_find,
    ("POST", "/api/models/import"): model_import,
    ("GET", "/api/memory"): memory_get,
    ("POST", "/api/memory"): memory_add,
    ("GET", "/api/workspace"): workspace_list,
    ("GET", "/api/workspace/text"): workspace_text,
    ("POST", "/api/workspace/upload"): workspace_upload,
    ("GET", "/api/schedules"): schedules_get,
    ("POST", "/api/schedules"): schedule_add,
    ("GET", "/api/bench"): bench_get,
    ("POST", "/api/bench"): bench_start,
    ("POST", "/api/bench/stop"): bench_stop,
    ("GET", "/api/settings"): settings_get,
    ("POST", "/api/settings/email"): settings_email,
    ("POST", "/api/settings/email/test"): settings_email_test,
    ("GET", "/api/activity"): activity,
}


class Handler(BaseHTTPRequestHandler):
    server_version = "offline-agent"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # quiet: runs and activity are recorded elsewhere
        pass

    # ---------------------------------------------------------- helpers
    def _send(self, status, body=b"", ctype="application/json", extra=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status, data):
        self._send(status, json.dumps(data, default=str).encode("utf-8"), "application/json; charset=utf-8")

    def _file(self, path, ctype=None, sandbox=False):
        ctype = ctype or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "image/svg+xml"):
            ctype += "; charset=utf-8"
        extra = {"Content-Security-Policy": "sandbox allow-scripts allow-forms allow-modals"} if sandbox else {}
        self._send(200, Path(path).read_bytes(), ctype, extra)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 200_000_000:
            raise ApiError(413, "Too large.")
        raw = self.rfile.read(n) if n else b""
        try:
            return json.loads(raw or b"{}")
        except ValueError:
            raise ApiError(400, "Send JSON.") from None

    def _guard(self, changing):
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].lower()
        if host not in LOCAL_HOSTS:
            raise ApiError(403, "Only reachable as localhost.")
        if changing and not secrets.compare_digest(self.headers.get(HEADER) or "", TOKEN):
            raise ApiError(403, "Requests must come from the Studio page. Reload it.")

    # ---------------------------------------------------------- verbs
    def do_GET(self):
        self._handle("GET")

    def do_HEAD(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PUT(self):
        self._handle("PUT")

    def do_DELETE(self):
        self._handle("DELETE")

    def do_OPTIONS(self):  # no cross-site requests, ever
        self._send(403, b"")

    def _handle(self, method):
        url = urlparse(self.path)
        path, q = url.path, parse_qs(url.query)
        try:
            self._guard(method != "GET")
            if path.startswith("/api/"):
                return self._api(method, path, q)
            if path.startswith("/ws/"):  # workspace files, so built websites preview with their CSS/JS
                p = _ws_path(path[4:])
                if not p.is_file():
                    raise ApiError(404, "No such file.")
                return self._file(p, sandbox=True)
            name = path.lstrip("/") or "index.html"
            p = (STATIC / name).resolve()
            if STATIC.resolve() not in p.parents or not p.is_file():
                p = STATIC / "index.html"  # the app routes itself (#/agents, #/activity...)
            if p.name == "index.html":
                html = p.read_text(encoding="utf-8").replace("__OA_TOKEN__", TOKEN)
                return self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
            return self._file(p)
        except ApiError as e:
            self._json(e.status, {"error": str(e)})
        except BrokenPipeError:
            pass
        except Exception as e:
            traceback.print_exc()
            try:
                self._json(500, {"error": f"{type(e).__name__}: {e}"})
            except Exception:
                pass

    def _api(self, method, path, q):
        body = self._body() if method in ("POST", "PUT", "DELETE") else {}
        fn = ROUTES.get((method, path))
        if fn:
            return self._json(200, fn(q, body))
        parts = [unquote(x) for x in path.split("/")[2:]]  # api/<what>/<id>/<action>
        what = parts[0] if parts else ""
        if what == "agents" and len(parts) == 2:
            if method == "GET":
                return self._json(200, get_agent(parts[1]))
            if method == "DELETE":
                return self._json(200, delete_agent(parts[1]))
        if what == "runs" and len(parts) >= 2:
            rid = parts[1]
            if len(parts) == 2 and method == "GET":
                return self._json(200, run_detail(rid))
            if len(parts) == 3 and parts[2] == "stream" and method == "GET":
                return self._stream_run(rid, int((q.get("from") or ["0"])[0]))
            if len(parts) == 4 and parts[2] == "shot":
                return self._file(run_shot(rid, parts[3]))
            if len(parts) == 3 and method == "POST":
                return self._json(200, run_action(rid, parts[2], body))
        if what == "models" and len(parts) == 2 and method == "DELETE":
            return self._json(200, model_delete(parts[1]))
        if what == "models" and parts[1:] == ["pull"] and method == "GET":  # a download: needs the secret too
            if not secrets.compare_digest((q.get("token") or [""])[0], TOKEN):
                raise ApiError(403, "Requests must come from the Studio page. Reload it.")
            return self._stream_pull((q.get("name") or [""])[0])
        if what == "memory" and len(parts) == 2 and method in ("PUT", "DELETE"):
            return self._json(200, memory_change(parts[1], body, delete=method == "DELETE"))
        if what == "workspace" and parts[1:] == ["zip"]:
            return self._send(200, workspace_zip(), "application/zip",
                              {"Content-Disposition": 'attachment; filename="workspace.zip"'})
        if what == "schedules" and len(parts) == 2 and method in ("PUT", "DELETE", "POST"):
            return self._json(200, schedule_change(parts[1], body, delete=method == "DELETE"))
        if what == "bench" and len(parts) == 3 and parts[1] == "report":
            return self._json(200, bench_report(parts[2]))
        raise ApiError(404, f"No API {method} {path}.")

    # ---------------------------------------------------------- live streams
    def _sse_start(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        self.close_connection = True

    def _sse(self, event, data):
        self.wfile.write(f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n".encode("utf-8"))
        self.wfile.flush()

    def _stream_run(self, rid, start):
        """New events as they happen, plus the run's status whenever it changes. Ends when the run stops."""
        run = _run(rid)
        self._sse_start()
        sent, last_meta, idle = max(0, start), None, time.time()
        try:
            while True:
                events = run.events[sent:]
                for e in events:
                    self._sse("event", {"i": sent, "e": e})
                    sent += 1
                m = {**run_row(run), "pending": run.pending, "attempts": run.attempts,
                     "relay_phase": (run.relay or {}).get("phase", "")}
                if m != last_meta:
                    self._sse("meta", m)
                    last_meta = m
                if events:
                    idle = time.time()
                if not run.active and sent >= len(run.events):
                    self._sse("end", {"status": run.status})
                    return
                if time.time() - idle > 15:
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
                    idle = time.time()
                time.sleep(0.3)
        except (BrokenPipeError, ConnectionResetError):
            return

    def _stream_pull(self, name):
        from ..engine import models
        self._sse_start()
        try:
            for status_text, frac in models.pull(name.strip()):
                self._sse("progress", {"status": status_text, "fraction": frac})
            self._sse("end", {"ok": True})
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as e:
            try:
                self._sse("end", {"ok": False, "error": str(e)})
            except Exception:
                pass


def serve(port=8765, open_browser=True, host="127.0.0.1"):
    from ..engine.scheduler import get_scheduler
    get_scheduler(get_manager()).start()  # run schedules while the Studio is open
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    url = f"http://127.0.0.1:{port}"
    print(f"Offline Agent Studio: {url}  (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()
