"""
engine/findings.py: the reviewer points at exact places, so fixes are small patches.

The Inspector returns findings: file + line + problem + fix. Code checks that the file exists
and the line is in range, and attaches the real lines around it (numbered by code). The agent
then fixes each spot with edit_file / insert_lines instead of rewriting whole files.
"""
from pathlib import Path

AROUND = 6       # lines of context shown on each side
MAX_FINDINGS = 10

SCHEMA = {"type": "array", "items": {
    "type": "object",
    "properties": {"file": {"type": "string"}, "line": {"type": "integer"},
                   "problem": {"type": "string"}, "fix": {"type": "string"}},
    "required": ["file", "line", "problem", "fix"]}}

PATCH_RULE = ("Fix each finding where it is, with edit_file (replace the exact old text) or insert_lines "
              "(add missing lines after a line number). Use read_lines to see exact text. Do not rewrite "
              "whole files with overwrite_file unless a file is mostly wrong.")


def find_file(name, roots=(), known=()):
    """The real path of a file the reviewer named (relative, absolute or just a file name)."""
    name = str(name or "").strip()
    if not name:
        return None
    p = Path(name).expanduser()
    cands = [p] if p.is_absolute() else [Path(r) / name for r in roots]
    for c in cands:
        if c.is_file():
            return c
    want = name.replace("\\", "/").lstrip("./").lower()
    for k in reversed(list(known)):
        k2 = str(k).replace("\\", "/").lower()
        if (k2.endswith("/" + want) or k2.endswith("/" + want.rsplit("/", 1)[-1])) and Path(k).is_file():
            return Path(k)
    return None


def locate(findings, roots=(), known=()):
    """Checked findings with the real lines around each (or a note that the file wasn't found)."""
    out = []
    for f in list(findings or [])[:MAX_FINDINGS]:
        if not isinstance(f, dict) or not str(f.get("problem", "")).strip():
            continue
        path = find_file(f.get("file"), roots, known)
        item = {"file": str(f.get("file", "")), "line": 0, "problem": str(f.get("problem", ""))[:300],
                "fix": str(f.get("fix", ""))[:500], "path": str(path) if path else "", "snippet": ""}
        if path:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            try:
                line = int(f.get("line") or 0)
            except (TypeError, ValueError):
                line = 0
            item["line"] = line if 1 <= line <= len(lines) else 0
            if item["line"]:
                lo, hi = max(1, line - AROUND), min(len(lines), line + AROUND)
                width = len(str(hi))
                item["snippet"] = "\n".join(f"{i:>{width}} | {lines[i - 1]}" for i in range(lo, hi + 1))
        out.append(item)
    return out


def as_text(items):
    """Findings as a block for the agent's message."""
    blocks = []
    for n, f in enumerate(items, 1):
        where = f"{f['file']}" + (f" line {f['line']}" if f["line"] else "")
        lines = [f"{n}. {where}: {f['problem']}"]
        if f["fix"]:
            lines.append(f"   Fix: {f['fix']}")
        if f["snippet"]:
            lines.append("   Current lines:\n" + "\n".join("   " + x for x in f["snippet"].splitlines()))
        elif f["file"] and not f["path"]:
            lines.append("   (file not found: create it, or check the name)")
        blocks.append("\n".join(lines))
    return "\n".join(blocks)
