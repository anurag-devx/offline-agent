from offline_agent.engine.agent import Agent
from offline_agent.engine.context import ToolContext, set_context
from offline_agent.engine.telegram import page, slim_schema
from offline_agent.engine.toolkits import files
from offline_agent.engine.tools import get_schemas, run_tool
from tests.conftest import config


def test_page_turner():
    text = "x" * 10000
    first = page(text, 0, 4000)
    assert len(first.splitlines()[0]) == 4000 and first.endswith("Next page: offset=4000")
    assert "more chars" not in page(text, 8000, 4000)  # last page, no footer
    assert page("short", 0, 4000) == "short"


def test_read_file_pages(downloads):
    (downloads / "big.txt").write_text("a" * 9000)
    cfg = config(permissions={"files": {"folders": [str(downloads)], "read": "allow"}})
    set_context(ToolContext(cfg, {"granted_folders": [], "granted_domains": [], "changes": 0}))
    out = files.read_file(str(downloads / "big.txt"))
    assert "+3000 more chars" in out and "offset=6000" in out


def test_slim_schemas_are_smaller_and_keep_the_contract():
    full = get_schemas(["move_files"])[0]
    slim = slim_schema(full)
    assert len(str(slim)) < len(str(full)) * 0.8
    assert slim["function"]["name"] == "move_files"
    assert slim["function"]["parameters"]["required"] == full["function"]["parameters"]["required"]


def test_morse_errors():
    assert run_tool("calculator", {"expression": "__import__('os')"}) == \
        "Error: Only numbers and + - * / // % ** ( ) are allowed."


def test_ghost_chatter_and_no_echo(fake):
    fake.script = [{"content": "I'll help you with that! Let me calculate it for you now.", "thinking": "hmm " * 50,
                    "calls": [("calculator", {"expression": "2+2"})]}, "4"]
    agent = Agent(config(plan_steps=False))
    list(agent.run("2+2"))
    stored = [m for m in agent.messages if not isinstance(m, dict) and m.tool_calls][0]
    assert stored.content == "" and not stored.thinking and agent.kept_out > 50


def test_fade_out_and_token_meter(fake, downloads):
    for i in range(30):
        (downloads / f"f{i}.pdf").write_text("x")
    cfg = config(plan_steps=False, permissions={"files": {"folders": [str(downloads)], "read": "allow"}})
    fake.script = [[("list_folder", {"path": str(downloads)})], [("calculator", {"expression": "1"})],
                   [("calculator", {"expression": "2"})], "done"]
    events = list(Agent(cfg).run("look"))
    last_sent = fake.calls[-1]["messages"]
    listing = [m for m in last_sent if isinstance(m, dict) and m.get("role") == "tool"][0]
    assert "[faded" in listing["content"] and len(listing["content"]) < 300
    meter = [e for e in events if e["type"] == "model_call"][-1]
    assert meter["sent"]["tools"] > 0 and meter["saved"]["slim_schemas"] > 0 and meter["saved"]["fade_out"] > 0


def test_telegram_off_keeps_everything(fake):
    fake.script = [{"content": "Narration", "calls": [("calculator", {"expression": "1"})]}, "ok"]
    agent = Agent(config(plan_steps=False, terse=False))
    list(agent.run("x"))
    assert [m for m in agent.messages if not isinstance(m, dict) and m.tool_calls][0].content == "Narration"
