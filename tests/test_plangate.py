"""Plan gate: code makes the PM's must_contain checkable, one chunk owns each id, and runs warn
when other models are loaded."""
import ollama

from offline_agent.engine import llm, plangate, relay
from offline_agent.engine.runs import RunManager
from tests.test_relay_quality import ch, plan, site_cfg, wait


def test_example_code_becomes_the_name_code_can_find():
    k = plangate.key
    assert k('<path d="..." fill="#a0522d" />') == "<path"
    assert k('<section id="menu">') == "#menu"
    assert k('<script src="script.js"></script>') == "script.js"
    assert k('<link rel="stylesheet" href="style.css">') == "style.css"
    assert k("<header>") == "<header"
    assert k(".card { border-radius: 10px; }") == ".card"
    assert k("@media (max-width: 600px) { /* phone */ }") == "@media"
    assert k("addToCart(itemId)") == "addToCart"
    assert k("setInterval(updateOpenStatus, 60000)") == "setInterval"
    assert k('id="menu-toggle"') == "#menu-toggle"
    assert k("site/index.html", "site/index.html") == ""  # its own path: code checks the file anyway
    assert k("site/images/bread.svg", "site/images/bread.svg") == ""
    assert k("bake the ... later") == ""
    for real in ("Sourdough bread", "₹120", "#cart", ".btn", "logo.svg", "data-category", "© 2026 Crumbs"):
        assert k(real) == real


def test_two_chunks_never_both_create_the_same_id():
    chunks = [relay._chunk("c1", "base", "site/index.html", "make the sections",
                           ["<section id=\"about\">", "<section id=\"hours\">"]),
              relay._chunk("c2", "about", "site/index.html", "fill about and hours", ['id="about"', 'id="hours"', "Our story"]),
              relay._chunk("c3", "css", "site/style.css", "style #about", ["#about"])]
    notes = plangate.gate(chunks)
    assert chunks[0]["must_contain"] == ["#about", "#hours"]
    assert chunks[1]["must_contain"] == ["Our story"]
    assert "already exist (made by an earlier chunk): #about (c1), #hours (c1)" in chunks[1]["goal"]
    assert chunks[2]["must_contain"] == ["#about"]  # another file may use the id
    assert any("c2: fills existing #about, #hours" in n for n in notes)


def test_the_gate_runs_on_every_plan_and_is_logged(fake, tmp_path):
    fake.format_replies = {"chunks": plan([ch("c1", "site/index.html", ["site/index.html", '<h1 id="title">', "Crumbs"])],
                                          page=""),
                           "complete": {"complete": True, "reason": "ok", "missing": ""}}
    fake.script = [[("write_file", {"path": "site/index.html",
                                    "content": '<html><body><h1 id="title">Crumbs</h1><div id="cart"></div></body></html>'})],
                   "made"]
    run = RunManager().start(site_cfg(tmp_path, route="relay"), "build the page")
    wait(run)
    c1 = run.relay["chunks"][0]
    assert c1["must_contain"][:2] == ["#title", "Crumbs"] and c1["status"] == "done" and c1["tries"] == 1
    assert any("Plan gate: code made 1 chunk(s) checkable" in (e.get("content") or "") for e in run.events)


def test_other_loaded_models_are_reported(fake, monkeypatch):
    m = lambda name, size: type("M", (), {"model": name, "size": size})()  # noqa: E731
    monkeypatch.setattr(ollama, "ps", lambda: type("PS", (), {"models": [
        m("qwen3.5:9b", 6.0e9), m("nomic-embed-text:latest", 3.7e8), m("gemma4:e4b", 7e9)]})())
    assert llm.busy(["gemma4:e4b"]) == ["qwen3.5:9b (6.0 GB)"]
    monkeypatch.setattr(ollama, "ps", lambda: (_ for _ in ()).throw(ConnectionError("no server")))
    assert llm.busy() == []
