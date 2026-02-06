"""
POST /automate: run automation pipeline.
Consumes the full event stream so Runner processes every event.
Optional Composio "Bridge" step runs after the pipeline when COMPOSIO_API_KEY is set.
"""
import asyncio
import logging
import sys
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from google.adk.runners import InMemoryRunner
from google.genai import types

from backend import config
from backend.agents.automation.pipeline import create_automation_agent
from backend.services.headless_browser import HEADLESS_INFRA_ERROR_PREFIX, get_page_dom_summary
from backend.services.script_utils import script_to_commands, strip_trailing_prose

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/automate", tags=["automate"])

APP_NAME = "interest_lens_automation"


class AutomateRequest(BaseModel):
    url: str = Field(..., description="Page URL for automation")
    command: str = Field(..., description="Natural language command")
    page_context: str | None = Field(None, description="DOM summary from the client (what the user sees); if set, skips headless fetch")
    composio_entity_id: str | None = Field(None, description="Composio connected-account entity ID for Gmail/Notion/Calendar etc.; only used if Composio is enabled")


class AutomateResponse(BaseModel):
    ok: bool = True
    script: str | None = Field(None, description="Final automation script (JavaScript)")
    commands: list[dict] | None = Field(None, description="CSP-safe command list")
    error: str | None = Field(None, description="Error message if ok is False")
    warning: str | None = Field(None, description="Optional warning")
    connector_summary: str | None = Field(None, description="If Composio ran (e.g. draft email, save to Notion), a short summary")
    connector_error: str | None = Field(None, description="If Composio step failed (e.g. app not connected), error message for the client")


def _get_runner():
    config.ensure_automation_config()
    agent = create_automation_agent()
    runner = InMemoryRunner(agent=agent, app_name=APP_NAME)
    return runner, runner.session_service


@router.post("/", response_model=AutomateResponse)
async def automate(request: AutomateRequest) -> AutomateResponse:
    try:
        runner, session_service = _get_runner()
    except Exception as e:
        logger.exception("Automation config or agent setup failed")
        raise HTTPException(status_code=500, detail=str(e)) from e

    user_id = "automate_user"
    session_id = str(uuid.uuid4())

    logger.info("[automate] START url=%s command=%r", request.url.strip()[:80], (request.command or "")[:80])

    # 1. Page context: use client-provided DOM summary if available, else headless fetch (fallback for old extensions)
    if request.page_context and (request.page_context or "").strip():
        page_context = request.page_context.strip()
        logger.info("[automate] Using client-provided page context (len=%d)", len(page_context))
    else:
        try:
            page_context = await get_page_dom_summary(request.url.strip())
        except Exception as e:
            logger.warning("Page observation failed: %s", e)
            return AutomateResponse(
                ok=False,
                error=f"{HEADLESS_INFRA_ERROR_PREFIX} Page load failed: {e!s}",
            )
        if not (page_context or "").strip():
            logger.info("[automate] FAIL: page context empty")
            return AutomateResponse(
                ok=False,
                error=f"{HEADLESS_INFRA_ERROR_PREFIX} Could not load page structure.",
            )

    # 2. Run the Agent Pipeline
    initial_state = {
        "user_command": request.command,
        "url": request.url.strip(),
        "last_error": "",
        "page_context": page_context.strip(),
    }

    session = await session_service.create_session(
        app_name=APP_NAME,
        user_id=user_id,
        session_id=session_id,
        state=initial_state,
    )
    session_id = session.id

    user_message = types.Content(parts=[types.Part(text=request.command)])

    event_count = 0
    try:
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=user_message,
        ):
            event_count += 1
    except Exception as e:
        logger.exception("[automate] Pipeline run failed: %s", e)
        return AutomateResponse(ok=False, error=str(e)[:500])

    # 3. Retrieve Final State and Return Script
    try:
        session = await session_service.get_session(
            app_name=APP_NAME,
            user_id=user_id,
            session_id=session_id,
        )
    except Exception as e:
        return AutomateResponse(ok=False, error="Could not read session result")

    state = getattr(session, "state", None) or {}
    raw_script = (state.get("automation_script") or "").strip()
    script = strip_trailing_prose(raw_script) if raw_script else ""
    task_spec = (state.get("task_spec") or "").strip()
    page_context_state = (state.get("page_context") or "").strip()
    user_command_state = (state.get("user_command") or request.command or "").strip()
    url_state = (state.get("url") or request.url or "").strip()

    # 4. Optional Composio "Bridge" step: draft email, save to Notion, calendar, etc.
    connector_summary = None
    connector_error = None
    if config.is_composio_enabled() and (user_command_state or task_spec):
        entity_id = (request.composio_entity_id or "").strip() or config.get_composio_entity_id() or user_id
        logger.info(
            "[automate] Composio connector starting entity_id=%s command_len=%d task_spec_len=%d",
            entity_id,
            len(user_command_state),
            len(task_spec),
        )
        try:
            from backend.services.composio_bridge import run_connector_step

            result = await asyncio.to_thread(
                run_connector_step,
                entity_id=entity_id,
                user_command=user_command_state,
                task_spec=task_spec,
                page_context=page_context_state[:6000],
                url=url_state,
            )
            if result.get("summary"):
                connector_summary = result["summary"]
                logger.info("[automate] Composio connector summary: %s", (result["summary"] or "")[:300])
            if result.get("tool_calls"):
                logger.info("[automate] Composio tool_calls: %s", result["tool_calls"])
            if result.get("error"):
                connector_error = result["error"][:500]
                logger.warning("[automate] Composio connector error: %s", connector_error)
        except Exception as e:
            connector_error = str(e)[:500]
            logger.warning("[automate] Composio connector skipped or failed: %s", e, exc_info=True)

    # If we have a script, return it! (The client will execute it)
    if script:
        commands = script_to_commands(script)
        logger.info("[automate] RETURN ok=True script_len=%d", len(script))
        return AutomateResponse(
            ok=True,
            script=script,
            commands=commands if commands else None,
            warning=state.get("last_error"),  # Pass warnings (e.g. from previous loops)
            connector_summary=connector_summary,
            connector_error=connector_error,
        )

    # Only fail if no script was generated
    last_error = state.get("last_error") or "No script generated by agents."
    return AutomateResponse(ok=False, error=last_error, connector_summary=connector_summary, connector_error=connector_error)
