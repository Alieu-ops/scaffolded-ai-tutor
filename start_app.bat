@echo off
rem Double-click this file to start the higher-education tutor.
rem It opens in your browser at http://localhost:8502
rem (port 8502, so it can run alongside the senior secondary app on 8501).
rem Uses .venv in this folder if there is one, otherwise the parent's ..\.venv.
rem Close this black window to stop the app.
cd /d "%~dp0"
set STREAMLIT=.venv\Scripts\streamlit.exe
if not exist "%STREAMLIT%" set STREAMLIT=..\.venv\Scripts\streamlit.exe
start "" http://localhost:8502
"%STREAMLIT%" run app.py --server.port 8502 --server.headless true
