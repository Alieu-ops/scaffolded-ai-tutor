"""
Start the web app from Spyder (open this file and press F5 / Run),
or from any Python: python run_app.py

A Streamlit app cannot be run like a normal script; it must be started
with "streamlit run app.py". This file does that for you, using the
project's own environment (.venv), whichever Python Spyder is set to.

The app opens at http://localhost:8502. To stop it, close the console
window or press the red Stop button in Spyder's console.
"""

import subprocess
import webbrowser
from pathlib import Path

PROJECT = Path(__file__).resolve().parent
# Use .venv in this folder if there is one, otherwise the parent's (..\.venv).
STREAMLIT = PROJECT / ".venv" / "Scripts" / "streamlit.exe"
if not STREAMLIT.exists():
    STREAMLIT = PROJECT.parent / ".venv" / "Scripts" / "streamlit.exe"

webbrowser.open("http://localhost:8502")
subprocess.run([str(STREAMLIT), "run", str(PROJECT / "app.py"), "--server.port", "8502", "--server.headless", "true"],
               cwd=PROJECT)
