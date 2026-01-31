"""
FastAPI server for web scraping with Browserbase.
Provides REST API endpoint to scrape URLs and return JSON.
"""

import traceback
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, HttpUrl
from dotenv import load_dotenv
from scraper import WebScraper

# Load environment variables
load_dotenv()

app = FastAPI(
    title="InterestLens Web Scraper",
    description="Scrape websites using Browserbase and extract article links, images, titles, and content",
    version="1.0.0"
)

# Initialize scraper
scraper = WebScraper()


class ScrapeRequest(BaseModel):
    url: HttpUrl


class ScrapeResponse(BaseModel):
    url: str
    title: str
    article_links: list
    images: list
    content: str
    scraped_at: Optional[str] = None


def validate_and_format_result(result: dict, url: str) -> dict:
    """Validate and format scraper result with defaults."""
    if not result or not isinstance(result, dict):
        raise HTTPException(
            status_code=500,
            detail="Scraping returned invalid result format"
        )
    
    return {
        "url": result.get("url", url),
        "title": result.get("title", "Untitled"),
        "article_links": result.get("article_links", []) if isinstance(result.get("article_links"), list) else [],
        "images": result.get("images", []) if isinstance(result.get("images"), list) else [],
        "content": result.get("content", "") if isinstance(result.get("content"), str) else "",
        "scraped_at": result.get("scraped_at")
    }


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "message": "InterestLens Web Scraper API",
        "endpoints": {
            "POST /scrape": "Scrape a URL and get structured data",
            "GET /health": "Check API health"
        }
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    redis_status = "connected" if scraper.redis_client else "disconnected"
    return {
        "status": "healthy",
        "redis": redis_status,
        "browserbase": "configured" if scraper.browserbase_api_key else "not configured"
    }


@app.post("/scrape", response_model=ScrapeResponse)
async def scrape_url(request: ScrapeRequest):
    """
    Scrape a URL and return structured data.
    
    - **url**: The website URL to scrape
    
    Returns JSON with:
    - title: Page title
    - article_links: List of article links found on the page
    - images: List of images found on the page
    - content: Main content text (ads removed)
    """
    try:
        url_str = str(request.url)
        result = await scraper.scrape(url_str)
        validated_result = validate_and_format_result(result, url_str)
        return JSONResponse(content=validated_result)
        
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        # Provide more detailed error information
        error_msg = str(e)
        error_detail = f"Scraping failed: {error_msg}"
        
        # Log the full traceback for debugging (in production, use proper logging)
        print(f"Error traceback: {traceback.format_exc()}")
        
        raise HTTPException(status_code=500, detail=error_detail)


@app.get("/scrape")
async def scrape_url_get(url: str):
    """
    Scrape a URL via GET request (for convenience).
    
    Query parameter:
    - **url**: The website URL to scrape
    """
    if not url:
        raise HTTPException(status_code=400, detail="URL parameter is required")
    
    try:
        # Ensure URL has protocol
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        
        result = await scraper.scrape(url)
        validated_result = validate_and_format_result(result, url)
        return JSONResponse(content=validated_result)
        
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        # Provide more detailed error information
        error_msg = str(e)
        error_detail = f"Scraping failed: {error_msg}"
        
        # Log the full traceback for debugging (in production, use proper logging)
        print(f"Error traceback: {traceback.format_exc()}")
        
        raise HTTPException(status_code=500, detail=error_detail)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
