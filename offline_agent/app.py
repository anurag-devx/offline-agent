"""
app.py: Offline Agent Studio.

  offline-agent studio        (or: streamlit run offline_agent/app.py)

Pages live in ui/. Streamlit reruns a page's script on every click;
st.session_state keeps values between reruns. Runs keep going in background threads
(engine/runs.py), so you can switch pages while agents work.
"""
import sys
from pathlib import Path

import streamlit as st

PKG = Path(__file__).resolve().parent
if str(PKG.parent) not in sys.path:  # `streamlit run offline_agent/app.py` from a checkout
    sys.path.insert(0, str(PKG.parent))

from offline_agent.engine import llm  # noqa: E402
from offline_agent.engine.runs import get_manager  # noqa: E402
from offline_agent.engine.scheduler import get_scheduler  # noqa: E402

st.set_page_config(page_title="Offline Agent Studio", page_icon="🤖", layout="wide")

pages = st.navigation([
    st.Page(str(PKG / "ui" / "studio.py"), title="Studio", icon="🛠", default=True),
    st.Page(str(PKG / "ui" / "runs.py"), title="Runs", icon="📊"),
    st.Page(str(PKG / "ui" / "catalog.py"), title="Catalog", icon="📖"),
    st.Page(str(PKG / "ui" / "workspace.py"), title="Workspace", icon="📁"),
    st.Page(str(PKG / "ui" / "memory.py"), title="Memory", icon="🧠"),
    st.Page(str(PKG / "ui" / "schedules.py"), title="Schedules", icon="⏰"),
    st.Page(str(PKG / "ui" / "bench.py"), title="Test Bench", icon="🧪"),
    st.Page(str(PKG / "ui" / "models.py"), title="Models", icon="🧩"),
    st.Page(str(PKG / "ui" / "settings.py"), title="Settings", icon="⚙️"),
])


get_scheduler(get_manager()).start()  # runs schedules while the app is open (no-op if already running)


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
