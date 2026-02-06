@echo off
REM Start Scraper API on port 8000 (Browserbase)
cd /d "%~dp0"
echo Starting Scraper API on http://127.0.0.1:8000 ...
echo Press Ctrl+C to stop.
call venv\Scripts\activate.bat
python -m uvicorn Browserbase.api:app --host 127.0.0.1 --port 8000
