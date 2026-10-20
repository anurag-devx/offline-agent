"""Workspace: the only folder agents' file tools can touch. Browse, preview websites, upload, download."""
import io
import re
import zipfile
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from engine import audit
from engine.config import WORKSPACE

st.title("📁 Workspace")
st.caption(f"Agents can read and write only inside `{WORKSPACE}`.")

files = sorted(p for p in WORKSPACE.rglob("*") if p.is_file())
rel = [str(p.relative_to(WORKSPACE)) for p in files]

left, right = st.columns([1, 3])
with left:
    up = st.file_uploader("Add files for agents to use", accept_multiple_files=True)
    if up and st.button("Save uploads"):
        for f in up:
            name = Path(f.name).name  # never trust a path from the browser
            (WORKSPACE / name).write_bytes(f.getvalue())
            audit.log("workspace_upload", file=name)
        st.rerun()
    if files:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for p, r in zip(files, rel):
                z.write(p, r)
        st.download_button("⬇ Download workspace (.zip)", buf.getvalue(), "workspace.zip")


def inline_assets(html, folder):
    """Put local CSS/JS files into the HTML so the preview below can show the full page."""
    def css(m):
        p = folder / m.group(1)
        return f"<style>{p.read_text(errors='replace')}</style>" if p.is_file() else m.group(0)

    def js(m):
        p = folder / m.group(1)
        return f"<script>{p.read_text(errors='replace')}</script>" if p.is_file() else m.group(0)

    html = re.sub(r'<link[^>]+href="(?!https?:)([^"]+\.css)"[^>]*>', css, html)
    return re.sub(r'<script[^>]+src="(?!https?:)([^"]+\.js)"[^>]*>\s*</script>', js, html)


with right:
    if not files:
        st.info("The workspace is empty.")
    else:
        pick = st.selectbox("File", rel)
        path = WORKSPACE / pick
        if path.suffix.lower() in (".html", ".htm"):
            view = st.radio("View", ["Website preview", "Source"], horizontal=True)
            text = path.read_text(errors="replace")
            if view == "Website preview":
                components.html(inline_assets(text, path.parent), height=650, scrolling=True)
                st.caption(f"Full browser view: open `{path}` in your browser.")
            else:
                st.code(text, language="html")
        elif path.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".svg"):
            st.image(str(path))
        else:
            lang = {".py": "python", ".css": "css", ".js": "javascript", ".json": "json",
                    ".md": "markdown", ".yaml": "yaml"}.get(path.suffix.lower())
            st.code(path.read_text(errors="replace")[:50000], language=lang)
