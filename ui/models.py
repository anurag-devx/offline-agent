"""Models: see what's installed, download new ones, and import .gguf files from your computer."""
import streamlit as st

from engine import llm, models

st.title("🧠 Models")
if not llm.is_running():
    st.error("Ollama is not running. Open the Ollama app, then reload.")
    st.stop()

tab_list, tab_pull, tab_import = st.tabs(["Installed", "Download", "Import from your computer"])

with tab_list:
    rows = models.installed()
    st.dataframe(rows, hide_index=True)
    st.caption("Agents need **tools** in capabilities. **thinking** = supports Thinking mode. "
               "**embedding** models can't chat.")
    with st.expander("Remove a model"):
        target = st.selectbox("Model", [r["name"] for r in rows], key="del_model")
        sure = st.checkbox(f"Yes, remove {target} from Ollama")
        if st.button("Remove", disabled=not sure):
            models.delete(target)
            st.success(f"Removed {target}.")
            st.rerun()

with tab_pull:
    st.markdown("Download from the [Ollama library](https://ollama.com/library), e.g. `qwen3:4b`, `llama3.2:3b`.")
    name = st.text_input("Model name", placeholder="qwen3:4b")
    if st.button("Download", disabled=not name.strip()):
        bar, label = st.progress(0.0), st.empty()
        try:
            for status, frac in models.pull(name.strip()):
                label.caption(status)
                if frac is not None:
                    bar.progress(min(frac, 1.0))
            st.success(f"{name} is ready.")
        except Exception as e:
            st.error(f"Download failed: {e}")

with tab_import:
    st.markdown(
        "Use model files already on this computer, for example a model you fine-tuned with **Unsloth** "
        "and exported with `model.save_pretrained_gguf(...)`. Ollama **copies** the file into its own "
        "storage; your original stays where it is (delete it afterwards to free space).")
    folder = st.text_input("Folder to search", "~/Downloads")
    if st.button("🔍 Find .gguf files"):
        try:
            st.session_state.gguf = models.find_gguf(folder)
        except Exception as e:
            st.error(str(e))
            st.session_state.gguf = []
    found = st.session_state.get("gguf")
    if found is not None:
        if not found:
            st.info("No .gguf files found there (looked 4 folders deep).")
        else:
            pick = st.selectbox("File", [f["path"] for f in found],
                                format_func=lambda p: f"{p}  ({next(f['size_gb'] for f in found if f['path'] == p)} GB)")
            default = pick.rsplit("/", 1)[-1].lower().removesuffix(".gguf").replace("_", "-")[:40]
            new_name = st.text_input("Name in Ollama", default)
            ok_name = models.valid_model_name(new_name)
            if not ok_name:
                st.caption("Use lowercase letters, numbers, - . _ and optionally :tag")
            if st.button("Import into Ollama", disabled=not ok_name):
                with st.spinner("Importing. Large files can take a few minutes..."):
                    ok, out = models.import_gguf(pick, new_name)
                (st.success if ok else st.error)(f"{'Imported as ' + new_name if ok else 'Import failed'}")
                st.code(out or "(no output)", language=None)
                if ok:
                    caps = llm.capabilities(new_name)
                    st.caption(f"Capabilities: {', '.join(caps) or 'unknown'}. "
                               + ("" if "tools" in caps else "No `tools`, so this model can chat but can't be an agent."))
