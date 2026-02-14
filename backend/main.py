"""
Single FastAPI app for Lucid Browsing: automate, scrape, health.
Scraper API uses port 8000; run this backend on 8001:
  uvicorn backend.main:app --host 127.0.0.1 --port 8001
"""
import logging
import sys
from dotenv import load_dotenv
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.routes import automate, scrape, voice, verify

logger = logging.getLogger(__name__)

# Load .env from repo root
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)

# Force backend INFO logs to appear in terminal (uvicorn's root logger often stays at WARNING)
_backend_log = logging.getLogger("backend")
_backend_log.setLevel(logging.INFO)
if not _backend_log.handlers:
    _h = logging.StreamHandler(sys.stderr)
    _h.setFormatter(logging.Formatter("%(levelname)s: [%(name)s] %(message)s"))
    _backend_log.addHandler(_h)

app = FastAPI(
    title="Lucid Browsing API",
    description="Automation agent pipeline and scraping",
    version="1.0.0",
)


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Return JSON on any unhandled exception so the extension gets a parseable error."""
    logger.exception("Unhandled exception")
    detail = str(exc).strip()[:500]
    if len(str(exc)) > 500:
        detail += "..."
    return JSONResponse(
        status_code=500,
        content={"ok": False, "error": "Internal Server Error", "detail": detail},
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(automate.router)
app.include_router(scrape.router)
app.include_router(voice.router)
app.include_router(verify.router)


@app.get("/")
async def root():
    return {
        "message": "Lucid Browsing API",
        "endpoints": {
            "POST /automate": "Run automation pipeline (body: url, command)",
            "POST /scrape": "Scrape URL (body: url, refresh_cache?)",
            "GET /scrape": "Scrape URL (query: url)",
            "GET /health": "Health check",
            "POST /verify": "News Truth – fact-check page or screenshot (body: url, content?, image_base64?)",
        },
    }
