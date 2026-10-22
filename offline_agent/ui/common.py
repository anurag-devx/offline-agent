"""Shared UI pieces: how runs and events are drawn, approvals/questions, file-change log."""
import csv
import io
import json

import streamlit as st

from offline_agent.engine.ledger import Ledger
from offline_agent.engine.runs import get_manager
from offline_agent.engine.speed import summarize

STATUS = {
    "running": "🔄 running", "waiting_approval": "✋ needs your OK", "waiting_input": "💬 needs your answer", "verifying": "🔍 verifying",
    "completed": "✅ completed", "failed": "❌ failed", "stopped": "⏹ stopped", "interrupted": "⚠️ interrupted",
}
OP_LABEL = {"move": "moved", "create_folder": "created folder", "create_file": "created file",
            "modify": "modified", "delete": "sent to Trash"}


def fmt_secs(s):
    s = int(s)
    return f"{s // 60}m {s % 60}s" if s >= 60 else f"{s}s"


def _args(a):
    return json.dumps(a, ensure_ascii=False)[:400]


def render_event(e):
    t = e["type"]
    if t == "user":
        if e.get("auto"):
            st.markdown(f"🔁 **Sent back to the agent:** {e['content']}")
        else:
            st.markdown(f"**🧑 You:** {e['content']}")
    elif t == "warning":
        st.warning(e["content"])
    elif t == "plan":
        st.markdown("📋 **Plan:** " + " → ".join(f"{i}. {x}" for i, x in enumerate(e["steps"], 1)))
    elif t == "rule":
        st.markdown("📐 **Rule written by the model:**")
        st.code(e["text"], language=None)
    elif t == "continued":
        st.caption(f"🗣 Full Voice: the answer was long, so it was written in {e['parts']} parts and joined.")
    elif t == "nudge":
        st.caption(f"🔔 Reminded the agent: {e['content']}")
    elif t == "compacted":
        st.caption(f"🗜 Dropped {e['dropped']} old messages from finished steps (their facts are in the notes).")
    elif t == "ledger":
        return
    elif t == "verify_start":
        st.markdown(f"🔍 **Verifying (round {e['attempt']})…**")
    elif t == "verify_step":
        st.caption(f"🔍 verifier checked with **{e['name']}** `{_args(e['args'])}`")
    elif t == "verification":
        if e["complete"]:
            st.success(f"🔍 Verified complete: {e['reason']}")
        else:
            st.error(f"🔍 Not complete: {e['reason']}  \nMissing: {e['missing']}")
    elif t == "model_call":
        what = {"plan": "planned the job", "rule": "wrote the rule",
                "continue": "continued the answer"}.get(e.get("purpose"), f"step {e['step']}")
        detail = (f" · load {e['load_s']}s · read {e['prompt_tokens']} tok in {e['read_s']}s"
                  f" · write {e['output_tokens']} tok in {e['write_s']}s") if "read_s" in e else \
            f" ({e['prompt_tokens']} in / {e['output_tokens']} out tokens)"
        st.caption(f"🧠 Model {what} in {e['seconds']}s{detail}")
        if e.get("thinking"):
            st.caption("💭 " + e["thinking"][:600].replace("\n", " ") + ("…" if len(e["thinking"]) > 600 else ""))
    elif t == "tool_call":
        st.markdown(f"🔧 **{e['name']}** `{_args(e['args'])}`")
    elif t == "approval_needed":
        st.markdown(f"✋ *Asked you to approve* **{e['name']}**")
    elif t == "approval":
        st.markdown(("👍 **Approved**" + (" (all for this run)" if e.get("all") else ""))
                    if e["approved"] else "🚫 **Denied**")
    elif t == "question":
        st.markdown(f"💬 **Agent asked:** {e['question']}")
    elif t == "answer_given":
        st.markdown(f"🧑 **You answered:** {e['answer']}")
    elif t == "folder_granted":
        st.caption(f"📂 Access granted for this run: {e['folder']}")
    elif t == "file_op":
        detail = f"{e.get('src', '')} → {e['dst']}" if e["op"] == "move" else (e.get("dst") or e.get("src"))
        st.caption(f"📁 {OP_LABEL.get(e['op'], e['op'])}: {detail}")
    elif t == "recalled":
        st.caption("🧠 Recalled from memory: " + " · ".join(f"#{i['id']} {i['text'][:60]}" for i in e["items"]))
    elif t == "memory_op":
        what = {"add": "remembered", "delete": "forgot", "summary": "saved run summary as"}.get(e["op"], e["op"])
        st.caption(f"🧠 {what} note #{e['id']}" + (f": {e['text']}" if e.get("text") else ""))
    elif t == "email_op":
        st.caption(f"✉️ moved email {e['uid']}: {e['from_folder']} → {e['to_folder']}")
    elif t == "network":
        st.caption(f"🌐 {'allowed' if e['allowed'] else '**BLOCKED**'} → {e['url'][:200]}")
    elif t == "tool_result":
        st.code(str(e["result"])[:1500], language=None)
    elif t == "answer":
        st.markdown(f"**🤖 Agent:**\n\n{e['content']}")
    elif t == "undo":
        st.markdown("↩️ **Undo:** " + "; ".join(f"{r['result']}: {r['file']}" for r in e["results"][:20]))
    elif t == "error":
        st.error(e["content"])
    elif t == "stopped":
        st.warning(e["content"])


def _pending(run, key):
    mgr, p = get_manager(), run.pending
    if p["kind"] == "question":
        st.info(f"💬 **The agent asks:** {p['question']}")
        with st.form(f"ans{key}", clear_on_submit=True):
            text = st.text_input("Your answer")
            if st.form_submit_button("Send answer", type="primary") and text.strip():
                mgr.answer(run.id, text.strip())
                st.rerun()
        return
    name, args = p["name"], p["args"]
    if name == "grant_folder_access":
        st.warning(f"📂 The agent wants access to **{args['folder']}** ({args.get('why', '')}). "
                   "Only for this run.")
    elif name == "open_website":
        st.warning(f"🌐 The agent wants to open **{args['site']}**:  \n`{args['url'][:300]}`")
    else:
        st.warning(f"✋ The agent wants to run **{name}** with:")
        st.code(json.dumps(args, indent=2, ensure_ascii=False)[:3000], language="json")
    one_off = name in ("grant_folder_access", "open_website", "create_folder", "apply_rule")
    cols = st.columns([1, 2, 1, 2] if not one_off else [1, 1, 4])
    if cols[0].button("👍 Approve", key=f"ok{key}", type="primary"):
        mgr.decide(run.id, "yes")
        st.rerun()
    if not one_off and cols[1].button(f"✅ Approve all `{name}` this run", key=f"all{key}"):
        mgr.decide(run.id, "all")
        st.rerun()
    if cols[2 if not one_off else 1].button("🚫 Deny", key=f"no{key}"):
        mgr.decide(run.id, "no")
        st.rerun()


def _file_changes(run, key):
    ops = [e for e in run.events if e["type"] == "file_op"]
    if not ops:
        return
    rows = [{"Time": e["time"][11:], "Action": OP_LABEL.get(e["op"], e["op"]),
             "From": e.get("src", ""), "To": e.get("dst", "")} for e in ops]
    with st.expander(f"📁 Files changed ({len(rows)})", expanded=not run.active):
        st.dataframe(rows, hide_index=True)
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=["Time", "Action", "From", "To"])
        w.writeheader()
        w.writerows(rows)
        a, b = st.columns(2)
        a.download_button("⬇ File log (CSV)", buf.getvalue(), f"file-changes-{run.id}.csv", key=f"csv{key}")
        if not run.active and not run.undone:
            if b.button("↩️ Undo file changes", key=f"undo{key}",
                        help="Moves files back and removes empty folders this run created."):
                get_manager().undo_file_changes(run.id)
                st.rerun()
        elif run.undone:
            b.caption("Undo already done.")


def _speed(run, key):
    sp = summarize(run)
    if not sp["calls"]:
        return
    with st.expander(f"⚡ Speed · {sp['total_s']:.0f}s total · {sp['model_s']:.0f}s in the model · "
                     f"{sp['calls']} model calls", expanded=False):
        import pandas as pd
        parts = {k: v for k, v in sp["parts"].items() if v > 0}
        if parts:
            st.bar_chart(pd.DataFrame({"seconds": parts}), horizontal=True, y_label="", x_label="seconds")
        a, b, c = st.columns(3)
        a.metric("Reading speed", f"{sp['read_tps']:.0f} tok/s", help="How fast the model reads the prompt")
        b.metric("Writing speed", f"{sp['write_tps']:.0f} tok/s", help="How fast the model writes its reply")
        c.metric("Tokens", f"{sp['prompt_tokens']:,} in · {sp['output_tokens']:,} out")
        if sp["sent"]:
            names = {"instructions": "Instructions", "tools": "Tool descriptions", "history": "History",
                     "notes": "Job notes"}
            st.markdown("**📡 Token Meter**: what the model had to read, over all calls (estimated)")
            st.bar_chart(pd.DataFrame({"tokens": {names.get(k, k): v for k, v in sp["sent"].items() if v}}),
                         horizontal=True, y_label="", x_label="tokens")
            feats = {"slim_schemas": "Slim Schemas", "fade_out": "Fade Out", "ghost_echo": "Ghost Chatter + No Echo"}
            saved = " · ".join(f"{feats.get(k, k)} {v:,}" for k, v in sp["saved"].items() if v)
            if saved:
                st.caption(f"✂️ Saved by Telegram style: about {sp['saved_pct']}% · {saved} tokens")
        for tip in sp["tips"]:
            st.markdown(f"- 💡 {tip}")
        st.dataframe(sp["per_call"], hide_index=True)


def render_run(run, key):
    mgr = get_manager()
    badge = " · 🔍 verified" if run.verified else (f" · verification round {run.attempts}" if run.attempts else "")
    st.markdown(f"**{run.agent}** · `{run.model}` · {STATUS.get(run.status, run.status)}{badge}")
    m = st.columns(6)
    m[0].metric("Steps", run.steps)
    m[1].metric("Tool calls", run.tool_calls)
    m[2].metric("Changes", run.file_changes + getattr(run, "email_changes", 0),
                help="Files changed + emails moved")
    m[3].metric("Web requests", run.network_requests)
    m[4].metric("Tokens", f"{run.prompt_tokens + run.output_tokens:,}")
    m[5].metric("Time", fmt_secs(run.duration()))

    if run.pending:
        _pending(run, key)
    if run.active and st.button("⏹ Stop run", key=f"stop{key}"):
        mgr.stop(run.id)

    if run.ledger:
        led = Ledger.from_dict(run.ledger)
        closed = sum(x.status != "todo" for x in led.steps)
        with st.expander(f"📋 Job notes · {closed}/{len(led.steps)} steps", expanded=True):
            st.markdown(led.to_markdown({"file changes": run.file_changes, "tool calls": run.tool_calls}))
            st.caption(f"Saved as runs/{run.id}/notes.md")

    with st.container(height=480):
        for e in run.events:
            render_event(e)

    _file_changes(run, key)
    _speed(run, key)

    if mgr.can_continue(run.id):
        with st.form(f"follow{key}", clear_on_submit=True):
            msg = st.text_input("Follow-up message (the agent remembers this run)")
            if st.form_submit_button("Send") and msg.strip():
                mgr.send(run.id, msg)
                st.rerun()
    elif not run.active:
        st.caption("This run is from an earlier session, so it can't take new messages.")

    st.download_button("⬇ Download full run log", json.dumps(
        {"run": {k: v for k, v in run.__dict__.items() if k != "events"}, "events": run.events},
        indent=2, default=str), file_name=f"run-{run.id}.json", key=f"dl{key}")


def live_run(run_id, key):
    """Show a run and refresh it every 1.5s while it's working."""
    mgr = get_manager()
    was_active = mgr.runs[run_id].active

    @st.fragment(run_every=1.5 if was_active else None)
    def view():
        run = mgr.runs[run_id]
        render_run(run, key)
        if was_active and not run.active:
            st.rerun()  # finished: redraw once so polling stops

    view()
