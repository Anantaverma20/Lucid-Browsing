"""
Configuration from environment. No hardcoded values.
All settings read from os.environ (e.g. .env).
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from repo root (parent of backend/)
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)


def _required(key: str) -> str:
    v = os.getenv(key)
    if not v or not str(v).strip():
        raise RuntimeError(f"Missing required env: {key}")
    return str(v).strip()


def _optional(key: str, default: str | None = None) -> str | None:
    v = os.getenv(key)
    if v is None or (isinstance(v, str) and not v.strip()):
        return default
    return str(v).strip()


# --- Automation agent (ADK + Daytona + headless browser). Loaded lazily so app can start without these. ---
_automation_loaded = False
GOOGLE_API_KEY: str | None = None
ADK_MODEL: str | None = None
AUTOMATION_MAX_ITERATIONS: int = 0
SANDBOX_TIMEOUT_SECONDS: int = 0
DAYTONA_API_KEY: str | None = None
DAYTONA_API_URL: str | None = None
DAYTONA_TARGET: str | None = None
DAYTONA_SANDBOX_LANGUAGE: str | None = None
HEADLESS_BROWSER_TIMEOUT_MS: int = 15000

# --- Composio (optional "Bridge" for Gmail, Notion, Calendar, etc.) ---


def is_composio_enabled() -> bool:
    """True if Composio integration is configured (COMPOSIO_API_KEY set)."""
    return bool(os.getenv("COMPOSIO_API_KEY", "").strip())


def get_composio_entity_id() -> str | None:
    """Composio entity (user) id for connected accounts. Set COMPOSIO_ENTITY_ID in .env to match the user_id in Composio dashboard."""
    return _optional("COMPOSIO_ENTITY_ID")


def ensure_automation_config() -> None:
    """Load automation env once. Call before using /automate. Raises if required keys missing."""
    global _automation_loaded, GOOGLE_API_KEY, ADK_MODEL, AUTOMATION_MAX_ITERATIONS
    global SANDBOX_TIMEOUT_SECONDS, DAYTONA_API_KEY, DAYTONA_API_URL, DAYTONA_TARGET, DAYTONA_SANDBOX_LANGUAGE
    global HEADLESS_BROWSER_TIMEOUT_MS
    if _automation_loaded:
        return
    GOOGLE_API_KEY = _required("GOOGLE_API_KEY")
    # Force AI Studio (API key) instead of Vertex AI; required when using Gemini API key from AI Studio
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "0"
    ADK_MODEL = _required("ADK_MODEL")
    AUTOMATION_MAX_ITERATIONS = int(_required("AUTOMATION_MAX_ITERATIONS"))
    SANDBOX_TIMEOUT_SECONDS = int(_required("SANDBOX_TIMEOUT_SECONDS"))
    DAYTONA_API_KEY = _required("DAYTONA_API_KEY")
    DAYTONA_API_URL = _optional("DAYTONA_API_URL")
    DAYTONA_TARGET = _optional("DAYTONA_TARGET")
    DAYTONA_SANDBOX_LANGUAGE = _required("DAYTONA_SANDBOX_LANGUAGE")
    raw = _optional("HEADLESS_BROWSER_TIMEOUT_MS", "15000")
    try:
        HEADLESS_BROWSER_TIMEOUT_MS = int(raw) if raw else 15000
    except (TypeError, ValueError):
        HEADLESS_BROWSER_TIMEOUT_MS = 15000
    _automation_loaded = True
