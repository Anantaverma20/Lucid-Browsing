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
from backend.services.script_utils import script_to_commands

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/automate", tags=["automate"])

APP_NAME = "interest_lens_automation"

# Cached runner and session_service (reused across requests)
_runner: InMemoryRunner | None = None
_session_service = None

# Keywords that suggest Composio (save to doc/sheet, email, calendar, Notion). If none match, skip Composio.
COMPOSIO_INTENT_KEYWORDS = (
    "save", "doc", "document", "sheet", "email", "gmail", "calendar", "notion",
    "draft", "send", "google doc", "google sheet", "add to calendar", "create event",
)


class ConversationMessage(BaseModel):
    role: str = Field(..., description="'user' or 'assistant'")
    content: str = Field(..., description="Message content")


class AutomateRequest(BaseModel):
    url: str = Field(..., description="Page URL for automation")
    command: str = Field(..., description="Natural language command (or latest message when conversation is used)")
    page_context: str | None = Field(None, description="DOM summary from the client (required; use the extension to provide it)")
    main_content: str | None = Field(None, description="Full text from main post/article (for summaries saved to Docs/Sheets)")
    composio_entity_id: str | None = Field(None, description="Composio connected-account entity ID for Gmail/Notion/Calendar etc.; only used if Composio is enabled")
    conversation: list[ConversationMessage] | None = Field(None, description="Previous messages for chatbot follow-up; when set, only Composio runs (no DOM pipeline)")


class AutomateResponse(BaseModel):
    ok: bool = True
    script: str | None = Field(None, description="Final automation script (JavaScript)")
    commands: list[dict] | None = Field(None, description="CSP-safe command list")
    error: str | None = Field(None, description="Error message if ok is False")
    warning: str | None = Field(None, description="Optional warning")
    connector_summary: str | None = Field(None, description="If Composio ran (e.g. draft email, save to Notion), a short summary")
    connector_error: str | None = Field(None, description="If Composio step failed (e.g. app not connected), error message for the client")


def _get_runner():
    global _runner, _session_service
    if _runner is not None and _session_service is not None:
        return _runner, _session_service
    config.ensure_automation_config()
    agent = create_automation_agent()
    _runner = InMemoryRunner(agent=agent, app_name=APP_NAME)
    _session_service = _runner.session_service
    return _runner, _session_service


@router.post("/", response_model=AutomateResponse)
async def automate(request: AutomateRequest) -> AutomateResponse:
    # Follow-up mode: conversation provided (chatbot); run only Composio, no DOM pipeline
    conversation = request.conversation or []
    if len(conversation) >= 2 and config.is_composio_enabled():
        page_context = (request.page_context or "").strip()
        main_content = (request.main_content or "").strip()
        if page_context:
            entity_id = (request.composio_entity_id or "").strip() or config.get_composio_entity_id() or "automate_user"
            conv_list = [{"role": m.role, "content": m.content} for m in conversation]
            logger.info("[automate] FOLLOW-UP Composio only conversation_len=%d", len(conv_list))
            try:
                from backend.services.composio_bridge import run_connector_step_with_conversation

                result = await asyncio.to_thread(
                    run_connector_step_with_conversation,
                    entity_id=entity_id,
                    conversation=conv_list,
                    latest_user_message=request.command.strip(),
                    page_context=page_context[:6000],
                    main_content=main_content[:8000] or None,
                    url=request.url.strip(),
                )
                summary = result.get("summary") or ""
                err = result.get("error")
                logger.info("[automate] FOLLOW-UP connector_summary len=%d", len(summary))
                return AutomateResponse(
                    ok=True,
                    script=";",
                    commands=[],
                    connector_summary=summary or None,
                    connector_error=err[:500] if err else None,
                )
            except Exception as e:
                logger.warning("[automate] follow-up Composio failed: %s", e, exc_info=True)
                return AutomateResponse(
                    ok=True,
                    script=";",
                    commands=[],
                    connector_summary=None,
                    connector_error=str(e)[:500],
                )

    try:
        runner, session_service = _get_runner()
    except Exception as e:
        logger.exception("Automation config or agent setup failed")
        raise HTTPException(status_code=500, detail=str(e)) from e

    user_id = "automate_user"
    session_id = str(uuid.uuid4())

    logger.info("[automate] START url=%s command=%r", request.url.strip()[:80], (request.command or "")[:80])

    # 1. Page context: required from the client (extension). No headless browser fallback.
    page_context = (request.page_context or "").strip()
    if not page_context:
        logger.info("[automate] FAIL: page_context required (use the extension to automate this page)")
        return AutomateResponse(
            ok=False,
            error="Page context is required. Use the Lucid Browsing extension on this page to run automation.",
        )
    logger.info("[automate] Using client-provided page context (len=%d)", len(page_context))

    # 2. Run the Agent Pipeline
    main_content = (request.main_content or "").strip()
    if main_content:
        logger.info("[automate] Using client-provided main_content (len=%d)", len(main_content))
    initial_state = {
        "user_command": request.command,
        "url": request.url.strip(),
        "last_error": "",
        "page_context": page_context.strip(),
        "main_content": main_content,
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
    script = (state.get("automation_script") or "").strip()
    task_spec = (state.get("task_spec") or "").strip()
    page_context_state = (state.get("page_context") or "").strip()
    main_content_state = (state.get("main_content") or "").strip()
    user_command_state = (state.get("user_command") or request.command or "").strip()
    url_state = (state.get("url") or request.url or "").strip()

    # 4. Optional Composio "Bridge" step: draft email, save to Notion, calendar, etc.
    connector_summary = None
    connector_error = None
    combined_for_composio = (user_command_state + " " + task_spec).lower()
    composio_intent = any(kw in combined_for_composio for kw in COMPOSIO_INTENT_KEYWORDS)
    if config.is_composio_enabled() and (user_command_state or task_spec) and composio_intent:
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
                main_content=main_content_state[:8000] or None,
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
