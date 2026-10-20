"""Schedules: run saved agents automatically, every day at a time or every N minutes."""
from datetime import time as dtime

import streamlit as st

from engine.config import AGENTS_DIR, ROOT, list_configs
from engine.runs import get_manager
from engine.scheduler import add_schedule, delete_schedule, get_scheduler, load_schedules, update_schedule
from ui.common import STATUS

st.title("⏰ Schedules")
sched = get_scheduler(get_manager())
st.caption(f"Scheduler: **{sched.status()}**. Schedules run while this app is open, or without it via "
           "`python run.py --scheduler`.")
st.info("Nobody may be watching a scheduled run. In the app, *Ask first* actions wait on the Runs page; "
        "in the headless runner they're denied. Rule mode or *Allow* settings work best.", icon="ℹ️")

agents = list_configs(AGENTS_DIR)
with st.expander("➕ New schedule", expanded=not load_schedules()):
    if not agents:
        st.warning("Save an agent first (Studio → Design → Save). Schedules run saved agents.")
    else:
        with st.form("new_schedule", clear_on_submit=True):
            agent = st.selectbox("Agent", list(agents))
            task = st.text_area("Task", placeholder="Collect today's stock market headlines and save them.")
            kind = st.radio("When", ["daily", "weekdays", "interval"], horizontal=True,
                            format_func={"daily": "Every day", "weekdays": "Chosen days",
                                         "interval": "Every N minutes"}.get)
            c1, c2 = st.columns(2)
            at = c1.time_input("At", dtime(9, 0), step=300)
            minutes = c2.number_input("Every N minutes", 5, 10080, 60, step=5)
            days = st.multiselect("Days (for 'Chosen days')", list(range(7)), [0, 1, 2, 3, 4],
                                  format_func=lambda d: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][d])
            name = st.text_input("Name", placeholder="Morning news")
            if st.form_submit_button("Save schedule", type="primary"):
                if not task.strip():
                    st.error("Give the schedule a task.")
                else:
                    path = str(agents[agent].relative_to(ROOT))
                    add_schedule(name or f"{agent} schedule", path, task,
                                 kind="interval" if kind == "interval" else "daily", time_=at.strftime("%H:%M"),
                                 weekdays=days if kind == "weekdays" else (), every_minutes=minutes)
                    st.rerun()

items = load_schedules()
if items:
    mgr = get_manager()
    st.dataframe([{"Name": s.name, "Agent": s.agent, "When": s.describe(), "Enabled": "✅" if s.enabled else "⏸",
                   "Next run": s.next_run.replace("T", " ") if s.enabled else "—",
                   "Last": (STATUS.get(mgr.runs[s.last_run_id].status, "") if s.last_run_id in mgr.runs
                            else s.last_result) or "never",
                   "Task": s.task[:60]} for s in items], hide_index=True)
    pick = st.selectbox("Schedule", [s.id for s in items], format_func=lambda i: next(s.name for s in items if s.id == i))
    s = next(x for x in items if x.id == pick)
    a, b, c = st.columns(3)
    if a.button("⏸ Pause" if s.enabled else "▶ Resume"):
        update_schedule(s.id, enabled=not s.enabled)
        st.rerun()
    if b.button("▶ Run now"):
        from engine.config import load_agent
        run = mgr.start(load_agent(ROOT / s.agent), s.task)
        update_schedule(s.id, last_run_id=run.id, last_result="started (manual)")
        st.success("Started. See the Runs page.")
    if c.button("🗑 Delete"):
        delete_schedule(s.id)
        st.rerun()
