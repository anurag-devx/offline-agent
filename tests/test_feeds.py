from datetime import datetime, timedelta

import pytest

from offline_agent.engine.context import ToolContext, set_context
from offline_agent.engine.toolkits import feeds
from tests.conftest import config

NOW = datetime.now().astimezone()
RSS = f"""<?xml version="1.0"?><rss version="2.0"><channel><title>Markets</title>
<item><title>Sensex jumps 600 points</title><link>https://ex.com/1</link>
<pubDate>{NOW.strftime('%a, %d %b %Y %H:%M:%S %z')}</pubDate><description>Banks &amp; IT rally</description></item>
<item><title>Monsoon update</title><link>https://ex.com/2</link>
<pubDate>{(NOW - timedelta(days=3)).strftime('%a, %d %b %Y %H:%M:%S %z')}</pubDate></item>
</channel></rss>"""
ATOM = """<feed xmlns="http://www.w3.org/2005/Atom"><title>A</title>
<entry><title>Nifty at record</title><link href="https://ex.com/a"/><updated>2026-10-20T08:00:00Z</updated></entry></feed>"""


def test_parse_rss_and_atom():
    title, items = feeds.parse_feed(RSS)
    assert title == "Markets" and items[0]["title"] == "Sensex jumps 600 points"
    assert items[0]["link"] == "https://ex.com/1" and "Banks & IT" in items[0]["summary"]
    _, atom = feeds.parse_feed(ATOM)
    assert atom[0]["link"] == "https://ex.com/a" and atom[0]["date"].year == 2026


def test_entities_refused():
    with pytest.raises(ValueError):
        feeds.parse_feed('<!DOCTYPE x [<!ENTITY a "b">]><rss/>')


def test_read_feed_filters_and_is_compact(monkeypatch):
    cfg = config(permissions={"internet": {"read": "allow", "domains": ["ex.com"]}})
    set_context(ToolContext(cfg, {"granted_folders": [], "granted_domains": [], "changes": 0}))
    monkeypatch.setattr(feeds, "http_get", lambda url: (RSS, "application/rss+xml"))
    out = feeds.read_feed("https://ex.com/rss", keywords="sensex", today_only=True)
    assert out.splitlines()[0] == "OK feed Markets · 1/2 items · keywords sensex · today"
    assert out.splitlines()[1].startswith("1. Sensex jumps 600 points | ")
    assert len(out) < 200
