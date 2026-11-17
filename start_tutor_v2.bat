@echo off
rem Double-click this file to start the version 2 tutor (qmtutor).
rem It opens in your browser at http://localhost:8504
rem (8502 = v1 higher-education app, so both can run at the same time).
rem Close this black window to stop the tutor.
cd /d "%~dp0"

set PYTHON=.venv\Scripts\python.exe
if not exist "%PYTHON%" set PYTHON=..\.venv\Scripts\python.exe
set STREAMLIT=.venv\Scripts\streamlit.exe
if not exist "%STREAMLIT%" set STREAMLIT=..\.venv\Scripts\streamlit.exe

rem 1. Make sure the local model server (Ollama) is running. The tutor still opens
rem    without it, but AI replies fall back to the lecturer's approved hints.
curl -s http://localhost:11434/api/version >nul 2>&1
if errorlevel 1 (
    echo Starting Ollama...
    start "" /min ollama serve
    timeout /t 5 /nobreak >nul
)

rem 2. Create the synthetic demo database the first time (does nothing if it exists).
"%PYTHON%" -m qmtutor.seed

rem 3. Open the browser and start the app.
start "" http://localhost:8504
"%STREAMLIT%" run streamlit_app.py --server.port 8504 --server.headless true
