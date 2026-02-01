// API endpoints
const SCRAPER_API = "http://localhost:8000";
const SCORING_API = "http://localhost:8001";

// NOTE: Content scripts are automatically injected by manifest.json content_scripts
// We don't need to manually inject them on tab updates - that causes duplicates!

// Send DOM action to content script
const sendDomAction = async (tabId, action, params = {}) => {
  try {
    const response = await chrome.tabs.sendMessage(tabId, {
      type: "interestlens:dom-action",
      action,
      params
    });
    return response;
  } catch (error) {
    console.error("Failed to send DOM action:", error);
    return { ok: false, error: error.message };
  }
};

// Toggle sidebar visibility
const toggleSidebar = async (tabId) => {
  try {
    await chrome.tabs.sendMessage(tabId, {
      type: "interestlens:toggle-sidebar"
    });
  } catch (error) {
    console.error("Failed to toggle sidebar:", error);
  }
};

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  // Scrape request
  if (message?.type === "interestlens:scrape") {
    const payload = { url: message.url };
    if (message.refreshCache) {
      payload.refresh_cache = true;
    }
    
    fetch(`${SCRAPER_API}/scrape`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`Status ${response.status}`);
        }
        const data = await response.json();
        sendResponse({ ok: true, data });
      })
      .catch((error) => {
        sendResponse({ ok: false, error: error?.message || "Request failed" });
      });

    return true;
  }

  // Authenticity check request
  if (message?.type === "interestlens:authenticity") {
    fetch(`${SCORING_API}/check_authenticity/batch`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(message.payload)
    })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`Status ${response.status}`);
        }
        const data = await response.json();
        sendResponse({ ok: true, data });
      })
      .catch((error) => {
        sendResponse({ ok: false, error: error?.message || "Request failed" });
      });

    return true;
  }

  // Voice session request (Daily + Pipecat)
  if (message?.type === "interestlens:voice-session") {
    fetch(`${SCORING_API}/voice/start-session`, {
      method: "POST",
      headers: { 
        "Content-Type": "application/json"
      }
    })
      .then(async (response) => {
        if (!response.ok) {
          if (response.status === 401 || response.status === 403) {
            throw new Error("Authentication required. Using browser voice recognition instead.");
          }
          throw new Error(`Status ${response.status}`);
        }
        const data = await response.json();
        sendResponse({ ok: true, data });
      })
      .catch((error) => {
        sendResponse({ 
          ok: false, 
          error: error?.message || "Voice session unavailable",
          fallback: "web-speech-api"
        });
      });

    return true;
  }

  // DOM action request (from voice commands or other sources)
  if (message?.type === "interestlens:execute-dom-action") {
    const { action, params } = message;
    
    chrome.tabs.query({ active: true, currentWindow: true }, async (tabs) => {
      if (tabs.length > 0) {
        const result = await sendDomAction(tabs[0].id, action, params);
        sendResponse(result);
      } else {
        sendResponse({ ok: false, error: "No active tab" });
      }
    });

    return true;
  }

  return false;
});

// Handle keyboard shortcuts
chrome.commands?.onCommand?.addListener((command) => {
  if (command === "toggle-sidebar") {
    chrome.tabs.query({ active: true, currentWindow: true }, async (tabs) => {
      if (tabs.length > 0) {
        await toggleSidebar(tabs[0].id);
      }
    });
  }
});
