"""
Run automation script in a Daytona sandbox (Node/JS) for parse/syntax validation.
Used by the Validator agent. Returns success and error_message for the pipeline.
"""
import logging
from dataclasses import dataclass

from daytona_sdk import (
    CodeLanguage,
    CreateSandboxFromSnapshotParams,
    Daytona,
    DaytonaConfig,
)

from backend import config
from backend.services.script_utils import strip_trailing_prose

logger = logging.getLogger(__name__)

# Prefix for infrastructure (non-script) failures so the route can show where to look.
DAYTONA_INFRA_ERROR_PREFIX = "Daytona sandbox error:"


@dataclass
class DaytonaResult:
    success: bool
    error_message: str


def _language_from_config() -> str:
    raw = (getattr(config, "DAYTONA_SANDBOX_LANGUAGE", None) or "").strip().lower()
    if raw in ("node", "js", "javascript"):
        return CodeLanguage.JAVASCRIPT.value
    if raw == "typescript" or raw == "ts":
        return CodeLanguage.TYPESCRIPT.value
    if raw == "python" or raw == "py":
        return CodeLanguage.PYTHON.value
    return CodeLanguage.JAVASCRIPT.value


def run_automation_script(script: str, *, parse_only: bool = False) -> DaytonaResult:
    """
    Run script in a Daytona sandbox. parse_only is accepted for API compatibility;
    we still execute the script so syntax/runtime errors surface via exit code and stderr.
    Returns DaytonaResult(success=True, error_message="") on success.
    """
    config.ensure_automation_config()
    timeout = getattr(config, "SANDBOX_TIMEOUT_SECONDS", 60) or 60
    lang = _language_from_config()

    daytona_config = DaytonaConfig(
        api_key=config.DAYTONA_API_KEY,
        api_url=config.DAYTONA_API_URL or None,
        target=config.DAYTONA_TARGET or None,
    )
    daytona = Daytona(daytona_config)
    params = CreateSandboxFromSnapshotParams(language=lang)
    sandbox = None
    script = strip_trailing_prose(script or "")
    if not script:
        return DaytonaResult(success=False, error_message="Empty script after stripping trailing prose.")
    try:
        logger.info("[Daytona] Creating sandbox (language=%s, timeout=%ds)", lang, timeout)
        sandbox = daytona.create(params, timeout=timeout)
        response = sandbox.process.code_run(script, timeout=timeout)
        success = response.exit_code == 0
        error_message = "" if success else (response.result or "").strip()[:500]
        logger.info("[Daytona] code_run exit_code=%s success=%s error=%r", response.exit_code, success, error_message[:150] if error_message else "")
        return DaytonaResult(success=success, error_message=error_message)
    except Exception as e:
        msg = str(e).strip()[:500]
        logger.exception("[Daytona] Sandbox error: %s", msg)
        infra_msg = f"{DAYTONA_INFRA_ERROR_PREFIX} {msg} Check DAYTONA_API_KEY, DAYTONA_API_URL, and network."
        return DaytonaResult(success=False, error_message=infra_msg[:500])
    finally:
        if sandbox is not None:
            try:
                sandbox.delete(timeout=timeout)
                logger.debug("Daytona sandbox deleted: %s", getattr(sandbox, "id", "?"))
            except Exception as del_err:
                logger.warning("Failed to delete Daytona sandbox after use: %s", del_err)
