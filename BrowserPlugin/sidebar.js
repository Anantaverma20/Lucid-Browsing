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

    if (data.imageUrl) {
      const imageWrap = document.createElement("div");
      imageWrap.className = "il-card-image";
      const img = document.createElement("img");
      img.alt = data.title || "Preview image";
      img.loading = "lazy";
      img.referrerPolicy = "no-referrer";
      img.src = data.imageUrl;
      imageWrap.appendChild(img);
      card.appendChild(imageWrap);
    }

    const content = document.createElement("div");
    content.className = "il-card-content";

    const title = document.createElement("div");
    title.className = "il-card-title";
    title.textContent = data.title || data.url;

    const desc = document.createElement("div");
    desc.className = "il-card-desc";
    desc.textContent = data.description || data.url || "";

    content.appendChild(title);
    content.appendChild(desc);

    card.appendChild(content);

    return { card, title, desc };
  };

  const renderCards = (cards) => {
    clearBody();
    cards.forEach((card) => sidebar.body.appendChild(card));
  };

  const requestScrape = (url) =>
    new Promise((resolve, reject) => {
      chrome.runtime.sendMessage(
        { type: "interestlens:scrape", url },
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

  const loadCards = async () => {
    renderMessage("Loading topics…", { loading: true });

    try {
      const data = await requestScrape(window.location.href);
      const links = Array.isArray(data?.article_links)
        ? data.article_links
        : [];

      if (!links.length) {
        renderMessage("No links returned from scraper.");
        return;
      }

      const cards = links.slice(0, MAX_CARDS).map((item) =>
        buildCard({
          url: item.url,
          title: item.title || item.url,
          description: item.url,
          imageUrl: item.image_url || ""
        }).card
      );

      renderCards(cards);
    } catch (error) {
      renderMessage("Failed to load from scraper.");
    }
  };

  sidebar.refresh.addEventListener("click", () => {
    loadCards();
  });

  loadCards();
})();
