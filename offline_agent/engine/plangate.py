"""
engine/plangate.py: the plan gate. Code checks what the PM wrote before anyone works from it.

A small model writes the plan, and code then acts on parts of it: it searches each output for the
chunk's `must_contain` strings, runs the browser checks, and gives each chunk its files. When the
PM writes something that can never pass, the chunk fails however good the work is, and every
retry is wasted. A real run lost 6 of 13 chunks (and hours) this way. So every instruction for code
goes through the gate first, and is made checkable or dropped:

    must_contain   example code becomes the one name code can find:
                     <path d="..." fill="#a0522d" />  ->  <path
                     <section id="menu">              ->  #menu
                     <script src="script.js">         ->  script.js
                     .card { border-radius: 10px; }   ->  .card
                     @media (max-width: 600px) {...}  ->  @media
                     addToCart(itemId)                ->  addToCart
                   the chunk's own file path is dropped (code checks the file exists anyway)
    ids            two chunks building the same file may not both create the same id: the first
                   one owns it, the later one is told to fill the existing element
    checks         (engine/browser.py) selectors naming elements HTML doesn't have are repaired
                   or the check is dropped

`gate(chunks)` changes the chunks in place and returns one line per change, for the run's log.
"""
import re
from pathlib import Path

MAX_MUST = 10
_ID = re.compile(r"""\bid\s*=\s*["']([\w-]+)["']""")
_SRC = re.compile(r"""\b(?:src|href)\s*=\s*["']([^"'#][^"']*)["']""")
_TAG = re.compile(r"^<\s*([a-zA-Z][\w-]*)")
_CALL = re.compile(r"^(?:function\s+|const\s+|let\s+|var\s+)?([A-Za-z_$][\w$.]*)\s*\(")
_CSS = re.compile(r"^([@.#]?[A-Za-z_][\w-]*)[^{]*\{")
_PATHLIKE = re.compile(r"^[\w./~-]+\.(html?|css|js|svg|png|jpe?g|json|md|txt|py)$", re.I)


def key(item, output=""):
    """The part of a must_contain item code can really find in a file ("" = drop it)."""
    s = " ".join(str(item).split())
    if not s:
        return ""
    out = output.replace("\\", "/").lower()
    low = s.replace("\\", "/").lower()
    if _PATHLIKE.match(s) and (low == out or out.endswith("/" + low) or low.endswith("/" + Path(out).name)
                               or "/" in low):
        return ""  # a path: code already checks the file exists
    if s.startswith("<"):
        tag = _TAG.match(s)
        if (m := _ID.search(s)):
            return "#" + m.group(1)
        if (m := _SRC.search(s)) and tag and tag.group(1).lower() in ("script", "link", "img", "a", "use", "image"):
            return m.group(1)
        return "<" + tag.group(1).lower() if tag else ""
    if (m := re.fullmatch(r"""id\s*=\s*["']([\w-]+)["']""", s)):
        return "#" + m.group(1)
    if (m := _CSS.match(s)) and "{" in s:
        return m.group(1)
    if (m := _CALL.match(s)) and s.rstrip(";").endswith(")"):
        return m.group(1).split(".")[-1]
    if "..." in s or "…" in s:
        return ""  # an example, not real content
    return s if len(s) <= 60 else ""


def clean_must(items, output=""):
    """must_contain items made checkable, without duplicates. Returns (items, changes)."""
    out, changes = [], []
    for item in items or []:
        k = key(item, output)
        if k != str(item).strip():
            changes.append(f"{item!s:.50} → {k or '(dropped)'}")
        if k and k.lower() not in (x.lower() for x in out):
            out.append(k)
    return out[:MAX_MUST], changes


def ids_in(chunk):
    found = {m[1:] for m in chunk["must_contain"] if m.startswith("#")}
    found |= set(re.findall(r"""\bid\s*=\s*["']([\w-]+)["']""", chunk["goal"]))
    return found


def gate(chunks):
    """Make every chunk's checks passable. Changes chunks in place; returns notes for the log."""
    notes = []
    for c in chunks:
        c["must_contain"], changes = clean_must(c["must_contain"], c["output"])
        if changes:
            notes.append(f"{c['id']}: " + "; ".join(changes[:6]) + (" …" if len(changes) > 6 else ""))
    owner = {}  # (file, id) -> the first chunk that creates it
    for c in chunks:
        if not c["output"]:
            continue
        theirs = []
        for i in sorted(ids_in(c)):
            first = owner.setdefault((c["output"].lower(), i), c)
            if first is not c:
                theirs.append((i, first["id"]))
        if theirs:
            c["must_contain"] = [m for m in c["must_contain"] if m[1:] not in {i for i, _ in theirs}]
            c["goal"] += ("\nThese elements already exist (made by an earlier chunk): " + ", ".join(
                f"#{i} ({who})" for i, who in theirs) + ". Fill them in place; never create a second element "
                "with the same id.")
            notes.append(f"{c['id']}: fills existing " + ", ".join(f"#{i}" for i, _ in theirs))
    return notes
