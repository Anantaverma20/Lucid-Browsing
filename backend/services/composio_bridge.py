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
    # Google Docs: search existing, insert into existing, or create new with content
    "GOOGLEDOCS_SEARCH_DOCUMENTS",
    "GOOGLEDOCS_CREATE_DOCUMENT_MARKDOWN",
    "GOOGLEDOCS_INSERT_TEXT_ACTION",
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
    main_content: str | None = None,
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

    main_block = ""
    if main_content and main_content.strip():
        main_block = f"\n\nMain content (full text from the page — use this for summaries):\n{main_content[:6000]}\n"
    prompt = f"""You are an executive assistant with access to Composio tools. The user is on a webpage and said: "{user_command}".
Task spec: {task_spec}
Page URL: {url}
Relevant page structure and text: {page_context[:4000]}{main_block}

EXTRACT FROM THE PAGE ABOVE: When the user asks for a "summary of this post", "caption text", or to save content to Google Docs, use the "Main content" section above if present. Write a real summary (or use the caption as-is). Only if there is no main content use a short placeholder. You MUST call a Composio tool when they ask to save to Docs: if they did not name a specific doc, call GOOGLEDOCS_CREATE_DOCUMENT_MARKDOWN now—do not ask "should I create a new one?" or reply with text only. If they named an existing doc, call GOOGLEDOCS_SEARCH_DOCUMENTS then GOOGLEDOCS_INSERT_TEXT_ACTION. Never refuse to call tools; always create or update the doc so the user gets something they can edit.

STRICT RULE — ONLY ACT WHEN EXPLICITLY ASKED: Use Composio tools ONLY when the user clearly and specifically asks for an external app action, e.g.: "draft an email", "send an email", "save to Google Sheet", "add to calendar", "create a doc", "save to Notion". Do NOT draft emails, create docs, or take any Composio action unless the user explicitly requested it. Do NOT infer or proactively do things like drafting an email "to document" or "to summarize" the user's request—that is forbidden. If the user only asked to remove elements, change the page, hide UI, or do something on the current webpage, do NOT call any tools; respond with exactly: "Not a Composio action; the browser automation will handle this."

SCOPE: Composio only handles external app actions (Gmail, Sheets, Docs, Calendar, Notion). Do NOT handle requests about changing the webpage itself—e.g. removing elements on the page, hiding UI, modifying the DOM, "remove elements on YouTube", hiding ads/sidebars. Those are handled by the browser automation, not by Composio. If the user's request is only about modifying the current page, respond with exactly: "Not a Composio action; the browser automation will handle this." Do not call any tools.

CRITICAL: When the user explicitly asks to "save to Google Sheet" (or save post/profile/data to a sheet), you MUST call the Composio tools—do NOT reply with text only. Do NOT say you will use a browser extension or find elements. Call GOOGLESHEETS_CREATE_GOOGLE_SHEET with a title like "Michael Berlingo - LinkedIn" or "Post summary - [Name]", then call GOOGLESHEETS_ADD_ROW or GOOGLESHEETS_APPEND_DATA with the spreadsheet ID from the create response and the row data (e.g. columns: Name, Title, Post summary, Profile info, etc.) extracted from the task spec and page context above. If you have GOOGLESHEETS_ADD_ROW/APPEND_DATA but not create, use the add/append tool with the data and a spreadsheet ID if the user provided one.

**Naming:** For new sheets, docs, or drafts use clear titles from the content (e.g. "Jia Chen - LinkedIn", "Mark M - Profile").

**Gmail (draft email):** Use GMAIL_CREATE_EMAIL_DRAFT. You MUST write a full, substantive email body—not a skeleton. For application emails (e.g. AI engineer, role at a company): (1) Extract from the page context: recipient name, company name, role, and if visible the user's profile (headline, e.g. "Data Scientist & AI/ML Engineer | LLM Development"). (2) Write a complete professional email: greeting (Dear [Name],), brief intro stating interest in the role/company, 1–2 paragraphs on why you're a fit (mention relevant qualifications: ML, LLM, AI/ML engineering, etc. from the user's context or infer "AI/ML experience"), something specific about the company if visible, and a closing (e.g. eager to discuss, thank you, sincerely). Subject line should be specific (e.g. "AI Engineer Opportunity at [Company]" or "Application – AI Engineer Role"). Do NOT output only "Dear [Name]," and "Add recipient email..."—that is forbidden. The body must read like a real application email. If no email address is in context, use recipient_email "recipient@example.com" and add one line at the very end: "Add recipient email in To field before sending."

**Google Sheets:** For "save to Google Sheet" you MUST use GOOGLESHEETS_CREATE_GOOGLE_SHEET (title from person/source) then GOOGLESHEETS_ADD_ROW or GOOGLESHEETS_APPEND_DATA with the extracted data. Put each field (name, title, post summary, profile info) in appropriate columns.

**Google Docs — existing doc vs new doc:**
- **If the user names an existing document** (e.g. "save the summary to the google doc named 'post summary'", "add to my doc 'Post Summary'", "save to existing doc 'X'"): do NOT create a new doc. Use GOOGLEDOCS_SEARCH_DOCUMENTS to find the document by title/name (e.g. query or title matching the name the user said). From the search result get the document ID, then use GOOGLEDOCS_INSERT_TEXT_ACTION with that documentId and the summary text (extracted from the page as below) to append to the existing doc. You may need two tool calls: first search, then insert.
- **If the user does NOT specify an existing doc name:** create a new doc with GOOGLEDOCS_CREATE_DOCUMENT_MARKDOWN (title + markdown with the summary). Do not use GOOGLEDOCS_CREATE_DOCUMENT (it creates an empty doc). NEVER ask "should I create a new one?" or "which doc?"—if they said "save to my google docs" or "save to google doc" without a doc name, immediately call GOOGLEDOCS_CREATE_DOCUMENT_MARKDOWN. Do not respond with text only; you MUST call the tool.
- **Extract from page:** For any summary, use the "Main content (full text from the page)" section above when present; otherwise read "Relevant page structure and text" and "Task spec". Write a real 2–4 sentence summary (or use the caption/post text as-is if the user asked for "caption text"). No generic "Summary of X post." Put that extracted summary in the doc (either as the markdown for a new doc or as the text for INSERT_TEXT_ACTION).

**Google Calendar:** Use GOOGLECALENDAR_CREATE_EVENT or GOOGLECALENDAR_QUICK_ADD; for delete use GOOGLECALENDAR_DELETE_EVENT.

**Notion:** Use NOTION_CREATE_PAGE only when the user explicitly asks to save to Notion.

If the user did not explicitly ask for an email, sheet, doc, calendar event, or Notion page, do NOT call any tools. If they did ask but you do not have the right tool connected, say briefly that the app is not connected. Only call tools when the user clearly requested one of these external actions.

When saving a summary or caption to a Google Doc: (1) When "Main content" is provided, use it—summarize into 2–4 sentences, or if the user asked for "caption text" use the main content as the body. Otherwise extract from page structure; only if content is missing use a one-line placeholder. (2) You MUST call the tools—never reply with only text or ask "should I create a new one?". If the user named an existing doc, call GOOGLEDOCS_SEARCH_DOCUMENTS then GOOGLEDOCS_INSERT_TEXT_ACTION. (3) If no existing doc was named (e.g. "save to my google docs", "save to google doc"), call GOOGLEDOCS_CREATE_DOCUMENT_MARKDOWN immediately with a title like "Venkat - LinkedIn post" and the markdown content. Do NOT ask for clarification; just create the doc. When drafting an application email (e.g. AI engineer): write a full email body with intro, qualifications, company interest, and closing—never just a greeting and a placeholder line."""

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
                fc = getattr(p, "function_call", None) or getattr(p, "functionCall", None)
                if fc:
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
    if len(tool_calls_done) == 0 and any(kw in (user_command or "").lower() for kw in ("save", "doc", "google", "gmail", "sheet", "calendar", "notion")):
        logger.warning("[Composio] model returned 0 tool_calls despite app-related command; summary may indicate missing extraction—check prompt/page_context")
    return {
        "summary": summary,
        "tool_calls": tool_calls_done,
        "error": None,
    }


def run_connector_step_with_conversation(
    entity_id: str,
    conversation: list[dict],
    latest_user_message: str,
    page_context: str,
    url: str,
    *,
    main_content: str | None = None,
    model: str = "gemini-2.0-flash",
) -> dict[str, Any]:
    """
    Run Composio with conversation history (chatbot follow-up). The user has replied to the
    assistant's previous message; use their reply to complete the action (e.g. create new doc,
    or add to existing doc). Returns same shape as run_connector_step.
    """
    logger.info("[Composio] run_connector_step_with_conversation entity_id=%s conv_len=%d latest=%r", entity_id, len(conversation), (latest_user_message or "")[:60])
    _ensure_composio()
    from google.genai import types

    tools = get_composio_tools(entity_id)
    if not tools:
        return {"summary": "No Composio tools available.", "tool_calls": [], "error": None}

    main_block = ""
    if main_content and main_content.strip():
        main_block = f"\n\nMain content (use for doc/sheet body):\n{main_content[:6000]}\n"

    conv_text = "\n".join(
        f"{m.get('role', 'user').capitalize()}: {m.get('content', '')}" for m in conversation
    )
    prompt = f"""You are an executive assistant with access to Composio tools. This is a follow-up in a conversation.

Conversation so far:
{conv_text}

User's latest reply: "{latest_user_message}"

Page URL: {url}
Relevant page structure: {page_context[:3000]}{main_block}

Use the user's latest reply to complete the action. For example: if they said "create a new one" or "yes, create one", call GOOGLEDOCS_CREATE_DOCUMENT_MARKDOWN with the main content above. If they gave a doc name, use GOOGLEDOCS_SEARCH_DOCUMENTS to find it then GOOGLEDOCS_INSERT_TEXT_ACTION. Do NOT ask more questions—perform the tool call now. Call the appropriate Composio tool (Google Docs, Sheets, Gmail, Calendar, Notion) based on what was discussed."""

    tools_for_config = [getattr(t, "_genai_tool", t) for t in tools] if tools else []
    if not tools_for_config:
        tools_for_config = tools
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
                fc = getattr(p, "function_call", None) or getattr(p, "functionCall", None)
                if fc:
                    round_calls.append({
                        "name": getattr(fc, "name", None) or "",
                        "args": getattr(fc, "args", None) or {},
                    })
            if not round_calls:
                break
            tool_calls_done.extend(round_calls)
            logger.info("[Composio] follow-up tool_calls (round %s): %s", _round + 1, round_calls)
            function_responses, executed = _COMPOSIO_CLIENT.provider.handle_response(response, tools)
            if not executed or not function_responses:
                break
            summary_parts.append(str(function_responses)[:500])
            response = chat.send_message(function_responses)
    except Exception as e:
        logger.exception("[Composio] connector step with conversation failed: %s", e)
        return {"summary": "", "tool_calls": tool_calls_done, "error": str(e)[:400]}

    summary = " ".join(summary_parts).strip() or "Done."
    return {"summary": summary, "tool_calls": tool_calls_done, "error": None}
