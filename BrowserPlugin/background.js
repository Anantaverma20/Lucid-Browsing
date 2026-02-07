// Backend (agents + scrape) – port 8001; scraper API stays on 8000
const API_BASE = "http://localhost:8001";

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  // Scrape request
  if (message?.type === "interestlens:scrape") {
    const payload = { url: message.url };
    if (message.refreshCache) {
      payload.refresh_cache = true;
    }

    fetch(`${API_BASE}/scrape`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    })
      .then(async (response) => {
        if (!response.ok) {
          const data = await response.json().catch(() => ({}));
          const msg = response.status === 404 ? "Not Found (wrong port?). Backend must run on 8001." : `Scrape failed (${response.status}).`;
          sendResponse({ ok: false, error: msg, detail: data.detail || msg });
          return;
        }
        const data = await response.json();
        sendResponse({ ok: true, data });
      })
      .catch((error) => {
        const msg = (error?.message || "").toLowerCase();
        const detail = msg.includes("fetch") || msg.includes("network") || msg.includes("failed")
          ? "Cannot reach backend on port 8001. Start it: run run_backend.bat in project folder."
          : (error?.message || "Request failed");
        sendResponse({ ok: false, error: "Backend unreachable", detail });
      });

    return true;
  }

  // Automate request: backend validates/generates script; we execute it in the user's active tab
  if (message?.type === "interestlens:automate") {
    const url = message.url || "";
    const command = message.command || "";
    const pageContext = message.pageContext != null ? String(message.pageContext) : undefined;
    if (!url || !command) {
      sendResponse({ ok: false, error: "Missing url or command", detail: "url and command are required" });
      return true;
    }

    const body = { url, command };
    if (pageContext !== undefined) body.page_context = pageContext;

    fetch(`${API_BASE}/automate/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    })
      .then(async (response) => {
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          let detail = data.detail || data.error;
          if (!detail) {
            if (response.status === 404) detail = "Not Found. Start backend on 8001: run run_backend.bat.";
            else if (response.status === 500) detail = "Server error. Check backend logs.";
            else detail = `Request failed (${response.status}).`;
          }
          sendResponse({
            ok: false,
            error: data.error || "Request failed",
            detail
          });
          return;
        }
        // Backend returns script when validation passed; we run it in the user's tab (validate on server, execute on client)
        if (!data.ok || !data.script) {
          const detail = (data.error || data.detail || "No script returned. Check backend logs or try again.").slice(0, 500);
          sendResponse({
            ok: false,
            error: (data.error || "Automation failed").slice(0, 200),
            detail
          });
          return;
        }
        // Automation request comes from the sidebar on the active page; sender.tab.id is the most reliable.
        let tabId = sender.tab?.id;
        if (tabId == null) {
          const [activeTab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
          tabId = activeTab?.id ?? null;
        }
        if (tabId == null) {
          sendResponse({ ok: false, error: "No tab", detail: "Cannot inject script. Open the page you want to automate and try again." });
          return;
        }
        try {
          const commands = Array.isArray(data.commands) ? data.commands : [];
          const useCommands = commands.length > 0;

          if (useCommands) {
            // CSP-safe: run structured commands in ISOLATED world (no eval, no inline script).
            const runResult = await chrome.scripting.executeScript({
              target: { tabId },
              world: "ISOLATED",
              func: (cmdList) => {
                try {
                  for (const cmd of cmdList) {
                    const t = (cmd && cmd.type) || "";
                    if (t === "hide" || t === "remove") {
                      const sel = cmd.selector;
                      if (sel && typeof sel === "string") {
                        document.querySelectorAll(sel).forEach((el) => {
                          if (t === "remove") el.remove();
                          else el.style.display = "none";
                        });
                      }
                    } else if (t === "click") {
                      const sel = cmd.selector;
                      if (sel && typeof sel === "string") {
                        const el = document.querySelector(sel);
                        if (el) el.click();
                      }
                    } else if (t === "scroll" && typeof cmd.x === "number" && typeof cmd.y === "number") {
                      window.scrollBy(cmd.x, cmd.y);
                    }
                  }
                  return null;
                } catch (e) {
                  return { error: (e && e.message) || String(e) };
                }
              },
              args: [commands]
            });
            const first = runResult && runResult[0];
            const res = first && first.result;
            if (res && typeof res === "object" && res.error) {
              sendResponse({ ok: false, error: "Script error", detail: res.error });
              return;
            }
          } else {
            // No CSP-safe command list was derived from the script; we only run structured commands (no eval).
            sendResponse({
              ok: false,
              error: "Script could not be run on this page",
              detail: "The backend could not derive safe commands from the script for this page. Try a simpler command (e.g. \"hide the weather card\" or \"remove the weather card\") or a different page."
            });
            return;
          }

          await chrome.scripting.executeScript({
            target: { tabId },
            world: "ISOLATED",
            func: () => {
              const toast = document.createElement("div");
              toast.textContent = "Lucid Browsing: script ran";
              toast.style.cssText = "position:fixed;bottom:16px;right:16px;z-index:2147483647;padding:8px 14px;background:#6366f1;color:#fff;border-radius:8px;font-family:system-ui,sans-serif;font-size:13px;box-shadow:0 4px 12px rgba(0,0,0,0.2);";
              document.body.appendChild(toast);
              setTimeout(() => toast.remove(), 2500);
            }
          });
          sendResponse({ ok: true });
        } catch (injectError) {
          sendResponse({
            ok: false,
            error: "Injection failed",
            detail: injectError?.message || String(injectError)
          });
        }
      })
      .catch((error) => {
        const msg = (error?.message || "").toLowerCase();
        const detail = msg.includes("fetch") || msg.includes("network") || msg.includes("failed")
          ? "Cannot reach backend on port 8001. Start it: run run_backend.bat in project folder."
          : (error?.message || "Backend may be down. Run run_backend.bat on port 8001.");
        sendResponse({
          ok: false,
          error: "Request failed",
          detail
        });
      });

    return true;
  }

  // Voice transcription: extension sends recorded audio (ArrayBuffer), backend uses Whisper
  if (message?.type === "interestlens:voice-transcribe") {
    const audio = message.audio;
    const filename = message.filename || "audio.webm";
    if (!audio || !(audio instanceof ArrayBuffer)) {
      sendResponse({ ok: false, error: "Missing audio", detail: "Send an ArrayBuffer as message.audio." });
      return true;
    }
    const blob = new Blob([audio], { type: "audio/webm" });
    const form = new FormData();
    form.append("audio", blob, filename);
    fetch(`${API_BASE}/voice/transcribe`, {
      method: "POST",
      body: form
    })
      .then(async (response) => {
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          sendResponse({
            ok: false,
            error: data.error || "Transcription failed",
            detail: data.detail || (response.status === 503 ? "OPENAI_API_KEY not set or openai not installed." : `Request failed (${response.status}).`)
          });
          return;
        }
        sendResponse({ ok: true, text: data.text != null ? String(data.text) : "" });
      })
      .catch((error) => {
        const msg = (error?.message || "").toLowerCase();
        const detail = msg.includes("fetch") || msg.includes("network") || msg.includes("failed")
          ? "Cannot reach backend on port 8001. Start it: run run_backend.bat in project folder."
          : (error?.message || "Request failed");
        sendResponse({ ok: false, error: "Backend unreachable", detail });
      });
    return true;
  }

  return false;
});

chrome.commands?.onCommand?.addListener((command) => {
  if (command === "toggle-sidebar") {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      if (tabs.length > 0) {
        chrome.tabs.sendMessage(tabs[0].id, { type: "interestlens:toggle-sidebar" });
      }
    });
  }
});
