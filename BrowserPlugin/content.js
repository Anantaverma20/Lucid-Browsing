(() => {
  // AGGRESSIVE CLEANUP - Remove ALL possible old sidebars
  const cleanup = () => {
    // Remove by various IDs and selectors that old versions might use
    const selectorsToRemove = [
      '#interestlens-sidebar-host',
      '[data-interestlens-sidebar]',
      '[id*="interestlens"]',
      '#interestlens-page-style'
    ];
    
    selectorsToRemove.forEach(selector => {
      try {
        document.querySelectorAll(selector).forEach(el => el.remove());
      } catch (e) {}
    });
    
    // Clean up any global references
    if (window.__interestLensSidebar) {
      try {
        if (window.__interestLensSidebar.observer) {
          window.__interestLensSidebar.observer.disconnect();
        }
      } catch (e) {}
      window.__interestLensSidebar = null;
    }
    
    // Clear old markers
    delete window.__interestLensSidebar_v2__;
  };
  
  cleanup();
  
  // Use a version-specific marker to prevent re-initialization
  const VERSION_KEY = '__IL_SIDEBAR_V3__';
  if (window[VERSION_KEY]) {
    return;
  }
  window[VERSION_KEY] = Date.now();

  // SVG Icons
  const ICONS = {
    eye: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>`,
    refresh: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>`,
    chevronLeft: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 18 9 12 15 6"/></svg>`,
    chevronRight: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>`,
    mic: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>`,
    check: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>`,
    alert: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`,
    warning: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`,
    empty: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>`
  };

  // State
  let isCollapsed = false;
  let currentWidth = 360;

  // Create main container
  const host = document.createElement("div");
  host.id = "interestlens-sidebar-host";
  host.setAttribute("data-interestlens-sidebar", "v3");
  
  // Create collapse toggle button (always visible)
  const toggleBtn = document.createElement("button");
  toggleBtn.id = "il-toggle-btn";
  toggleBtn.innerHTML = ICONS.chevronRight;
  toggleBtn.setAttribute("aria-label", "Toggle sidebar");
  
  // Apply toggle button styles inline (so it works even without CSS loaded)
  Object.assign(toggleBtn.style, {
    position: 'fixed',
    top: '50%',
    right: '0',
    transform: 'translateY(-50%)',
    zIndex: '2147483647',
    width: '24px',
    height: '48px',
    border: 'none',
    borderRadius: '8px 0 0 8px',
    background: 'linear-gradient(135deg, #6366f1 0%, #a855f7 100%)',
    color: 'white',
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    boxShadow: '-2px 0 8px rgba(0,0,0,0.2)',
    transition: 'all 0.2s ease',
    padding: '0'
  });

  // Host styles
  Object.assign(host.style, {
    position: 'fixed',
    top: '0',
    right: '0',
    width: '360px',
    height: '100vh',
    zIndex: '2147483646',
    margin: '0',
    padding: '0',
    border: '0',
    transition: 'transform 0.3s ease'
  });
  
  const shadowRoot = host.attachShadow({ mode: "open" });

  // Load CSS
  const styleLink = document.createElement("link");
  styleLink.rel = "stylesheet";
  styleLink.href = chrome.runtime.getURL("sidebar.css");

  // Main wrapper
  const wrapper = document.createElement("div");
  wrapper.className = "il-sidebar";

  // Header
  const header = document.createElement("div");
  header.className = "il-header";
  header.innerHTML = `
    <div class="il-logo"><img src="${chrome.runtime.getURL("icons/icon48.png")}" alt="" class="il-logo-img" /></div>
    <div class="il-title">Lucid Browsing</div>
    <div class="il-header-actions">
      <button class="il-btn" id="il-refresh-btn" type="button" aria-label="Refresh">${ICONS.refresh}</button>
    </div>
  `;

  // Automation section (command input + Run)
  const automationSection = document.createElement("div");
  automationSection.className = "il-automation";
  automationSection.innerHTML = `
    <label class="il-automation-label">Automate this page</label>
    <div class="il-automation-row">
      <input type="text" id="il-automate-input" class="il-automate-input" placeholder="e.g. Click the login button" />
      <button type="button" id="il-automate-run" class="il-btn il-automate-run" aria-label="Run">Run</button>
      <button type="button" id="il-automate-voice" class="il-btn il-automate-voice" aria-label="Voice">${ICONS.mic}</button>
    </div>
    <div id="il-automate-status" class="il-automate-status" aria-live="polite"></div>
  `;

  // Body (cards from scrape)
  const body = document.createElement("div");
  body.className = "il-body";

  // Assemble
  wrapper.appendChild(header);
  wrapper.appendChild(automationSection);
  wrapper.appendChild(body);
  shadowRoot.appendChild(styleLink);
  shadowRoot.appendChild(wrapper);

  // Page margin style
  const pageStyle = document.createElement("style");
  pageStyle.id = "interestlens-page-style";
  pageStyle.textContent = `
    body { margin-right: 360px !important; transition: margin-right 0.3s ease; }
  `;

  // Toggle function
  const toggleSidebar = () => {
    isCollapsed = !isCollapsed;
    
    if (isCollapsed) {
      host.style.transform = 'translateX(100%)';
      toggleBtn.innerHTML = ICONS.chevronLeft;
      toggleBtn.style.right = '0';
      pageStyle.textContent = `body { margin-right: 0 !important; transition: margin-right 0.3s ease; }`;
    } else {
      host.style.transform = 'translateX(0)';
      toggleBtn.innerHTML = ICONS.chevronRight;
      toggleBtn.style.right = '360px';
      pageStyle.textContent = `body { margin-right: 360px !important; transition: margin-right 0.3s ease; }`;
    }
  };

  // Attach to DOM
  const attachSidebar = () => {
    if (!host.isConnected) {
      document.documentElement.appendChild(host);
    }
    if (!toggleBtn.isConnected) {
      document.documentElement.appendChild(toggleBtn);
    }
    if (!pageStyle.isConnected) {
      document.head.appendChild(pageStyle);
    }
    toggleBtn.style.right = isCollapsed ? '0' : '360px';
  };
  attachSidebar();

  // Re-attach if the page (e.g. Yahoo SPA) removes our nodes
  const observer = new MutationObserver(() => {
    if (!host.isConnected || !toggleBtn.isConnected) {
      attachSidebar();
    }
  });
  observer.observe(document.documentElement, { childList: true, subtree: true });

  // Toggle button click
  toggleBtn.addEventListener("click", toggleSidebar);

  const refreshBtn = shadowRoot.getElementById("il-refresh-btn");

  const automateInput = shadowRoot.getElementById("il-automate-input");
  const automateRunBtn = shadowRoot.getElementById("il-automate-run");
  const automateVoiceBtn = shadowRoot.getElementById("il-automate-voice");
  const automateStatus = shadowRoot.getElementById("il-automate-status");

  window.__interestLensSidebar = {
    host,
    shadowRoot,
    body,
    refreshBtn,
    toggleBtn,
    automateInput,
    automateRunBtn,
    automateVoiceBtn,
    automateStatus,
    observer,
    isCollapsed: () => isCollapsed,
    toggle: toggleSidebar,
    ICONS
  };

  // Keyboard shortcut
  document.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key.toLowerCase() === "s") {
      e.preventDefault();
      toggleSidebar();
    }
  });

  // Scroll handling in sidebar
  host.addEventListener("wheel", (e) => {
    const path = e.composedPath ? e.composedPath() : [];
    if (path.includes(body) || path.includes(wrapper)) {
      e.preventDefault();
      e.stopPropagation();
      body.scrollBy({ top: e.deltaY, behavior: "auto" });
    }
  }, { passive: false, capture: true });
})();
