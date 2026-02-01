(() => {
  const sidebar = window.__interestLensSidebar;
  if (!sidebar) {
    return;
  }

  const MAX_CARDS = 12;

  const clearBody = () => {
    sidebar.body.textContent = "";
  };

  const renderMessage = (message, { loading = false } = {}) => {
    clearBody();
    const el = document.createElement("div");
    el.className = "il-loading";
    el.textContent = message;
    sidebar.body.appendChild(el);

    if (loading) {
      const spinner = document.createElement("div");
      spinner.className = "il-spinner";
      sidebar.body.appendChild(spinner);
    }
  };

  const buildCard = (data) => {
    const card = document.createElement("a");
    card.className = "il-card";
    card.href = data.url;
    card.target = "_blank";
    card.rel = "noopener";

    const content = document.createElement("div");
    content.className = "il-card-content";

    const title = document.createElement("div");
    title.className = "il-card-title";
    title.textContent = data.title || data.url;

    const desc = document.createElement("div");
    desc.className = "il-card-desc";
    desc.textContent = data.description || data.url || "";

    const badge = document.createElement("div");
    badge.className = "il-badge";
    badge.textContent = "Authenticity: …";

    content.appendChild(title);
    content.appendChild(desc);
    content.appendChild(badge);

    card.appendChild(content);

    return { card, title, desc, badge };
  };

  const renderCards = (cards) => {
    clearBody();
    cards.forEach((card) => sidebar.body.appendChild(card));
  };

  const requestScrape = (url, { refreshCache = false } = {}) =>
    new Promise((resolve, reject) => {
      chrome.runtime.sendMessage(
        { type: "interestlens:scrape", url, refreshCache },
        (response) => {
          if (!response) {
            reject(new Error("No response from background"));
            return;
          }
          if (!response.ok) {
            reject(new Error(response.error || "Scrape failed"));
            return;
          }
          resolve(response.data);
        }
      );
    });

  const requestAuthenticity = (payload) =>
    new Promise((resolve, reject) => {
      chrome.runtime.sendMessage(
        { type: "interestlens:authenticity", payload },
        (response) => {
          if (!response) {
            reject(new Error("No response from background"));
            return;
          }
          if (!response.ok) {
            reject(new Error(response.error || "Authenticity failed"));
            return;
          }
          resolve(response.data);
        }
      );
    });

  const loadCards = async ({ refreshCache = false } = {}) => {
    renderMessage("Loading topics…", { loading: true });

    try {
      const data = await requestScrape(window.location.href, { refreshCache });
      const links = Array.isArray(data?.article_links)
        ? data.article_links
        : [];

      if (!links.length) {
        renderMessage("No links returned from scraper.");
        return;
      }

      const items = links.slice(0, MAX_CARDS).map((item) => ({
        item_id: crypto.randomUUID(),
        url: item.url,
        title: item.title || item.url,
        image_url: item.image_url || ""
      }));

      const cardsWithParts = items.map((item) => ({
        item,
        parts: buildCard({
          url: item.url,
          title: item.title,
          description: item.url,
          imageUrl: item.image_url
        })
      }));

      const cards = cardsWithParts.map(({ parts }) => parts.card);

      renderCards(cards);

      const payload = {
        items: items.map((item) => ({
          item_id: item.item_id,
          url: item.url,
          text: item.title,
          check_depth: "standard"
        })),
        max_concurrent: 20
      };

      const authenticity = await requestAuthenticity(payload);
      const results = Array.isArray(authenticity?.results)
        ? authenticity.results
        : [];
      const scoresById = new Map(
        results.map((result) => [result.item_id, result.authenticity_score])
      );

      cardsWithParts.forEach(({ item, parts }) => {
        const score = scoresById.get(item.item_id);
        if (typeof score === "number") {
          parts.badge.textContent = `Authenticity: ${score}`;
          parts.badge.dataset.score = `${score}`;
        } else {
          parts.badge.textContent = "Authenticity: N/A";
        }
      });
    } catch (error) {
      renderMessage("Failed to load from scraper.");
    }
  };

  sidebar.refresh.addEventListener("click", () => {
    loadCards({ refreshCache: true });
  });

  loadCards();
})();
