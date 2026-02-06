"""
Executor agent: if validation_ok, run automation_script in a real headless browser at the page URL.
Sets execution_ok / execution_error from the headless run result.
"""
import logging
from typing import AsyncGenerator

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions

from backend.services.headless_browser import run_script_in_headless_browser

logger = logging.getLogger(__name__)


class ExecutorAgent(BaseAgent):
    """Runs the automation script in a headless Chromium page at the target URL."""

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        validation_ok = ctx.session.state.get("validation_ok", False)
        script = ctx.session.state.get("automation_script") or ""
        url = (ctx.session.state.get("url") or "").strip()
        if not validation_ok or not script:
            logger.info("[Executor] SKIP: validation_ok=%s script_len=%d (validation failed or no script)", validation_ok, len(script))
            ctx.session.state["execution_ok"] = False
            ctx.session.state["execution_error"] = "Validation failed or no script."
            yield Event(
                author=self.name,
                actions=EventActions(state_delta={"execution_ok": False, "execution_error": "Validation failed or no script."}),
            )
            return
        if not url:
            logger.info("[Executor] SKIP: url missing")
            ctx.session.state["execution_ok"] = False
            ctx.session.state["execution_error"] = "Missing url for headless browser."
            yield Event(
                author=self.name,
                actions=EventActions(state_delta={"execution_ok": False, "execution_error": "Missing url for headless browser."}),
            )
            return
        logger.info("[Executor] Running headless browser url=%s script_len=%d", url[:60], len(script))
        result = await run_script_in_headless_browser(url, script)
        logger.info("[Executor] RESULT success=%s error=%r", result.success, (result.error_message or "")[:150])
        ctx.session.state["execution_ok"] = result.success
        ctx.session.state["execution_error"] = "" if result.success else result.error_message
        yield Event(
            author=self.name,
            actions=EventActions(
                state_delta={
                    "execution_ok": result.success,
                    "execution_error": ctx.session.state["execution_error"],
                }
            ),
        )
