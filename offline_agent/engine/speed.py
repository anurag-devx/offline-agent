"""
engine/speed.py: where does the time go?

Every model call has three costs, all reported by Ollama:
    load    reading the model into memory (0 if it was already loaded)
    read    "prompt evaluation": the model reading everything we sent
    write   "generation": the model writing its reply, token by token
A run also spends time running tools (code) and waiting for you (approvals, questions).

summarize(run) adds it all up and turns it into tips, so optimizations get measured, not guessed.
"""


def _s(ns):
    return round((ns or 0) / 1e9, 2)


def timing(resp):
    """Speed numbers for one Ollama response (seconds, tokens, tokens/second)."""
    prompt_tokens, output_tokens = resp.prompt_eval_count or 0, resp.eval_count or 0
    load, read, write = _s(resp.load_duration), _s(resp.prompt_eval_duration), _s(resp.eval_duration)
    return {
        "load_s": load, "read_s": read, "write_s": write,
        "prompt_tokens": prompt_tokens, "output_tokens": output_tokens,
        "read_tps": round(prompt_tokens / read, 1) if read else 0.0,
        "write_tps": round(output_tokens / write, 1) if write else 0.0,
    }


def summarize(run):
    """Totals, shares and tips for a run."""
    calls = [e for e in run.events if e["type"] == "model_call"]
    tools = [e for e in run.events if e["type"] == "tool_result"]
    load = sum(e.get("load_s", 0) for e in calls)
    read = sum(e.get("read_s", 0) for e in calls)
    write = sum(e.get("write_s", 0) for e in calls)
    tool = sum(e.get("seconds", 0) for e in tools)
    wait = getattr(run, "wait_s", 0.0)
    verify = getattr(run, "verify_s", 0.0)
    model = load + read + write
    total = run.duration() or (model + tool + wait + verify)
    other = max(0.0, total - model - tool - wait - verify)
    prompt_tokens = sum(e.get("prompt_tokens", 0) for e in calls)
    output_tokens = sum(e.get("output_tokens", 0) for e in calls)
    parts = {"Model: loading": load, "Model: reading prompts": read, "Model: writing replies": write,
             "Verifier (model)": verify, "Tools (code)": tool, "Waiting for you": wait, "Other": other}
    tips = []
    if model:
        if load > 0.2 * model:
            tips.append(f"Loading the model took {load:.0f}s. Keep it loaded between runs "
                        "(Ollama keep_alive, or a run right after the last one).")
        if read >= max(write, load) and read > 2:
            tips.append(f"Reading prompts is the biggest model cost ({read:.0f}s for {prompt_tokens:,} tokens). "
                        "Send less: fewer tools, filters on tool output, smaller context.")
        if write > read and write > 2:
            tips.append(f"Writing replies is the biggest model cost ({write:.0f}s for {output_tokens:,} tokens). "
                        "Ask for shorter replies (telegram style, lower max reply tokens) or let code write the text.")
    sent, saved = {}, {}
    for e in calls:
        for k, v in (e.get("sent") or {}).items():
            sent[k] = sent.get(k, 0) + v
        for k, v in (e.get("saved") or {}).items():
            saved[k] = saved.get(k, 0) + v
    sent_total, saved_total = sum(sent.values()), sum(saved.values())
    if sent_total and sent.get("tools", 0) > 0.4 * sent_total:
        tips.append(f"Tool descriptions are {sent['tools'] / sent_total:.0%} of what each call sends. "
                    "Turn off permissions this agent doesn't need: fewer tools, less to read.")
    if sent_total and sent.get("history", 0) > 0.5 * sent_total:
        tips.append(f"Conversation history is {sent['history'] / sent_total:.0%} of what we send. "
                    "Turn on Job notes (finished steps get dropped) or start a new run for new tasks.")
    if len(calls) >= 5:
        tips.append(f"{len(calls)} model calls. Rule mode or reusing a verified plan can cut this to 1 or 0.")
    if total and wait > 0.3 * total:
        tips.append(f"{wait:.0f}s waiting for your approval. 'Approve all' or 'Allow' for trusted actions saves this.")
    if total and tool > 0.5 * total and tool > 5:
        tips.append(f"Tools took {tool:.0f}s. Check slow web requests or large folders.")
    return {"total_s": round(total, 1), "model_s": round(model, 1), "calls": len(calls),
            "prompt_tokens": prompt_tokens, "output_tokens": output_tokens,
            "read_tps": round(prompt_tokens / read, 1) if read else 0.0,
            "write_tps": round(output_tokens / write, 1) if write else 0.0,
            "parts": {k: round(v, 1) for k, v in parts.items()}, "tips": tips,
            "sent": sent, "saved": saved,
            "saved_pct": round(saved_total / (sent_total + saved_total) * 100) if sent_total + saved_total else 0,
            "per_call": [{"#": i, "what": e.get("purpose") or f"step {e.get('step')}",
                          "load s": e.get("load_s", 0), "read s": e.get("read_s", 0),
                          "read tokens": e.get("prompt_tokens", 0), "read tok/s": e.get("read_tps", 0),
                          "write s": e.get("write_s", 0), "write tokens": e.get("output_tokens", 0),
                          "write tok/s": e.get("write_tps", 0)} for i, e in enumerate(calls, 1)]}
