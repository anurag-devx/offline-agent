"""Joins: code checks that a page's HTML, CSS and JS fit together; Relay uses it to integrate and fix."""
import pytest

from offline_agent.engine import browser, joins, relay
from offline_agent.engine.runs import RunManager
from tests.test_relay_quality import ch, plan, site_cfg, wait

HTML = """<!doctype html><html><head><link rel="stylesheet" href="style.css"></head><body>
<div class="filter-buttons">
  <button data-filter="all">All</button>
  <button data-filter="bread">Breads</button>
</div>
<div id="menu"></div>
<button type="submit" class="primary-button">Order</button>
<script src="script.js"></script></body></html>"""
CSS = """:root { --brown: #5d4037; }
.btn { padding: 8px; }
.btn-primary { background: var(--brown); }
.menu-card { border: 1px solid; }
body { margin: 0; }
h1 { font-size: 2rem; }
body { color: #333; }
h1 { font-weight: 800; }
"""
JS = """const menu = document.getElementById('menu');
function render(items) {
  items.forEach(i => { const card = document.createElement('div'); card.className = 'menu-card';
    card.setAttribute('data-category', i.category); card.innerHTML = `<button class="add-btn">Add</button>`;
    menu.append(card); });
}
document.querySelectorAll('.filter-btn').forEach(b => b.addEventListener('click', () => {}));
document.querySelector('#cart-total').textContent = '0';
document.querySelectorAll('.menu-card[data-category="bread"]');
"""


def files(html=HTML, css=CSS, js=JS):
    return {"site/index.html": html, "site/style.css": css, "site/script.js": js}


def problems(found):
    return " | ".join(f["problem"] for f in found)


def test_script_looking_for_names_the_page_does_not_have():
    found = joins.check(files())
    text = problems(found)
    assert "looks for `.filter-btn`, but no element has class \"filter-btn\"" in text
    assert "The page has data-filter" in text  # points at what the buttons really use
    assert "`#cart-total`" in text
    assert "menu-card" not in text.split("CSS never styles")[0].split("looks for")[-1]  # made by the script: fine
    js_line = next(f for f in found if ".filter-btn" in f["problem"])
    assert js_line["file"] == "site/script.js" and js_line["line"] == 7


def test_css_and_html_that_picked_different_class_names():
    text = problems(joins.check(files()))
    assert "use classes the CSS never styles: .primary-button (maybe .btn-primary)" in text
    assert "styles classes nothing uses: .btn, .btn-primary" in text
    assert "<button> element(s) have no class and the CSS has no `button` rule" in text


def test_duplicate_rules_and_a_block_that_is_never_closed():
    text = problems(joins.check(files()))
    assert "writes 2 selectors more than once" in text and "`body` (lines 5, 7)" in text
    broken = joins.file_checks("s.css", ":root {\n  --a: 1;\n\nbody { margin: 0; }\n.x { y: z; }\n")
    assert "is never closed" in broken[0]["problem"] and broken[0]["line"] == 1
    nested = joins.file_checks("s.css", ":root {\n --a: 1;\nbody { margin: 0; }\n}\n")
    assert "`body` (line 3) is inside `:root {` (line 1)" in nested[0]["problem"]
    ok = ":root { --a: 1; }\n@media (max-width: 600px) { .a { b: c; } }\n.c { &:hover { d: e; } }\n"
    assert joins.file_checks("s.css", ok) == []


def test_files_that_fit_together_pass():
    html = '<button class="btn filter-btn" data-filter="all">All</button><div id="cart-total"></div><div id="menu"></div>'
    css = ".btn { a: b; } .filter-btn { a: b; } .menu-card { a: b; } .add-btn { a: b; }"
    assert joins.check(files(html=html, css=css)) == []


def test_page_map_tells_workers_the_real_names():
    pmap = joins.page_map(files())
    assert "#menu" in pmap and ".filter-buttons" in pmap and "data-filter" in pmap
    assert "made by the script: " in pmap and ".menu-card" in pmap and ".add-btn" in pmap
    assert ".btn-primary" in joins.css_map(files())


def test_selectors_naming_elements_html_does_not_have():
    assert joins.bad_tags("#order-form submit") == ["submit"]
    assert joins.bad_tags("#menu [data-category=bread]") == []
    assert joins.bad_tags(".menu-card button, nav a:hover") == []
    assert joins.bad_tags("text=Add to cart") == []
    assert browser.repair('click "#order-form submit"') == ('click "#order-form [type=submit]"', "")
    dropped = []
    kept = browser.clean_checks([{"name": "a", "steps": ["click \"#f gizmo\""]},
                                 {"name": "b", "steps": ["click #go"]}], dropped)
    assert [c["name"] for c in kept] == ["b"] and "<gizmo> is not an HTML element" in dropped[0]


def test_must_contain_accepts_selector_spelling(tmp_path):
    page = tmp_path / "index.html"
    page.write_text('<button id="menu-toggle" class="btn nav-btn">☰</button>', encoding="utf-8")
    chunk = relay._chunk("c1", "base", "index.html", must=["#menu-toggle", ".nav-btn", "#theme-toggle"])
    assert relay.check_output(chunk, str(page)) == ["missing: #theme-toggle"]


def test_svg_drawings_need_some_detail(tmp_path):
    svg = tmp_path / "bread.svg"
    svg.write_text('<svg viewBox="0 0 10 10"><path d="M0 0 L5 5"/></svg>', encoding="utf-8")
    chunk = relay._chunk("c1", "bread", "bread.svg", must=["viewBox"])
    assert "too simple (1 shapes)" in relay.check_output(chunk, str(svg))[0]
    svg.write_text("<svg viewBox='0 0 10 10'>" + "<circle r='1'/>" * 8 + "</svg>", encoding="utf-8")
    assert relay.check_output(chunk, str(svg)) == []


def test_ids_the_checks_use_become_some_chunks_job():
    p = relay.clean_plan(plan([ch("c1", "site/index.html", ["Crumbs"]), ch("c2", "site/script.js", ["menu"])],
                              [{"name": "phone menu", "owner": "c2", "steps": ["phone", "click #menu-toggle"]}]), "t")
    html = p["chunks"][0]
    assert "#menu-toggle" in html["goal"] and "#menu-toggle" in html["must_contain"]
    assert "#cart" in html["must_contain"]  # from the contract "ids: #cart"


def test_a_script_using_names_the_page_lacks_fails_its_chunk_and_gets_fixed(fake, tmp_path):
    fake.format_replies = {"chunks": plan([ch("c1", "site/index.html", ["Crumbs"]),
                                           ch("c2", "site/script.js", ["filter"])], page=""),
                           "complete": {"complete": True, "reason": "ok", "missing": ""}}
    html = ('<html><body><h1>Crumbs</h1><button data-filter="all">All</button><div id="cart">empty</div>'
            '<script src="script.js"></script></body></html>')
    js = "// filter\nconst cart = document.getElementById('cart');\ndocument.querySelectorAll('.filter-btn');\n"
    fake.script = [
        [("write_file", {"path": "site/index.html", "content": html})], "page",
        [("write_file", {"path": "site/script.js", "content": js})], "script",
        [("edit_file", {"path": "site/index.html", "old_text": '<button data-filter="all">',
                        "new_text": '<button class="filter-btn" data-filter="all">'})], "added the class",
        "all fits"]
    run = RunManager().start(site_cfg(tmp_path, route="relay"), "build the page")
    wait(run)
    briefs = [e["content"] for e in run.events if e.get("worker")]
    assert "PAGE MAP (what the HTML really has" in briefs[1] and "data-filter" in briefs[1]
    assert "looks for `.filter-btn`, but no element has class" in briefs[2]  # code's reason, with the line
    assert [c["status"] for c in run.relay["chunks"]] == ["done", "done"], run.relay["chunks"]
    assert run.relay["joins"] == [] and run.status == "completed"


def test_integration_is_given_codes_mismatches_and_unfinished_chunks(fake, tmp_path):
    fake.format_replies = {"chunks": plan([ch("c1", "site/index.html", ["Crumbs", "#menu-toggle"]),
                                           ch("c2", "site/style.css", [".btn"])], page=""),
                           "complete": {"complete": True, "reason": "ok", "missing": ""}}
    html = '<html><body><h1>Crumbs</h1><div id="cart"></div><button class="primary-button">Go</button></body></html>'
    fake.script = [
        [("write_file", {"path": "site/index.html", "content": html})], "page",
        "it is done",  # try 2 changes nothing: the same failure again, so c1 fails
        [("write_file", {"path": "site/style.css", "content": ".btn { a: b; }\n.btn-primary { a: b; }\n"})], "css",
        [("edit_file", {"path": "site/index.html", "old_text": '<button class="primary-button">Go</button>',
                        "new_text": '<button id="menu-toggle" class="btn btn-primary">Go</button>'})], "fixed"]
    run = RunManager().start(site_cfg(tmp_path, route="relay"), "build the page")
    wait(run)
    integ = next(e["content"] for e in run.events if e.get("worker") and "YOUR CHUNK: integration" in e["content"])
    assert "CODE CHECKED THE FILES AND FOUND THESE MISMATCHES" in integ and ".primary-button" in integ
    assert "UNFINISHED PART c1" in integ and "missing: #menu-toggle" in integ
    assert run.relay["chunks"][0]["status"] == "done"  # code re-checked c1 after integration
    assert run.relay["joins"] == []


@pytest.mark.skipif(not browser.available(), reason="needs Playwright + Chromium")
def test_real_browser_says_why_a_click_failed(tmp_path):
    page = tmp_path / "index.html"
    page.write_text("""<html><body>
<button id="menu-toggle" style="position:absolute;top:10px;left:10px;width:40px;height:40px">=</button>
<button id="theme-toggle" style="position:absolute;top:10px;left:10px;width:40px;height:40px">*</button>
<button id="ghost" style="display:none">x</button></body></html>""", encoding="utf-8")
    r = browser.run(str(page), [{"name": "menu", "steps": ["click #menu-toggle"]},
                                {"name": "ghost", "steps": ["click #ghost"]},
                                {"name": "none", "steps": ["click #nope"]}], timeout_ms=600)
    why = {c["name"]: c["detail"] for c in r["checks"]}
    assert "covered by <button#theme-toggle>" in why["menu"]
    assert "hidden" in why["ghost"]
    assert why["none"] == "no element matches `#nope`"
