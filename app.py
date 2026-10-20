"""Kept for compatibility: `streamlit run app.py` still works. Prefer: offline-agent studio"""
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parent / "offline_agent" / "app.py"), run_name="__main__")
