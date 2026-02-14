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

logger = logging.getLogger(__name__)

# Prefix for infrastructure (non-script) failures so the route can show where to look.
DAYTONA_INFRA_ERROR_PREFIX = "Daytona sandbox error:"

# Reused sandbox across calls (one per process/language)
_sandbox = None
_sandbox_lang = None


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
    Reuses a single sandbox per process (per language); creates on first use, reuses on subsequent calls.
    Returns DaytonaResult(success=True, error_message="") on success.
    """
    global _sandbox, _sandbox_lang
    config.ensure_automation_config()
    timeout = getattr(config, "SANDBOX_TIMEOUT_SECONDS", 60) or 60
    lang = _language_from_config()

    script = (script or "").strip()
    if not script:
        return DaytonaResult(success=False, error_message="Empty script after stripping trailing prose.")

    daytona_config = DaytonaConfig(
        api_key=config.DAYTONA_API_KEY,
        api_url=config.DAYTONA_API_URL or None,
        target=config.DAYTONA_TARGET or None,
    )
    daytona = Daytona(daytona_config)
    params = CreateSandboxFromSnapshotParams(language=lang)

    try:
        if _sandbox is not None and _sandbox_lang == lang:
            response = _sandbox.process.code_run(script, timeout=timeout)
        else:
            if _sandbox is not None:
                try:
                    _sandbox.delete(timeout=timeout)
                except Exception as del_err:
                    logger.warning("Failed to delete previous Daytona sandbox: %s", del_err)
                _sandbox = None
                _sandbox_lang = None
            logger.info("[Daytona] Creating sandbox (language=%s, timeout=%ds)", lang, timeout)
            _sandbox = daytona.create(params, timeout=timeout)
            _sandbox_lang = lang
            response = _sandbox.process.code_run(script, timeout=timeout)
        success = response.exit_code == 0
        error_message = "" if success else (response.result or "").strip()[:500]
        logger.info("[Daytona] code_run exit_code=%s success=%s error=%r", response.exit_code, success, error_message[:150] if error_message else "")
        return DaytonaResult(success=success, error_message=error_message)
    except Exception as e:
        if _sandbox is not None:
            try:
                _sandbox.delete(timeout=timeout)
            except Exception as del_err:
                logger.warning("Failed to delete Daytona sandbox after error: %s", del_err)
            _sandbox = None
            _sandbox_lang = None
        msg = str(e).strip()[:500]
        logger.exception("[Daytona] Sandbox error: %s", msg)
        infra_msg = f"{DAYTONA_INFRA_ERROR_PREFIX} {msg} Check DAYTONA_API_KEY, DAYTONA_API_URL, and network."
        return DaytonaResult(success=False, error_message=infra_msg[:500])
