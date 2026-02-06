"""
Validator agent: run automation_script in Daytona (parse-only) and set validation_ok, validation_errors.
Runs Daytona in a thread so the event loop is not blocked; uses timeout so the user gets a clear error.
"""
import asyncio
import logging
from typing import AsyncGenerator

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions

from backend import config
from backend.services.daytona_sandbox import DAYTONA_INFRA_ERROR_PREFIX, run_automation_script

logger = logging.getLogger(__name__)


class ValidatorAgent(BaseAgent):
    """Runs the automation script in sandbox (parse-only) and sets validation_ok / validation_errors in state."""

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        script = ctx.session.state.get("automation_script") or ""
        if not script:
            logger.info("[Validator] SKIP: no automation_script in state (Writer did not produce script)")
            ctx.session.state["validation_ok"] = False
            ctx.session.state["validation_errors"] = "No automation_script in state. Check Writer/ADK state injection (task_spec, page_context) and Writer model."
            yield Event(author=self.name, actions=EventActions(state_delta={"validation_ok": False, "validation_errors": ctx.session.state["validation_errors"]}))
            return
        timeout_sec = getattr(config, "SANDBOX_TIMEOUT_SECONDS", 60) or 60
        logger.info("[Validator] Running Daytona sandbox (script_len=%d, timeout=%ds)", len(script), timeout_sec)
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(run_automation_script, script, parse_only=True),
                timeout=float(timeout_sec + 30),
            )
        except asyncio.TimeoutError:
            logger.info("[Validator] TIMEOUT after %ds", timeout_sec + 30)
            ctx.session.state["validation_ok"] = False
            ctx.session.state["validation_errors"] = (
                f"{DAYTONA_INFRA_ERROR_PREFIX} Validator (Daytona) timed out after {timeout_sec}s. "
                "Check SANDBOX_TIMEOUT_SECONDS and Daytona availability."
            )
            yield Event(
                author=self.name,
                actions=EventActions(
                    state_delta={
                        "validation_ok": False,
                        "validation_errors": ctx.session.state["validation_errors"],
                    }
                ),
            )
            return
        ctx.session.state["validation_ok"] = result.success
        ctx.session.state["validation_errors"] = "" if result.success else result.error_message
        logger.info("[Validator] RESULT success=%s error=%r", result.success, (result.error_message or "")[:150])
        yield Event(
            author=self.name,
            actions=EventActions(
                state_delta={
                    "validation_ok": result.success,
                    "validation_errors": ctx.session.state["validation_errors"],
                }
            ),
        )
