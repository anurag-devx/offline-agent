"""Memory: everything agents remember, stored on this computer. View, search, add, edit, delete."""
import streamlit as st

from engine.memory import EMBED_MODEL, get_store

st.title("🧠 Memory")
store = get_store()
try:
    import ollama
    semantic = any(m.model.startswith(EMBED_MODEL) for m in ollama.list().models)
except Exception:
    semantic = False
st.caption(("🟢 Search by meaning (" + EMBED_MODEL + ")") if semantic else
           f"🟡 Keyword search only. For search by meaning run `ollama pull {EMBED_MODEL}`.")
st.caption("Notes are information for agents, never instructions. Stored in `memory/memory.db`.")

scopes = store.scopes()
if not scopes:
    st.info("No memories yet. Turn on Memory for an agent in Studio → Design.")
scope = st.selectbox("Agent memory", scopes or ["shared"],
                     format_func=lambda s: "🌐 shared" if s == "shared" else s)

with st.expander("➕ Add a note yourself"):
    with st.form("add_note", clear_on_submit=True):
        text = st.text_input("Note", placeholder="PDFs from Downloads go to ~/Downloads/all_pdf")
        if st.form_submit_button("Save") and text.strip():
            store.add(scope, text, kind="fact", run="manual")
            st.rerun()

query = st.text_input("Search", placeholder="what do you want to find?")
rows = store.search(scope, query, k=50, min_score=0.2) if query.strip() else store.rows(scope)
st.dataframe([{"#": r["id"], "Kind": r["kind"], "Saved": r["created"].replace("T", " "),
               "Note": r["text"], **({"Match": r["score"]} if "score" in r else {})} for r in rows],
             hide_index=True)

if rows:
    c1, c2 = st.columns(2)
    with c1.form("edit"):
        pick = st.selectbox("Edit note #", [r["id"] for r in rows])
        new = st.text_input("New text", next(r["text"] for r in rows if r["id"] == pick))
        if st.form_submit_button("Update"):
            store.update(pick, new)
            st.rerun()
    with c2.form("delete"):
        gone = st.selectbox("Delete note #", [r["id"] for r in rows])
        sure = st.checkbox("Yes, delete it")
        if st.form_submit_button("Delete") and sure:
            store.delete(gone)
            st.rerun()
