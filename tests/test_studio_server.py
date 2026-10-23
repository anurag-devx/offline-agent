"""The Studio's web server: API, the page's secret, localhost only, workspace sandbox, live stream."""
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from offline_agent.web import server


@pytest.fixture
def studio(fake, tmp_path, monkeypatch):
    monkeypatch.setattr(server, "WORKSPACE", tmp_path / "ws")
    (tmp_path / "ws" / "site").mkdir(parents=True)
    (tmp_path / "ws" / "site" / "index.html").write_text("<h1>Crumbs</h1>", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("no", encoding="utf-8")
    from offline_agent.engine import config, runs
    monkeypatch.setattr(runs, "_manager", runs.RunManager())
    monkeypatch.setattr(server, "AGENTS_DIR", tmp_path / "agents")
    monkeypatch.setattr(config, "AGENTS_DIR", tmp_path / "agents")
    (tmp_path / "agents").mkdir()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def call(base, method, path, body=None, token=True, host=None):
    req = urllib.request.Request(base + path, method=method, data=None if body is None else json.dumps(body).encode())
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header(server.HEADER, server.TOKEN)
    if host:
        req.add_header("Host", host)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if r.headers.get_content_type() == "application/json" else raw)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def test_page_gets_the_secret_and_the_api_needs_it(studio):
    status, html = call(studio, "GET", "/", token=False)
    assert status == 200 and server.TOKEN.encode() in html
    assert call(studio, "POST", "/api/memory", {"text": "x"}, token=False)[0] == 403
    assert call(studio, "POST", "/api/memory", {"scope": "shared", "text": "x"})[0] == 200


def test_only_localhost_hosts(studio):
    assert call(studio, "GET", "/api/status", host="evil.example.com")[0] == 403


def test_agents_list_check_save(studio):
    status, data = call(studio, "GET", "/api/agents")
    assert status == 200 and any(a["name"] == "Math Helper" for a in data["templates"])
    _, agent = call(studio, "GET", "/api/agents/t-math_helper")
    cfg = agent["config"]
    cfg["name"], cfg["permissions"]["files"]["read"] = "Web Math", "allow"
    _, checked = call(studio, "POST", "/api/agents/check", {"config": cfg})
    assert checked["unsaved"] and "read_file" in checked["tools"]
    status, saved = call(studio, "POST", "/api/agents", {"config": cfg})
    assert status == 200 and saved["id"] == "a-web_math"
    assert call(studio, "DELETE", "/api/agents/t-math_helper", {})[0] == 400  # templates stay


def test_run_starts_streams_and_finishes(studio, fake):
    fake.script = [[("calculator", {"expression": "2+2"})], "It is 4."]
    _, r = call(studio, "POST", "/api/runs", {"agent": "t-math_helper", "task": "2+2?"})
    with urllib.request.urlopen(f"{studio}/api/runs/{r['id']}/stream?from=0", timeout=15) as s:
        text = s.read().decode()
    assert "event: event" in text and '"It is 4."' in text and "event: end" in text
    _, d = call(studio, "GET", f"/api/runs/{r['id']}")
    assert d["status"] == "completed" and d["answer"] == "It is 4." and "speed" in d


def test_workspace_files_are_served_and_sandboxed(studio):
    with urllib.request.urlopen(studio + "/ws/site/index.html") as r:
        assert b"Crumbs" in r.read() and "sandbox" in r.headers["Content-Security-Policy"]
    assert call(studio, "GET", "/ws/%2e%2e/secret.txt")[0] in (403, 404)
    assert call(studio, "GET", "/api/workspace/text?path=../secret.txt")[0] == 403
    _, ws = call(studio, "GET", "/api/workspace")
    assert [f["path"] for f in ws["files"]] == ["site/index.html"]


def test_model_download_stream_needs_the_secret(studio):
    assert call(studio, "GET", "/api/models/pull?name=x", token=False)[0] == 403
