"""
Fact Hunter: for a single claim, search trusted sources (Tavily with include_domains)
and return evidence snippets (title, url, content).
"""
import logging
from typing import Any

import httpx

from backend import config
from backend.agents.truth.trusted_sources import TRUTH_TRUSTED_DOMAINS

logger = logging.getLogger(__name__)

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
MAX_RESULTS = 8


def search_claim(claim: str, *, timeout: float = 10.0) -> list[dict[str, Any]]:
    """
    Search for evidence supporting or contradicting the claim, restricted to trusted domains.
    Returns list of { "title", "url", "snippet" } (snippet = content from Tavily).
    """
    config.ensure_truth_config()
    api_key = config.TAVILY_API_KEY
    if not api_key:
        return []

    query = claim.strip()
    if not query:
        return []

    payload = {
        "api_key": api_key,
        "query": query,
        "search_depth": "basic",
        "max_results": min(MAX_RESULTS, 20),
        "include_domains": list(TRUTH_TRUSTED_DOMAINS)[:300],
        "include_answer": False,
    }

    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(TAVILY_SEARCH_URL, json=payload)
        if resp.status_code != 200:
            logger.warning("Tavily search returned %s: %s", resp.status_code, resp.text[:200])
            return []
        data = resp.json()
        results = data.get("results", []) if isinstance(data, dict) else []
        if not isinstance(results, list):
            return []
        out = []
        for r in results:
            if not isinstance(r, dict):
                continue
            title = r.get("title") or ""
            url = r.get("url") or ""
            content = r.get("content") or r.get("snippet") or ""
            out.append({"title": title, "url": url, "snippet": content})
        return out
    except Exception as e:
        logger.warning("Fact Hunter search failed: %s", e)
        return []
