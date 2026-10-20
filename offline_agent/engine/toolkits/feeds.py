"""
News feeds (RSS and Atom), parsed in code.

A raw feed is thousands of tokens of XML. read_feed returns one short line per item,
    3. Sensex jumps 600 points as banks rally | 2026-10-20 14:05 | https://...
and can filter by keywords and date, so the model only sees what matters.
Uses the same allowed-sites rules and logging as fetch_url.
"""
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from html import unescape

from ..tools import tool
from .web import http_get

MAX_ITEMS = 100


def _local(name):
    return name.rsplit("}", 1)[-1].lower()  # "{http://www.w3.org/2005/Atom}entry" -> "entry"


def _text(el, *names):
    for child in el:
        if _local(child.tag) in names:
            return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", "".join(child.itertext())))).strip()
    return ""


def _link(el):
    for child in el:
        if _local(child.tag) == "link":
            if child.get("href"):                      # Atom
                if child.get("rel", "alternate") == "alternate":
                    return child.get("href")
            elif (child.text or "").strip():           # RSS
                return child.text.strip()
    return ""


def _date(value):
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)              # RSS: "Mon, 20 Oct 2026 14:05:00 +0530"
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))  # Atom: ISO 8601
        except ValueError:
            return None
    return dt.astimezone() if dt.tzinfo else dt        # to this computer's local time


def parse_feed(xml_text):
    """XML -> (feed title, [{"title", "link", "date", "summary"}])."""
    if re.search(r"<!ENTITY", xml_text[:5000], re.I):
        raise ValueError("Feed refused: it declares XML entities (unsafe).")
    root = ET.fromstring(xml_text.lstrip("﻿").strip())
    title = ""
    items = []
    for el in root.iter():
        tag = _local(el.tag)
        if tag in ("channel", "feed") and not title:
            title = _text(el, "title")
        if tag in ("item", "entry"):
            items.append({
                "title": _text(el, "title"),
                "link": _link(el),
                "date": _date(_text(el, "pubdate", "published", "updated", "date")),
                "summary": _text(el, "description", "summary", "content")[:300],
            })
    return title, items


@tool("internet.read")
def read_feed(url: str, keywords: str = "", today_only: bool = False, since_hours: int = 0,
              limit: int = 20):
    """Read a news feed (RSS/Atom) and return one line per item: headline | time | link.
    Much shorter than fetch_url. Use filters to keep only what you need.

    Args:
        url: Feed address, e.g. "https://www.livemint.com/rss/markets"
        keywords: Optional, comma separated; keep items mentioning any of them, e.g. "sensex,nifty"
        today_only: true to keep only items published today
        since_hours: Optional; keep only items from the last N hours (0 = no limit)
        limit: Max items to show (default 20)
    """
    body, _ = http_get(url)
    title, items = parse_feed(body)
    total = len(items)
    words = [w.strip().lower() for w in keywords.split(",") if w.strip()]
    now = datetime.now().astimezone()
    if words:
        items = [i for i in items if any(w in f"{i['title']} {i['summary']}".lower() for w in words)]
    if today_only:
        items = [i for i in items if i["date"] and i["date"].date() == now.date()]
    if since_hours:
        items = [i for i in items if i["date"] and i["date"] >= now - timedelta(hours=int(since_hours))]
    limit = max(1, min(int(limit), MAX_ITEMS))
    filt = " · ".join(x for x in [f"keywords {keywords}" if words else "", "today" if today_only else "",
                                  f"last {since_hours}h" if since_hours else ""] if x)
    lines = [f"OK feed {title or url} · {len(items)}/{total} items" + (f" · {filt}" if filt else "")]
    for n, i in enumerate(items[:limit], 1):
        when = i["date"].strftime("%Y-%m-%d %H:%M") if i["date"] else "no date"
        lines.append(f"{n}. {i['title']} | {when} | {i['link']}")
    if len(items) > limit:
        lines.append(f"+{len(items) - limit} more. Raise limit or narrow keywords.")
    return "\n".join(lines)
