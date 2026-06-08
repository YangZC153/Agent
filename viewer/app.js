let allPapers = [];
let favorites = new Set();
const FAVORITES_STORAGE_KEY = "hermes-arxiv-agent:favorites";

function loadFavorites() {
  try {
    const raw = window.localStorage.getItem(FAVORITES_STORAGE_KEY);
    const payload = raw ? JSON.parse(raw) : [];
    const arr = Array.isArray(payload) ? payload : [];
    favorites = new Set(arr.map((x) => String(x)));
  } catch (err) {
    console.warn("加载本地收藏失败", err);
    favorites = new Set();
  }
}

function saveFavorites() {
  try {
    window.localStorage.setItem(FAVORITES_STORAGE_KEY, JSON.stringify(Array.from(favorites)));
  } catch (err) {
    throw new Error(`保存收藏失败: ${err.message || err}`);
  }
}

function isFavorite(arxivId) {
  return favorites.has(String(arxivId));
}

async function toggleFavorite(arxivId) {
  const key = String(arxivId);
  if (favorites.has(key)) {
    favorites.delete(key);
  } else {
    favorites.add(key);
  }
  await saveFavorites();
}

function text(v) {
  return (v || "").toString();
}

function formatDate(date) {
  const y = date.getFullYear();
  const m = `${date.getMonth() + 1}`.padStart(2, "0");
  const d = `${date.getDate()}`.padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function daysAgo(baseDate, days) {
  const d = new Date(baseDate);
  d.setDate(d.getDate() - days);
  return d;
}

function inRange(dateValue, start, end) {
  if (!dateValue) {
    return false;
  }
  if (start && dateValue < start) {
    return false;
  }
  if (end && dateValue > end) {
    return false;
  }
  return true;
}

function matchesKeyword(paper, keyword) {
  if (!keyword) {
    return true;
  }
  const target = [
    paper.arxiv_id,
    paper.title,
    paper.authors,
    paper.affiliations,
    paper.categories,
    paper.summary_cn,
    paper.abstract,
  ].join(" ").toLowerCase();
  return target.includes(keyword.toLowerCase());
}

function renderCards(papers) {
  const container = document.getElementById("cards");
  container.innerHTML = "";

  if (!papers.length) {
    const div = document.createElement("div");
    div.className = "empty";
    div.textContent = "当前筛选条件下没有论文。";
    container.appendChild(div);
    return;
  }

  const tpl = document.getElementById("paperTpl");
  papers.forEach((p) => {
    const node = tpl.content.cloneNode(true);

    node.querySelector(".pill").textContent = p.arxiv_id;

    const title = node.querySelector(".title");
    title.textContent = text(p.title) || p.arxiv_id;
    title.href = `https://arxiv.org/abs/${p.arxiv_id}`;

    const favBtn = node.querySelector(".favorite-btn");
    const favored = isFavorite(p.arxiv_id);
    favBtn.classList.toggle("active", favored);
    favBtn.textContent = favored ? "★ 已收藏" : "☆ 收藏";
    favBtn.addEventListener("click", async () => {
      favBtn.disabled = true;
      try {
        await toggleFavorite(p.arxiv_id);
        applyFilter();
      } catch (err) {
        alert(err.message || "保存收藏失败");
      } finally {
        favBtn.disabled = false;
      }
    });

    node.querySelector(".meta").textContent =
      `抓取: ${text(p.crawled_date) || "-"} | 发表: ${text(p.published_date) || "-"}` +
      `\n作者: ${text(p.authors) || "-"}`;

    const tags = node.querySelector(".tags");
    const cats = text(p.categories)
      .split(",")
      .map((x) => x.trim())
      .filter(Boolean);
    cats.forEach((cat) => {
      const span = document.createElement("span");
      span.className = "tag";
      span.textContent = cat;
      tags.appendChild(span);
    });

    node.querySelector(".affiliations").textContent = text(p.affiliations) || "未提供";
    node.querySelector(".summary-cn").textContent = text(p.summary_cn) || "未提供";
    node.querySelector(".abstract").textContent = text(p.abstract) || "未提供";

    container.appendChild(node);
  });
}

function applyFilter() {
  const dateMode = document.getElementById("dateMode").value;
  const start = document.getElementById("startDate").value;
  const end = document.getElementById("endDate").value;
  const keyword = document.getElementById("keyword").value.trim();
  const favoriteOnly = document.getElementById("favoriteOnly").checked;

  const papers = allPapers.filter((p) =>
    inRange(text(p[dateMode]), start, end) &&
    matchesKeyword(p, keyword) &&
    (!favoriteOnly || isFavorite(p.arxiv_id))
  );
  renderCards(papers);

  const summary = document.getElementById("summary");
  summary.textContent = `共 ${allPapers.length} 篇，收藏 ${favorites.size} 篇，当前展示 ${papers.length} 篇（按 ${dateMode === "crawled_date" ? "抓取日期" : "发表日期"} 筛选）`;
}

function resetFilter(defaultMin, defaultMax) {
  document.getElementById("dateMode").value = "crawled_date";
  document.getElementById("startDate").value = defaultMin || "";
  document.getElementById("endDate").value = defaultMax || "";
  document.getElementById("keyword").value = "";
  document.getElementById("favoriteOnly").checked = false;
  applyFilter();
}

function applyQuickRange(range) {
  const startDate = document.getElementById("startDate");
  const endDate = document.getElementById("endDate");
  const today = new Date();
  const end = formatDate(today);

  if (range === "all") {
    startDate.value = "";
    endDate.value = "";
    applyFilter();
    return;
  }

  if (range === "today") {
    startDate.value = end;
    endDate.value = end;
    applyFilter();
    return;
  }

  if (range === "3d") {
    startDate.value = formatDate(daysAgo(today, 2));
    endDate.value = end;
    applyFilter();
    return;
  }

  if (range === "7d") {
    startDate.value = formatDate(daysAgo(today, 6));
    endDate.value = end;
    applyFilter();
  }
}

async function init() {
  const res = await fetch("papers_data.json", { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`加载 papers_data.json 失败: HTTP ${res.status}`);
  }

  const payload = await res.json();
  allPapers = payload.papers || [];
  loadFavorites();

  const defaultMin = payload.crawled_date_min || "";
  const defaultMax = payload.crawled_date_max || "";

  document.getElementById("metaText").textContent =
    `收录 ${payload.count || allPapers.length} 篇 | 抓取区间 ${defaultMin || "-"} ~ ${defaultMax || "-"}`;

  const startDate = document.getElementById("startDate");
  const endDate = document.getElementById("endDate");
  startDate.value = defaultMin;
  endDate.value = defaultMax;

  document.getElementById("applyBtn").addEventListener("click", applyFilter);
  document.getElementById("resetBtn").addEventListener("click", () => resetFilter(defaultMin, defaultMax));
  document.getElementById("favoriteOnly").addEventListener("change", applyFilter);
  document.getElementById("quickRange").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-range]");
    if (!btn) {
      return;
    }
    applyQuickRange(btn.dataset.range);
  });
  document.getElementById("keyword").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      applyFilter();
    }
  });

  applyFilter();
}

init().catch((err) => {
  const summary = document.getElementById("summary");
  summary.textContent = err.message;
});
