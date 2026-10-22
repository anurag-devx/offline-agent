"""
File and folder tools.

Rules enforced here, in code (the model can't talk its way around them):
  - Only folders in the agent's scope (plus ones you grant during the run).
  - Credential folders and this project's code/records are always blocked.
  - Optional file-type filter, and a cap on changes per run.
  - Nothing is ever overwritten by create/move. Delete goes to the Trash.
  - Every change is recorded as a "file_op" event (shown in the run, undoable).
"""
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
        p = roots[0] / p
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


@tool("files.read")
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


@tool("files.read")
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


@tool("files.create")
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


@tool("files.create")
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


@tool("files.modify")
def overwrite_file(path: str, content: str):
    """Replace the content of an EXISTING text file.

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


@tool("files.modify")
def append_note(text: str):
    """Add a timestamped line to notes.md in the workspace.

    Args:
        text: The note to save
    """
    ctx = get_context()
    p = resolve(str(WORKSPACE / "notes.md"), "write")
    _count_change(ctx, "modify", dst=str(p))
    with open(p, "a", encoding="utf-8") as f:
        f.write(f"- [{datetime.now():%Y-%m-%d %H:%M}] {text}\n")
    return "Note saved to notes.md."


@tool("files.move")
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


@tool("files.move", preview=_preview_move_files)
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


@tool("files.delete")
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
