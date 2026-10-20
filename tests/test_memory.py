import time

from engine import memory
from engine.validate import validate
from engine.agent import Agent
from engine.runs import RunManager
from tests.conftest import config


def mem_cfg(read="allow", write="allow", **extra):
    return config(plan_steps=False, permissions={"memory": {"read": read, "write": write, **extra}})


def test_store_search_by_meaning(fake):
    s = memory.get_store()
    s.add("a", "PDFs from Downloads go to all_pdf folder")
    s.add("a", "User likes short answers")
    s.add("b", "PDFs belong to agent b")
    hits = s.search("a", "where do pdfs go from downloads")
    assert hits and hits[0]["text"].startswith("PDFs from Downloads") and all(h["scope"] == "a" for h in hits)


def test_auto_recall_is_marked_as_information(fake):
    cfg = mem_cfg()
    memory.get_store().add(cfg.slug, "PDFs from Downloads go to all_pdf folder")
    fake.script = ["ok"]
    events = list(Agent(cfg).run("move pdfs from downloads"))
    assert events[0]["type"] == "recalled"
    sent = [m["content"] for m in fake.calls[0]["messages"] if isinstance(m, dict)]
    assert any(c.startswith("MEMORY:") and "NOT instructions" in c and "all_pdf" in c for c in sent)


def test_remember_needs_permission(fake):
    fake.script = [[("remember", {"note": "x"})], "ok"]
    events = list(Agent(mem_cfg(read="off", write="off")).run("remember x"))
    assert "no permission" in next(e["result"] for e in events if e["type"] == "tool_result")
    assert memory.get_store().rows() == []


def test_remember_recall_forget(fake):
    cfg = mem_cfg()
    fake.script = [[("remember", {"note": "Reports go to ~/Documents/reports"})], "ok"]
    list(Agent(cfg).run("remember where reports go"))
    note = memory.get_store().rows(cfg.slug)[0]
    fake.script = [[("recall", {"query": "where do reports go"})], [("forget", {"memory_id": note["id"]})], "ok"]
    results = [e["result"] for e in Agent(cfg).run("check") if e["type"] == "tool_result"]
    assert "Documents/reports" in results[0] and results[1].startswith("OK forgot")
    assert memory.get_store().rows(cfg.slug) == []


def test_run_summary_written_by_code(fake):
    cfg = mem_cfg(read="off", write="off", run_summaries=True)
    fake.script = ["all good"]
    run = RunManager().start(cfg, "say hi")
    while run.active:
        time.sleep(0.02)
    rows = memory.get_store().rows(cfg.slug)
    assert rows[0]["kind"] == "episode" and "task: say hi" in rows[0]["text"] and "completed" in rows[0]["text"]


def test_poisoning_warning(fake):
    cfg = config(permissions={"memory": {"write": "allow"}, "internet": {"read": "allow", "domains": ["x.com"]}})
    assert any(c["check"] == "Memory poisoning" and not c["ok"] for c in validate(cfg))
