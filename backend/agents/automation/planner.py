"""
Planner agent: user command + url -> task_spec (structured intent for DOM automation).
Model and config from backend.config.
"""
from backend.services.llm import get_adk_model
from google.adk.agents import LlmAgent


def create_planner() -> LlmAgent:
    return LlmAgent(
        name="Planner",
        model=get_adk_model(),
        instruction=(
            "You are a browser automation planner. The user is on a page and gave a natural language command. "
            "Input: user_command={user_command}, url={url}. "
            "Page structure (real elements from the page, one per line: tag#id.class \"text\"): {page_context}. "
            "Use page_context to make the task spec concrete: mention actual selectors (id, class) that appear in page_context when they match the user's intent (e.g. 'remove #right-rail-ad', 'hide .sidebar'). "
            "Output a short, structured task spec (plain text), no code."
        ),
        output_key="task_spec",
    )
