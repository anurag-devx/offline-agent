"""Settings: email account for email agents, and what data leaves your computer."""
import streamlit as st

from offline_agent.engine import audit
from offline_agent.engine.credentials import CRED_PATH, load_credentials, save_credentials

st.title("⚙️ Settings")

st.subheader("Email (IMAP)")
st.markdown(
    "For Gmail: turn on 2-Step Verification, then create an **app password** at "
    "[myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) "
    "and paste it below (not your normal password). You can revoke it there any time.")
creds = load_credentials()
e = creds.get("email") or {}
with st.form("email"):
    host = st.text_input("IMAP server", e.get("imap_host", "imap.gmail.com"))
    address = st.text_input("Email address", e.get("address", ""))
    saved = bool(e.get("password"))
    password = st.text_input("App password", "", type="password",
                             placeholder="saved: leave empty to keep it" if saved else "")
    if st.form_submit_button("Save"):
        creds["email"] = {"imap_host": host.strip(), "address": address.strip(),
                          "password": password.replace(" ", "") or e.get("password", "")}
        save_credentials(creds)
        audit.log("email_settings_saved", address=address.strip(), host=host.strip())
        st.success("Saved.")
st.caption(f"Stored on this computer only, in `{CRED_PATH}` (readable only by your user). "
           "Never inside the project folder, so it can't end up on GitHub.")

if st.button("Test connection"):
    try:
        from offline_agent.engine.toolkits.mail import _connect, list_folder_names
        conn = _connect()
        names = list_folder_names(conn)
        conn.logout()
        st.success(f"Connected. {len(names)} folders found.")
    except Exception as ex:
        st.error(f"Could not connect: {ex}")

st.divider()
st.subheader("What leaves your computer")
st.markdown("""
- **Your prompts and data never go to an AI company.** The model runs in Ollama on this machine.
- **Internet**: only agents with an internet permission, only to the sites you list (or approve
  during a run). Every request, allowed or blocked, is recorded. Redirects to other sites are blocked.
  Whatever is in a requested address (e.g. a search query) does reach that site, so use
  **Ask first** to review each request.
- **Email**: only between this computer and your mail server. No agent can send or delete email.
- **Files**: only the folders each agent lists, or ones you grant during a run. Credential folders
  (~/.ssh, ~/.aws, Keychains…) and this app's own code and records are always blocked.
  Delete goes to the Trash. Every file change is logged and moves can be undone.
- **Records**: runs in `runs/`, activity in `logs/`. Both stay on this computer.
""")
