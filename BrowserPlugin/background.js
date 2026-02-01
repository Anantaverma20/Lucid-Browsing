const CONTENT_FILES = ["content.js", "sidebar.js"];
const STYLE_FILES = ["sidebar.css"];

const isInjectableUrl = (url) => {
  if (!url) {
    return false;
  }
  return url.startsWith("http://") || url.startsWith("https://");
};

const injectSidebar = async (tabId) => {
  try {
    await chrome.scripting.insertCSS({
      target: { tabId },
      files: STYLE_FILES
    });
  } catch (error) {
    // Ignore insertCSS errors (e.g., already injected).
  }

  try {
    await chrome.scripting.executeScript({
      target: { tabId },
      files: CONTENT_FILES,
      world: "ISOLATED"
    });
  } catch (error) {
    // Ignore executeScript errors (e.g., non-injectable pages).
  }
};

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status !== "complete") {
    return;
  }
  if (!isInjectableUrl(tab.url)) {
    return;
  }
  injectSidebar(tabId);
});

chrome.runtime.onInstalled.addListener(async () => {
  const tabs = await chrome.tabs.query({});
  await Promise.all(
    tabs
      .filter((tab) => isInjectableUrl(tab.url))
      .map((tab) => injectSidebar(tab.id))
  );
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type === "interestlens:scrape") {
    const payload = { url: message.url };
    if (message.refreshCache) {
      payload.refresh_cache = true;
    }
    fetch("http://localhost:8000/scrape", {
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

  if (message?.type === "interestlens:authenticity") {
    fetch("http://localhost:8001/check_authenticity/batch", {
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

  return false;
});
