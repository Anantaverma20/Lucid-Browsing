"""
Scrape and health routes. Uses Browserbase.scraper.WebScraper.
POST /scrape, GET /scrape, GET /health. All config via WebScraper env.
"""
import re
import sys
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# Ensure repo root is on path so Browserbase can be imported when running backend.main
_repo_root = Path(__file__).resolve().parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from Browserbase.scraper import WebScraper

router = APIRouter(tags=["scrape"])
scraper = WebScraper()


def _normalize_scrape_url(raw: str) -> str:
    """Strip whitespace and common copy-paste prefixes (e.g. ' or http://...') so URL is valid."""
    url = (raw or "").strip()
    # Remove leading " or ", " and ", "or ", "and " (case insensitive)
    url = re.sub(r"^\s*(?:or|and)\s+", "", url, flags=re.IGNORECASE)
    return url.strip()


class ScrapeRequest(BaseModel):
    url: str  # Normalized in route so copy-paste like " or http://..." works
    refresh_cache: bool = False


class ArticleLink(BaseModel):
    url: str
    title: str
    image_url: str


class ScrapeResponse(BaseModel):
    url: str
    title: str
    article_links: List[ArticleLink]
    content: str
    scraped_at: Optional[str] = None


def _validate_and_format_result(result: dict, url: str) -> dict:
    if not result or not isinstance(result, dict):
        raise HTTPException(status_code=500, detail="Scraping returned invalid result format")
    article_links = result.get("article_links", [])
    if isinstance(article_links, list):
        formatted_links = []
        for link in article_links:
            if isinstance(link, dict):
                formatted_links.append({
                    "url": link.get("url", ""),
                    "title": link.get("title", ""),
                    "image_url": link.get("image_url", ""),
                })
        article_links = formatted_links
    else:
        article_links = []
    return {
        "url": result.get("url", url),
        "title": result.get("title", "Untitled"),
        "article_links": article_links,
        "content": result.get("content", "") if isinstance(result.get("content"), str) else "",
        "scraped_at": result.get("scraped_at"),
    }


@router.get("/health")
async def health():
    """Health check. Reports Redis and Browserbase status."""
    redis_status = "connected" if scraper.redis_client else "disconnected"
    return {
        "status": "healthy",
        "redis": redis_status,
        "browserbase": "configured" if scraper.browserbase_api_key else "not configured",
    }


@router.post("/scrape", response_model=ScrapeResponse)
async def scrape_url(request: ScrapeRequest):
    """Scrape a URL and return structured data (title, article_links, content)."""
    url_str = _normalize_scrape_url(request.url)
    if not url_str:
        raise HTTPException(status_code=400, detail="URL is required")
    if not url_str.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="URL must start with http:// or https://")
    try:
        result = await scraper.scrape(url_str, refresh_cache=request.refresh_cache)
        validated = _validate_and_format_result(result, url_str)
        return JSONResponse(content=validated)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scraping failed: {e}")


@router.get("/scrape", response_model=ScrapeResponse)
async def scrape_url_get(url: str):
    """Scrape a URL via GET (query param: url)."""
    if not url or not url.strip():
        raise HTTPException(status_code=400, detail="url parameter is required")
    url = _normalize_scrape_url(url)
    if not url:
        raise HTTPException(status_code=400, detail="URL is empty after normalization")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        result = await scraper.scrape(url)
        validated = _validate_and_format_result(result, url)
        return JSONResponse(content=validated)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scraping failed: {e}")
