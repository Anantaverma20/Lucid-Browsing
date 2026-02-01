(() => {
  // Wait for sidebar to be initialized
  const sidebar = window.__interestLensSidebar;
  if (!sidebar) {
    console.log("InterestLens: Waiting for sidebar...");
    return;
  }

  // Prevent duplicate initialization
  if (sidebar._initialized) {
    return;
  }
  sidebar._initialized = true;

  const MAX_CARDS = 12;
  const ICONS = sidebar.ICONS || {};

  // Voice state
  let voiceState = 'idle';
  let recognition = null;

  const clearBody = () => {
    if (sidebar.body) {
      sidebar.body.innerHTML = "";
    }
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
        <div class="il-empty-icon">${ICONS.empty || ''}</div>
        <div class="il-empty-title">${title || 'No content found'}</div>
        <div class="il-empty-desc">${desc || 'Try a different page.'}</div>
      </div>
    `;
  };

  const renderError = (message) => {
    clearBody();
    if (!sidebar.body) return;
    sidebar.body.innerHTML = `
      <div class="il-error">
        <div class="il-error-icon">${ICONS.alert || ''}</div>
        <div class="il-error-text">${message || 'Something went wrong'}</div>
      </div>
    `;
  };

  const getScoreClass = (score) => {
    if (score == null) return 'il-badge-loading';
    if (score >= 80) return 'il-badge-good';
    if (score >= 50) return 'il-badge-warning';
    return 'il-badge-danger';
  };

  const getScoreIcon = (score) => {
    if (score == null) return '';
    if (score >= 80) return ICONS.check || '';
    if (score >= 50) return ICONS.warning || '';
    return ICONS.alert || '';
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
      domain = new URL(data.url).hostname.replace('www.', '');
    } catch (e) {}

    card.innerHTML = `
      <div class="il-card-image">
        ${hasImage ? `<img src="${data.imageUrl}" alt="" loading="lazy" onerror="this.parentElement.innerHTML='<div class=il-card-placeholder>No image</div>'">` : '<div class="il-card-placeholder">No image</div>'}
      </div>
      <div class="il-card-content">
        <div class="il-card-title">${data.title || 'Untitled'}</div>
        <div class="il-card-desc">${domain}</div>
        <div class="il-badge il-badge-loading"><span>Checking...</span></div>
      </div>
    `;

    return card;
  };

  const updateCardBadge = (card, score) => {
    const badge = card.querySelector('.il-badge');
    if (!badge) return;
    
    const scoreClass = getScoreClass(score);
    const icon = getScoreIcon(score);
    badge.className = `il-badge ${scoreClass}`;
    
    if (score == null) {
      badge.innerHTML = `<span>N/A</span>`;
    } else {
      badge.innerHTML = `<span class="il-badge-icon">${icon}</span><span>${score}% authentic</span>`;
    }
  };

  const requestScrape = (url, refreshCache = false) => {
    return new Promise((resolve, reject) => {
      try {
        chrome.runtime.sendMessage(
          { type: "interestlens:scrape", url, refreshCache },
          (response) => {
            if (chrome.runtime.lastError) {
              reject(new Error(chrome.runtime.lastError.message));
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
        reject(e);
      }
    });
  };

  const requestAuthenticity = (payload) => {
    return new Promise((resolve, reject) => {
      try {
        chrome.runtime.sendMessage(
          { type: "interestlens:authenticity", payload },
          (response) => {
            if (chrome.runtime.lastError) {
              reject(new Error(chrome.runtime.lastError.message));
              return;
            }
            if (!response || !response.ok) {
              reject(new Error(response?.error || "Authenticity failed"));
              return;
            }
            resolve(response.data);
          }
        );
      } catch (e) {
        reject(e);
      }
    });
  };

  const loadCards = async (refreshCache = false) => {
    renderLoading("Scanning page for content...");
    if (sidebar.updateStats) sidebar.updateStats(null, 0, 0);

    try {
      const data = await requestScrape(window.location.href, refreshCache);
      const links = Array.isArray(data?.article_links) ? data.article_links : [];

      if (!links.length) {
        renderEmpty("No articles found", "This page doesn't have article links to analyze.");
        return;
      }

      const items = links.slice(0, MAX_CARDS).map((item) => ({
        id: crypto.randomUUID(),
        url: item.url,
        title: item.title || item.url,
        imageUrl: item.image_url || ""
      }));

      // Render cards
      clearBody();
      const cards = items.map(item => {
        const card = buildCard(item);
        card.dataset.itemId = item.id;
        if (sidebar.body) sidebar.body.appendChild(card);
        return { item, card };
      });

      if (sidebar.updateStats) sidebar.updateStats(null, items.length, 0);

      // Request authenticity
      const payload = {
        items: items.map(item => ({
          item_id: item.id,
          url: item.url,
          text: item.title,
          check_depth: "standard"
        })),
        max_concurrent: 20
      };

      try {
        const auth = await requestAuthenticity(payload);
        const results = Array.isArray(auth?.results) ? auth.results : [];
        const scores = new Map(results.map(r => [r.item_id, r.authenticity_score]));

        let total = 0, count = 0, verified = 0;

        cards.forEach(({ item, card }) => {
          const score = scores.get(item.id);
          updateCardBadge(card, score);
          
          if (typeof score === "number") {
            total += score;
            count++;
            if (score >= 80) verified++;
          }
        });

        const avg = count > 0 ? total / count : null;
        if (sidebar.updateStats) sidebar.updateStats(avg, items.length, verified);
      } catch (e) {
        console.warn("Authenticity failed:", e);
        cards.forEach(({ card }) => updateCardBadge(card, null));
      }
    } catch (e) {
      console.error("Load failed:", e);
      renderError("Failed to load content. Check if the backend is running.");
    }
  };

  // Voice handlers
  const setVoiceState = (state) => {
    voiceState = state;
    const btn = sidebar.voiceBtn;
    if (!btn) return;

    btn.classList.remove('il-voice-listening', 'il-voice-processing');
    const mic = ICONS.mic || '';

    if (state === 'listening') {
      btn.classList.add('il-voice-listening');
      btn.innerHTML = `<span class="il-voice-icon">${mic}</span><span>Listening...</span>`;
      if (sidebar.updateVoiceStatus) sidebar.updateVoiceStatus("Speak now...");
    } else if (state === 'processing') {
      btn.classList.add('il-voice-processing');
      btn.innerHTML = `<span class="il-voice-icon">${mic}</span><span>Processing...</span>`;
    } else {
      btn.innerHTML = `<span class="il-voice-icon">${mic}</span><span>Ask InterestLens</span>`;
    }
  };

  const handleVoiceCommand = (cmd) => {
    const c = cmd.toLowerCase();
    if (sidebar.updateVoiceStatus) {
      sidebar.updateVoiceStatus(`Heard: "${cmd}"`);
    }
  };

  const startVoice = () => {
    if (voiceState !== 'idle') {
      if (recognition) {
        try { recognition.stop(); } catch (e) {}
      }
      setVoiceState('idle');
      return;
    }

    if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
      if (sidebar.updateVoiceStatus) sidebar.updateVoiceStatus("Voice not supported in this browser");
      return;
    }

    setVoiceState('listening');

    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    recognition = new SR();
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.lang = 'en-US';

    recognition.onresult = (e) => {
      const cmd = e.results[0][0].transcript;
      setVoiceState('processing');
      setTimeout(() => {
        handleVoiceCommand(cmd);
        setVoiceState('idle');
      }, 500);
    };

    recognition.onerror = (e) => {
      if (sidebar.updateVoiceStatus) sidebar.updateVoiceStatus(`Error: ${e.error}`);
      setVoiceState('idle');
    };

    recognition.onend = () => {
      if (voiceState === 'listening') setVoiceState('idle');
    };

    try {
      recognition.start();
    } catch (e) {
      if (sidebar.updateVoiceStatus) sidebar.updateVoiceStatus("Could not start voice");
      setVoiceState('idle');
    }
  };

  // Attach event listeners safely
  if (sidebar.refreshBtn) {
    sidebar.refreshBtn.onclick = () => loadCards(true);
  }

  if (sidebar.voiceBtn) {
    sidebar.voiceBtn.onclick = startVoice;
  }

  // Listen for messages
  try {
    chrome.runtime.onMessage.addListener((msg, sender, respond) => {
      if (msg?.type === "interestlens:toggle-sidebar") {
        if (sidebar.toggle) sidebar.toggle();
        respond({ ok: true });
        return true;
      }
    });
  } catch (e) {
    console.warn("Could not add message listener:", e);
  }

  // Initial load
  loadCards();
})();
