"""Relay quality: feature chunks, style guide, browser tests, visual review, lead model."""
import time

import ollama
import pytest
from ollama import ListResponse

from offline_agent.engine import browser, llm, relay
from offline_agent.engine.runs import RunManager
from tests.conftest import config

PAGE = "<html><body><h1>Crumbs</h1><div id='cart'>empty</div><script src='script.js'></script></body></html>"


def wait(run, seconds=20):
    end = time.time() + seconds
    while run.active and time.time() < end:
        time.sleep(0.05)


def site_cfg(folder, **kw):
    return config(max_steps=6, permissions={"files": {"folders": [str(folder)], "read": "allow",
                                                      "create": "allow", "modify": "allow"}}, **kw)


def plan(chunks, checks=(), page="site/index.html"):
    return {"understanding": "A page.", "contract": "ids: #cart", "chunks": chunks, "page": page,
            "checks": list(checks)}


def ch(cid, output, must, title=None, deps=()):
    return {"id": cid, "title": title or cid, "output": output, "goal": f"do {cid}", "depends_on": list(deps),
            "must_contain": must}


def test_checks_are_cleaned_and_get_an_owner():
    p = relay.clean_plan(plan([ch("c1", "site/index.html", ["Crumbs"]), ch("c2", "site/script.js", ["cart"])],
                              [{"name": "add", "owner": "nobody", "steps": ["click #add", "fly away"]},
                               {"name": "bad", "owner": "c1", "steps": ["fly"]}]), "t")
    assert p["checks"] == [{"name": "add", "steps": ["click #add"], "owner": "c2"}]  # bad step dropped, js owner


def test_feature_chunks_share_a_file_and_may_not_break_each_other(fake, tmp_path):
    fake.format_replies = {"chunks": plan([ch("c1", "site/script.js", ["const items"]),
                                           ch("c2", "site/script.js", ["function addToCart"])], page=""),
                           "complete": {"complete": True, "reason": "ok", "missing": ""}}
    fake.script = [
        [("write_file", {"path": "site/script.js", "content": "const items = [1, 2, 3];\n"})], "base",
        [("overwrite_file", {"path": "site/script.js", "content": "function addToCart(id) {}\n"})], "cart",  # wipes c1
        [("insert_lines", {"path": "site/script.js", "after_line": 0, "text": "const items = [1, 2, 3];"})], "fixed"]
    run = RunManager().start(site_cfg(tmp_path, route="relay"), "build the script")
    wait(run)
    briefs = [e["content"] for e in run.events if e.get("worker")]
    assert "This file already exists" in briefs[1] and "ADD only your part" in briefs[1]
    assert "you removed c1's part" in briefs[2]
    assert [c["status"] for c in run.relay["chunks"]] == ["done", "done"], run.relay["chunks"]


def test_style_guide_goes_to_visual_chunks(fake, tmp_path):
    fake.format_replies = {"chunks": plan([ch("c1", "site/index.html", ["Crumbs"])]),
                           "complete": {"complete": True, "reason": "ok", "missing": ""}}
    fake.script = [[("write_file", {"path": "site/index.html", "content": PAGE})], "made"]
    run = RunManager().start(site_cfg(tmp_path, route="relay"), "build the page")
    wait(run)
    assert run.relay["design"].startswith("STYLE GUIDE")
    assert "STYLE GUIDE (follow it exactly)" in [e["content"] for e in run.events if e.get("worker")][0]


def test_browser_failures_go_back_to_the_owner_as_patches(fake, tmp_path, monkeypatch):
    js = tmp_path / "site" / "script.js"
    results = iter([
        {"js_errors": ["x is null (script.js:2)"], "smoke": [], "shots": {},
         "js_where": [{"file": str(js), "line": 2, "problem": "x is null", "text": "x is null (script.js:2)"}],
         "checks": [{"name": "add to cart", "owner": "c2", "ok": False, "failed_step": "click #add",
                     "detail": "#add not found", "errors": [], "where": []}], "ok": False},
        {"js_errors": [], "js_where": [], "smoke": [], "shots": {}, "ok": True,
         "checks": [{"name": "add to cart", "owner": "c2", "ok": True, "failed_step": "", "detail": ""}]}])
    monkeypatch.setattr(browser, "available", lambda: True)
    monkeypatch.setattr(browser, "run", lambda page, checks, shots_dir=None: next(results))
    fake.format_replies = {
        "chunks": plan([ch("c1", "site/index.html", ["Crumbs"]), ch("c2", "site/script.js", ["cart"])],
                       [{"name": "add to cart", "owner": "c2", "steps": ["click #add", "expect_text #cart 1"]}]),
        "complete": {"complete": True, "reason": "ok", "missing": ""}}
    fake.script = [
        [("write_file", {"path": "site/index.html", "content": PAGE})], "page",
        [("write_file", {"path": "site/script.js", "content": "const cart = [];\nx.textContent = 1;\n"})], "js",
        "all fits",
        [("edit_file", {"path": "site/script.js", "old_text": "x.textContent = 1;", "new_text": "// fixed"})], "fixed"]
    run = RunManager().start(site_cfg(tmp_path, route="relay"), "build the page")
    wait(run)
    assert run.status == "completed", run.answer
    fix_brief = [e["content"] for e in run.events if e.get("worker")][-1]
    assert "YOUR CHUNK c2" in fix_brief and "Browser check 'add to cart' failed at `click #add`" in fix_brief
    assert "script.js line 2: JavaScript error: x is null" in fix_brief and "2 | x.textContent = 1;" in fix_brief
    assert "A browser will test your part like this" in [e["content"] for e in run.events if e.get("worker")][1]
    assert run.relay["test"]["ok"] and "Browser test: 1/1 checks passed" in run.answer


def test_visual_review_sends_css_fixes_with_screenshots(fake, tmp_path, monkeypatch):
    shots = {"desktop": str(tmp_path / "d.png"), "phone": str(tmp_path / "p.png")}
    for p in shots.values():
        open(p, "wb").write(b"png")
    monkeypatch.setattr(browser, "available", lambda: True)
    monkeypatch.setattr(browser, "run", lambda page, checks, shots_dir=None: {
        "js_errors": [], "js_where": [], "smoke": [], "checks": [], "shots": shots, "ok": True})
    monkeypatch.setattr(llm, "capabilities", lambda m: ("completion", "tools", "vision"))
    looks = iter([{"looks_good": False, "findings": [{"file": "style.css", "problem": "header is cramped",
                                                      "fix": "add gap: 24px to header nav"}]}])
    fake.format_replies = {"chunks": plan([ch("c1", "site/index.html", ["Crumbs"]), ch("c2", "site/style.css", ["body"])]),
                           "looks_good": lambda: next(looks),
                           "complete": {"complete": True, "reason": "ok", "missing": ""}}
    fake.script = [
        [("write_file", {"path": "site/index.html", "content": PAGE})], "page",
        [("write_file", {"path": "site/style.css", "content": "body { margin: 0; }\nheader nav { }\n"})], "css",
        "all fits",
        [("edit_file", {"path": "site/style.css", "old_text": "header nav { }", "new_text": "header nav { gap: 24px; }"})],
        "spaced"]
    run = RunManager().start(site_cfg(tmp_path, route="relay"), "build the page")
    wait(run)
    assert run.status == "completed", run.answer
    look_call = next(c for c in fake.calls if c["format"] and "looks_good" in c["format"]["properties"])
    assert look_call["messages"][-1]["images"] == [shots["desktop"], shots["phone"]]
    assert "header is cramped" in [e["content"] for e in run.events if e.get("worker")][-1]
    assert "gap: 24px" in (tmp_path / "site" / "style.css").read_text(encoding="utf-8")


def test_lead_model_plans_and_workers_use_the_agent_model(fake, tmp_path, monkeypatch):
    monkeypatch.setattr(ollama, "list", lambda: ListResponse(models=[ListResponse.Model(model="test-model"),
                                                                     ListResponse.Model(model="big-model")]))
    fake.format_replies = {"chunks": plan([ch("c1", "notes.md", ["Plan"])], page=""),
                           "complete": {"complete": True, "reason": "ok", "missing": ""}}
    fake.script = [[("write_file", {"path": "notes.md", "content": "# Plan\nship it on Friday"})], "made"]
    models = []
    real_chat = ollama.chat
    monkeypatch.setattr(ollama, "chat", lambda model, messages, **kw: (models.append(model), real_chat(model, messages, **kw))[1])
    run = RunManager().start(site_cfg(tmp_path, route="relay", lead_model="big-model"), "write the plan")
    wait(run)
    assert run.status == "completed", run.answer
    assert models[0] == "big-model" and "test-model" in models[1:]
    assert run.relay["lead"] == "big-model"


def _playwright_ready():
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            p.chromium.launch().close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _playwright_ready(), reason="needs Playwright + Chromium")
def test_real_browser_runs_steps_and_finds_errors(tmp_path):
    (tmp_path / "index.html").write_text(
        "<html><head><meta charset='utf-8'></head><body><button id='add'>Add to cart</button><div id='cart'>Your cart is empty</div>"
        "<img src='missing.png'><script src='app.js'></script></body></html>", encoding="utf-8")
    (tmp_path / "app.js").write_text(
        "document.getElementById('add').onclick = () => {\n"
        "  document.getElementById('cart').textContent = 'Sourdough ₹250';\n"
        "  localStorage.setItem('c', '1');\n};\n"
        "if (localStorage.getItem('c')) document.getElementById('cart').textContent = 'Sourdough ₹250';\n"
        "document.getElementById('nope').textContent = 'x';\n", encoding="utf-8")
    r = browser.run(tmp_path / "index.html", [
        {"name": "add", "steps": ['click "text=Add to cart"', "expect_text #cart ₹250"]},
        {"name": "keeps cart", "steps": ['click #add', "reload", 'expect_no_text #cart "empty"']},
        {"name": "wrong", "steps": ["expect_text #cart free"]}], shots_dir=tmp_path / "shots")
    assert [c["ok"] for c in r["checks"]] == [True, True, False]
    assert "app.js:6" in r["js_errors"][0] and any("broken images" in x for x in r["smoke"])
    assert (tmp_path / "shots" / "desktop.png").exists()
    assert not any("charset" in x for x in r["smoke"])
    (tmp_path / "plain.html").write_text("<p>Prices</p><script src='app.js'></script>", encoding="utf-8")
    assert any("charset" in x for x in browser.run(tmp_path / "plain.html")["smoke"])
    f = browser.error_findings(r)[0]
    assert f["file"].endswith("app.js") and f["line"] == 6


def test_step_language():
    assert browser.parse('fill "#order-form input" Asha Rao') == ("fill", "#order-form input", "Asha Rao")
    assert browser.parse("reload") == ("reload", "", "")
    for bad in ("fly away", "click", "expect_count .card many"):
        with pytest.raises(ValueError):
            browser.parse(bad)
