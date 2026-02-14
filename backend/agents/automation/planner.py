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
            "CRITICAL - Composio-only vs DOM: If the user ONLY asks to save or send content to an external app (e.g. 'save to Google Doc', 'save caption to my google docs', 'email this', 'add to calendar', 'save to Notion', 'save to sheet') and does NOT ask to hide, remove, click, or change anything on the page, output a task spec that says exactly: 'No DOM automation. User only requested [saving to Google Doc / email / etc.]. Do not hide, remove, or modify any page elements.' In that case do NOT suggest any selectors, remove, hide, or click actions—the external app action is handled separately; the browser script must do nothing. "
            "When the user asks for BOTH page changes AND saving (e.g. 'hide the sidebar and save the post to a doc'), then include both. "
            "Use page_context to make the task spec concrete only when the user wants DOM actions: mention actual selectors (id, class) that appear in page_context (e.g. 'remove #right-rail-ad', 'hide .sidebar'). "
            "When the user wants to save or summarize post content and profile (e.g. LinkedIn feed) AND also wants DOM automation: include expand/see-more if needed, then profile and post content. If they only want to save to Doc/sheet/email, use the 'No DOM automation' task spec above. "
            "Output a short, structured task spec (plain text), no code."
        ),
        output_key="task_spec",
    )
