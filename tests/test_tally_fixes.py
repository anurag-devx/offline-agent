import ollama
from ollama import ChatResponse, Message

from offline_agent.engine import llm
from offline_agent.engine.agent import Agent
from offline_agent.engine.context import ToolContext, set_context
from offline_agent.engine.toolkits import files
from tests.conftest import config


def test_answer_with_open_steps_is_accepted(fake, downloads):
    fake.format_replies = {"steps": {"steps": ["Read notes", "Find date", "Answer"]}}
    fake.script = [[("read_file", {"path": str(downloads / "notes.docx")})], "The launch is on Friday."]
    cfg = config(permissions={"files": {"folders": [str(downloads)], "read": "allow"}})
    agent = Agent(cfg)
    events = list(agent.run("when is the launch"))
    assert events[-1] == {"type": "answer", "content": "The launch is on Friday.", "step": 2}
    assert not any(e["type"] == "nudge" for e in events)
    assert all(s.status == "done" for s in agent.ledger.steps)
    assert agent.ledger.steps[-1].unverified and "final answer" in agent.ledger.steps[-1].note


def test_relative_paths_against_workspace_are_not_doubled(tmp_path, monkeypatch):
    WORKSPACE = tmp_path / "workspace"
    monkeypatch.setattr(files, "WORKSPACE", WORKSPACE)
    box = WORKSPACE / "_bench" / "t1"
    box.mkdir(parents=True, exist_ok=True)
    (box / "notes.txt").write_text("Friday")
    cfg = config(permissions={"files": {"folders": [str(box)], "read": "allow"}})
    set_context(ToolContext(cfg, {"granted_folders": [], "granted_domains": [], "changes": 0}))
    assert files.resolve("_bench/t1/notes.txt") == (box / "notes.txt").resolve()   # workspace-relative
    assert files.resolve("notes.txt") == (box / "notes.txt").resolve()             # folder-relative
    assert files.resolve("new.txt") == (box / "new.txt").resolve()                 # new file -> the folder


def test_empty_reply_cut_by_cap_is_retried_without_cap(monkeypatch):
    calls = []

    def chat(model, messages, tools=None, **kw):
        calls.append(kw["options"])
        if "num_predict" in kw["options"]:
            return ChatResponse(model=model, done_reason="length", message=Message(role="assistant", content=""))
        return ChatResponse(model=model, done_reason="stop", message=Message(role="assistant", content='{"ok": 1}'))
    monkeypatch.setattr(ollama, "chat", chat)
    monkeypatch.setattr(llm, "capabilities", lambda m: ())
    resp = llm.chat("m", [], format={"type": "object"}, num_predict=300)
    assert resp.message.content == '{"ok": 1}' and len(calls) == 2


def test_gpt_oss_gets_low_reasoning(monkeypatch):
    monkeypatch.setattr(llm, "capabilities", lambda m: ("completion", "tools", "thinking"))
    assert llm._options("gpt-oss:20b", 0.2, False)["think"] == "low"
    assert llm._options("qwen3.5:9b", 0.2, False)["think"] is False
