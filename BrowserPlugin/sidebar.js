(() => {
  const sidebar = window.__interestLensSidebar;
  if (!sidebar) {
    console.log("InterestLens: Waiting for sidebar...");
    return;
  }
  if (sidebar._initialized) return;
  sidebar._initialized = true;

  const MAX_CARDS = 12;
  const ICONS = sidebar.ICONS || {};

  const normalizeExtensionError = (msg) => {
    if (!msg || typeof msg !== "string") return msg;
    const m = msg.toLowerCase();
    if (m.includes("extension context invalidated") || m.includes("context invalidated")) {
      return "Extension was reloaded. Refresh this page (F5) and try again.";
    }
    return msg;
  };

  const clearBody = () => {
    if (sidebar.body) sidebar.body.innerHTML = "";
  };

  const renderLoading = (message = "Loading...") => {
    clearBody();
    if (!sidebar.body) return;
    sidebar.body.innerHTML = `
      <div class="il-loading">
        <div class="il-spinner"></div>
        <div class="il-loading-text">${message}</div>
      </div>
    `;
  };

  const renderEmpty = (title, desc) => {
    clearBody();
    if (!sidebar.body) return;
    sidebar.body.innerHTML = `
      <div class="il-empty">
        <div class="il-empty-icon">${ICONS.empty || ""}</div>
        <div class="il-empty-title">${title || "No content found"}</div>
        <div class="il-empty-desc">${desc || "Try a different page."}</div>
      </div>
    `;
  };

  const renderError = (message) => {
    clearBody();
    if (!sidebar.body) return;
    sidebar.body.innerHTML = `
      <div class="il-error">
        <div class="il-error-icon">${ICONS.alert || ""}</div>
        <div class="il-error-text">${message || "Something went wrong"}</div>
      </div>
    `;
  };

  const buildCard = (data) => {
    const card = document.createElement("a");
    card.className = "il-card";
    card.href = data.url;
    card.target = "_blank";
    card.rel = "noopener";
    const hasImage = data.imageUrl && data.imageUrl.length > 0;
    let domain = data.url;
    try {
      domain = new URL(data.url).hostname.replace("www.", "");
    } catch (e) {}
    card.innerHTML = `
      <div class="il-card-image">
        ${hasImage ? `<img src="${data.imageUrl}" alt="" loading="lazy" onerror="this.parentElement.innerHTML='<div class=il-card-placeholder>No image</div>'">` : '<div class="il-card-placeholder">No image</div>'}
      </div>
      <div class="il-card-content">
        <div class="il-card-title">${(data.title || "Untitled").replace(/</g, "&lt;")}</div>
        <div class="il-card-desc">${domain.replace(/</g, "&lt;")}</div>
      </div>
    `;
    return card;
  };

  const requestScrape = (url, refreshCache = false) => {
    return new Promise((resolve, reject) => {
      try {
        chrome.runtime.sendMessage(
          { type: "interestlens:scrape", url, refreshCache },
          (response) => {
            if (chrome.runtime.lastError) {
              reject(new Error(normalizeExtensionError(chrome.runtime.lastError.message)));
              return;
            }
            if (!response || !response.ok) {
              reject(new Error(response?.error || "Scrape failed"));
              return;
            }
            resolve(response.data);
          }
        );
      } catch (e) {
        reject(new Error(normalizeExtensionError(e?.message || "Request failed")));
      }
    });
  };

  // Capture page structure (DOM summary) from the actual tab the user sees.
  // Logic adapted from backend/services/headless_browser.py _DOM_SUMMARY_SCRIPT.
  const getPageContext = () => {
    const lines = [];
    const maxLines = 150;
    const textLen = 50;
    const maxChars = 6000;
    const seen = new Set();
    const validClass = /^[a-zA-Z_][a-zA-Z0-9_-]*$/;
    const validId = /^[a-zA-Z_][a-zA-Z0-9_-]*$/;
    const add = (el) => {
      if (lines.length >= maxLines || !el || seen.has(el)) return;
      seen.add(el);
      const id = el.id && validId.test(el.id) ? "#" + el.id : "";
      let cls = "";
      if (typeof el.className === "string" && el.className) {
        const safe = el.className.trim().split(/\s+/).filter((c) => validClass.test(c)).slice(0, 3);
        if (safe.length) cls = "." + safe.join(".");
      }
      const tag = el.tagName ? el.tagName.toLowerCase() : "?";
      let text = (el.innerText || el.textContent || "").replace(/\s+/g, " ").trim().slice(0, textLen);
      if (text) text = ' "' + text + '"';
      lines.push(tag + id + cls + text);
    };
    try {
      const semantic = 'section, article, aside, main, header, footer, nav, [role="region"], [role="complementary"], [role="main"], [role="banner"], [role="contentinfo"]';
      const commonUI = '[class*="card"], [class*="widget"], [class*="item"], [class*="block"], [class*="box"], [class*="panel"], [class*="container"], [class*="section"], .sidebar, .side-bar, .feed-item, .promo, .banner, [data-testid], [data-component]';
      const adsWeather = '[id*="ad"], [id*="Ad"], [class*="ad"], [class*="Ad"], [data-ad], .sponsored, [class*="sponsor"], [id*="banner"], [id*="weather"], [id*="Weather"], [class*="weather"], [class*="Weather"]';
      const youtube = "ytd-rich-item-renderer, ytd-video-renderer, ytd-compact-video-renderer, ytd-grid-video-renderer";
      document.querySelectorAll([semantic, commonUI, adsWeather, youtube].join(", ")).forEach(add);
      document.querySelectorAll("[id]").forEach(add);
      let summary = lines.join("\n");
      if (summary.length > maxChars) summary = summary.slice(0, maxChars - 3).trimEnd() + "...";
      return summary;
    } catch (e) {
      return "Error: " + (e.message || String(e)).slice(0, 200);
    }
  };

  const requestAutomate = (url, command) => {
    return new Promise((resolve, reject) => {
      try {
        const pageContext = getPageContext();
        chrome.runtime.sendMessage(
          { type: "interestlens:automate", url, command, pageContext },
          (response) => {
            if (chrome.runtime.lastError) {
              reject(new Error(normalizeExtensionError(chrome.runtime.lastError.message)));
              return;
            }
            if (!response) {
              reject(new Error("No response"));
              return;
            }
            if (response.ok) {
              resolve(response);
            } else if (response && !response.ok) {
              reject(new Error(response.detail || response.error || "Automation failed"));
            }
          }
        );
      } catch (e) {
        reject(new Error(normalizeExtensionError(e?.message || "Request failed")));
      }
    });
  };

  const setAutomateStatus = (text, isError = false) => {
    if (!sidebar.automateStatus) return;
    sidebar.automateStatus.textContent = text || "";
    sidebar.automateStatus.className = "il-automate-status" + (isError ? " il-error" : text ? " il-success" : "");
  };

  const runAutomation = async () => {
    const input = sidebar.automateInput;
    const command = (input?.value || "").trim();
    if (!command) {
      setAutomateStatus("Enter a command first.", true);
      return;
    }
    setAutomateStatus("Running...");
    try {
      await requestAutomate(window.location.href, command);
      setAutomateStatus("Script run on this page.");
      if (input) input.value = "";
    } catch (e) {
      setAutomateStatus(e?.message || "Automation failed", true);
    }
  };

  const loadCards = async (refreshCache = false) => {
    renderLoading("Scanning page for content...");
    try {
      const data = await requestScrape(window.location.href, refreshCache);
      const links = Array.isArray(data?.article_links) ? data.article_links : [];
      if (!links.length) {
        renderEmpty("No articles found", "This page doesn't have article links.");
        return;
      }
      const items = links.slice(0, MAX_CARDS).map((item) => ({
        id: crypto.randomUUID(),
        url: item.url,
        title: item.title || item.url,
        imageUrl: item.image_url || ""
      }));
      clearBody();
      items.forEach((item) => {
        const card = buildCard(item);
        if (sidebar.body) sidebar.body.appendChild(card);
      });
    } catch (e) {
      console.error("Load failed:", e);
      const msg = e?.message || "Load failed";
      renderError(msg.includes("run_backend") ? msg : msg + " Start backend: run_backend.bat (port 8001).");
    }
  };

  if (sidebar.refreshBtn) {
    sidebar.refreshBtn.onclick = () => loadCards(true);
  }
  if (sidebar.automateRunBtn) {
    sidebar.automateRunBtn.onclick = () => runAutomation();
  }
  if (sidebar.automateVoiceBtn) {
    sidebar.automateVoiceBtn.onclick = () => setAutomateStatus("Voice coming soon.");
  }
  if (sidebar.automateInput) {
    sidebar.automateInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") runAutomation();
    });
  }

  try {
    chrome.runtime.onMessage.addListener((msg, _sender, respond) => {
      if (msg?.type === "interestlens:toggle-sidebar") {
        if (sidebar.toggle) sidebar.toggle();
        respond({ ok: true });
        return true;
      }
    });
  } catch (e) {
    console.warn("Could not add message listener:", e);
  }

  loadCards();
})();
