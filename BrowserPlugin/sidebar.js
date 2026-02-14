(() => {
  const sidebar = window.__interestLensSidebar;
  if (!sidebar) {
    console.log("Lucid Browsing: Waiting for sidebar...");
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

  const requestVerifyTruth = (includeScreenshot = false) => {
    return new Promise((resolve, reject) => {
      try {
        const { mainContent } = getPageContextAndMainContent("");
        const url = window.location.href || "";
        const content = (mainContent || "").trim().slice(0, 15000);
        chrome.runtime.sendMessage(
          { type: "interestlens:verify-truth", url, content, includeScreenshot },
          (response) => {
            if (chrome.runtime.lastError) {
              reject(new Error(normalizeExtensionError(chrome.runtime.lastError.message)));
              return;
            }
            if (!response || !response.ok) {
              reject(new Error(response?.detail || response?.error || "Verify failed"));
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

  const renderTruthReport = (data) => {
    clearBody();
    if (!sidebar.body) return;
    const score = Math.round(Number(data.page_trust_score) || 0);
    const claims = Array.isArray(data.claims) ? data.claims : [];
    let band = "il-truth-mid";
    if (score >= 70) band = "il-truth-high";
    else if (score < 40) band = "il-truth-low";
    const scoreLabel = score >= 70 ? "High trust" : score >= 40 ? "Mixed" : "Low trust / Misinformation";
    let claimsHtml = claims
      .map((c) => {
        const verdict = (c.verdict || "Unverified").toString();
        const claimEsc = (c.claim || "").replace(/</g, "&lt;").replace(/"/g, "&quot;");
        const explEsc = (c.explanation || "").replace(/</g, "&lt;").replace(/"/g, "&quot;");
        const src = c.source_url ? (c.source_url || "").replace(/</g, "&lt;") : "";
        let icon = ICONS.alert;
        if (verdict === "True") icon = ICONS.check;
        else if (verdict === "False") icon = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';
        const linkPart = src ? `<a href="${src}" target="_blank" rel="noopener" class="il-truth-source">Source</a>` : "";
        return `<div class="il-truth-claim il-truth-verdict-${verdict.toLowerCase()}">
          <div class="il-truth-claim-icon">${icon}</div>
          <div class="il-truth-claim-body">
            <div class="il-truth-claim-text">${claimEsc}</div>
            <div class="il-truth-claim-meta">${explEsc} ${linkPart}</div>
          </div>
        </div>`;
      })
      .join("");
    if (!claimsHtml) claimsHtml = "<p class=\"il-truth-no-claims\">No testable claims extracted.</p>";
    sidebar.body.innerHTML = `
      <div class="il-truth-report">
        <div class="il-truth-gauge-wrap ${band}">
          <div class="il-truth-gauge" role="meter" aria-valuenow="${score}" aria-valuemin="0" aria-valuemax="100" aria-label="Page trust score">
            <div class="il-truth-gauge-value">${score}</div>
            <div class="il-truth-gauge-label">${scoreLabel}</div>
          </div>
        </div>
        <div class="il-truth-claims">
          <h3 class="il-truth-claims-title">Claim breakdown</h3>
          ${claimsHtml}
        </div>
      </div>
    `;
  };

  // Single DOM pass: page structure (for automation) + main post content (for summaries).
  // Returns { pageContext, mainContent }. Logic adapted from headless_browser and previous getMainContentText.
  const maxLines = 150;
  const textLen = 50;
  const maxChars = 6000;
  const MAIN_CONTENT_MAX_CHARS = 4000;
  const validClass = /^[a-zA-Z_][a-zA-Z0-9_-]*$/;
  const validId = /^[a-zA-Z_][a-zA-Z0-9_-]*$/;

  const isPostContainer = (el) => {
    if (!el || !el.tagName) return false;
    const tag = el.tagName.toLowerCase();
    const cls = typeof el.className === "string" ? el.className : "";
    const testId = el.getAttribute && el.getAttribute("data-testid");
    return tag === "article" ||
      cls.includes("feed-shared-update-v2") ||
      testId === "feed-post-content" ||
      testId === "tweet" ||
      cls.includes("update-components-update-v2");
  };

  const getPageContextAndMainContent = (command) => {
    const lines = [];
    const blocks = [];
    const linesSeen = new Set();
    const blocksSeen = new Set();
    const cmd = (command || "").trim();
    const authorFromCommand = (() => {
      const fromMatch = cmd.match(/(?:from|by)\s+([^.]+?)(?:\s+to\s|\.|$)/i);
      if (fromMatch) return fromMatch[1].trim().replace(/\s+/g, " ");
      return null;
    })();

    try {
      const semantic = 'section, article, aside, main, header, footer, nav, [role="region"], [role="complementary"], [role="main"], [role="banner"], [role="contentinfo"]';
      const commonUI = '[class*="card"], [class*="widget"], [class*="item"], [class*="block"], [class*="box"], [class*="panel"], [class*="container"], [class*="section"], .sidebar, .side-bar, .feed-item, .promo, .banner, [data-testid], [data-component]';
      const adsWeather = '[id*="ad"], [id*="Ad"], [class*="ad"], [class*="Ad"], [data-ad], .sponsored, [class*="sponsor"], [id*="banner"], [id*="weather"], [id*="Weather"], [class*="weather"], [class*="Weather"]';
      const youtube = "ytd-rich-item-renderer, ytd-video-renderer, ytd-compact-video-renderer, ytd-grid-video-renderer";
      const postSelectors = ".feed-shared-update-v2, [data-testid='feed-post-content'], [data-testid='tweet'], .update-components-update-v2";
      const combined = [semantic, commonUI, adsWeather, youtube, "[id]", postSelectors].join(", ");
      const all = document.querySelectorAll(combined);

      for (let i = 0; i < all.length; i++) {
        const el = all[i];
        if (!el) continue;
        if (lines.length < maxLines && !linesSeen.has(el)) {
          linesSeen.add(el);
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
        }
        if (isPostContainer(el) && !blocksSeen.has(el)) {
          const text = (el.innerText || el.textContent || "").replace(/\s+/g, " ").trim();
          if (text && text.length >= 30) {
            blocksSeen.add(el);
            const rect = el.getBoundingClientRect();
            const centerY = rect.top + rect.height / 2;
            const viewportCenter = window.innerHeight / 2;
            const distanceFromCenter = Math.abs(centerY - viewportCenter);
            const inView = rect.top < window.innerHeight && rect.bottom > 0;
            blocks.push({
              text: text.slice(0, MAIN_CONTENT_MAX_CHARS),
              distanceFromCenter: inView ? distanceFromCenter : 1e9,
              inView
            });
          }
        }
      }

      let pageContext = lines.join("\n");
      if (pageContext.length > maxChars) pageContext = pageContext.slice(0, maxChars - 3).trimEnd() + "...";

      let mainContent = "";
      if (blocks.length === 0) {
        const main = document.querySelector("main");
        if (main) {
          const text = (main.innerText || main.textContent || "").replace(/\s+/g, " ").trim();
          if (text && text.length >= 30) mainContent = text.slice(0, MAIN_CONTENT_MAX_CHARS);
        }
      } else {
        let best = blocks[0];
        if (authorFromCommand) {
          const nameParts = authorFromCommand.split(/\s+/).filter((p) => p.length > 1);
          const byAuthor = blocks.filter((b) => {
            const t = b.text.toLowerCase();
            return nameParts.some((part) => t.includes(part.toLowerCase()));
          });
          if (byAuthor.length) {
            best = byAuthor.reduce((a, b) => (a.text.length >= b.text.length ? a : b));
          } else {
            const byView = blocks.filter((b) => b.inView).sort((a, b) => a.distanceFromCenter - b.distanceFromCenter);
            if (byView.length) best = byView[0];
          }
        } else {
          const inView = blocks.filter((b) => b.inView).sort((a, b) => a.distanceFromCenter - b.distanceFromCenter);
          if (inView.length) best = inView[0];
        }
        mainContent = best.text;
      }

      return { pageContext, mainContent };
    } catch (e) {
      return { pageContext: "Error: " + (e.message || String(e)).slice(0, 200), mainContent: "" };
    }
  };

  // In-memory conversation for Composio follow-up (list of { role: "user"|"assistant", content: string })
  const chatMessagesList = [];

  const appendMessage = (role, content) => {
    const text = (content || "").trim();
    if (!text) return;
    chatMessagesList.push({ role, content: text });
    const container = sidebar.chatMessages;
    if (!container) return;
    const bubble = document.createElement("div");
    bubble.className = "il-chat-message il-chat-" + (role === "user" ? "user" : "assistant");
    bubble.textContent = text;
    container.appendChild(bubble);
    container.scrollTop = container.scrollHeight;
  };

  const requestAutomate = (url, command, conversation = null) => {
    return new Promise((resolve, reject) => {
      try {
        const { pageContext, mainContent } = getPageContextAndMainContent(command);
        const payload = { type: "interestlens:automate", url, command, pageContext, mainContent };
        if (Array.isArray(conversation) && conversation.length > 0) payload.conversation = conversation;
        chrome.runtime.sendMessage(payload, (response) => {
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
        });
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
    if (input) input.value = "";
    const isFollowUp = chatMessagesList.length >= 2;
    if (isFollowUp) {
      appendMessage("user", command);
    }
    setAutomateStatus("Running...");
    try {
      const conversation = isFollowUp ? chatMessagesList.slice(0, -1) : null;
      const response = await requestAutomate(window.location.href, command, conversation);
      const assistantText = (response.connector_summary && response.connector_summary.trim())
        ? response.connector_summary.trim()
        : (response.connector_error ? "Error: " + response.connector_error : "Script run on this page.");
      if (!isFollowUp) {
        appendMessage("user", command);
      }
      appendMessage("assistant", assistantText);
      setAutomateStatus(chatMessagesList.length > 0 ? "" : "Script run on this page.");
    } catch (e) {
      if (isFollowUp) {
        chatMessagesList.pop();
        if (sidebar.chatMessages && sidebar.chatMessages.lastElementChild?.classList.contains("il-chat-user")) {
          sidebar.chatMessages.lastElementChild.remove();
        }
      }
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
  const runVerifyTruth = async (includeScreenshot) => {
    renderLoading(includeScreenshot ? "Capturing screenshot and verifying..." : "Verifying truth...");
    try {
      const data = await requestVerifyTruth(includeScreenshot);
      renderTruthReport(data);
    } catch (e) {
      const msg = e?.message || "Verify failed";
      const hint = msg.includes("run_backend") || msg.includes("Restart the backend") ? "" : " Start backend: run_backend.bat (port 8001).";
      renderError(msg + hint);
    }
  };
  if (sidebar.verifyTruthBtn) {
    sidebar.verifyTruthBtn.onclick = () => runVerifyTruth(false);
  }
  if (sidebar.verifyScreenshotBtn) {
    sidebar.verifyScreenshotBtn.onclick = () => runVerifyTruth(true);
  }
  if (sidebar.automateRunBtn) {
    sidebar.automateRunBtn.onclick = () => runAutomation();
  }
  const voiceRecording = { active: false, recorder: null, chunks: [] };
  if (sidebar.automateVoiceBtn) {
    sidebar.automateVoiceBtn.onclick = async () => {
      if (voiceRecording.active) {
        if (voiceRecording.recorder && voiceRecording.recorder.state !== "inactive") {
          voiceRecording.recorder.stop();
        }
        voiceRecording.active = false;
        return;
      }
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        voiceRecording.chunks = [];
        voiceRecording.recorder = new MediaRecorder(stream);
        voiceRecording.recorder.ondataavailable = (e) => {
          if (e.data && e.data.size > 0) voiceRecording.chunks.push(e.data);
        };
        voiceRecording.recorder.onstop = async () => {
          stream.getTracks().forEach((t) => t.stop());
          const blob = new Blob(voiceRecording.chunks, { type: "audio/webm" });
          setAutomateStatus("Processing...");
          const buf = await blob.arrayBuffer();
          chrome.runtime.sendMessage(
            { type: "interestlens:voice-transcribe", audio: buf, filename: "audio.webm" },
            (response) => {
              if (chrome.runtime.lastError) {
                setAutomateStatus(normalizeExtensionError(chrome.runtime.lastError.message), true);
                return;
              }
              if (!response || !response.ok) {
                setAutomateStatus(response?.detail || response?.error || "Transcription failed", true);
                return;
              }
              const text = (response.text != null ? String(response.text) : "").trim();
              if (sidebar.automateInput) {
                sidebar.automateInput.value = text;
                setAutomateStatus(text ? "Ready. Click Run or press Enter." : "No speech detected.");
              } else {
                setAutomateStatus(text ? "Transcribed." : "No speech detected.");
              }
            }
          );
        };
        voiceRecording.recorder.start();
        voiceRecording.active = true;
        setAutomateStatus("Listening... Click mic again to stop.");
      } catch (e) {
        setAutomateStatus(e?.message || "Microphone access denied.", true);
      }
    };
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
