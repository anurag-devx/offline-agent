from engine.agent import Agent
from tests.conftest import config


def files_cfg(downloads, **kw):
    return config(permissions={"files": {"folders": [str(downloads)], "read": "allow", "create": "allow", "move": "ask"}}, **kw)


def test_tool_loop_and_answer(fake):
    fake.script = [[("calculator", {"expression": "6*7"})], "42"]
    events = list(Agent(config(plan_steps=False)).run("what is 6*7"))
    assert [e["result"] for e in events if e["type"] == "tool_result"] == ["42"]
    assert events[-1] == {"type": "answer", "content": "42", "step": 2}


def test_ask_first_denied_without_approver(fake, downloads):
    fake.script = [[("move_files", {"folder": str(downloads), "destination_folder": str(downloads / "p"),
                                    "extensions": ".pdf"})], "ok"]
    events = list(Agent(files_cfg(downloads, plan_steps=False)).run("move pdfs"))
    assert any(e["type"] == "approval" and not e["approved"] for e in events)
    assert (downloads / "a.pdf").exists()


def test_approval_shows_preview(fake, downloads):
    seen = {}
    fake.script = [[("move_files", {"folder": str(downloads), "destination_folder": str(downloads / "p"),
                                    "extensions": ".pdf"})], "ok"]
    agent = Agent(files_cfg(downloads, plan_steps=False), approver=lambda n, a: seen.update(a) or "yes")
    list(agent.run("move pdfs"))
    assert "Move 2 files" in seen["will_do"] and (downloads / "p" / "a.pdf").exists()


def test_notes_nudge_and_compaction(fake, downloads):
    fake.format_replies = {"steps": {"steps": ["List pdfs", "Report"]}}
    fake.script = [[("list_folder", {"path": str(downloads), "extensions": ".pdf"})],
                   [("update_step", {"step": 1, "status": "done", "note": "2 pdfs"})],
                   "finished?",                                   # step 2 still open -> nudge
                   [("update_step", {"step": 2, "status": "done", "note": "reported"})],
                   "2 pdfs found"]
    agent = Agent(files_cfg(downloads))
    events = list(agent.run("count pdfs"))
    types = [e["type"] for e in events]
    assert "plan" in types and "nudge" in types and "compacted" in types
    assert events[-1]["type"] == "answer"
    assert all(s.status == "done" for s in agent.ledger.steps)
    # notes are sent last on every call
    assert fake.calls[-1]["messages"][-1]["content"].startswith("NOTES")


def test_context_length_and_reply_cap_are_sent(fake):
    list(Agent(config(plan_steps=False, context_length=12345, max_reply_tokens=321)).run("hi"))
    assert fake.calls[-1]["options"]["num_ctx"] == 12345
    assert fake.calls[-1]["options"]["num_predict"] == 321


def test_no_create_permission_means_no_new_folder(fake, downloads):
    cfg = config(plan_steps=False, permissions={"files": {"folders": [str(downloads)], "read": "allow",
                                                          "move": "allow"}})
    fake.script = [[("move_files", {"folder": str(downloads), "destination_folder": str(downloads / "new"),
                                    "extensions": ".pdf"})], "ok"]
    events = list(Agent(cfg).run("move pdfs"))
    assert "may not create folders" in next(e["result"] for e in events if e["type"] == "tool_result")
    assert not (downloads / "new").exists()
