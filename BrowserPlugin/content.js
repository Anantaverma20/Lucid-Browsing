(() => {
  if (window.__interestLensSidebar) {
    return;
  }

  const host = document.createElement("div");
  host.id = "interestlens-sidebar-host";
  host.style.position = "fixed";
  host.style.top = "0";
  host.style.right = "0";
  const storedWidth = Number.parseInt(
    window.localStorage.getItem("interestlens.sidebarWidth") || "",
    10
  );
  const defaultWidth = Math.round(window.innerWidth * 0.4);
  const initialWidth = Number.isFinite(storedWidth) ? storedWidth : defaultWidth;
  let currentWidth = initialWidth;
  host.style.width = `${initialWidth}px`;

  const pageStyle = document.createElement("style");
  pageStyle.id = "interestlens-page-style";
  pageStyle.textContent = `
    html {
      --interestlens-panel-width: ${initialWidth}px;
    }
    body {
      margin-right: var(--interestlens-panel-width) !important;
      box-sizing: border-box;
    }
  `;
  document.head?.appendChild(pageStyle);
  host.style.height = "100vh";
  host.style.zIndex = "2147483647";
  host.style.display = "block";
  host.style.pointerEvents = "auto";
  host.style.margin = "0";
  host.style.padding = "0";
  host.style.border = "0";
  host.style.background = "#EDE8D0";
  const shadowRoot = host.attachShadow({ mode: "open" });

  const styleLink = document.createElement("link");
  styleLink.rel = "stylesheet";
  styleLink.href = chrome.runtime.getURL("sidebar.css");

  const wrapper = document.createElement("div");
  wrapper.className = "il-sidebar il-slide-in";

  const resizer = document.createElement("div");
  resizer.className = "il-resizer";
  resizer.setAttribute("aria-hidden", "true");

  const header = document.createElement("div");
  header.className = "il-header";

  const title = document.createElement("div");
  title.className = "il-title";
  title.textContent = "InterestLens Panel";

  const refresh = document.createElement("button");
  refresh.className = "il-refresh";
  refresh.type = "button";
  refresh.textContent = "Refresh";
  refresh.setAttribute("aria-label", "Refresh cards");

  const close = document.createElement("button");
  close.className = "il-close";
  close.type = "button";
  close.textContent = "Close";
  close.setAttribute("aria-label", "Close sidebar");

  header.appendChild(title);
  header.appendChild(refresh);
  header.appendChild(close);

  const body = document.createElement("div");
  body.className = "il-body";

  const loading = document.createElement("div");
  loading.className = "il-loading";
  loading.textContent = "Scanning links…";

  body.appendChild(loading);

  wrapper.appendChild(resizer);
  wrapper.appendChild(header);
  wrapper.appendChild(body);

  shadowRoot.appendChild(styleLink);
  shadowRoot.appendChild(wrapper);

  const attachHost = () => {
    const parent = document.documentElement || document.body;
    if (!parent) {
      return false;
    }
    if (!parent.contains(host)) {
      parent.appendChild(host);
    }
    return true;
  };

  const ensureAttached = () => {
    if (!attachHost()) {
      setTimeout(ensureAttached, 50);
    }
  };

  ensureAttached();

  const observer = new MutationObserver(() => {
    if (!host.isConnected) {
      attachHost();
    }
  });
  observer.observe(document.documentElement, {
    childList: true,
    subtree: true
  });

  const setHidden = (hidden) => {
    host.style.display = hidden ? "none" : "block";
    window.__interestLensSidebar.isHidden = hidden;
    const widthValue = hidden ? 0 : currentWidth;
    document.documentElement.style.setProperty(
      "--interestlens-panel-width",
      `${widthValue}px`
    );
  };

  window.__interestLensSidebar = {
    host,
    shadowRoot,
    body,
    refresh,
    observer,
    isHidden: false,
    setHidden
  };

  const handleWheel = (event) => {
    const path = event.composedPath ? event.composedPath() : [];
    const isInsidePanel =
      path.includes(wrapper) ||
      path.includes(body) ||
      (event.target && wrapper.contains(event.target));
    if (!isInsidePanel) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    body.scrollBy({ top: event.deltaY, left: 0, behavior: "auto" });
  };

  host.addEventListener("wheel", handleWheel, {
    passive: false,
    capture: true
  });

  let prevHtmlOverflow = "";
  let prevBodyOverflow = "";

  const lockPageScroll = () => {
    prevHtmlOverflow = document.documentElement.style.overflow;
    prevBodyOverflow = document.body?.style.overflow || "";
    document.documentElement.style.overflow = "hidden";
    if (document.body) {
      document.body.style.overflow = "hidden";
    }
  };

  const unlockPageScroll = () => {
    document.documentElement.style.overflow = prevHtmlOverflow;
    if (document.body) {
      document.body.style.overflow = prevBodyOverflow;
    }
  };

  host.addEventListener("mouseenter", lockPageScroll);
  host.addEventListener("mouseleave", unlockPageScroll);

  const MIN_WIDTH = 240;
  const MAX_WIDTH = 520;
  let isDragging = false;

  const updateWidth = (clientX) => {
    const nextWidth = Math.min(
      MAX_WIDTH,
      Math.max(MIN_WIDTH, window.innerWidth - clientX)
    );
    currentWidth = nextWidth;
    host.style.width = `${nextWidth}px`;
    document.documentElement.style.setProperty(
      "--interestlens-panel-width",
      `${nextWidth}px`
    );
    window.localStorage.setItem(
      "interestlens.sidebarWidth",
      `${Math.round(nextWidth)}`
    );
  };

  const stopDrag = () => {
    if (!isDragging) {
      return;
    }
    isDragging = false;
    document.documentElement.classList.remove("il-resize-active");
  };

  resizer.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) {
      return;
    }
    isDragging = true;
    resizer.setPointerCapture(event.pointerId);
    document.documentElement.classList.add("il-resize-active");
    updateWidth(event.clientX);
  });

  resizer.addEventListener("pointermove", (event) => {
    if (!isDragging) {
      return;
    }
    updateWidth(event.clientX);
  });

  resizer.addEventListener("pointerup", () => stopDrag());
  resizer.addEventListener("pointercancel", () => stopDrag());

  close.addEventListener("click", () => {
    setHidden(true);
  });

  document.addEventListener("keydown", (event) => {
    if (!event.metaKey || !event.shiftKey) {
      return;
    }
    if (event.key.toLowerCase() !== "s") {
      return;
    }
    event.preventDefault();
    setHidden(!window.__interestLensSidebar.isHidden);
  });
})();
