"""
FastAPI server for web scraping with Browserbase.
Provides REST API endpoint to scrape URLs and return JSON.
"""

import traceback
from typing import Optional, List
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
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

# Configure CORS middleware for browser frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origins: ["http://localhost:3000", "https://yourdomain.com"]
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods: GET, POST, OPTIONS, etc.
    allow_headers=["*"],  # Allows all headers
)

# Initialize scraper
scraper = WebScraper()


class ScrapeRequest(BaseModel):
    url: HttpUrl


class ArticleLink(BaseModel):
    """Schema for individual article links."""
    url: str
    title: str
    image_url: str


class ScrapeResponse(BaseModel):
    """Response schema for scraped data."""
    url: str
    title: str
    article_links: List[ArticleLink]  # Each link contains: url, title, image_url
    content: str
    scraped_at: Optional[str] = None


def validate_and_format_result(result: dict, url: str) -> dict:
    """Validate and format scraper result with defaults."""
    if not result or not isinstance(result, dict):
        raise HTTPException(
            status_code=500,
            detail="Scraping returned invalid result format"
        )
    
    # Ensure article_links have the correct structure
    article_links = result.get("article_links", [])
    if isinstance(article_links, list):
        # Validate and format each link to ensure it has url, title, image_url
        formatted_links = []
        for link in article_links:
            if isinstance(link, dict):
                formatted_links.append({
                    "url": link.get("url", ""),
                    "title": link.get("title", ""),
                    "image_url": link.get("image_url", "")
                })
        article_links = formatted_links
    else:
        article_links = []
    
    return {
        "url": result.get("url", url),
        "title": result.get("title", "Untitled"),
        "article_links": article_links,
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
            "GET /scrape": "Scrape a URL via GET request (query parameter: ?url=...)",
            "GET /health": "Check API health",
            "OPTIONS /scrape": "CORS preflight support (handled automatically by CORS middleware)",
            "OPTIONS /": "CORS preflight for root endpoint (handled automatically)"
        },
        "frontend_integration": {
            "cors": True,
            "cors_enabled": True,
            "usage_example": {
                "curl": "curl -X POST -H \"Content-Type: application/json\" -d '{\"url\": \"https://example.com\"}' http://localhost:8000/scrape",
                "js_fetch": "fetch('http://localhost:8000/scrape', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({url: 'https://example.com'}) })",
                "js_fetch_get": "fetch('http://localhost:8000/scrape?url=https://example.com')"
            },
            "response_schema": {
                "url": "string - The scraped URL",
                "title": "string - Page title",
                "article_links": "array of objects - Each contains: {url: string, title: string, image_url: string}",
                "content": "string - Main content text (ads removed)",
                "scraped_at": "string (ISO format) - Timestamp of scraping"
            },
            "frontend_status": "Ready for direct browser integration - CORS middleware enabled"
        }
    }


@app.options("/")
async def root_options():
    """CORS preflight handler for root endpoint."""
    return JSONResponse(content={}, headers={
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Access-Control-Allow-Headers": "*",
    })


@app.options("/scrape")
async def scrape_options():
    """CORS preflight handler for scrape endpoint."""
    return JSONResponse(content={}, headers={
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "*",
    })


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
    - article_links: List of article links (each with url, title, image_url)
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


@app.get("/scrape", response_model=ScrapeResponse)
async def scrape_url_get(url: str):
    """
    Scrape a URL via GET request (for convenience).
    
    Query parameter:
    - **url**: The website URL to scrape
    
    Returns JSON with:
    - title: Page title
    - article_links: List of article links (each with url, title, image_url)
    - content: Main content text (ads removed)
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
