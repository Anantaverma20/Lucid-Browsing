# Lucid Browsing

A Chrome extension that helps you browse with clarity: scrape and score article links, automate page actions with natural language, and speak commands using voice (MiniMax or OpenAI Whisper).

## Features

- **Sidebar** – Toggle a sidebar on any page to see article links and run commands.
- **Scraping** – Fetches and scores article links from the current page (Browserbase + optional Redis cache).
- **Automation** – Describe what you want in plain English (e.g. “Click the login button”, “Hide the weather card”); the backend generates and validates a script, then the extension runs it on the page.
- **Voice** – Use the microphone button to speak a command; audio is sent to the backend, transcribed with MiniMax (if `MINIMAX_API_KEY` or `MINI_MAX_API_KEY` is set) or OpenAI Whisper, and the text is filled into the command box. Click **Run** (or press Enter) to execute.
- **Optional integrations** – Composio bridge for Gmail, Google Docs/Sheets, Notion, Calendar, etc., when you explicitly ask (e.g. “Save this to a Google Doc”).

## Project structure

```
├── backend/                 # FastAPI app (port 8001): automate, scrape, voice
│   ├── agents/automation/   # Planner, writer, checker, validator, executor
│   ├── routes/              # automate, scrape, voice (MiniMax / Whisper)
│   └── services/            # Composio, headless browser, Daytona sandbox
├── Browserbase/             # Scraper API (port 8000) – optional separate service
├── BrowserPlugin/           # Chrome extension (manifest v3)
│   ├── icons/               # Extension icons (16, 48, 128)
│   ├── background.js        # Service worker (API calls, voice upload)
│   ├── content.js           # Injects sidebar
│   └── sidebar.js            # UI logic, scrape, automate, voice recording
├── .env.example             # Copy to .env and fill in keys
├── run_backend.bat          # Start backend on 8001
└── run_scraper.bat          # Start Browserbase scraper on 8000
```

## Prerequisites

- **Python 3.10+** and a virtual environment
- **Chrome** (or Chromium-based browser) for the extension
- API keys (see [Environment](#environment))

## Setup

1. **Clone and enter the repo**
   ```bash
   git clone https://github.com/Anantaverma20/Lucid-Browsing.git
   cd Lucid-Browsing
   ```

2. **Create a virtual environment and install dependencies**
   ```bash
   python -m venv venv
   venv\Scripts\activate          # Windows
   # source venv/bin/activate      # macOS/Linux
   pip install -r backend/requirements.txt
   ```
   For the Browserbase scraper (port 8000):  
   `pip install -r Browserbase/requirements.txt`

3. **Environment**
   - Copy `.env.example` to `.env`
   - Fill in at least:
     - `BROWSERBASE_API_KEY`, `BROWSERBASE_PROJECT_ID` (scraping)
     - `GOOGLE_API_KEY` (Gemini, for automation)
     - `MINIMAX_API_KEY` or `MINI_MAX_API_KEY` and/or `OPENAI_API_KEY` (optional: **voice transcription**; MiniMax tried first, then Whisper. OpenAI also used for ad removal.)
   - See `.env.example` for Composio, Redis, Daytona, etc.

4. **Start the backend**
   - **Backend (required for extension):** port **8001**  
     `run_backend.bat` or:  
     `uvicorn backend.main:app --host 127.0.0.1 --port 8001`
   - **Scraper API (optional):** port **8000**  
     `run_scraper.bat` or:  
     `uvicorn Browserbase.api:app --host 127.0.0.1 --port 8000`

5. **Load the extension**
   - Open Chrome → `chrome://extensions`
   - Enable **Developer mode**
   - Click **Load unpacked** and select the `BrowserPlugin` folder

## Usage

- **Toggle sidebar:** `Ctrl+Shift+S` (Windows) / `Cmd+Shift+S` (Mac), or use the extension icon.
- **Article links:** Open the sidebar; it will scrape the page and show links (with backend on 8001; scraper on 8000 if used).
- **Automation:** Type a command (e.g. “Click the login button”) and click **Run**, or press Enter.
- **Voice:** Click the microphone, speak your command, click again to stop. The transcribed text is placed in the command box; click **Run** (or Enter) to execute.

## Environment

| Variable | Purpose |
|----------|---------|
| `BROWSERBASE_API_KEY`, `BROWSERBASE_PROJECT_ID` | Scraping (Browserbase) |
| `GOOGLE_API_KEY` | Automation agent (Gemini) |
| `MINIMAX_API_KEY` or `MINI_MAX_API_KEY` | Optional: **voice transcription** (tried first) |
| `OPENAI_API_KEY` | Optional: ad removal + **voice transcription (Whisper fallback)** |
| `COMPOSIO_API_KEY`, `COMPOSIO_ENTITY_ID` | Optional: Gmail, Docs, Notion, Calendar, etc. |
| `REDIS_URL` | Optional: cache scrape results |
| `BEM_API_KEY`, `TAVILY_API_KEY` | News Truth (Verify Truth / fact-check) |

Full list and comments are in `.env.example`. Do not commit `.env`.

## License

See repository for license information.
