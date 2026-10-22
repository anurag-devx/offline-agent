"""
File and folder tools.

Rules enforced here, in code (the model can't talk its way around them):
  - Only folders in the agent's scope (plus ones you grant during the run).
  - Credential folders and this project's code/records are always blocked.
  - Optional file-type filter, and a cap on changes per run.
  - Nothing is ever overwritten by create/move. Delete goes to the Trash.
  - Every change is recorded as a "file_op" event (shown in the run, undoable).
"""
import difflib
import re
import shutil
from datetime import datetime
from pathlib import Path

from ..context import get_context
from ..paths import HOME, WORKSPACE, is_inside, is_protected, resolve_folder
from ..permissions import ASK, OFF
from ..telegram import page
from ..tools import tool

MAX_READ = 20000
MAX_LIST = 500
KINDS = {
    "image": ".jpg .jpeg .png .gif .heic .heif .webp .svg .bmp .tif .tiff .raw .cr2 .nef .ico",
    "document": ".pdf .doc .docx .txt .md .rtf .odt .pages .xls .xlsx .csv .ppt .pptx .key .numbers .epub",
    "video": ".mp4 .mov .avi .mkv .webm .m4v .wmv",
    "audio": ".mp3 .wav .m4a .aac .flac .ogg .aiff",
    "archive": ".zip .rar .7z .tar .gz .tgz .bz2 .dmg .pkg .iso",
    "code": ".py .js .ts .html .css .json .yaml .yml .sh .ipynb .java .c .cpp .go .rs",
}
_KIND_OF = {ext: kind for kind, exts in KINDS.items() for ext in exts.split()}


def kind_of(path):
    return _KIND_OF.get(Path(path).suffix.lower(), "other")


def short(p):
    """Telegram style: /Users/you/Downloads -> ~/Downloads (fewer tokens). Always forward slashes."""
    path = Path(p)
    try:
        path = path.resolve()
    except OSError:
        pass
    s, h = path.as_posix(), HOME.as_posix()
    if s == h:
        return "~"
    return "~" + s[len(h):] if s.startswith(h + "/") else s


def _size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


# ---------------------------------------------------------------- scope checks

def _roots(ctx):
    return [resolve_folder(f) for f in ctx.config.permissions.files.folders] + ctx.state["granted_folders"]


def resolve(path, purpose="use"):
    """Turn the model's path into a real path, or refuse. May ask you to grant a folder."""
    ctx = get_context()
    roots = _roots(ctx)
    p = Path(str(path).strip()).expanduser()
    if not p.is_absolute():
        if not roots:
            raise PermissionError("Give a full path, e.g. ~/Downloads/file.pdf.")
        # Models write relative paths against different bases ("notes.txt", "_bench/04/notes.txt",
        # "workspace/notes.txt"). Use the first candidate that exists; otherwise the first folder.
        candidates = [r / p for r in roots] + [WORKSPACE / p, WORKSPACE.parent / p]
        p = (next((c for c in candidates if c.exists()), None)              # an existing file/folder
             or next((c for c in candidates[:len(roots)] if c.parent.exists()  # a new file in an existing
                      and c.parent != c.parent.parent and len(p.parts) > 1), None)  # subfolder of a root
             or next((c for c in candidates[len(roots):] if c.parent.exists() and len(p.parts) > 1), None)
             or roots[0] / p)
    p = p.resolve()
    if is_protected(p):
        raise PermissionError(f"{p} is a protected location. Agents can never use it.")
    if any(is_inside(p, r) for r in roots):
        return p
    if ctx.config.permissions.files.ask_for_other_folders:
        folder = p if p.is_dir() else p.parent
        if ctx.approve("grant_folder_access", {"folder": str(folder), "why": f"to {purpose} {p.name or p}"}):
            ctx.state["granted_folders"].append(folder)
            ctx.record("folder_granted", folder=str(folder))
            return p
        raise PermissionError(f"The user did not grant access to {folder}.")
    allowed = ", ".join(str(r) for r in roots) or "none"
    raise PermissionError(f"{p} is outside this agent's folders ({allowed}).")


def _check_type(p):
    types = get_context().config.permissions.files.file_types
    if types and p.suffix.lower() not in types:
        raise PermissionError(f"This agent may only handle these file types: {', '.join(types)}.")


def _count_change(ctx, op, **data):
    limit = ctx.config.permissions.files.max_changes
    if ctx.state["changes"] >= limit:
        raise PermissionError(f"Reached this agent's limit of {limit} file changes per run.")
    ctx.state["changes"] += 1
    ctx.record("file_op", op=op, **data)


def _unique(dest):
    """'photo.jpg' exists -> 'photo_1.jpg', 'photo_2.jpg', ..."""
    if not dest.exists():
        return dest
    i = 1
    while (dest.parent / f"{dest.stem}_{i}{dest.suffix}").exists():
        i += 1
    return dest.parent / f"{dest.stem}_{i}{dest.suffix}"


def _ensure_folder(folder, ctx):
    """Create a folder if needed, respecting the Create permission."""
    if folder.is_dir():
        return
    mode = ctx.config.permissions.files.create
    if mode == OFF:
        raise PermissionError(f"{folder} does not exist and this agent may not create folders.")
    if mode == ASK and not ctx.approve("create_folder", {"path": str(folder)}):
        raise PermissionError(f"The user did not allow creating {folder}.")
    folder.mkdir(parents=True)
    _count_change(ctx, "create_folder", dst=str(folder))


# ---------------------------------------------------------------- tools

def _split(text):
    return [x.strip().lower() for x in str(text or "").replace(";", ",").split(",") if x.strip()]


def _matches(p, kinds, exts, contains):
    if kinds and kind_of(p) not in kinds:
        return False
    if exts and p.suffix.lower() not in [e if e.startswith(".") else "." + e for e in exts]:
        return False
    return not contains or contains.lower() in p.name.lower()


@tool("files.read", safety="Only the agent's folders; hidden files are skipped.", example='OK ~/Downloads filter .pdf · 140 files · 0 folders · .pdf:140\na.pdf | document | 297.6 KB')
def list_folder(path: str = "", recursive: bool = False, kinds: str = "", extensions: str = "",
                limit: int = 50):
    """List a folder. First line: counts per file type. Then one line per item: name | kind | size.
    Names are relative to the folder shown. Use filters to keep the list short.
    Kinds: image, document, video, audio, archive, code, other.

    Args:
        path: Folder to list, e.g. "~/Downloads". Empty = the agent's folders.
        recursive: true to include subfolders
        kinds: Optional, comma separated, e.g. "image" or "document,image"
        extensions: Optional, comma separated, e.g. ".pdf" or ".jpg,.png"
        limit: Max lines to show (default 50)
    """
    ctx = get_context()
    targets = [resolve(path, "list")] if str(path).strip() else _roots(ctx)
    if not targets:
        return "This agent has no folders yet. Ask the user which folder to use."
    kinds_, exts = _split(kinds), _split(extensions)
    limit = max(1, min(int(limit), 2000))
    out = []
    for folder in targets:
        if not folder.is_dir():
            out.append(f"(not a folder: {folder})")
            continue
        items = sorted(folder.rglob("*") if recursive else folder.iterdir())
        items = [p for p in items if not any(x.startswith(".") for x in p.relative_to(folder).parts)]
        files = [p for p in items if p.is_file() and _matches(p, kinds_, exts, "")]
        dirs = [p for p in items if p.is_dir()] if not (kinds_ or exts) else []
        counts = {}
        for p in files:
            ext = p.suffix.lower() or "(none)"
            counts[ext] = counts.get(ext, 0) + 1
        top = sorted(counts.items(), key=lambda x: -x[1])
        summary = " ".join(f"{e}:{n}" for e, n in top[:10]) + (f" +{len(top) - 10} types" if len(top) > 10 else "")
        filt = f" filter {','.join(kinds_ + exts)}" if kinds_ or exts else ""
        out.append(f"OK {short(folder)}{filt} · {len(files)} files · {len(dirs)} folders · {summary or 'no files'}")
        rows = [f"{p.relative_to(folder)}/" for p in dirs] + \
               [f"{p.relative_to(folder)} | {kind_of(p)} | {_size(p.stat().st_size)}" for p in files]
        out.extend(rows[:limit])
        if len(rows) > limit:
            out.append(f"+{len(rows) - limit} more. Use filters (extensions/kinds) or limit.")
    return "\n".join(out)


@tool("files.read", safety="Only the agent's folders and allowed file types. Long files come in pages.", example='(first 6000 characters)\n+3000 more chars. Next page: offset=6000')
def read_file(path: str, offset: int = 0, limit: int = 6000):
    """Read a text file, one page at a time.

    Args:
        path: Full path, e.g. "~/Downloads/notes.txt"
        offset: Start at this character (from the previous page's "Next page" hint)
        limit: Characters per page (default 6000)
    """
    p = resolve(path, "read")
    _check_type(p)
    if not p.is_file():
        return f"Error: {short(p)} does not exist. Use list_folder to see what is there."
    return page(p.read_text(encoding="utf-8", errors="replace"), offset, min(int(limit), MAX_READ), short(p))


@tool("files.read", safety="Only the agent's folders and allowed file types. Line numbers are added by code.",
      example='OK ~/site/script.js lines 40-42 of 210\n40 | function addToCart(id) {\n41 |   cart.push(id);\n42 | }')
def read_lines(path: str, start: int = 1, count: int = 80):
    """Read part of a text file WITH line numbers, to find the exact place to look at or change.

    Args:
        path: Full path, e.g. "~/site/script.js"
        start: First line number to show (1 = top of the file)
        count: How many lines (default 80, max 300)
    """
    p = resolve(path, "read")
    _check_type(p)
    if not p.is_file():
        return f"Error: {short(p)} does not exist. Use list_folder to see what is there."
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    return numbered(lines, int(start), max(1, min(int(count), 300)), short(p))


def numbered(lines, start, count, name):
    total = len(lines)
    start = max(1, min(start, total or 1))
    end = min(total, start + count - 1)
    width = len(str(end or 1))
    body = "\n".join(f"{i:>{width}} | {lines[i - 1]}" for i in range(start, end + 1))
    more = f"\n+{total - end} more lines. Next: start={end + 1}" if end < total else ""
    return f"OK {name} lines {start}-{end} of {total}\n{body}{more}"


_NUM = re.compile(r"^\s*\d+ \| ?")


def _unnumber(text):
    """Models sometimes paste read_lines output with its numbers: strip them."""
    lines = text.splitlines()
    if lines and all(_NUM.match(x) for x in lines if x.strip()):
        return "\n".join(_NUM.sub("", x, count=1) for x in lines)
    return text


def _loose_find(lines, old_lines):
    """Positions where old_lines match ignoring spaces at the start/end of each line."""
    want = [x.strip() for x in old_lines]
    k = len(want)
    return [i for i in range(len(lines) - k + 1) if [x.strip() for x in lines[i:i + k]] == want]


def _closest(lines, old):
    first = next((x.strip() for x in old.splitlines() if x.strip()), "")
    stripped = [x.strip() for x in lines]
    near = difflib.get_close_matches(first, stripped, n=3, cutoff=0.5)
    hits = [i for i, x in enumerate(stripped) if x in near][:3]
    return "\n".join(f"{i + 1} | {lines[i]}" for i in hits) or "(nothing similar)"


@tool("files.modify", safety="Changes only the exact text you quote, which must appear exactly once. Recorded in the file log.",
      example='OK edited ~/site/script.js at line 42 (1 → 2 lines)')
def edit_file(path: str, old_text: str, new_text: str):
    """Change part of an EXISTING file: replace old_text with new_text. Much cheaper than rewriting
    the whole file. old_text must be copied exactly from the file (use read_lines first, without the
    line numbers) and must appear only once; include a few lines around it if needed.

    Args:
        path: Full path of the file
        old_text: The exact text to replace (one or a few lines)
        new_text: The text to put there instead ("" deletes old_text)
    """
    ctx = get_context()
    p = resolve(path, "modify")
    _check_type(p)
    if not p.is_file():
        return f"Error: {short(p)} does not exist. Use write_file to create it."
    text = p.read_text(encoding="utf-8", errors="replace")
    old, new = _unnumber(str(old_text)), _unnumber(str(new_text))
    if not old.strip():
        return "Error: old_text is empty. Use insert_lines to add new lines."
    n = text.count(old)
    if n > 1:
        return f"Error: old_text appears {n} times in {short(p)}. Include more lines around it so it is unique."
    if n == 1:
        at = text[:text.index(old)].count("\n") + 1
        updated = text.replace(old, new, 1)
    else:  # tolerate different indentation / trailing spaces, line by line
        lines, olds = text.splitlines(keepends=True), old.splitlines()
        hits = _loose_find([x.rstrip("\r\n") for x in lines], olds)
        if len(hits) != 1:
            why = "appears more than once" if hits else "was not found"
            return (f"Error: old_text {why} in {short(p)}. Closest lines:\n{_closest(text.splitlines(), old)}\n"
                    "Copy the exact text with read_lines and try again.")
        i, at = hits[0], hits[0] + 1
        tail = "\n" if lines[i + len(olds) - 1].endswith("\n") and new and not new.endswith("\n") else ""
        updated = "".join(lines[:i]) + new + tail + "".join(lines[i + len(olds):])
    _count_change(ctx, "modify", dst=str(p))
    p.write_text(updated, encoding="utf-8")
    return f"OK edited {short(p)} at line {at} ({len(old.splitlines())} → {len(new.splitlines())} lines)"


@tool("files.modify", safety="Adds lines to an existing file; nothing else changes. Recorded in the file log.",
      example='OK inserted 5 lines after line 120 in ~/site/index.html')
def insert_lines(path: str, after_line: int, text: str):
    """Insert new lines into an EXISTING file after a line number (0 = at the very top).
    Use read_lines to find the right number. Nothing else in the file changes.

    Args:
        path: Full path of the file
        after_line: Insert after this line number (0 = top; a number past the end = at the end)
        text: The lines to insert
    """
    ctx = get_context()
    p = resolve(path, "modify")
    _check_type(p)
    if not p.is_file():
        return f"Error: {short(p)} does not exist. Use write_file to create it."
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    n = max(0, min(int(after_line), len(lines)))
    if n and not lines[n - 1].endswith("\n"):
        lines[n - 1] += "\n"
    add = str(text) if str(text).endswith("\n") or n == len(lines) else str(text) + "\n"
    _count_change(ctx, "modify", dst=str(p))
    p.write_text("".join(lines[:n]) + add + "".join(lines[n:]), encoding="utf-8")
    return f"OK inserted {len(str(text).splitlines())} lines after line {n} in {short(p)}"


@tool("files.create", safety="Only inside the agent's folders. Counts toward the change limit.", example='OK created ~/Downloads/all_pdf/')
def create_folder(path: str):
    """Create a folder (and any missing parent folders). Does nothing if it already exists.

    Args:
        path: Full path of the new folder, e.g. "~/Downloads/anurag_img"
    """
    ctx = get_context()
    p = resolve(path, "create")
    if p.exists():
        return f"{p} already exists."
    p.mkdir(parents=True)
    _count_change(ctx, "create_folder", dst=str(p))
    return f"OK created {short(p)}/"


@tool("files.create", safety="Creates NEW files only; never overwrites. Only the agent's folders.", example='OK created ~/site/index.html (2140 chars)')
def write_file(path: str, content: str):
    """Create a NEW text file. Fails if the file already exists (use overwrite_file for that).

    Args:
        path: Full path, e.g. "~/Documents/site/index.html" or "my-site/index.html" in workspace
        content: The full text of the file
    """
    ctx = get_context()
    p = resolve(path, "create")
    _check_type(p)
    if p.exists():
        return f"Error: {p} already exists. Use overwrite_file to replace it (needs Modify permission)."
    _ensure_folder(p.parent, ctx)
    _count_change(ctx, "create_file", dst=str(p))
    p.write_text(content, encoding="utf-8")
    return f"OK created {short(p)} ({len(content)} chars)"


@tool("files.modify", safety='Changes an existing file: use Ask first. Recorded in the file log.', example='OK replaced ~/site/style.css (980 chars)')
def overwrite_file(path: str, content: str):
    """Replace ALL of an EXISTING text file. To change only part of it, use edit_file or
    insert_lines instead: much less to write.

    Args:
        path: Full path of the file
        content: The new full text
    """
    ctx = get_context()
    p = resolve(path, "modify")
    _check_type(p)
    if not p.is_file():
        return f"Error: {p} does not exist. Use write_file to create it."
    _count_change(ctx, "modify", dst=str(p))
    p.write_text(content, encoding="utf-8")
    return f"OK replaced {short(p)} ({len(content)} chars)"


@tool("files.modify", safety="Adds a line to notes.md in the agent's first folder.", example='Note saved to notes.md.')
def append_note(text: str):
    """Add a timestamped line to notes.md (in the agent's first folder, usually the workspace).

    Args:
        text: The note to save
    """
    ctx = get_context()
    roots = _roots(ctx)
    p = resolve(str((roots[0] if roots else WORKSPACE) / "notes.md"), "write")
    _count_change(ctx, "modify", dst=str(p))
    with open(p, "a", encoding="utf-8") as f:
        f.write(f"- [{datetime.now():%Y-%m-%d %H:%M}] {text}\n")
    return "Note saved to notes.md."


@tool("files.move", safety='Never overwrites: name clashes get _1, _2. Undo moves it back.', example='OK moved ~/Downloads/a.pdf → ~/Downloads/all_pdf/a.pdf')
def move_file(source: str, destination_folder: str, new_name: str = ""):
    """Move (or rename) a file into a folder. Creates the folder if needed (if allowed).
    Never overwrites: if the name exists, it adds _1, _2...

    Args:
        source: Full path of the file to move
        destination_folder: Full path of the folder to move it into
        new_name: Optional new file name; leave empty to keep the name
    """
    ctx = get_context()
    src = resolve(source, "move")
    if not src.is_file():
        return f"Error: {src} is not a file. Use list_folder to check the path."
    _check_type(src)
    dst_dir = resolve(destination_folder, "move files into")
    _ensure_folder(dst_dir, ctx)
    dst = _unique(dst_dir / (new_name.strip() or src.name))
    _count_change(ctx, "move", src=str(src), dst=str(dst))
    shutil.move(str(src), str(dst))
    renamed = " (renamed: name existed)" if dst.name != (new_name.strip() or src.name) else ""
    return f"OK moved {short(src)} → {short(dst)}{renamed}"


def _batch(folder, extensions, kinds, name_contains, destination_folder=None):
    src_dir = resolve(folder, "move files from")
    if not src_dir.is_dir():
        raise ValueError(f"{src_dir} is not a folder.")
    kinds_, exts = _split(kinds), _split(extensions)
    if not (kinds_ or exts or str(name_contains).strip()):
        raise ValueError("Give at least one filter: extensions, kinds or name_contains.")
    dest = Path(str(destination_folder)).expanduser() if destination_folder else None
    picked = []
    for p in sorted(src_dir.iterdir()):
        if p.name.startswith(".") or not p.is_file():
            continue
        if dest is not None and p.parent.resolve() == dest.resolve():
            continue
        if _matches(p, kinds_, exts, str(name_contains).strip()):
            picked.append(p)
    return src_dir, picked


def _preview_move_files(folder, destination_folder, extensions="", kinds="", name_contains=""):
    _, picked = _batch(folder, extensions, kinds, name_contains, destination_folder)
    names = ", ".join(p.name for p in picked[:15]) + (f" … and {len(picked) - 15} more" if len(picked) > 15 else "")
    return f"Move {len(picked)} files to {destination_folder}: {names or '(nothing matches)'}"


@tool("files.move", preview=_preview_move_files, safety='Needs at least one filter; top level only (subfolders untouched); never overwrites; you see the exact file list before approving.', example='OK moved 138/140 ~/Downloads → ~/Downloads/all_pdf · NOT MOVED 2: …')
def move_files(folder: str, destination_folder: str, extensions: str = "", kinds: str = "",
               name_contains: str = ""):
    """Move ALL matching files from a folder (top level only) into another folder, in one step.
    Use this instead of many move_file calls. Needs at least one filter. Never overwrites.

    Args:
        folder: Folder to take files from, e.g. "~/Downloads"
        destination_folder: Folder to move them into, e.g. "~/Downloads/all_pdf" (created if needed)
        extensions: Comma separated, e.g. ".pdf" or ".jpg,.png,.heic"
        kinds: Comma separated: image, document, video, audio, archive, code, other
        name_contains: Only files whose name contains this text
    """
    ctx = get_context()
    src_dir, picked = _batch(folder, extensions, kinds, name_contains, destination_folder)
    if not picked:
        return f"OK nothing matches in {short(src_dir)}. Moved 0."
    dst_dir = resolve(destination_folder, "move files into")
    _ensure_folder(dst_dir, ctx)
    moved, skipped = [], []
    for src in picked:
        try:
            _check_type(src)
            dst = _unique(dst_dir / src.name)
            _count_change(ctx, "move", src=str(src), dst=str(dst))
            shutil.move(str(src), str(dst))
            moved.append(dst.name)
        except Exception as e:
            skipped.append(f"{src.name} ({e})")
    msg = f"OK moved {len(moved)}/{len(picked)} {short(src_dir)} → {short(dst_dir)}"
    if skipped:
        msg += f" · NOT MOVED {len(skipped)}: " + "; ".join(skipped[:10])
    return msg


@tool("files.delete", safety='Sends files to the Trash (recoverable), files only, never folders. Use Ask first.', example='OK ~/Downloads/old.zip → Trash')
def delete_file(path: str):
    """Send a file to the Trash (recoverable). Only when the user explicitly asked to delete it.

    Args:
        path: Full path of the file
    """
    ctx = get_context()
    p = resolve(path, "delete")
    if not p.is_file():
        return f"Error: {p} is not a file."
    _check_type(p)
    try:
        from send2trash import send2trash
    except ImportError:
        return "Error: delete needs the send2trash package. Run: pip install -r requirements.txt"
    _count_change(ctx, "delete", src=str(p))
    send2trash(str(p))
    return f"OK {short(p)} → Trash"
