"""
engine/browser.py: check a web page in a real (invisible) browser, like a person would.

A check is a name plus a few steps in a tiny language, so a small model (or you) can write them:

    click "text=Add to cart"            click the first match
    fill #phone 9876543210              type into a field
    select #pickup 10:00                choose an option
    expect_text #cart ₹250              the element's text contains it ("a|b" = either)
    expect_no_text #cart empty          ... does not contain it
    expect_visible #order-confirmation  shown on screen
    expect_hidden #cart-empty
    expect_count "#menu [data-category=bread]" 0     how many are visible
    expect_at_least ".menu-card" 6
    expect_class body dark              its class contains this
    reload                              reload the page (the browser keeps localStorage)
    phone / desktop                     switch the window size
    wait 300                            milliseconds

Selectors are Playwright selectors: CSS (#id, .class, [attr]) or text=... . Every check starts on
a fresh page with empty storage. Code also checks, on every page: JavaScript errors, broken
images, and sideways scrolling on a phone.

Needs Playwright (optional): pip install playwright && python -m playwright install chromium
"""
import re
import shlex
from pathlib import Path
from urllib.parse import unquote, urlparse

INSTALL = "pip install playwright && python -m playwright install chromium"
PHONE, DESKTOP = {"width": 390, "height": 844}, {"width": 1280, "height": 900}
VERBS = {"click": 1, "fill": 2, "select": 2, "expect_text": 2, "expect_no_text": 2, "expect_visible": 1,
         "expect_hidden": 1, "expect_count": 2, "expect_at_least": 2, "expect_class": 2,
         "reload": 0, "phone": 0, "desktop": 0, "wait": 1}
MAX_CHECKS, MAX_STEPS = 12, 12


_FRAME = re.compile(r"\(?(file://[^\s)]+?):(\d+):\d+\)?")


def _error(e):
    """A JavaScript error as {"text", "file", "line"} (file and line from its stack, when it has one)."""
    msg = getattr(e, "message", None) or str(e)
    m = _FRAME.search(getattr(e, "stack", "") or "")
    file = unquote(urlparse(m.group(1)).path) if m else ""
    if file and re.match(r"^/[A-Za-z]:/", file):  # Windows: /C:/Users/... -> C:/Users/...
        file = file[1:]
    line = int(m.group(2)) + 1 if m else 0  # the browser counts lines from 0 here; editors count from 1
    where = f" ({Path(file).name}:{line})" if file else ""
    return {"text": f"{msg[:250]}{where}", "file": file, "line": line, "problem": msg[:250]}


def error_findings(result):
    """JavaScript errors as findings (file + line + problem), so they can be fixed as patches."""
    seen, out = set(), []
    for e in result.get("js_where", []) + [x for c in result.get("checks", []) for x in c.get("where", [])]:
        key = (e["file"], e["line"], e["problem"])
        if e["file"] and key not in seen:
            seen.add(key)
            out.append({"file": e["file"], "line": e["line"], "problem": f"JavaScript error: {e['problem']}",
                        "fix": "make this line work when the page loads and when buttons are used"})
    return out


def available():
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except Exception:
        return False


def parse(step):
    """'fill #phone 98765' -> ('fill', '#phone', '98765'). Raises ValueError for a bad step."""
    try:
        parts = shlex.split(str(step))
    except ValueError as e:
        raise ValueError(f"can't read step {step!r}: {e}") from None
    if not parts or parts[0] not in VERBS:
        raise ValueError(f"unknown step {step!r}; use one of: {', '.join(VERBS)}")
    verb, need = parts[0], VERBS[parts[0]]
    if len(parts) - 1 < need:
        raise ValueError(f"step {step!r} needs {need} argument(s)")
    target = parts[1] if need >= 1 else ""
    value = " ".join(parts[2:]) if need >= 2 else ""
    if verb in ("expect_count", "expect_at_least", "wait"):
        num = value if need == 2 else target
        if not num.lstrip("-").isdigit():
            raise ValueError(f"step {step!r} needs a number")
    return verb, target, value


def clean_checks(checks):
    """Keep only well-formed checks: [{"name", "steps", "owner"?}]."""
    out = []
    for c in list(checks or [])[:MAX_CHECKS]:
        if not isinstance(c, dict):
            continue
        steps = []
        for s in list(c.get("steps") or [])[:MAX_STEPS]:
            try:
                parse(s)
                steps.append(str(s))
            except ValueError:
                continue
        if steps:
            out.append({"name": str(c.get("name") or steps[0])[:80], "steps": steps,
                        "owner": str(c.get("owner") or c.get("chunk") or "")})
    return out


def _visible_count(page, sel):
    return page.evaluate("""(sel) => [...document.querySelectorAll(sel)].filter(e => {
        const r = e.getBoundingClientRect(), s = getComputedStyle(e);
        return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
    }).length""", sel)


def _poll(page, test, timeout_ms):
    """Wait up to timeout for test() to be true (pages update a moment after a click)."""
    waited = 0
    while True:
        if test():
            return True
        if waited >= timeout_ms:
            return False
        page.wait_for_timeout(100)
        waited += 100


def _text(page, sel):
    loc = page.locator(sel)
    return loc.first.inner_text(timeout=1000) if loc.count() else None


def _step(page, step, timeout_ms):
    """Run one step. Returns "" if fine, else what went wrong."""
    verb, target, value = parse(step)
    if verb == "click":
        page.locator(target).first.click(timeout=timeout_ms)
        page.wait_for_timeout(150)
    elif verb == "fill":
        page.locator(target).first.fill(value, timeout=timeout_ms)
    elif verb == "select":
        page.locator(target).first.select_option(value, timeout=timeout_ms)
    elif verb == "reload":
        page.reload()
        page.wait_for_timeout(300)
    elif verb == "phone":
        page.set_viewport_size(PHONE)
        page.wait_for_timeout(150)
    elif verb == "desktop":
        page.set_viewport_size(DESKTOP)
        page.wait_for_timeout(150)
    elif verb == "wait":
        page.wait_for_timeout(min(int(target), 5000))
    elif verb in ("expect_text", "expect_no_text"):
        options = [v.strip().lower() for v in value.split("|") if v.strip()]
        if page.locator(target).count() == 0:
            return f"{target} not found on the page"
        has = lambda: any(o in (_text(page, target) or "").lower() for o in options)  # noqa: E731
        if verb == "expect_text" and not _poll(page, has, timeout_ms):
            return f"{target} shows {(_text(page, target) or '')[:120]!r}, expected {value!r}"
        if verb == "expect_no_text" and not _poll(page, lambda: not has(), timeout_ms):
            return f"{target} still shows {value!r}: {(_text(page, target) or '')[:120]!r}"
    elif verb in ("expect_visible", "expect_hidden"):
        want = verb == "expect_visible"
        if not _poll(page, lambda: (_visible_count(page, target) > 0) == want, timeout_ms):
            return f"{target} is {'not visible' if want else 'still visible'}"
    elif verb in ("expect_count", "expect_at_least"):
        n = int(value)
        ok = (lambda: _visible_count(page, target) == n) if verb == "expect_count" else \
             (lambda: _visible_count(page, target) >= n)
        if not _poll(page, ok, timeout_ms):
            return f"{_visible_count(page, target)} visible {target}, expected {'' if verb == 'expect_count' else '≥'}{n}"
    elif verb == "expect_class":
        get = lambda: page.evaluate("(s) => { const e = document.querySelector(s); return e ? e.className : null }",  # noqa: E731
                                    target)
        if not _poll(page, lambda: value.lower() in str(get() or "").lower(), timeout_ms):
            return f"{target} has class {get()!r}, expected it to include {value!r}"
    return ""


def _smoke(page):
    """Problems any page should not have: broken images, sideways scrolling on a phone."""
    problems = []
    if page.evaluate("() => document.characterSet").upper() != "UTF-8":
        problems.append('no <meta charset="utf-8"> in the page head, so symbols like ₹ show as garbage')
    broken = page.evaluate("""() => [...document.images].filter(i => i.complete && i.naturalWidth === 0)
                                  .map(i => i.getAttribute('src'))""")
    if broken:
        problems.append("broken images: " + ", ".join(broken[:5]))
    page.set_viewport_size(PHONE)
    page.wait_for_timeout(200)
    wide = page.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")
    if wide > 4:
        problems.append(f"on a phone the page scrolls sideways ({wide}px too wide)")
    page.set_viewport_size(DESKTOP)
    return problems


def run(page_path, checks=(), shots_dir=None, timeout_ms=2500):
    """Open a page and run the checks. Returns {"js_errors", "smoke", "checks", "shots", "ok"}."""
    from playwright.sync_api import sync_playwright
    url = Path(page_path).resolve().as_uri()
    out = {"js_errors": [], "js_where": [], "smoke": [], "checks": [], "shots": {}, "ok": True}

    def on_error(e, into):
        err = _error(e)
        into["js_errors" if "js_errors" in into else "errors"].append(err["text"])
        into["js_where" if "js_where" in into else "where"].append(err)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            ctx = browser.new_context(viewport=DESKTOP)
            page = ctx.new_page()
            page.on("pageerror", lambda e: on_error(e, out))
            page.goto(url)
            page.wait_for_timeout(600)
            out["smoke"] = _smoke(page)
            if shots_dir:
                Path(shots_dir).mkdir(parents=True, exist_ok=True)
                desk = Path(shots_dir) / "desktop.png"
                page.screenshot(path=str(desk), full_page=True)
                page.set_viewport_size(PHONE)
                page.wait_for_timeout(200)
                phone = Path(shots_dir) / "phone.png"
                page.screenshot(path=str(phone))
                out["shots"] = {"desktop": str(desk), "phone": str(phone)}
            ctx.close()
            for c in clean_checks(checks):
                ctx = browser.new_context(viewport=DESKTOP)  # fresh page, empty storage
                page = ctx.new_page()
                result = {"name": c["name"], "owner": c["owner"], "ok": True, "failed_step": "", "detail": "",
                          "errors": [], "where": []}
                page.on("pageerror", lambda e, result=result: on_error(e, result))
                try:
                    page.goto(url)
                    page.wait_for_timeout(300)
                    for s in c["steps"]:
                        try:
                            why = _step(page, s, timeout_ms)
                        except Exception as e:
                            why = str(e).splitlines()[0][:200]
                        if why:
                            result.update(ok=False, failed_step=s, detail=why)
                            break
                finally:
                    ctx.close()
                result["errors"], result["where"] = result["errors"][:3], result["where"][:3]
                out["checks"].append(result)
        finally:
            browser.close()
    out["ok"] = not out["js_errors"] and not out["smoke"] and all(c["ok"] for c in out["checks"])
    return out


def summary(result):
    """One line per problem, for messages and reports."""
    lines = [f"JavaScript error on load: {e}" for e in result["js_errors"][:3]]
    lines += result["smoke"]
    for c in result["checks"]:
        if not c["ok"]:
            lines.append(f"check '{c['name']}' failed at `{c['failed_step']}`: {c['detail']}"
                         + (f" (JS error: {c['errors'][0]})" if c.get("errors") else ""))
    return lines
