@echo off
REM Start Lucid Browsing backend on port 8001 (scraper API stays on 8000)
cd /d "%~dp0"
echo Starting backend on http://127.0.0.1:8001 ...
echo Press Ctrl+C to stop.
call venv\Scripts\activate.bat
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8001
