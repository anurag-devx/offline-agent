"""Test Bench: run agents one by one, check results in code, and compare settings and models."""
import itertools
import json

import pandas as pd
import streamlit as st

from offline_agent.engine import llm
from offline_agent.engine.bench import (available_agents, case_for, compare, current_job, past_reports,
                                        report_markdown, start_job)
from offline_agent.engine.runs import get_manager

st.title("🧪 Test Bench")
st.caption("Runs agents one by one on a test task, checks the result in code, and compares settings or models. "
           "Each test runs in its own sandbox folder (workspace/_bench/), so your files are never touched. "
           "Email tests are dry: the rule is checked, nothing is moved.")

agents = available_agents()
job = current_job()

if not job or job.done:
    with st.form("bench"):
        default = [a for a in agents if case_for(a, agents[a]).get("needs") is None
                   and not case_for(a, agents[a]).get("smoke")]
        chosen = st.multiselect("Agents", list(agents), default)
        models = st.multiselect("Models (empty = each agent's own model)", llm.list_models())
        c1, c2, c5 = st.columns(3)
        telegram = c1.multiselect("Telegram style", ["on", "off"], ["on"])
        voice = c2.multiselect("Full Voice", ["on", "off"], ["on"])
        notes = c5.multiselect("Job notes", ["on", "off"], [], help="Empty = as each agent is saved")
        c3, c4 = st.columns(2)
        internet = c3.checkbox("Include internet tests (News Collector, Web Researcher)")
        email = c4.checkbox("Include email tests (dry: nothing is moved)")
        variants = [" + ".join(x for x in (f"Telegram {t}" if t else "", f"Full Voice {v}" if v else "",
                                           f"Job notes {n}" if n else "") if x)
                    for t, v, n in itertools.product(telegram or [""], voice or [""], notes or [""])]
        total = len(chosen) * max(1, len(models)) * max(1, len(variants))
        st.caption(f"{total} test runs. Local models are slow: expect about 1–5 minutes per run.")
        if st.form_submit_button("▶ Run bench", type="primary", disabled=not chosen):
            start_job(get_manager(), agents=chosen, models=models or [""], variants=variants or [""],
                      internet=internet, email=email)
            st.rerun()


def show(results, live=False):
    if not results:
        return
    summary = compare(results)
    if summary:
        st.subheader("Comparison")
        st.dataframe([{"Model": s["model"], "Variant": s["variant"], "Passed": s["passed"],
                       "Avg time (s)": s["avg_seconds"], "Avg model time (s)": s["avg_model_s"],
                       "Avg calls": s["avg_calls"], "Avg tokens in": s["avg_tokens_in"],
                       "Avg tokens out": s["avg_tokens_out"], "Saved by Telegram": f"{s['avg_saved_pct']:.0f}%"}
                      for s in summary], hide_index=True)
        if len(summary) > 1:
            st.bar_chart(pd.DataFrame({"avg seconds": {f"{s['model']} · {s['variant']}": s["avg_seconds"]
                                                       for s in summary}}), horizontal=True, x_label="seconds",
                         y_label="")
            best = summary[0]
            st.success(f"Best: **{best['model']} · {best['variant']}**: {best['passed']} passed, "
                       f"{best['avg_seconds']}s per test on average.")
    st.subheader("Every test")
    st.dataframe([{"Agent": r["agent"], "Model": r["model"], "Variant": r["variant"],
                   "Result": "⏭ skipped" if r.get("passed") is None else ("✅ pass" if r["passed"] else "❌ fail"),
                   "Time (s)": r.get("seconds", ""), "Calls": r.get("calls", ""),
                   "Failed checks": "; ".join(c["check"] + (f" ({c['detail']})" if c["detail"] else "")
                                              for c in r.get("checks", []) if not c["ok"]) or r.get("why", ""),
                   "Run": r.get("run_id", "")} for r in results], hide_index=True)
    if not live:
        st.caption("Open any run on the Runs page (its task starts with [bench]) to see every step.")


if job and not job.done:
    @st.fragment(run_every=2)
    def progress():
        j = current_job()
        st.progress(len(j.results) / max(1, j.total), text=f"Running {j.current or '…'}")
        if st.button("⏹ Stop bench"):
            j.stop()
        show(j.results, live=True)
        if j.done:
            st.rerun()
    progress()
elif job and job.done:
    st.subheader(f"Latest bench: {job.id}")
    show(job.results)
    st.download_button("⬇ Report (Markdown)", report_markdown({"id": job.id, "results": job.results,
                                                                "summary": job.summary()}),
                       f"bench-{job.id}.md")

reports = past_reports()
if reports:
    with st.expander(f"Earlier benches ({len(reports)})"):
        pick = st.selectbox("Report", reports, format_func=lambda p: p.stem)
        data = json.loads(pick.read_text(encoding="utf-8"))
        show(data["results"])
