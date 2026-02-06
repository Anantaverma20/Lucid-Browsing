"""
Checker agent: if validation_ok is True, escalate to exit loop; else set last_error for Writer.
The Writer uses last_error on the next iteration to fix the script.
"""
import logging
from typing import AsyncGenerator

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions

logger = logging.getLogger(__name__)

_MAX_ERROR_LEN = 500


def _truncate(s: str, max_len: int = _MAX_ERROR_LEN) -> str:
    s = (s or "").strip()
    if not s:
        return s
    if len(s) <= max_len:
        return s
    return s[: max_len - 3].rstrip() + "..."


class CheckerAgent(BaseAgent):
    """Checks state and either escalates (success) or sets last_error for the next Writer iteration."""

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        validation_ok = ctx.session.state.get("validation_ok", False)
        # We no longer check execution_ok because execution happens in the user's browser

        validation_errors = _truncate(ctx.session.state.get("validation_errors") or "")

        # If syntax is valid, we are done! The browser extension will run the script.
        if validation_ok:
            logger.info("Checker: validation OK -> escalating (exit loop)")
            yield Event(
                author=self.name,
                actions=EventActions(state_delta={"last_error": ""}, escalate=True),
            )
            return

        # If not valid, report errors to the Writer so it can try again
        parts = []
        if not validation_ok and validation_errors:
            parts.append(f"Validation: {validation_errors}")

        last_error = " ".join(parts).strip() or "Validation failed."
        ctx.session.state["last_error"] = last_error
        logger.info("Checker: not OK -> setting last_error for next Writer iteration: %s", last_error[:200])
        yield Event(author=self.name, actions=EventActions(state_delta={"last_error": last_error}))
