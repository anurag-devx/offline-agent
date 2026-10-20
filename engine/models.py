"""
engine/models.py: manage the models on this computer.

    installed()      what Ollama has, with size and capabilities
    pull(name)       download a model from the Ollama library
    delete(name)     remove a model from Ollama
    find_gguf()      look for .gguf model files in a folder on your computer
    import_gguf()    copy a .gguf file (e.g. an Unsloth export) into Ollama
"""
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import ollama

from . import audit, llm

OLLAMA_CANDIDATES = ["/usr/local/bin/ollama", "/opt/homebrew/bin/ollama",
                     "/Applications/Ollama.app/Contents/Resources/ollama"]


def installed():
    rows = []
    for m in ollama.list().models:
        d = m.details
        rows.append({
            "name": m.model,
            "size_gb": round((m.size or 0) / 1e9, 2),
            "parameters": getattr(d, "parameter_size", "") if d else "",
            "quantization": getattr(d, "quantization_level", "") if d else "",
            "family": getattr(d, "family", "") if d else "",
            "capabilities": ", ".join(llm.capabilities(m.model)),
            "modified": m.modified_at.strftime("%Y-%m-%d") if m.modified_at else "",
        })
    return rows


def pull(name):
    """Yields (status, fraction or None) while downloading."""
    audit.log("model_pull_started", model=name)
    for p in ollama.pull(name, stream=True):
        frac = (p.completed / p.total) if p.total and p.completed else None
        yield p.status, frac
    llm.capabilities.cache_clear()
    audit.log("model_pulled", model=name)


def delete(name):
    ollama.delete(name)
    llm.capabilities.cache_clear()
    audit.log("model_deleted", model=name)


def find_gguf(folder, max_depth=4, limit=200):
    """Find .gguf files under a folder, skipping hidden folders."""
    root = Path(folder).expanduser()
    if not root.is_dir():
        raise FileNotFoundError(f"{root} is not a folder.")
    found, base_depth = [], len(root.parts)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        if len(Path(dirpath).parts) - base_depth >= max_depth:
            dirnames[:] = []
        for f in filenames:
            if f.lower().endswith(".gguf"):
                p = Path(dirpath) / f
                found.append({"path": str(p), "size_gb": round(p.stat().st_size / 1e9, 2)})
                if len(found) >= limit:
                    return found
    return found


def valid_model_name(name):
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9._\-]*(:[a-z0-9._\-]+)?", name or ""))


def import_gguf(path, name):
    """Create an Ollama model from a .gguf file. Ollama copies it; the original stays."""
    exe = shutil.which("ollama") or next((c for c in OLLAMA_CANDIDATES if os.path.exists(c)), None)
    if not exe:
        return False, "Could not find the `ollama` command. Is Ollama installed?"
    src = Path(path).expanduser().resolve()
    if not src.is_file():
        return False, f"{src} not found."
    with tempfile.TemporaryDirectory() as tmp:
        link = Path(tmp) / "model.gguf"
        link.symlink_to(src)  # avoids problems with spaces in the original path
        (Path(tmp) / "Modelfile").write_text("FROM ./model.gguf\n")
        proc = subprocess.run([exe, "create", name, "-f", "Modelfile"], cwd=tmp,
                              capture_output=True, text=True, timeout=3600)
    ok = proc.returncode == 0
    llm.capabilities.cache_clear()
    audit.log("model_imported" if ok else "model_import_failed", model=name, source=str(src))
    return ok, (proc.stdout + proc.stderr)[-3000:]
