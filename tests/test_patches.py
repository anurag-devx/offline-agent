"""Patch fixes: line-numbered reads, exact edits, inserts, reviewer findings."""
import time

from offline_agent.engine import findings, llm, speed
from offline_agent.engine.context import ToolContext, set_context
from offline_agent.engine.runs import RunManager
from offline_agent.engine.toolkits import files, web
from tests.conftest import config

JS = "function add(id) {\n  cart.push(id);\n}\n\nfunction total() {\n  return 0;\n}\n"


def setup(tmp_path):
    cfg = config(permissions={"files": {"folders": [str(tmp_path)], "read": "allow", "create": "allow",
                                        "modify": "allow"}})
    set_context(ToolContext(cfg, {"granted_folders": [], "granted_domains": [], "changes": 0}))
    f = tmp_path / "script.js"
    f.write_text(JS, encoding="utf-8")
    return f


def test_read_lines_numbers_and_pages(tmp_path):
    f = setup(tmp_path)
    out = files.read_lines(str(f), start=5, count=2)
    assert out.splitlines()[1:] == ["5 | function total() {", "6 |   return 0;", "+1 more lines. Next: start=7"]


def test_edit_file_replaces_one_exact_spot(tmp_path):
    f = setup(tmp_path)
    out = files.edit_file(str(f), "  return 0;", "  return cart.length;")
    assert out.startswith("OK edited") and "line 6" in out
    assert f.read_text(encoding="utf-8") == JS.replace("return 0;", "return cart.length;")


def test_edit_file_refuses_ambiguous_or_missing_text(tmp_path):
    f = setup(tmp_path)
    assert "appears 2 times" in files.edit_file(str(f), "function", "fn")
    miss = files.edit_file(str(f), "return 1;", "x")
    assert miss.startswith("Error") and "Closest lines" in miss and "return 0;" in miss
    assert f.read_text(encoding="utf-8") == JS  # nothing changed


def test_edit_file_tolerates_indentation_and_pasted_numbers(tmp_path):
    f = setup(tmp_path)
    assert files.edit_file(str(f), "6 | return 0;", "  return 42;").startswith("OK")
    assert "  return 42;\n}" in f.read_text(encoding="utf-8")


def test_insert_lines(tmp_path):
    f = setup(tmp_path)
    assert files.insert_lines(str(f), 3, "// totals below").startswith("OK inserted 1 lines after line 3")
    assert f.read_text(encoding="utf-8").splitlines()[3] == "// totals below"
    files.insert_lines(str(f), 999, "// end")
    assert f.read_text(encoding="utf-8").endswith("// end")


def test_findings_are_checked_and_get_real_lines(tmp_path):
    f = setup(tmp_path)
    items = findings.locate([{"file": "script.js", "line": 6, "problem": "total is always 0", "fix": "count"},
                             {"file": "missing.css", "line": 3, "problem": "no styles", "fix": "create"},
                             {"file": "script.js", "line": 999, "problem": "bad line", "fix": ""}], roots=[tmp_path])
    assert items[0]["path"] == str(f) and "6 |   return 0;" in items[0]["snippet"]
    assert items[1]["path"] == "" and items[2]["line"] == 0
    text = findings.as_text(items)
    assert "script.js line 6: total is always 0" in text and "file not found" in text


def test_verifier_findings_reach_the_agent_as_patches(fake, tmp_path):
    f = tmp_path / "script.js"
    verdicts = iter([{"complete": False, "reason": "total wrong", "missing": "total",
                      "findings": [{"file": "script.js", "line": 6, "problem": "returns 0", "fix": "sum prices"}]},
                     {"complete": True, "reason": "ok", "missing": "", "findings": []}])
    fake.format_replies = {"complete": lambda: next(verdicts)}
    fake.script = [[("write_file", {"path": "script.js", "content": JS})], "made",
                   "done",  # verifier round 1
                   [("edit_file", {"path": "script.js", "old_text": "return 0;", "new_text": "return 1;"})], "fixed"]
    cfg = config(plan_steps=False, permissions={"files": {"folders": [str(tmp_path)], "read": "allow",
                                                          "create": "allow", "modify": "allow"}})
    cfg.verify.enabled = True
    run = RunManager().start(cfg, "write script.js")
    end = time.time() + 20
    while run.active and time.time() < end:
        time.sleep(0.05)
    assert run.status == "completed" and run.verified
    sent_back = [e["content"] for e in run.events if e["type"] == "user" and e.get("auto")][0]
    assert "script.js line 6: returns 0" in sent_back and "6 |   return 0;" in sent_back and "edit_file" in sent_back
    assert "return 1;" in f.read_text(encoding="utf-8")


def test_every_call_keeps_the_model_loaded_with_one_context_size():
    opts = llm._options("m", 0.2, False)
    assert opts["keep_alive"] == llm.KEEP_ALIVE and opts["options"]["num_ctx"] == llm.DEFAULT_CTX


def test_web_cache_serves_the_same_page_once_per_job(monkeypatch):
    cfg = config(permissions={"internet": {"read": "allow", "domains": ["example.com"]}})
    ctx = ToolContext(cfg, {"granted_folders": [], "granted_domains": [], "changes": 0})
    ctx.job = "job1"
    set_context(ctx)
    hits = []

    class Resp:
        headers = type("H", (), {"get_content_charset": lambda s: "utf-8", "get_content_type": lambda s: "text/plain"})()

        def read(self, n):
            hits.append(1)
            return b"hello " * 2000

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(web.urllib.request, "build_opener", lambda *a: type("O", (), {"open": lambda s, r, timeout: Resp()})())
    web.fetch_url("https://example.com/a")
    web.fetch_url("https://example.com/a", offset=4000)
    assert len(hits) == 1 and [e["type"] for e in ctx.events].count("web_cache") == 1
    ctx.job = "job2"
    web.fetch_url("https://example.com/a")
    assert len(hits) == 2


def test_prompt_reuse_is_estimated():
    class R:
        events = [{"type": "model_call", "sent": {"instructions": 500, "history": 500}, "prompt_tokens": 1000},
                  {"type": "model_call", "sent": {"instructions": 500, "history": 600}, "prompt_tokens": 100}]
        wait_s = verify_s = 0.0

        def duration(self):
            return 10.0
    assert speed.summarize(R())["reuse_pct"] == 48
