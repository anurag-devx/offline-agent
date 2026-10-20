"""
app.py: Offline Agent Studio.

  streamlit run app.py

Pages live in ui/. Streamlit reruns a page's script on every click;
st.session_state keeps values between reruns. Runs keep going in background threads
(engine/runs.py), so you can switch pages while agents work.
"""
import streamlit as st

from engine import llm
from engine.runs import get_manager

st.set_page_config(page_title="Offline Agent Studio", page_icon="🤖", layout="wide")

pages = st.navigation([
    st.Page("ui/studio.py", title="Studio", icon="🛠", default=True),
    st.Page("ui/runs.py", title="Runs", icon="📊"),
    st.Page("ui/workspace.py", title="Workspace", icon="📁"),
    st.Page("ui/memory.py", title="Memory", icon="🧠"),
    st.Page("ui/models.py", title="Models", icon="🧠"),
    st.Page("ui/settings.py", title="Settings", icon="⚙️"),
])


@st.fragment(run_every=3)
def status_panel():
    ok = llm.is_running()
    st.markdown("Ollama: 🟢 running" if ok else "Ollama: 🔴 not running")
    c = get_manager().counts()
    st.markdown(f"🔄 Running: **{c.get('running', 0)}**  \n"
                f"🔍 Verifying: **{c.get('verifying', 0)}**  \n"
                f"✋ Waiting for you: **{c.get('waiting_approval', 0) + c.get('waiting_input', 0)}**  \n"
                f"✅ Completed: **{c.get('completed', 0)}**")


with st.sidebar:
    st.title("🤖 Offline Agent Studio")
    status_panel()

pages.run()
