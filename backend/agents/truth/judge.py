"""
Truth Judge: given a claim and evidence snippets, return verdict (True/False/Unverified),
confidence 0-100, explanation, and best source_url.
"""
import json
import logging
import re
import os
from typing import Any, Literal

from backend import config

logger = logging.getLogger(__name__)

Verdict = Literal["True", "False", "Unverified"]


def judge_claim(
    claim: str,
    evidence: list[dict[str, Any]],
    *,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """
    Evaluate whether evidence supports, contradicts, or is insufficient for the claim.
    Returns: { "verdict": "True"|"False"|"Unverified", "confidence": 0-100, "explanation": str, "source_url": str|None }
    """
    config.ensure_truth_config()
    api_key = os.environ.get("GOOGLE_API_KEY") or getattr(config, "GOOGLE_API_KEY", None) or ""
    if not api_key:
        return {
            "verdict": "Unverified",
            "confidence": 0,
            "explanation": "Missing API key for Truth Judge.",
            "source_url": None,
        }

    evidence_text = ""
    best_url: str | None = None
    for i, e in enumerate(evidence[:10]):
        title = e.get("title") or ""
        url = e.get("url") or ""
        snippet = e.get("snippet") or e.get("content") or ""
        if url and best_url is None:
            best_url = url
        evidence_text += f"[Source {i + 1}] {title}\nURL: {url}\n{snippet}\n\n"

    if not evidence_text.strip():
        evidence_text = "(No evidence from trusted sources found.)"

    prompt = f"""You are a fact-checker. Evaluate whether the EVIDENCE supports, contradicts, or is insufficient to verify the CLAIM.

CLAIM: {claim}

EVIDENCE from trusted news/fact-check sources:
{evidence_text[:8000]}

Respond with a JSON object with exactly these keys:
- "verdict": one of "True", "False", "Unverified"
  - "True" = evidence from trusted sources supports the claim
  - "False" = evidence contradicts or debunks the claim
  - "Unverified" = evidence is missing or insufficient to decide
- "confidence": number 0-100 (how confident you are in the verdict)
- "explanation": one sentence citing the source (e.g. "Refuted by AP News: actual revenue was lower.")
- "source_url": the URL of the best supporting or refuting article, or null if Unverified

Output ONLY valid JSON, no markdown or other text."""

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.2,
                response_mime_type="application/json",
            ),
        )
        if not response or not response.text:
            return {
                "verdict": "Unverified",
                "confidence": 0,
                "explanation": "No response from Judge model.",
                "source_url": best_url,
            }
        raw = response.text.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```\w*\n?", "", raw)
            raw = re.sub(r"\n?```\s*$", "", raw)
        data = json.loads(raw)
        verdict = data.get("verdict") or "Unverified"
        if verdict not in ("True", "False", "Unverified"):
            verdict = "Unverified"
        confidence = data.get("confidence")
        if not isinstance(confidence, (int, float)):
            confidence = 0
        confidence = max(0, min(100, int(confidence)))
        explanation = (data.get("explanation") or "").strip() or "No explanation."
        source_url = data.get("source_url") if data.get("source_url") else best_url
        return {
            "verdict": verdict,
            "confidence": confidence,
            "explanation": explanation,
            "source_url": source_url,
        }
    except Exception as e:
        logger.warning("Truth Judge failed: %s", e)
        return {
            "verdict": "Unverified",
            "confidence": 0,
            "explanation": f"Judge error: {str(e)[:200]}",
            "source_url": best_url,
        }
