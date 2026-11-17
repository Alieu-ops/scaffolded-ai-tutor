"""
Start the version 2 tutor from Spyder or VS Code (open this file and press Run),
or from any Python: python run_tutor_v2.py

Same steps as start_tutor_v2.bat:
    1. check the local model server (Ollama) and start it if needed;
    2. create the synthetic demo database the first time;
    3. open the browser and run "streamlit run streamlit_app.py".

The tutor opens at http://localhost:8504. To stop it, close the console or press Stop.
"""

import subprocess
import time
import webbrowser
from pathlib import Path

import requests

PROJECT = Path(__file__).resolve().parent
PORT = 8504


def project_tool(name: str) -> Path:
    """Use .venv in this folder if there is one, otherwise the parent's (..\\.venv)."""
    local = PROJECT / ".venv" / "Scripts" / name
    return local if local.exists() else PROJECT.parent / ".venv" / "Scripts" / name


def ensure_ollama() -> None:
    try:
        requests.get("http://localhost:11434/api/version", timeout=3)
    except requests.ConnectionError:
        print("Starting Ollama...")
        subprocess.Popen(["ollama", "serve"], creationflags=subprocess.CREATE_NO_WINDOW)
        time.sleep(5)


if __name__ == "__main__":
    ensure_ollama()
    subprocess.run([str(project_tool("python.exe")), "-m", "qmtutor.seed"], cwd=PROJECT, check=True)
    webbrowser.open(f"http://localhost:{PORT}")
    subprocess.run([str(project_tool("streamlit.exe")), "run", str(PROJECT / "streamlit_app.py"),
                    "--server.port", str(PORT), "--server.headless", "true"], cwd=PROJECT)
