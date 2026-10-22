"""
Internet tools, locked to the agent's allowed domains.

- Other sites are blocked, or (if the policy says "ask") you're asked per new site.
- Every request, allowed or blocked, is recorded in the run log.
- Redirects to a site that isn't allowed are blocked before they happen.
"""
import ssl
import urllib.parse
import urllib.request
from html.parser import HTMLParser

from ..context import get_context
from ..telegram import page
from ..tools import tool

MAX_BYTES = 2_000_000
MAX_TEXT = 12000
SEARCH_HOST = "html.duckduckgo.com"


def domain_allowed(host, allowed):
    """True if host is one of the allowed domains or a subdomain of one."""
    host = (host or "").lower()
    for d in allowed:
        d = d.lower().strip().removeprefix("https://").removeprefix("http://").split("/")[0]
        d = d.removeprefix("*.")
        if d and (host == d or host.endswith("." + d)):
            return True
    return False


def _ssl_context():
    """Verify HTTPS certificates with certifi's trusted list. (python.org Python on macOS ships
    without one, which causes CERTIFICATE_VERIFY_FAILED.) Verification is never turned off."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


class _RedirectGuard(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed):
        self.allowed = allowed

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        host = urllib.parse.urlparse(newurl).hostname
        if not domain_allowed(host, self.allowed):
            raise PermissionError(f"Blocked a redirect to {host}, which is not an allowed domain.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def http_get(url, extra_allowed=()):
    """GET a URL if its domain is allowed. Returns (text, content_type)."""
    ctx = get_context()
    policy = ctx.config.permissions.internet
    allowed = list(policy.domains) + ctx.state["granted_domains"] + list(extra_allowed)
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Only http:// and https:// links are supported.")
    host = (parsed.hostname or "").lower()
    ok = domain_allowed(host, allowed)
    if not ok and policy.other_domains == "ask":
        ok = ctx.approve("open_website", {"site": host, "url": url})
        if ok:
            ctx.state["granted_domains"].append(host)
    ctx.record("network", url=url, host=host, allowed=ok)
    if not ok:
        raise PermissionError(
            f"{host} is not an allowed site. Allowed: {', '.join(allowed) or 'none'}.")
    opener = urllib.request.build_opener(_RedirectGuard(allowed),
                                         urllib.request.HTTPSHandler(context=_ssl_context()))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (offline-agent)"})
    with opener.open(req, timeout=20) as resp:
        data = resp.read(MAX_BYTES)
        charset = resp.headers.get_content_charset() or "utf-8"
        return data.decode(charset, errors="replace"), resp.headers.get_content_type()


class _TextExtractor(HTMLParser):
    """Turn HTML into readable text, skipping scripts and styles."""
    SKIP = {"script", "style", "noscript", "svg", "head"}
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "tr", "section", "article"}

    def __init__(self):
        super().__init__()
        self.parts, self.skip, self.title, self._in_title = [], 0, "", False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        if tag == "title":
            self._in_title = True
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self.skip and data.strip():
            self.parts.append(data.strip() + " ")

    def text(self):
        lines = [line.strip() for line in "".join(self.parts).splitlines()]
        return "\n".join(line for line in lines if line)


@tool("internet.read", safety='Allowed sites only; redirects to other sites are blocked; every request is logged. Long pages come in pages.', example='Title: Ollama\n(first 4000 characters)\n+8200 more chars. Next page: offset=4000')
def fetch_url(url: str, offset: int = 0, limit: int = 4000):
    """Read a web page as plain text, one page at a time. Only the agent's allowed sites.

    Args:
        url: Full address, e.g. "https://en.wikipedia.org/wiki/Python_(programming_language)"
        offset: Start at this character (from the previous page's "Next page" hint)
        limit: Characters per page (default 4000)
    """
    body, ctype = http_get(url)
    if "html" in ctype:
        parser = _TextExtractor()
        parser.feed(body)
        body = (f"Title: {parser.title.strip()}\n" if parser.title.strip() else "") + parser.text()
    return page(body, offset, min(int(limit), MAX_TEXT), "page")


class _SearchParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.results, self._href, self._text = [], None, ""

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a" and "result__a" in (a.get("class") or ""):
            self._href, self._text = a.get("href", ""), ""

    def handle_data(self, data):
        if self._href is not None:
            self._text += data

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            href = self._href
            q = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
            href = q.get("uddg", [href])[0]  # DuckDuckGo wraps the real link
            self.results.append((self._text.strip(), href))
            self._href = None


@tool("internet.search", safety='Your search words are sent to DuckDuckGo. Reading a result needs Read web pages + an allowed site.', example='OK 8 results\n1. Ollama | https://ollama.com')
def web_search(query: str):
    """Search the web (DuckDuckGo) and return the top results as title + link.
    Your query is sent to DuckDuckGo. To read a result, use fetch_url (allowed sites only).

    Args:
        query: What to search for
    """
    url = f"https://{SEARCH_HOST}/html/?q={urllib.parse.quote(query)}"
    body, _ = http_get(url, extra_allowed=[SEARCH_HOST])
    parser = _SearchParser()
    parser.feed(body)
    if not parser.results:
        return "OK no results"
    return f"OK {len(parser.results[:8])} results\n" + "\n".join(
        f"{i}. {t[:90]} | {h}" for i, (t, h) in enumerate(parser.results[:8], 1))
