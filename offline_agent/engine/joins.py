"""
engine/joins.py: code checks that a web page's files fit together. No model, no browser.

Separate workers write index.html, style.css and script.js. Each file can pass its own checks and
the page still breaks where they meet: the script looks for a class the HTML doesn't have, the CSS
styles class names nobody uses, a button gets no style at all. This module reads the files and
reports exactly those joins, with the file and line, so the fix is one edit:

    page_map(files)          what the HTML (and the elements the script makes) really has:
                             ids, classes, data attributes; told to workers so they use real names
    check(files)             every mismatch:
      - script uses #id / .class / [data-x] that no element has            (JS -> HTML)
      - CSS styles classes nothing uses, while buttons/links use classes
        CSS never styles (the two sides picked different names)             (CSS <-> HTML)
      - buttons with no class and no `button` rule (plain browser buttons)
      - a CSS block that is never closed (everything after it is lost)
      - the same CSS selector written several times (later copies win)
      - an id used twice in the HTML
    file_checks(path, text)  the checks of one file on its own (unclosed CSS block)

`files` is {path: text}. Findings are {"file", "line", "problem", "fix"} like the Inspector's.
"""
import difflib
import re
from pathlib import Path

WEB = (".html", ".htm", ".css", ".js")
TAGS = set("""a abbr address article aside audio b blockquote body br button canvas caption cite code
col colgroup data datalist dd details dfn dialog div dl dt em fieldset figcaption figure footer form h1
h2 h3 h4 h5 h6 head header hgroup hr html i iframe img input ins kbd label legend li link main map mark
menu meta meter nav noscript object ol optgroup option output p picture pre progress q s samp script
search section select slot small source span strong style sub summary sup table tbody td template
textarea tfoot th thead time title tr u ul var video svg path rect circle ellipse line polyline polygon
g text defs use symbol""".split())
INTERACTIVE = ("button", "a", "input", "select", "textarea")
MAX_FINDINGS = 12


def _line(text, pos):
    return text.count("\n", 0, pos) + 1


def _kebab(name):  # dataset.someThing -> some-thing
    return re.sub(r"[A-Z]", lambda m: "-" + m.group(0).lower(), name)


# ------------------------------------------------------------ reading the files
_TAG = re.compile(r"<([a-zA-Z][a-zA-Z0-9-]*)(\s[^<>]*?)?/?>", re.S)
_ATTR = re.compile(r"""([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))""")


def html_names(text):
    """{"ids": {id: line}, "classes": {cls: line}, "data": {attr: line}, "tags": [(tag, classes, line)]}"""
    out = {"ids": {}, "classes": {}, "data": {}, "tags": [], "dup_ids": []}
    text = re.sub(r"<!--.*?-->", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    for m in _TAG.finditer(text):
        tag, line = m.group(1).lower(), _line(text, m.start())
        classes = []
        for a in _ATTR.finditer(m.group(2) or ""):
            name, value = a.group(1).lower(), next(v for v in a.groups()[1:] if v is not None)
            if "${" in value or "{{" in value:
                continue
            if name == "id" and value.strip():
                if value in out["ids"]:
                    out["dup_ids"].append((value, line))
                out["ids"].setdefault(value.strip(), line)
            elif name == "class":
                classes = value.split()
                for c in classes:
                    out["classes"].setdefault(c, line)
            elif name.startswith("data-"):
                out["data"].setdefault(name, line)
        out["tags"].append((tag, classes, line))
    return out


def _str(n):
    """A quoted JS string; group n is the quote, group n+1 the text."""
    return r"""(['"`])((?:\\.|(?!\%d).)*?)\%d""" % (n, n)


_JS_SEL = re.compile(r"(?:querySelector(?:All)?|closest|matches)\s*\(\s*" + _str(1))
_JS_ID = re.compile(r"getElementById\s*\(\s*" + _str(1))
_JS_CLASSES = re.compile(r"getElementsByClassName\s*\(\s*" + _str(1))
_JS_MAKE_CLASS = re.compile(r"classList\s*\.\s*(?:add|toggle|replace)\s*\(([^)]*)\)")
_JS_SET = re.compile(r"\.\s*(id|className)\s*=\s*" + _str(2))
_JS_SETATTR = re.compile(r"setAttribute\s*\(\s*['\"]([\w-]+)['\"]\s*,\s*" + _str(2))
_JS_DATASET_SET = re.compile(r"dataset\s*\.\s*(\w+)\s*=(?!=)")
_JS_SETDATA = re.compile(r"setAttribute\s*\(\s*['\"](data-[\w-]+)['\"]")
_LOOKS = re.compile(r"(^|-)(btn|button|card|nav|hero)(-|$)")


def js_names(text):
    """What a script uses and what it makes. {"uses": [(kind, name, line, selector)], "ids", "classes", "data"}"""
    out = {"uses": [], "ids": {}, "classes": {}, "data": {}}
    clean = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    clean = re.sub(r"(?m)(^|[^:\\'\"])//[^\n]*", r"\1", clean)
    made = html_names(clean)  # elements the script writes as HTML strings (innerHTML, templates)
    for key in ("ids", "classes", "data"):
        out[key].update(made[key])
    for m in _JS_SET.finditer(clean):
        if "${" not in m.group(3):
            for v in m.group(3).split() if m.group(1) == "className" else [m.group(3)]:
                out["classes" if m.group(1) == "className" else "ids"].setdefault(v, _line(clean, m.start()))
    for m in _JS_SETATTR.finditer(clean):
        attr, value, line = m.group(1).lower(), m.group(3), _line(clean, m.start())
        if attr == "id":
            out["ids"].setdefault(value, line)
        elif attr == "class":
            for v in value.split():
                out["classes"].setdefault(v, line)
        elif attr.startswith("data-"):
            out["data"].setdefault(attr, line)
    for m in _JS_MAKE_CLASS.finditer(clean):
        for s in re.findall(r"['\"]([\w-]+)['\"]", m.group(1)):
            out["classes"].setdefault(s, _line(clean, m.start()))
    for m in _JS_SETDATA.finditer(clean):
        out["data"].setdefault(m.group(1).lower(), _line(clean, m.start()))
    for m in _JS_DATASET_SET.finditer(clean):
        out["data"].setdefault("data-" + _kebab(m.group(1)), _line(clean, m.start()))
    for m in _JS_ID.finditer(clean):
        if "${" not in m.group(2) and m.group(2).strip():
            out["uses"].append(("id", m.group(2).strip(), _line(clean, m.start()), "#" + m.group(2).strip()))
    for m in _JS_CLASSES.finditer(clean):
        for c in m.group(2).split():
            out["uses"].append(("class", c, _line(clean, m.start()), "." + c))
    for m in _JS_SEL.finditer(clean):
        sel = m.group(2)
        if "${" in sel or "+" in sel and m.group(1) != "`":
            continue
        for kind, name in selector_parts(sel):
            out["uses"].append((kind, name, _line(clean, m.start()), sel))
    return out


def selector_parts(sel):
    """'#menu .card[data-category=bread]' -> [("id","menu"), ("class","card"), ("data","data-category")]"""
    sel = re.sub(r"""(['"]).*?\1""", "", sel)  # attribute values
    parts = [("id", x) for x in re.findall(r"#([\w-]+)", sel)]
    parts += [("class", x) for x in re.findall(r"\.([A-Za-z_][\w-]*)", sel)]
    parts += [("data", x.lower()) for x in re.findall(r"\[\s*(data-[\w-]+)", sel)]
    return parts


def bad_tags(sel):
    """Words used as element names in a selector that aren't HTML elements ('#form submit' -> ['submit'])."""
    sel = re.sub(r"""\[[^\]]*\]|\([^)]*\)|(['"]).*?\1""", " ", sel)
    if sel.strip().startswith("text="):
        return []
    found = re.findall(r"(?:^|[\s>+~,])([a-zA-Z][\w-]*)", sel)
    return [w for w in found if w.lower() not in TAGS and "-" not in w]


def _css_blocks(text):
    """Rules as (context, selector, line); plus the line of a block that is never closed (0 = all closed)."""
    clean = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), text, flags=re.S)
    clean = re.sub(r"""(["'])(?:\\.|(?!\1).)*?\1""", lambda m: " " * len(m.group(0)), clean)
    rules, stack, start, nested = [], [], 0, None
    for i, ch in enumerate(clean):
        if ch == "{":
            head = clean[start:i].strip()
            line = _line(clean, start + len(clean[start:i]) - len(clean[start:i].lstrip()))
            parent = stack[-1] if stack else None
            if nested is None and parent and not parent[0].startswith("@") and not head.startswith(("&", "@")):
                nested = (head, line, parent[0], parent[1])  # a rule inside a rule: usually a missing }
            stack.append((head, line))
            if not head.startswith("@") and not any(h.startswith("@keyframes") for h, _ in stack[:-1]):
                ctx = " ".join(h for h, _ in stack[:-1] if h.startswith("@"))
                rules.append((ctx, " ".join(head.split()), line))
            start = i + 1
        elif ch == "}":
            if stack:
                stack.pop()
            start = i + 1
        elif ch == ";" and stack and not stack[-1][0].startswith("@"):
            start = i + 1
        elif ch == ";":
            start = i + 1
    unclosed = stack[0][1] if stack else 0
    return rules, unclosed, stack[0][0] if stack else "", nested


def css_names(text):
    rules, unclosed, head, nested = _css_blocks(text)
    classes, ids, data, tags = {}, {}, {}, set()
    for _, sel, line in rules:
        for kind, name in selector_parts(sel):
            {"class": classes, "id": ids, "data": data}[kind].setdefault(name, line)
        for part in sel.split(","):
            last = re.sub(r"::?[\w-]+(\([^)]*\))?", "", part.strip().split()[-1] if part.strip() else "")
            m = re.match(r"^([a-zA-Z][\w-]*)", last)
            if m:
                tags.add(m.group(1).lower())
    return {"rules": rules, "classes": classes, "ids": ids, "data": data, "tags": tags,
            "unclosed": unclosed, "unclosed_head": head, "nested": nested}


# ------------------------------------------------------------ the checks
def _kind(path):
    return Path(path).suffix.lower().lstrip(".").replace("htm", "html").replace("htmll", "html")


def _near(name, pool, n=3):
    return difflib.get_close_matches(name, list(pool), n=n, cutoff=0.5)


def file_checks(path, text):
    """Problems a single file has on its own."""
    out = []
    if _kind(path) == "css":
        css = css_names(text)
        if css["unclosed"]:
            out.append({"file": str(path), "line": css["unclosed"],
                        "problem": f"the CSS block `{css['unclosed_head'][:60]} {{` is never closed, so every "
                                   "rule after it is lost or misread",
                        "fix": "add the missing } at the end of that block"})
        elif css["nested"]:
            head, line, parent, pline = css["nested"]
            out.append({"file": str(path), "line": pline,
                        "problem": f"the rule `{head[:40]}` (line {line}) is inside `{parent[:40]} {{` (line {pline}): "
                                   "a } is missing, so the rules after it don't apply as written",
                        "fix": f"close `{parent[:40]}` with }} before line {line}, and remove the extra }} later"})
    return out


def page_map(files, limit=60):
    """What the page really has, in a few lines a worker can follow."""
    ids, classes, data, made = {}, {}, {}, {}
    for path, text in files.items():
        k = _kind(path)
        if k == "html":
            h = html_names(text)
            ids.update(h["ids"]), classes.update(h["classes"]), data.update(h["data"])
        elif k == "js":
            j = js_names(text)
            for key in ("ids", "classes", "data"):
                made.setdefault(key, {}).update(j[key])
    if not (ids or classes or data or made):
        return ""
    lines = []
    if ids:
        lines.append("ids: " + ", ".join("#" + x for x in list(ids)[:limit]))
    if classes:
        lines.append("classes: " + ", ".join("." + x for x in list(classes)[:limit]))
    if data:
        lines.append("data attributes: " + ", ".join(list(data)[:limit]))
    extra = {k: [x for x in v if x not in {"ids": ids, "classes": classes, "data": data}[k]] for k, v in made.items()}
    if any(extra.values()):
        lines.append("made by the script: " + ", ".join(
            ["#" + x for x in extra.get("ids", [])[:20]] + ["." + x for x in extra.get("classes", [])[:30]]
            + extra.get("data", [])[:10]))
    return "\n".join(lines)


def css_map(files, limit=60):
    """The class names the CSS already styles (so HTML and JS can use them)."""
    names = {}
    for path, text in files.items():
        if _kind(path) == "css":
            names.update(css_names(text)["classes"])
    return ", ".join("." + x for x in list(names)[:limit])


def check(files):
    """Every join problem between the page's files. Returns findings, most important first."""
    html = {p: html_names(t) for p, t in files.items() if _kind(p) == "html"}
    js = {p: js_names(t) for p, t in files.items() if _kind(p) == "js"}
    css = {p: css_names(t) for p, t in files.items() if _kind(p) == "css"}
    out = []
    for p, t in files.items():
        out += file_checks(p, t)
    have = {"id": {}, "class": {}, "data": {}}
    for h in list(html.values()) + list(js.values()):
        have["id"].update(h["ids"]), have["class"].update(h["classes"]), have["data"].update(h["data"])
    first_html = next(iter(html), "the HTML")

    # 1. the script looks for things no element has
    if html:
        seen = set()
        for p, j in js.items():
            for kind, name, line, sel in j["uses"]:
                if name in have[kind] or (p, kind, name) in seen:
                    continue
                seen.add((p, kind, name))
                label = {"id": f'id "{name}"', "class": f'class "{name}"', "data": f"attribute {name}"}[kind]
                near = _near(name, have[kind])
                hint = (f" Close names on the page: {', '.join(near)}." if near else "")
                if kind == "class":
                    alt = [d for d in have["data"] if name.split("-")[0] in d]
                    hint += f" The page has {', '.join(alt[:3])}." if alt else ""
                out.append({"file": p, "line": line,
                            "problem": f"{Path(p).name} looks for `{sel}`, but no element has {label}.{hint}",
                            "fix": f"use a name the page really has, or add {label} to the right element in "
                                   f"{Path(first_html).name}"})

    # 2. CSS and HTML picked different class names
    if css and html:
        styled = {}
        for c in css.values():
            styled.update(c["classes"])
        dead = [x for x in styled if x not in have["class"]]
        unstyled = []
        for p, h in html.items():
            for tag, classes, line in h["tags"]:
                for c in classes:
                    if c not in styled and (tag in INTERACTIVE or _LOOKS.search(c)):
                        if c not in [u for u, _, _ in unstyled]:
                            unstyled.append((c, p, line))
        for p, j in js.items():
            for c in j["classes"]:
                if c not in styled and _LOOKS.search(c) and c not in [u for u, _, _ in unstyled]:
                    unstyled.append((c, p, j["classes"][c]))
        if dead and unstyled:
            css_file = next(iter(css))
            pairs = [f".{u} (maybe .{_near(u, dead, 1)[0]})" if _near(u, dead, 1) else f".{u}" for u, _, _ in unstyled]
            out.append({"file": unstyled[0][1], "line": unstyled[0][2],
                        "problem": f"the HTML/script use classes the CSS never styles: {', '.join(pairs[:8])}; "
                                   f"while {Path(css_file).name} styles classes nothing uses: "
                                   f"{', '.join('.' + d for d in dead[:10])}. The two sides picked different names",
                        "fix": "use ONE set of names: change the class names in the HTML/script to the styled ones "
                               "(or rename the CSS selectors)"})
        # buttons with no class and no button rule look like plain browser buttons
        tags_styled = set().union(*(c["tags"] for c in css.values()))
        for p, h in html.items():
            bare = [line for tag, classes, line in h["tags"] if tag == "button" and not classes]
            if bare and "button" not in tags_styled:
                out.append({"file": p, "line": bare[0],
                            "problem": f"{len(bare)} <button> element(s) have no class and the CSS has no `button` "
                                       "rule, so they show as plain grey browser buttons",
                            "fix": "give them the style guide's button class"})

    # 3. the same selector written several times
    for p, c in css.items():
        where = {}
        for ctx, sel, line in c["rules"]:
            where.setdefault((ctx, sel), []).append(line)
        dups = [(sel, lines) for (ctx, sel), lines in where.items() if len(lines) > 1]
        if len(dups) >= 2:
            out.append({"file": p, "line": dups[0][1][1],
                        "problem": f"{Path(p).name} writes {len(dups)} selectors more than once, so later copies "
                                   "override earlier ones: " + "; ".join(
                                       f"`{s[:40]}` (lines {', '.join(map(str, ls[:4]))})" for s, ls in dups[:6]),
                        "fix": "merge each into one rule; when you change a style, edit the existing rule instead "
                               "of adding a new one"})

    # 4. an id used twice
    for p, h in html.items():
        for name, line in h["dup_ids"][:3]:
            out.append({"file": p, "line": line, "problem": f'id "{name}" is used more than once',
                        "fix": "ids must be unique; use a class for repeated elements"})
    return out[:MAX_FINDINGS]


def read(paths):
    """{path: text} for the web files among paths."""
    out = {}
    for p in paths:
        if p and str(p).lower().endswith(WEB) and Path(p).is_file():
            out[str(p)] = Path(p).read_text(encoding="utf-8", errors="replace")
    return out
