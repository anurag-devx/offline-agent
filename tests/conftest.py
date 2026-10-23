"""
Test setup. No Ollama needed: a fake model plays back scripted replies.

Every test gets a temporary HOME (so file tools never touch your real folders) and
temporary runs/ and logs/ folders (so tests never write into the project).
"""
import json
import os
import sys
import tempfile
from pathlib import Path

_HOME = os.path.realpath(tempfile.mkdtemp(prefix="oa-home-"))
os.environ["HOME"] = _HOME         # macOS/Linux; must happen before engine is imported (paths.HOME)
os.environ["USERPROFILE"] = _HOME  # Windows uses this for the home folder
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ollama  # noqa: E402
import pytest  # noqa: E402
from ollama import ChatResponse, ListResponse, Message  # noqa: E402


class FakeModel:
    """script: list of replies. Each is "text" (an answer) or [(tool, args), ...] (tool calls).
    format_replies: {schema property name: dict} for structured calls (plan, rule, verdict)."""

    def __init__(self):
        self.script, self.format_replies, self.calls = [], {}, []
        # nanoseconds, like Ollama: load 0.5s, read 10 tokens in 1s, write 5 tokens in 0.5s
        self.durations = {"load_duration": 500_000_000, "prompt_eval_duration": 1_000_000_000,
                          "eval_duration": 500_000_000}

    def chat(self, model, messages, tools=None, stream=False, format=None, **kw):
        self.calls.append({"messages": list(messages), "format": format, "options": kw.get("options")})
        if format:
            for key, reply in self.format_replies.items():
                if key in format.get("properties", {}):
                    if callable(reply):
                        try:
                            value = reply(messages)
                        except TypeError:
                            value = reply()
                    else:
                        value = reply
                    return ChatResponse(model=model, prompt_eval_count=10, eval_count=5, **self.durations,
                                        message=Message(role="assistant", content=json.dumps(value)))
            raise AssertionError(f"no fake reply for schema {list(format.get('properties', {}))}")
        if not tools and str(messages[0].get("content", "")).startswith("You are the design lead. Write"):
            return ChatResponse(model=model, prompt_eval_count=10, eval_count=5, **self.durations,
                                message=Message(role="assistant", content="STYLE GUIDE: cream #fdf6e3, brown #6b3e26"))
        reply = self.script.pop(0) if self.script else "done"
        if isinstance(reply, dict):  # {"content", "calls": [(tool, args)], "thinking"}
            msg = Message(role="assistant", content=reply.get("content", ""), thinking=reply.get("thinking"),
                          tool_calls=[Message.ToolCall(function=Message.ToolCall.Function(name=n, arguments=a))
                                      for n, a in reply.get("calls", [])] or None)
        elif isinstance(reply, str):
            msg = Message(role="assistant", content=reply)
        else:
            msg = Message(role="assistant", content="", tool_calls=[
                Message.ToolCall(function=Message.ToolCall.Function(name=n, arguments=a)) for n, a in reply])
        done = reply.get("done_reason") if isinstance(reply, dict) else None
        return ChatResponse(model=model, prompt_eval_count=10, eval_count=5, **self.durations, message=msg,
                            done_reason=done)


@pytest.fixture
def fake(monkeypatch, tmp_path):
    model = FakeModel()
    monkeypatch.setattr(ollama, "chat", model.chat)
    monkeypatch.setattr(ollama, "list", lambda: ListResponse(models=[ListResponse.Model(model="test-model")]))
    monkeypatch.setattr(ollama, "show", lambda m: type("Info", (), {"capabilities": ["completion", "tools"],
                                                                  "modelinfo": {"x.context_length": 32768}})())
    from offline_agent.engine import audit, llm, memory, runs
    monkeypatch.setattr(memory, "_store", memory.MemoryStore(tmp_path / "memory.db"))
    vocab = {}

    def fake_embed(model, input):  # bag-of-words vectors: shared words = similar meaning
        vec = [0.0] * 64
        for w in memory._words(input):
            vec[vocab.setdefault(w, len(vocab) % 64)] += 1.0
        return {"embeddings": [vec]}
    monkeypatch.setattr(ollama, "embed", fake_embed)
    llm.capabilities.cache_clear()
    llm.context_limit.cache_clear()
    monkeypatch.setattr(runs, "RUNS_DIR", tmp_path / "runs")
    from offline_agent.engine import browser
    monkeypatch.setattr(browser, "available", lambda: False)  # tests that need a real browser opt in
    monkeypatch.setattr(audit, "LOG_FILE", tmp_path / "logs" / "activity.jsonl")
    return model


@pytest.fixture
def downloads():
    """A fresh ~/Downloads in the temporary HOME."""
    import shutil
    d = Path(_HOME) / "Downloads"
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir()
    for name in ("a.pdf", "b.pdf", "photo.jpg", "notes.docx", "song.mp3"):
        (d / name).write_text("x")
    (d / "sub").mkdir()
    (d / "sub" / "deep.pdf").write_text("x")
    return d


def config(**kw):
    """An AgentConfig with sensible test defaults."""
    from offline_agent.engine.config import AgentConfig
    from offline_agent.engine.permissions import Policy
    perms = kw.pop("permissions", None) or {}
    return AgentConfig(model="test-model", permissions=Policy.from_dict(perms), **kw)
