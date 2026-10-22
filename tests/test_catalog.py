from pathlib import Path

from offline_agent.engine import catalog
from offline_agent.engine.config import TEMPLATES_DIR, list_configs, load_agent
from offline_agent.engine.tools import TOOLS

DOCS = Path(__file__).resolve().parent.parent / "docs" / "CATALOG.md"


def test_every_template_has_a_complete_card():
    for name, path in list_configs(TEMPLATES_DIR).items():
        card = catalog.agent_card(load_agent(path))
        assert card["what"] and card["what"] != "(no description)", name
        assert card["good_for"] and card["not_for"] and card["examples"], f"{name}: add good_for, not_for, examples"
        assert card["needs"] and card["tools"], name


def test_every_tool_has_a_complete_card():
    for name in TOOLS:
        card = catalog.tool_card(name)
        assert card["what"], name
        assert card["safety"] and card["example"], f"{name}: add safety= and example= to its @tool(...)"
        assert all(a["about"] for a in card["args"]), f"{name}: describe every argument in its docstring"


def test_needs_in_plain_words():
    cfg = load_agent(TEMPLATES_DIR / "file_sorter.yaml")
    text = catalog.needs_in_words(cfg)
    assert "a folder you choose" in text and "Asks before" in text and "No internet" in text


def test_info_finds_agents_and_tools():
    assert catalog.find("file_sorter")[0] == "agent"
    assert catalog.find("File Sorter")[0] == "agent"
    assert catalog.find("move_files")[0] == "tool"
    assert catalog.find("nothing_here") == (None, None)


def test_docs_catalog_is_up_to_date():
    assert DOCS.read_text(encoding="utf-8") == catalog.catalog_markdown(), \
        "docs/CATALOG.md is out of date: run `offline-agent catalog --write`"
