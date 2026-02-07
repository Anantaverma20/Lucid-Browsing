# Lucid Browsing Web Scraper

A web scraping service that uses Browserbase to extract structured information from websites. Extracts article links, images, titles, and content while removing ads. Results are cached in Redis.

## Features

- 🌐 **Browserbase Integration**: Uses Browserbase for reliable browser automation
- 📰 **Content Extraction**: Extracts article links, images, titles, and main content
- 🚫 **Ad Removal**: Automatically filters out advertisements and promotional content
- 💾 **Redis Caching**: Caches results in Redis to avoid redundant scraping
- 🔌 **REST API**: FastAPI-based REST API for easy integration
- 📝 **CLI Support**: Command-line interface for direct usage

## Setup

### 1. Install Dependencies

```bash
# Activate virtual environment
.\venv\Scripts\Activate.ps1  # Windows PowerShell
# or
.\venv\Scripts\activate.bat  # Windows CMD

# Install Python packages
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium
```

### 2. Configure Environment Variables

Update the `.env` file with your credentials:

```env
BROWSERBASE_PROJECT_ID=your-project-id
BROWSERBASE_API_KEY=your-api-key

# Redis Configuration (choose one):
# Option 1: Redis URL (for Redis Cloud)
REDIS_URL=redis://default:password@host:port

# Option 2: Individual parameters
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=your-password
REDIS_DB=0
```

### 3. Redis Setup

If using Redis Cloud:
1. Get your Redis connection URL from your Redis Cloud dashboard
2. Add it to `.env` as `REDIS_URL`

If using local Redis:
1. Install Redis: https://redis.io/download
2. Start Redis server
3. Update `.env` with connection details

## Usage

### Command Line Interface

The CLI tool will:
- Ask for a URL (or accept it as a command-line argument)
- Use Browserbase to scrape the website
- Save results to Redis (cached for 24 hours)
- Save JSON output to `output/` folder locally

```bash
# Scrape a URL interactively (will prompt for URL)
python scraper.py

# Or provide URL as argument
python scraper.py https://example.com
```

**Output:**
- JSON files are saved in the `output/` folder
- Filename format: `scrape_YYYYMMDD_HHMMSS_[url_hash].json`
- Results are also cached in Redis for 24 hours

### REST API Server

Start the API server:

```bash
python api.py
```

Or using uvicorn directly:

```bash
uvicorn api:app --reload
```

The API will be available at `http://localhost:8000`

#### API Endpoints

**POST /scrape**
```bash
curl -X POST "http://localhost:8000/scrape" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'
```

**GET /scrape** (convenience endpoint)
```bash
curl "http://localhost:8000/scrape?url=https://example.com"
```

**GET /health**
```bash
curl "http://localhost:8000/health"
```

**GET /**
```bash
curl "http://localhost:8000/"
```

#### API Response Format

```json
{
  "url": "https://example.com",
  "title": "Example Domain",
  "article_links": [
    {
      "url": "https://example.com/article1",
      "title": "Article Title"
    }
  ],
  "images": [
    {
      "url": "https://example.com/image.jpg",
      "alt": "Image description"
    }
  ],
  "content": "Main content text with ads removed...",
  "scraped_at": "2026-01-31T12:00:00.000Z"
}
```

## How It Works

1. **URL Input**: Takes a website URL as input
2. **Browserbase Session**: Creates a browser session using Browserbase
3. **Page Loading**: Loads the page and waits for content to render
4. **HTML Parsing**: Parses the HTML using BeautifulSoup
5. **Ad Removal**: Removes ad elements based on common patterns
6. **Content Extraction**:
   - Extracts page title (from `<title>`, `og:title`, or `<h1>`)
   - Finds article links in main content areas
   - Extracts images with alt text
   - Extracts main content text (excluding navigation, ads, etc.)
7. **Redis Caching**: Stores results in Redis (24-hour TTL)
8. **JSON Output**: Returns structured JSON response

## Project Structure

```
Lucid Browsing/
├── .env                 # Environment variables
├── requirements.txt     # Python dependencies
├── scraper.py          # Main scraper class and CLI
├── api.py              # FastAPI REST API server
└── README.md           # This file
```

## Notes

- Results are cached in Redis for 24 hours to avoid redundant scraping
- The scraper automatically filters out ads based on common class names and IDs
- Content extraction focuses on main article/content areas
- Images smaller than 50x50 pixels are filtered out (likely icons/sprites)
- Maximum limits: 50 article links, 30 images, 10,000 characters of content

## Troubleshooting

**Redis Connection Issues:**
- Check your Redis credentials in `.env`
- Ensure Redis server is running (if using local Redis)
- Verify network connectivity (if using Redis Cloud)

**Browserbase Errors:**
- Verify your API key and project ID in `.env`
- Check your Browserbase account quota/limits

**Playwright Errors:**
- Run `playwright install chromium` to install browser binaries
- Ensure you have sufficient system resources

## License

MIT
