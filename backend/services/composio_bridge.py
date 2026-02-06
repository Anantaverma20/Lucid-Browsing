"""
Optional Composio "Bridge" for browser-to-inbox (and other app) workflows.
Only loaded when COMPOSIO_API_KEY is set. Adds no dependency when disabled.

Uses current Composio API: Composio(provider=GeminiProvider()) + composio.tools.get / provider.handle_response.
Use cases: draft email from page, save to Notion, add to calendar, create Linear/Jira ticket, etc.
"""
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_COMPOSIO_CLIENT = None
_GENAI_CLIENT = None

# Tool action names for all connected apps: Gmail, Google Sheets, Google Docs, Google Calendar
DEFAULT_COMPOSIO_TOOLS = [
    # Gmail: send and create drafts
    "GMAIL_SEND_EMAIL",
    "GMAIL_CREATE_EMAIL_DRAFT",
    # Google Sheets: create new sheet, add/append rows
    "GOOGLESHEETS_CREATE_GOOGLE_SHEET",
    "GOOGLESHEETS_ADD_ROW",
    "GOOGLESHEETS_APPEND_DATA",
    # Google Docs: create document; use CREATE_DOCUMENT_MARKDOWN for full body (profile + post summary)
    "GOOGLEDOCS_CREATE_DOCUMENT",
    "GOOGLEDOCS_CREATE_DOCUMENT_MARKDOWN",
    # Google Calendar: create, update, delete events
    "GOOGLECALENDAR_CREATE_EVENT",
    "GOOGLECALENDAR_UPDATE_EVENT",
    "GOOGLECALENDAR_DELETE_EVENT",
    "GOOGLECALENDAR_QUICK_ADD",
    # Notion (if connected)
    "NOTION_CREATE_PAGE",
]


def _ensure_composio():
    """Lazy-init Composio client (with GeminiProvider) and genai client. Raises if COMPOSIO_API_KEY not set."""
    global _COMPOSIO_CLIENT, _GENAI_CLIENT
    if _COMPOSIO_CLIENT is not None:
        return
    key = os.getenv("COMPOSIO_API_KEY", "").strip()
    if not key:
        raise RuntimeError("COMPOSIO_API_KEY is not set; Composio bridge is disabled.")
    try:
        from composio import Composio
        from composio_gemini import GeminiProvider
        from google import genai

        _COMPOSIO_CLIENT = Composio(provider=GeminiProvider(), api_key=key)
        _GENAI_CLIENT = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
    except ImportError as e:
        logger.warning("Composio not available: %s. Install composio, composio-gemini and set GOOGLE_API_KEY.", e)
        raise RuntimeError(
            "Composio bridge requires composio, composio-gemini and google-genai. "
            "Install with: pip install composio composio-gemini"
        ) from e


def get_composio_tools(entity_id: str, *, tool_names: list[str] | None = None):
    """
    Return Composio tools in Gemini format for the given entity (connected account).
    tool_names: list of action names e.g. GMAIL_SEND_EMAIL; defaults to DEFAULT_COMPOSIO_TOOLS.
    """
    _ensure_composio()
    tools_param = tool_names or DEFAULT_COMPOSIO_TOOLS
    tools = _COMPOSIO_CLIENT.tools.get(user_id=entity_id, tools=tools_param)
    return tools


def run_connector_step(
    entity_id: str,
    user_command: str,
    task_spec: str,
    page_context: str,
    url: str,
    *,
    model: str = "gemini-2.0-flash",
) -> dict[str, Any]:
    """
    Run one optional "Connector" step: use Gemini + Composio tools to perform
    external actions (draft email, save to Notion, add to calendar, create ticket)
    based on user command and page context. Returns a result dict with
    'summary', 'tool_calls', 'error'.
    """
    logger.info("[Composio] run_connector_step entity_id=%s url=%s command=%s", entity_id, url[:60] if url else "", (user_command or "")[:80])
    _ensure_composio()
    from google.genai import types

    tools = get_composio_tools(entity_id)
    tools_count = len(tools) if isinstance(tools, list) else (1 if tools else 0)
    tool_slugs = [getattr(getattr(t, "tool", None), "slug", None) or getattr(t, "__name__", str(t)) for t in (tools or [])]
    logger.info("[Composio] get_tools entity_id=%s -> %s tools: %s", entity_id, tools_count, tool_slugs)
    if not tools:
        logger.warning("[Composio] No tools available for entity_id=%s (check connected apps in Composio dashboard)", entity_id)
        return {"summary": "No Composio tools available.", "tool_calls": [], "error": None}

    prompt = f"""You are an executive assistant with access to Composio tools. The user is on a webpage and said: "{user_command}".
Task spec: {task_spec}
Page URL: {url}
Relevant page structure and text: {page_context[:4000]}

STRICT RULE — ONLY ACT WHEN EXPLICITLY ASKED: Use Composio tools ONLY when the user clearly and specifically asks for an external app action, e.g.: "draft an email", "send an email", "save to Google Sheet", "add to calendar", "create a doc", "save to Notion". Do NOT draft emails, create docs, or take any Composio action unless the user explicitly requested it. Do NOT infer or proactively do things like drafting an email "to document" or "to summarize" the user's request—that is forbidden. If the user only asked to remove elements, change the page, hide UI, or do something on the current webpage, do NOT call any tools; respond with exactly: "Not a Composio action; the browser automation will handle this."

SCOPE: Composio only handles external app actions (Gmail, Sheets, Docs, Calendar, Notion). Do NOT handle requests about changing the webpage itself—e.g. removing elements on the page, hiding UI, modifying the DOM, "remove elements on YouTube", hiding ads/sidebars. Those are handled by the browser automation, not by Composio. If the user's request is only about modifying the current page, respond with exactly: "Not a Composio action; the browser automation will handle this." Do not call any tools.

CRITICAL: When the user explicitly asks to "save to Google Sheet" (or save post/profile/data to a sheet), you MUST call the Composio tools—do NOT reply with text only. Do NOT say you will use a browser extension or find elements. Call GOOGLESHEETS_CREATE_GOOGLE_SHEET with a title like "Michael Berlingo - LinkedIn" or "Post summary - [Name]", then call GOOGLESHEETS_ADD_ROW or GOOGLESHEETS_APPEND_DATA with the spreadsheet ID from the create response and the row data (e.g. columns: Name, Title, Post summary, Profile info, etc.) extracted from the task spec and page context above. If you have GOOGLESHEETS_ADD_ROW/APPEND_DATA but not create, use the add/append tool with the data and a spreadsheet ID if the user provided one.

**Naming:** For new sheets, docs, or drafts use clear titles from the content (e.g. "Jia Chen - LinkedIn", "Mark M - Profile").

**Gmail:** Use GMAIL_CREATE_EMAIL_DRAFT or GMAIL_SEND_EMAIL with subject and body from context.

**Google Sheets:** For "save to Google Sheet" you MUST use GOOGLESHEETS_CREATE_GOOGLE_SHEET (title from person/source) then GOOGLESHEETS_ADD_ROW or GOOGLESHEETS_APPEND_DATA with the extracted data. Put each field (name, title, post summary, profile info) in appropriate columns.

**Google Docs (profile and post summary):** Prefer GOOGLEDOCS_CREATE_DOCUMENT_MARKDOWN so you can pass the full document body in one call (title + markdown content). If not available, use GOOGLEDOCS_CREATE_DOCUMENT for title only. The document body MUST be complete—no truncated sentences, no cut-off headline or post text.
- **Profile section:** Full name, full headline (do not cut off with "..." or mid-word), profile viewers, post impressions, and any other visible stats. Use clear labels: "Name:", "Headline:", "Profile viewers:", "Post impressions:".
- **Post summary:** Write a proper 2–4 sentence summary of each post in your own words. Describe what the post is about and its main point. BAD (forbidden): "Post Summary: We just won 1st place at Hack the Stackathon 🏆 On" (incomplete). GOOD: "Post Summary: Mark Morgan shared that his team won first place at Hack the Stackathon. The post celebrates this achievement and goes on to describe the event or next steps." Never end the summary mid-sentence. If the source post was truncated ("...more"), write a complete summary of the visible part and add "(Summary based on visible portion.)" at the end of that paragraph.

**Google Calendar:** Use GOOGLECALENDAR_CREATE_EVENT or GOOGLECALENDAR_QUICK_ADD; for delete use GOOGLECALENDAR_DELETE_EVENT.

**Notion:** Use NOTION_CREATE_PAGE only when the user explicitly asks to save to Notion.

If the user did not explicitly ask for an email, sheet, doc, calendar event, or Notion page, do NOT call any tools. If they did ask but you do not have the right tool connected, say briefly that the app is not connected. Only call tools when the user clearly requested one of these external actions.

When creating a Google Doc for "summary of this post and profile info": use GOOGLEDOCS_CREATE_DOCUMENT_MARKDOWN with a title (e.g. "Mark Morgan - Profile and Post Summary") and a markdown body that contains (1) full profile section with complete headline and all stats, (2) a Post Summary paragraph of 2–4 complete sentences that explain what the post says—never a snippet that ends mid-sentence. The entire body must be complete and readable."""

    # Gemini SDK expects list of genai Tool; Composio returns GeminiTool wrappers with ._genai_tool
    tools_for_config = [getattr(t, "_genai_tool", t) for t in tools] if tools else []
    if not tools_for_config:
        tools_for_config = tools  # fallback if no _genai_tool
    config = types.GenerateContentConfig(tools=tools_for_config)
    chat = _GENAI_CLIENT.chats.create(model=model, config=config)
    summary_parts = []
    tool_calls_done: list[dict] = []
    max_tool_rounds = 3

    try:
        response = chat.send_message(prompt)
        for _round in range(max_tool_rounds):
            if not response or not getattr(response, "candidates", None) or not response.candidates:
                break
            cand = response.candidates[0]
            parts = getattr(cand, "content", None) and getattr(cand.content, "parts", None) or []
            round_calls: list[dict] = []
            for p in parts:
                if getattr(p, "text", None) and p.text:
                    summary_parts.append(p.text)
                if getattr(p, "function_call", None):
                    fc = p.function_call
                    round_calls.append({
                        "name": getattr(fc, "name", None) or "",
                        "args": getattr(fc, "args", None) or {},
                    })
            if not round_calls:
                break
            tool_calls_done.extend(round_calls)
            logger.info("[Composio] Executing tool_calls (round %s): %s", _round + 1, round_calls)
            function_responses, executed = _COMPOSIO_CLIENT.provider.handle_response(response, tools)
            if not executed or not function_responses:
                logger.info("[Composio] handle_response executed=%s, stopping", executed)
                break
            # Log actual tool result (e.g. spreadsheet ID/URL or error) for debugging
            try:
                resp_repr = str(function_responses)[:800]
                logger.info("[Composio] tool result: %s", resp_repr)
            except Exception:
                pass
            summary_parts.append(str(function_responses)[:500])
            logger.info("[Composio] handle_response executed=%s responses_len=%d", executed, len(function_responses))
            response = chat.send_message(function_responses)
    except Exception as e:
        logger.exception("[Composio] connector step failed: %s", e)
        return {
            "summary": "",
            "tool_calls": tool_calls_done,
            "error": str(e)[:400],
        }

    summary = " ".join(summary_parts).strip() or "Connector step completed."
    logger.info("[Composio] connector step done tool_calls=%d summary_len=%d", len(tool_calls_done), len(summary))
    return {
        "summary": summary,
        "tool_calls": tool_calls_done,
        "error": None,
    }
