"""
LLM config for ADK agents. ADK reads GOOGLE_API_KEY from env;
this module exposes config so agents use the same model and key source.
No hardcoded values; all from backend.config.
"""
from backend import config


def get_adk_model() -> str:
    """Return ADK model name. Call after ensure_automation_config() (e.g. in route)."""
    config.ensure_automation_config()
    return config.ADK_MODEL
