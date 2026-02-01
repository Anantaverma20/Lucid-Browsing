InterestLens Chrome Extension
=============================

A modern AI-powered content authenticity checker with voice interaction.

FEATURES:
---------
- Modern UI with automatic light/dark mode (follows system preference)
- Displays article links with authenticity scores from AI analysis
- Color-coded badges: Green (80%+), Yellow (50-79%), Red (<50%)
- Voice interaction for hands-free control
- DOM manipulation to hide distractions/ads
- Stats summary showing average authenticity score

HOW TO LOAD:
------------
1) Open Chrome -> chrome://extensions
2) Enable "Developer mode" (toggle in top right)
3) Click "Load unpacked" and select this BrowserPlugin folder
4) The extension will automatically inject on all web pages

KEYBOARD SHORTCUTS:
-------------------
- Ctrl+Shift+S (Windows) / Cmd+Shift+S (Mac): Toggle sidebar visibility

VOICE COMMANDS:
---------------
Click the "Ask InterestLens" button and say:
- "Hide distractions" - Removes ads and distracting elements
- "Show distractions" / "Restore" - Brings back hidden elements
- "Show me [topic] content" - Highlights content about a specific topic
- "Reset" / "Clear highlight" - Restores all content visibility
- "What's the authenticity?" - Reads the average authenticity score

REQUIREMENTS:
-------------
The extension requires these backend services running:
1) Scraper API on http://localhost:8000 (Browserbase folder)
2) Scoring API on http://localhost:8001 (scoring/backend folder)

To start the backends:
  cd Browserbase && python api.py
  cd scoring/backend && python main.py

TESTING DARK MODE:
------------------
1) Open Chrome Settings -> Appearance
2) Set "Mode" to "Dark" or "System default"
3) Or use your OS dark mode setting
4) The sidebar will automatically switch themes

FILES:
------
- manifest.json  - Extension configuration
- background.js  - Service worker handling API calls
- content.js     - Sidebar DOM creation and manipulation
- sidebar.js     - Card rendering and voice interaction
- sidebar.css    - Modern UI styles with light/dark mode
