"""
engine/telegram.py: say it short. Helpers for the "Telegram style" speed features.

    Morse          tools answer in compact one-liners
    Page Turner    long text comes one page at a time ("+N more chars, offset=...")
    Slim Schemas   tool descriptions sent in short form
    Fade Out       old tool results shrink to a one-line receipt
Every token costs time on a laptop: the model re-reads everything we send, on every call.
"""
import re


def page(text, offset=0, limit=4000, what="text"):
    """Page Turner: one page of a long text, with a footer saying how to get the rest."""
    text = str(text)
    offset = max(0, int(offset or 0))
    limit = max(200, int(limit or 4000))
    chunk = text[offset:offset + limit]
    rest = len(text) - (offset + len(chunk))
    if offset >= len(text) and text:
        return f"(end of {what}: {len(text)} chars total)"
    footer = f"\n+{rest} more chars. Next page: offset={offset + len(chunk)}" if rest > 0 else ""
    return chunk + footer


def first_sentence(text, max_len=140):
    """Slim Schemas: 'Move ALL matching files ... in one step. Use this instead ...' -> first sentence."""
    text = re.sub(r"\s+", " ", str(text)).strip()
    m = re.match(r"(.+?[.!?])(\s|$)", text)
    s = m.group(1) if m else text
    return s if len(s) <= max_len else s[:max_len - 1] + "…"


def slim_schema(schema):
    """A smaller copy of a tool schema: short description, short argument notes."""
    fn = schema["function"]
    props = {k: {**v, "description": first_sentence(v.get("description", ""), 60)}
             for k, v in fn["parameters"]["properties"].items()}
    return {"type": "function", "function": {
        "name": fn["name"], "description": first_sentence(fn["description"]),
        "parameters": {**fn["parameters"], "properties": props}}}


def receipt(result, max_len=160):
    """Fade Out: a tool result the model already used, shrunk to its first line."""
    first = str(result).strip().splitlines()[0] if str(result).strip() else ""
    return (first[:max_len] + (" …" if len(first) > max_len or "\n" in str(result).strip() else "")
            + " [faded: details in notes/run log]")


def tokens(text):
    """Rough token count (about 4 characters per token), for the Token Meter."""
    return (len(text) + 3) // 4
