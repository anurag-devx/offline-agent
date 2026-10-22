import time

from offline_agent.engine import relay as relay_mod
from offline_agent.engine.runs import RunManager
from offline_agent.engine.triage import by_code, signals, triage
from tests.conftest import config

BIG = "Build a site with index.html, style.css and script.js.\n" + "\n".join(f"- feature {i}" for i in range(9))


def wait(run, seconds=20):
    end = time.time() + seconds
    while run.active and time.time() < end:
        time.sleep(0.05)


def site_cfg(folder, **kw):
    return config(max_steps=6, permissions={"files": {"folders": [str(folder)], "read": "allow",
                                                      "create": "allow", "modify": "allow"}}, **kw)


PLAN = {"understanding": "A two-file page.", "contract": "index.html links style.css; class .box",
        "chunks": [
            {"id": "c1", "title": "Page", "output": "site/index.html", "goal": "HTML with Crumbs",
             "depends_on": [], "must_contain": ["Crumbs", "style.css"]},
            {"id": "c2", "title": "Styles", "output": "site/style.css", "goal": ".box styles",
             "depends_on": ["c1"], "must_contain": [".box"]}]}


def test_triage_code_signals():
    assert by_code(signals("What is 18% of 1240?")) == "simple"
    assert by_code(signals(BIG)) == "complex"
    assert triage(config(), "What is 2+2?")["route"] == "single"
    assert triage(config(), BIG)["route"] == "relay"
    assert triage(config(route="single"), BIG)["by"] == "setting"


def test_triage_asks_the_model_when_unsure(fake):
    fake.format_replies = {"complexity": {"complexity": "complex", "parts": 6, "reason": "many parts"}}
    task = " ".join(["Write a detailed report about local models and compare them carefully"] * 6)
    t = triage(config(), task)
    assert t["by"] == "model" and t["route"] == "relay" and t["call"]


def test_relay_builds_chunks_checks_them_and_reviews(fake, tmp_path):
    fake.format_replies = {"chunks": PLAN, "complete": {"complete": True, "reason": "all there", "missing": ""}}
    fake.script = [
        [("write_file", {"path": "site/index.html", "content": "<h1>Crumbs</h1><link href='style.css'>"})], "made page",
        [("write_file", {"path": "site/style.css", "content": ".box { color: brown; padding: 4px; }"})], "made css",
        "all fits"]
    mgr = RunManager()
    run = mgr.start(site_cfg(tmp_path, route="relay"), "build the page")
    wait(run)
    assert run.status == "completed", run.answer
    assert run.route == "relay" and run.verified
    assert [c["status"] for c in run.relay["chunks"]] == ["done", "done"]
    assert (tmp_path / "site" / "style.css").exists()
    assert "2/2 chunks done" in run.answer and "review passed" in run.answer
    briefs = [e["content"] for e in run.events if e.get("worker")]
    assert "CONTRACT" in briefs[1] and "ALREADY DONE BY OTHERS" in briefs[1] and "YOUR CHUNK c2" in briefs[1]


def test_failed_chunk_is_retried_with_the_reason(fake, tmp_path):
    plan = {**PLAN, "chunks": PLAN["chunks"][:1]}
    fake.format_replies = {"chunks": plan, "complete": {"complete": True, "reason": "ok", "missing": ""}}
    fake.script = [
        [("write_file", {"path": "site/index.html", "content": "<h1>Bakery</h1> no stylesheet here"})], "made",
        [("overwrite_file", {"path": "site/index.html", "content": "<h1>Crumbs</h1><link href='style.css'>"})], "fixed"]
    mgr = RunManager()
    run = mgr.start(site_cfg(tmp_path, route="relay"), "build the page")
    wait(run)
    c1 = run.relay["chunks"][0]
    assert c1["status"] == "done" and c1["tries"] == 2
    retry = [e["content"] for e in run.events if e.get("worker")][1]
    assert "YOUR LAST TRY FAILED THE CHECK" in retry and "Crumbs" in retry


def test_review_sends_chunks_back_through_the_pm(fake, tmp_path):
    verdicts = iter([{"complete": False, "reason": "no footer", "missing": "footer"},
                     {"complete": True, "reason": "ok now", "missing": ""}])
    plan = {**PLAN, "chunks": PLAN["chunks"][:1]}
    fake.format_replies = {"chunks": plan, "complete": lambda: next(verdicts),
                           "redo": {"redo": [{"id": "c1", "fix": "add a footer"}]}}
    fake.script = [
        [("write_file", {"path": "site/index.html", "content": "<h1>Crumbs</h1><link href='style.css'>"})], "made",
        "done",  # verifier, round 1
        [("overwrite_file", {"path": "site/index.html",
                             "content": "<h1>Crumbs</h1><link href='style.css'><footer>x</footer>"})], "fixed"]
    mgr = RunManager()
    run = mgr.start(site_cfg(tmp_path, route="relay"), "build the page")
    wait(run)
    assert run.status == "completed" and run.attempts == 2
    assert "add a footer" in [e["content"] for e in run.events if e.get("worker")][-1]


def test_stopped_relay_job_resumes_where_it_was(fake, tmp_path, monkeypatch):
    fake.format_replies = {"chunks": PLAN, "complete": {"complete": True, "reason": "ok", "missing": ""}}
    fake.script = [
        [("write_file", {"path": "site/index.html", "content": "<h1>Crumbs</h1><link href='style.css'>"})], "made page"]
    mgr = RunManager()
    original = relay_mod.Relay.build_chunk

    def build_then_stop(self, chunk):
        original(self, chunk)
        if chunk["id"] == "c1":
            mgr.stop(self.run.id)
    monkeypatch.setattr(relay_mod.Relay, "build_chunk", build_then_stop)
    run = mgr.start(site_cfg(tmp_path, route="relay"), "build the page")
    wait(run)
    assert run.status == "stopped" and mgr.can_resume(run.id)
    assert [c["status"] for c in run.relay["chunks"]] == ["done", "todo"]

    monkeypatch.setattr(relay_mod.Relay, "build_chunk", original)
    fake.script = [[("write_file", {"path": "site/style.css", "content": ".box { color: brown; }"})], "made css",
                   "all fits"]
    fresh = RunManager()  # like after an app restart
    assert fresh.can_resume(run.id)
    fresh.resume(run.id)
    again = fresh.runs[run.id]
    wait(again)
    assert again.status == "completed", again.answer
    assert [c["tries"] for c in again.relay["chunks"]] == [1, 1]


def test_review_findings_go_straight_to_the_chunk_that_owns_the_file(fake, tmp_path):
    verdicts = iter([{"complete": False, "reason": "no footer", "missing": "footer",
                      "findings": [{"file": "site/index.html", "line": 1, "problem": "no footer",
                                    "fix": "add <footer>"}]},
                     {"complete": True, "reason": "ok", "missing": "", "findings": []}])
    plan = {**PLAN, "chunks": PLAN["chunks"][:1]}
    fake.format_replies = {"chunks": plan, "complete": lambda: next(verdicts)}  # no "redo": the PM isn't asked
    fake.script = [
        [("write_file", {"path": "site/index.html", "content": "<h1>Crumbs</h1><link href='style.css'>"})], "made",
        "done",
        [("insert_lines", {"path": "site/index.html", "after_line": 1, "text": "<footer>x</footer>"})], "fixed"]
    mgr = RunManager()
    run = mgr.start(site_cfg(tmp_path, route="relay"), "build the page")
    wait(run)
    assert run.status == "completed", run.answer
    assert [c["id"] for c in run.relay["chunks"]] == ["c1"]  # no extra fix chunk
    brief = [e["content"] for e in run.events if e.get("worker")][-1]
    assert "site/index.html line 1: no footer" in brief and "1 | <h1>Crumbs</h1>" in brief and "insert_lines" in brief
    assert "<footer>" in (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
