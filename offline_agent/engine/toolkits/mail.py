"""
Email tools over IMAP (works with Gmail using an app password).

Your mail travels only between this computer and your mail server.
There is deliberately no tool to send or delete email.
"""
import email
import imaplib
import re
from email.header import decode_header, make_header

from ..context import get_context
from ..credentials import load_credentials
from ..telegram import page
from ..tools import tool

MAX_BODY = 4000
_LIST_RE = re.compile(r'\((?P<flags>[^)]*)\) (?P<delim>"[^"]*"|NIL) (?P<name>.+)')


def _connect():
    creds = load_credentials().get("email") or {}
    if not (creds.get("address") and creds.get("password")):
        raise RuntimeError("Email is not set up. Add it on the Settings page.")
    host = creds.get("imap_host") or "imap.gmail.com"
    try:
        get_context().record("network", url=f"imaps://{host}", host=host, allowed=True)
    except RuntimeError:
        pass  # called outside an agent (e.g. Settings test)
    conn = imaplib.IMAP4_SSL(host, timeout=30)
    conn.login(creds["address"], creds["password"])
    return conn


def _q(folder):
    """IMAP needs folder names quoted, e.g. "Receipts 2026"."""
    return '"' + folder.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _short_date(value):
    """Morse: 'Mon, 20 Oct 2026 14:05:00 +0530' -> '20 Oct 14:05'."""
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(value).strftime("%d %b %H:%M")
    except Exception:
        return _h(value)[:16]


def _sender(value):
    """Morse: 'Amazon <ship@amazon.in>' -> 'Amazon (amazon.in)'."""
    name, _, addr = _h(value).rpartition("<")
    name, addr = name.strip().strip('"'), addr.rstrip(">").strip()
    domain = addr.split("@")[-1] if "@" in addr else ""
    return f"{name or addr}" + (f" ({domain})" if domain and name else "")


def _h(value):
    try:
        return str(make_header(decode_header(value or "")))
    except Exception:
        return value or ""


def _check_folder(folder):
    allowed = get_context().config.permissions.email.folders
    if allowed and folder not in allowed:
        raise PermissionError(f"This agent may only use these mail folders: {', '.join(allowed)}.")


def _select(conn, folder, readonly=True):
    try:
        _check_folder(folder)
    except RuntimeError:
        pass  # outside an agent (Settings test)
    typ, data = conn.select(_q(folder), readonly=readonly)
    if typ != "OK":
        raise RuntimeError(f"Folder '{folder}' not found. Use email_folders to see folder names.")


def _body_text(msg):
    if msg.is_multipart():
        html = ""
        for part in msg.walk():
            ctype = part.get_content_type()
            if part.get_filename():
                continue
            payload = part.get_payload(decode=True) or b""
            text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
            if ctype == "text/plain":
                return text
            if ctype == "text/html" and not html:
                html = text
        return re.sub(r"<[^>]+>", " ", html)
    payload = msg.get_payload(decode=True) or b""
    return payload.decode(msg.get_content_charset() or "utf-8", errors="replace")


def list_folder_names(conn):
    typ, data = conn.list()
    names = []
    for line in data or []:
        m = _LIST_RE.match(line.decode(errors="replace"))
        if m and "\\Noselect" not in m["flags"]:
            names.append(m["name"].strip().strip('"'))
    return names


@tool("email.read", safety='Reads folder names only, from your mail server.', example='INBOX\nReceipts\n[Gmail]/Spam')
def email_folders():
    """List the mailbox folders (in Gmail these are labels, e.g. INBOX, [Gmail]/Spam)."""
    conn = _connect()
    try:
        return "\n".join(list_folder_names(conn))
    finally:
        conn.logout()


@tool("email.read", safety='Does not mark mail as read. Only allowed mail folders.', example='OK 20 emails in INBOX (uid | date | from | subject)\n102 | 20 Oct 14:05 | Amazon (amazon.in) | Your order shipped')
def email_list(folder: str = "INBOX", limit: int = 20, unread_only: bool = False):
    """List the newest emails in a folder: uid, date, sender and subject. Does not mark them read.

    Args:
        folder: Folder name, default "INBOX"
        limit: How many emails, max 50
        unread_only: true to list only unread emails
    """
    conn = _connect()
    try:
        _select(conn, folder)
        typ, data = conn.uid("search", None, "UNSEEN" if unread_only else "ALL")
        uids = (data[0] or b"").split()[-max(1, min(int(limit), 50)):][::-1]
        if not uids:
            return "No emails found."
        typ, data = conn.uid("fetch", b",".join(uids),
                             "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
        rows = []
        for item in data:
            if not isinstance(item, tuple):
                continue
            uid = re.search(rb"UID (\d+)", item[0])
            msg = email.message_from_bytes(item[1])
            rows.append(f"{uid.group(1).decode() if uid else '?'} | {_short_date(msg['Date'])} | "
                        f"{_sender(msg['From'])} | {_h(msg['Subject'])[:80]}")
        return f"OK {len(rows)} emails in {folder} (uid | date | from | subject)\n" + "\n".join(rows)
    finally:
        conn.logout()


@tool("email.read", safety='Does not mark mail as read. Long emails come in pages.', example='From: Amazon (amazon.in) · 20 Oct 14:05\nSubject: Your order shipped\n\n…')
def email_read(uid: str, folder: str = "INBOX", offset: int = 0, limit: int = 1500):
    """Read one email's headers and text, one page at a time. Does not mark it read.

    Args:
        uid: The uid from email_list
        folder: Folder the email is in, default "INBOX"
        offset: Start at this character of the body (from the "Next page" hint)
        limit: Characters per page (default 1500)
    """
    conn = _connect()
    try:
        _select(conn, folder)
        typ, data = conn.uid("fetch", str(uid), "(BODY.PEEK[])")
        raw = next((i[1] for i in data or [] if isinstance(i, tuple)), None)
        if not raw:
            return f"Error: no email with uid {uid} in {folder}."
        msg = email.message_from_bytes(raw)
        body = re.sub(r"\n\s*\n+", "\n\n", _body_text(msg)).strip()
        return (f"From: {_sender(msg['From'])} · {_short_date(msg['Date'])}\nSubject: {_h(msg['Subject'])}\n\n"
                + page(body, offset, min(int(limit), MAX_BODY), "email"))
    finally:
        conn.logout()


@tool("email.organize", safety='Moves only; there is no send or delete tool. Only allowed mail folders.', example='Moved email 102 from INBOX to Receipts.')
def email_move(uid: str, to_folder: str, from_folder: str = "INBOX"):
    """Move an email to another folder (Gmail: label), creating the folder if needed.

    Args:
        uid: The uid from email_list
        to_folder: Destination folder, e.g. "Receipts"
        from_folder: Where the email is now, default "INBOX"
    """
    _check_folder(to_folder)
    conn = _connect()
    try:
        if to_folder not in list_folder_names(conn):
            conn.create(_q(to_folder))
        _select(conn, from_folder, readonly=False)
        typ, data = conn.uid("MOVE", str(uid), _q(to_folder))
        if typ != "OK":
            return f"Error: move failed: {data}"
        return f"Moved email {uid} from {from_folder} to {to_folder}."
    finally:
        conn.logout()


@tool("email.organize", safety='Changes the read flag only.', example='Marked email 102 as read.')
def email_mark_read(uid: str, folder: str = "INBOX"):
    """Mark an email as read.

    Args:
        uid: The uid from email_list
        folder: Folder the email is in, default "INBOX"
    """
    conn = _connect()
    try:
        _select(conn, folder, readonly=False)
        conn.uid("store", str(uid), "+FLAGS", "(\\Seen)")
        return f"Marked email {uid} as read."
    finally:
        conn.logout()


# ---------------------------------------------------------------- used by email rule mode

def _criterion(value):
    value = str(value).strip()
    if not value.isascii():
        raise ValueError(f"Use plain (ASCII) text in email rules: {value!r}")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def search_uids(conn, folder, from_contains="", subject_contains="", unread_only=False):
    """Server-side IMAP search (the mail server does the matching; no mail is downloaded)."""
    _select(conn, folder)
    parts = []
    if from_contains:
        parts += ["FROM", _criterion(from_contains)]
    if subject_contains:
        parts += ["SUBJECT", _criterion(subject_contains)]
    if unread_only:
        parts.append("UNSEEN")
    if not (from_contains or subject_contains):
        raise ValueError("An email rule needs from_contains and/or subject_contains.")
    typ, data = conn.uid("search", None, *parts)
    return [u.decode() for u in (data[0] or b"").split()]


def headers(conn, uids):
    """[(uid, sender, subject)] for a few uids (the folder must be selected)."""
    if not uids:
        return []
    typ, data = conn.uid("fetch", ",".join(uids), "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)])")
    out = []
    for item in data or []:
        if isinstance(item, tuple):
            uid = re.search(rb"UID (\d+)", item[0])
            msg = email.message_from_bytes(item[1])
            out.append((uid.group(1).decode() if uid else "?", _h(msg["From"]), _h(msg["Subject"])))
    return out


def move_uids(conn, uids, from_folder, to_folder):
    """Move many emails in one command. Creates the destination folder if needed."""
    _check_folder(to_folder)
    if to_folder not in list_folder_names(conn):
        conn.create(_q(to_folder))
    _select(conn, from_folder, readonly=False)
    typ, data = conn.uid("MOVE", ",".join(uids), _q(to_folder))
    if typ != "OK":
        raise RuntimeError(f"move failed: {data}")
    return len(uids)
