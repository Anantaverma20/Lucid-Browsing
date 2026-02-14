"""
Bem.ai client for News Truth: extract claims, is_opinion, entities from URL or image.
When BEM_API_KEY is set, attempts Bem API (async/webhook in practice); falls back to
Gemini extraction from text or image so the feature works without Bem.
"""
import base64
import json
import logging
import re
from typing import Any

from backend import config

logger = logging.getLogger(__name__)

# JSON schema shape for extraction output (one or more items)
TRUTH_EXTRACTION_SCHEMA = {
    "items": [
        {
            "claims": ["string"],
            "is_opinion": False,
            "entities": ["string"],
        }
    ]
}


def _extract_with_gemini_text(text: str) -> list[dict[str, Any]]:
    """Use Gemini to extract claims, is_opinion, entities from plain text. Returns list of items."""
    config.ensure_truth_config()
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        raise RuntimeError("google-genai is required for Truth extraction fallback.")

    import os
    api_key = os.environ.get("GOOGLE_API_KEY") or getattr(config, "GOOGLE_API_KEY", None) or ""
    client = genai.Client(api_key=api_key)
    prompt = f"""Extract from the following text all factual claims that can be verified or debunked by news/fact-checkers.
Ignore opinions, predictions, and subjective statements.

Return a JSON object with a single key "items" which is an array of objects. Each object has:
- "claims": array of strings (each string is one specific, testable factual claim)
- "is_opinion": boolean (true if this item is opinion/subjective, false if factual)
- "entities": array of strings (people, organizations mentioned)

Only include items where is_opinion is false for fact-checking. But still list opinion items with is_opinion true so we can filter them out.
Output ONLY valid JSON, no markdown or explanation.

Text:
---
{text[:12000]}
---
JSON:"""

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.2,
            response_mime_type="application/json",
        ),
    )
    if not response or not response.text:
        return []
    raw = response.text.strip()
    # Strip markdown code block if present
    if raw.startswith("```"):
        raw = re.sub(r"^```\w*\n?", "", raw)
        raw = re.sub(r"\n?```\s*$", "", raw)
    data = json.loads(raw)
    items = data.get("items", [])
    if isinstance(items, list):
        return items
    return []


def _extract_with_gemini_image(image_bytes: bytes, mime_type: str = "image/png") -> list[dict[str, Any]]:
    """Use Gemini vision to extract claims, is_opinion, entities from an image. Returns list of items."""
    config.ensure_truth_config()
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        raise RuntimeError("google-genai is required for Truth extraction fallback.")

    import os
    api_key = os.environ.get("GOOGLE_API_KEY") or getattr(config, "GOOGLE_API_KEY", None) or ""
    client = genai.Client(api_key=api_key)
    prompt = """Extract from this image all factual claims that can be verified or debunked by news/fact-checkers (e.g. text in a screenshot, meme, or article image).
Ignore opinions and subjective statements.

Return a JSON object with a single key "items" which is an array of objects. Each object has:
- "claims": array of strings (each string is one specific, testable factual claim)
- "is_opinion": boolean (true if this item is opinion/subjective, false if factual)
- "entities": array of strings (people, organizations mentioned)
Output ONLY valid JSON, no markdown or explanation."""

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=[
            types.Content(
                role="user",
                parts=[
                    types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                    types.Part.from_text(text=prompt),
                ],
            )
        ],
        config=types.GenerateContentConfig(
            temperature=0.2,
            response_mime_type="application/json",
        ),
    )
    if not response or not response.text:
        return []
    raw = response.text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```\w*\n?", "", raw)
        raw = re.sub(r"\n?```\s*$", "", raw)
    data = json.loads(raw)
    items = data.get("items", [])
    if isinstance(items, list):
        return items
    return []


def _try_bem_image(image_bytes: bytes, filename: str = "image.png") -> list[dict[str, Any]] | None:
    """Try Bem API with image file. Returns None if not configured or async/error (caller should fallback)."""
    if not config.BEM_API_KEY:
        return None
    try:
        import httpx
        url = f"{config.BEM_API_BASE.rstrip('/')}/v2/functions/{config.BEM_TRANSFORM_FUNCTION}/call"
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                url,
                headers={"x-api-key": config.BEM_API_KEY},
                files={"file": (filename, image_bytes, "image/png")},
            )
        if resp.status_code != 200:
            if resp.status_code == 404 and "function not found" in (resp.text or "").lower():
                logger.info(
                    "Bem: function %r not found (create it in Bem dashboard or set BEM_TRANSFORM_FUNCTION). Using Gemini fallback.",
                    config.BEM_TRANSFORM_FUNCTION,
                )
            else:
                logger.warning("Bem API returned %s: %s", resp.status_code, (resp.text or "")[:200])
            return None
        data = resp.json()
        # Normalize to list of items with claims, is_opinion, entities
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            if "items" in data:
                return data["items"]
            if "claims" in data:
                return [{"claims": data["claims"], "is_opinion": data.get("is_opinion", False), "entities": data.get("entities", [])}]
        return None
    except Exception as e:
        logger.warning("Bem API call failed: %s", e)
        return None


def _try_bem_url(url: str) -> list[dict[str, Any]] | None:
    """Try Bem API with URL. Returns None if not configured or async/error."""
    if not config.BEM_API_KEY:
        return None
    try:
        import httpx
        # Some Bem setups accept URL in metadata; if not, we fallback to Gemini after fetch
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            page_resp = client.get(url)
        if page_resp.status_code != 200:
            return None
        html = page_resp.text
        if not html or len(html) > 500_000:
            return None
        # Try sending as file (HTML)
        bem_url = f"{config.BEM_API_BASE.rstrip('/')}/v2/functions/{config.BEM_TRANSFORM_FUNCTION}/call"
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                bem_url,
                headers={"x-api-key": config.BEM_API_KEY},
                files={"file": ("page.html", html.encode("utf-8"), "text/html")},
            )
        if resp.status_code != 200:
            if resp.status_code == 404 and "function not found" in (resp.text or "").lower():
                logger.info(
                    "Bem: function %r not found. Using Gemini fallback.",
                    config.BEM_TRANSFORM_FUNCTION,
                )
            else:
                logger.warning("Bem API (URL) returned %s: %s", resp.status_code, (resp.text or "")[:200])
            return None
        data = resp.json()
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "items" in data:
            return data["items"]
        if isinstance(data, dict) and "claims" in data:
            return [{"claims": data["claims"], "is_opinion": data.get("is_opinion", False), "entities": data.get("entities", [])}]
        return None
    except Exception as e:
        logger.warning("Bem URL fetch/call failed: %s", e)
        return None


def extract_claims(
    *,
    url: str | None = None,
    content: str | None = None,
    image_bytes: bytes | None = None,
    image_base64: str | None = None,
) -> list[dict[str, Any]]:
    """
    Extract structured items (claims, is_opinion, entities) from URL, text content, or image.
    Returns list of dicts with keys: claims (list[str]), is_opinion (bool), entities (list[str]).
    """
    if image_base64:
        try:
            image_bytes = base64.b64decode(image_base64)
        except Exception:
            image_bytes = None
    if image_bytes:
        # Prefer Bem for image if configured
        items = _try_bem_image(image_bytes)
        if items is not None and len(items) > 0:
            return items
        return _extract_with_gemini_image(image_bytes)
    if url and (content is None or not content.strip()):
        # Try Bem with URL (fetch inside)
        items = _try_bem_url(url)
        if items is not None and len(items) > 0:
            return items
        # Fallback: fetch URL and use Gemini on text
        try:
            import httpx
            with httpx.Client(timeout=15.0, follow_redirects=True) as client:
                r = client.get(url)
            if r.status_code == 200 and r.text:
                content = r.text
                # Strip HTML tags roughly for Gemini
                if "<" in content:
                    import re
                    content = re.sub(r"<[^>]+>", " ", content)
                    content = re.sub(r"\s+", " ", content).strip()[:15000]
        except Exception as e:
            logger.warning("Fetch URL for extraction failed: %s", e)
    if content and content.strip():
        return _extract_with_gemini_text(content[:15000])
    return []


def flatten_and_filter_claims(items: list[dict[str, Any]]) -> list[str]:
    """
    From Bem/Gemini extraction items, discard opinion items and return a flat list of claim strings.
    """
    claims: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("is_opinion") is True:
            continue
        for c in item.get("claims") or []:
            if isinstance(c, str) and c.strip():
                claims.append(c.strip())
    return claims
