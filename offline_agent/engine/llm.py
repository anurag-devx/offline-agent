"""
engine/llm.py: the only file that talks to Ollama.

Everything else (agent loop, validation, UI) calls these functions.
To support another backend later (LM Studio, llama.cpp), you change this file only.
"""
from functools import lru_cache

import ollama


def is_running():
    """True if the Ollama server is reachable on this machine."""
    try:
        ollama.list()
        return True
    except Exception:
        return False


def list_models():
    """Names of installed chat models, e.g. ['qwen3.5:9b', 'gemma4:e4b']."""
    try:
        names = [m.model for m in ollama.list().models]
    except Exception:
        return []
    return [n for n in names if "embed" not in n]  # embedding models can't chat


@lru_cache(maxsize=None)
def capabilities(model):
    """What a model supports, e.g. ['completion', 'tools', 'thinking']. Empty if unknown."""
    try:
        info = ollama.show(model)
        return tuple(getattr(info, "capabilities", None) or [])
    except Exception:
        return ()


@lru_cache(maxsize=None)
def context_limit(model):
    """The longest context the model supports (from its metadata), or 0 if unknown."""
    try:
        info = getattr(ollama.show(model), "modelinfo", None) or {}
        return int(next((v for k, v in info.items() if k.endswith(".context_length")), 0))
    except Exception:
        return 0


def _options(model, temperature, think, num_ctx=None, num_predict=None):
    # num_ctx = how many tokens the model can see at once. Ollama's default is small and it
    # silently drops the START of longer conversations (your instructions!), so set it explicitly.
    opts = {"temperature": temperature}
    if num_ctx:
        opts["num_ctx"] = int(num_ctx)
    if num_predict:
        opts["num_predict"] = int(num_predict)  # max tokens in the reply ("telegram" cap)
    kwargs = {"options": opts}
    # Only reasoning models accept the `think` switch; others error if we send it.
    if "thinking" in capabilities(model):
        kwargs["think"] = think
        if think is False and str(model).startswith("gpt-oss"):
            kwargs["think"] = "low"  # gpt-oss can't switch reasoning off; "low" is its lightest level
    return kwargs


def chat(model, messages, tools=None, temperature=0.2, think=False, format=None, num_ctx=None,
         num_predict=None):
    """One call to the model. Returns the full response (may contain tool calls).
    format: a JSON schema to force structured output (planner, generator, verifier)."""
    kwargs = _options(model, temperature, think, num_ctx, num_predict)
    if format:
        kwargs["format"] = format
    resp = ollama.chat(model=model, messages=messages, tools=tools or None, **kwargs)
    msg = resp.message
    if (num_predict and getattr(resp, "done_reason", "") == "length" and not (msg.content or "").strip()
            and not msg.tool_calls):
        # The reply cap was used up by hidden reasoning (e.g. gpt-oss), leaving nothing.
        # Retry once without the cap rather than return an empty answer.
        kwargs["options"] = {k: v for k, v in kwargs["options"].items() if k != "num_predict"}
        resp = ollama.chat(model=model, messages=messages, tools=tools or None, **kwargs)
    if format and not (resp.message.content or "").strip():
        # Some reasoning models (gpt-oss) put the structured reply inside their reasoning.
        found = _json_in(getattr(resp.message, "thinking", None) or "")
        if found:
            resp = resp.model_copy(update={"message": resp.message.model_copy(update={"content": found})})
    return resp


def _json_in(text):
    """The last complete {...} block in a text, if it parses as JSON."""
    import json
    end = text.rfind("}")
    while end != -1:
        depth = 0
        for i in range(end, -1, -1):
            depth += {"}": 1, "{": -1}.get(text[i], 0)
            if depth == 0:
                try:
                    json.loads(text[i:end + 1])
                    return text[i:end + 1]
                except ValueError:
                    break
        end = text.rfind("}", 0, end)
    return ""


def chat_stream(model, messages, temperature=0.2, think=False):
    """Like chat(), but yields the reply text piece by piece. No tools."""
    stream = ollama.chat(model=model, messages=messages, stream=True,
                         **_options(model, temperature, think))
    for chunk in stream:
        yield chunk.message.content or ""
