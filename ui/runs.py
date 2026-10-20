"""Runs: every agent run, live. How many are running, their status, and the full record."""
import streamlit as st

from engine.audit import read_activity
from engine.runs import get_manager
from ui.common import STATUS, fmt_secs, live_run

mgr = get_manager()
st.title("📊 Runs")
any_active = any(r.active for r in mgr.runs.values())


@st.fragment(run_every=2 if any_active else None)
def overview():
    c = mgr.counts()
    m = st.columns(5)
    m[0].metric("🔄 Running", c.get("running", 0) + c.get("verifying", 0))
    m[1].metric("✋ Waiting for you", c.get("waiting_approval", 0) + c.get("waiting_input", 0))
    m[2].metric("✅ Completed", c.get("completed", 0))
    m[3].metric("❌ Failed / stopped", c.get("failed", 0) + c.get("stopped", 0) + c.get("interrupted", 0))
    m[4].metric("Total", len(mgr.runs))
    rows = [{
        "Status": STATUS.get(r.status, r.status), "Agent": r.agent, "Model": r.model,
        "Task": r.task[:80], "Steps": r.steps, "Tools": r.tool_calls, "Files": r.file_changes,
        "Web": r.network_requests,
        "Tokens": r.prompt_tokens + r.output_tokens, "Time": fmt_secs(r.duration()),
        "Started": r.started.replace("T", " "), "ID": r.id,
    } for r in mgr.list()]
    if rows:
        st.dataframe(rows, hide_index=True)
    else:
        st.info("No runs yet. Start one from the Studio's Run tab.")


tab_runs, tab_log = st.tabs(["Runs", "Activity log"])
with tab_runs:
    overview()
    runs = mgr.list()
    if runs:
        st.divider()
        rid = st.selectbox("Open a run", [r.id for r in runs],
                           format_func=lambda i: f"{i} · {mgr.runs[i].agent} · {mgr.runs[i].task[:60]}")
        live_run(rid, key="runs")
        st.caption(f"Recorded in `runs/{rid}/` (agent.yaml, meta.json, events.jsonl).")

with tab_log:
    st.caption("Everything that happened: agents saved/generated, runs, approvals, model changes. "
               "Stored in `logs/activity.jsonl`.")
    log = read_activity()
    if log:
        st.dataframe([{"Time": e.get("time", "").replace("T", " "), "Action": e.get("action"),
                       "Details": {k: v for k, v in e.items() if k not in ("time", "action")}} for e in log],
                     hide_index=True)
    else:
        st.info("Nothing logged yet.")
