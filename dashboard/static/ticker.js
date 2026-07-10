/* ticker.js — the browser-side logic for a single ticker's detail page.
   Loads everything from /api/ticker/<symbol>, draws the chart (line or
   candles), the stats grid, the news list, and the plain-English deep dive. */

/* esc() makes text safe to drop into our HTML template strings by turning
   the special characters into their harmless display forms ("<" → "&lt;").
   Without it, a news headline or AI sentence containing HTML would be
   EXECUTED by the browser instead of displayed — the classic "XSS" attack.
   (Same helper lives in app.js — each page's script is self-contained.) */
function esc(text) {
  return String(text ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

/* Links from outside (news articles) go through safeUrl(): only real web
   addresses pass; anything else (e.g. "javascript:...") becomes "#". */
function safeUrl(url) {
  return /^https?:\/\//i.test(url || "") ? url : "#";
}

let pageData = null;      // everything the API sent us
let chart = null;         // the LightweightCharts chart object
let series = null;        // the line/candle series currently on the chart
let rangeDays = 180;      // which time range is selected
let chartType = "line";   // "line" or "candles"

const fmt = new Intl.NumberFormat("en-US");

/* ── Load everything ─────────────────────────────────────────────────── */
async function load() {
  const res = await fetch(`/api/ticker/${encodeURIComponent(SYMBOL)}`);
  pageData = await res.json();
  if (pageData.status !== "ok") {
    document.getElementById("big-price").textContent = "not found";
    return;
  }

  renderPrice();
  buildChart();
  drawSeries();
  renderStats();
  renderNews();
  renderDeepDive(pageData.deep_dive);
  renderMembership();

  document.getElementById("chart-note").textContent =
    pageData.data_source === "sample"
      ? "Simulated development data (sample mode)."
      : "Live market data — Yahoo Finance daily bars, cached a few minutes.";
}

/* ── Price header ────────────────────────────────────────────────────── */
function renderPrice() {
  const { quote, stats } = pageData;
  document.getElementById("big-price").textContent = `$${quote.price}`;
  const el = document.getElementById("big-change");
  const pct = stats.day_change_pct;
  el.textContent = `${pct >= 0 ? "+" : ""}${pct}% today`;
  el.className = "ticker-change " + (pct >= 0 ? "up" : "down");
}

/* ── Watchlist membership ────────────────────────────────────────────── */
/* A row of tickable chips — one per watchlist. Ticked = this stock is in
   that list. Only watchlisted stocks get the daily AI analysis. */
async function renderMembership() {
  const res = await fetch("/api/watchlists");
  const data = await res.json();
  const inLists = new Set(pageData.in_watchlists || []);
  const box = document.getElementById("wl-membership");

  box.innerHTML = data.watchlists.map((wl) => `
    <label class="wl-check ${inLists.has(wl.id) ? "on" : ""}">
      <input type="checkbox" data-id="${esc(wl.id)}" ${inLists.has(wl.id) ? "checked" : ""}>
      <span class="wl-dot-mini" style="background:${esc(wl.tag.value)}"></span>${esc(wl.name)}
    </label>`).join("");

  box.querySelectorAll("input").forEach((cb) =>
    cb.addEventListener("change", async () => {
      const id = cb.dataset.id;
      if (cb.checked) {
        await fetch(`/api/watchlists/${id}/stocks`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ symbol: SYMBOL, name: pageData.asset.name,
                                 type: pageData.asset.type }),
        });
        inLists.add(id);
      } else {
        await fetch(`/api/watchlists/${id}/stocks/` + encodeURIComponent(SYMBOL),
                    { method: "DELETE" });
        inLists.delete(id);
      }
      pageData.in_watchlists = [...inLists];
      renderMembership();  // redraw so the chip's on/off style updates
    }));
}

/* ── Chart ───────────────────────────────────────────────────────────── */
function buildChart() {
  const box = document.getElementById("chart");
  // chartThemeColors() (from theme.js) returns the current light/dark
  // greys, because the chart canvas can't read CSS variables itself.
  const theme = chartThemeColors();
  chart = LightweightCharts.createChart(box, {
    height: 340,
    layout: { background: { color: "transparent" }, textColor: theme.text,
              fontFamily: getComputedStyle(document.body).fontFamily },
    grid: { vertLines: { visible: false },
            horzLines: { color: theme.grid } },
    rightPriceScale: { borderVisible: false },
    timeScale: { borderVisible: false },
    crosshair: { horzLine: { labelBackgroundColor: theme.crosshairLabel },
                 vertLine: { labelBackgroundColor: theme.crosshairLabel } },
  });
  // Keep the chart the right width when the window resizes.
  new ResizeObserver(() => chart.applyOptions({ width: box.clientWidth }))
    .observe(box);
  // When the ☾/☀ button is pressed, re-read the colours and restyle.
  window.addEventListener("themechange", () => {
    const t = chartThemeColors();
    chart.applyOptions({
      layout: { textColor: t.text },
      grid: { horzLines: { color: t.grid } },
      crosshair: { horzLine: { labelBackgroundColor: t.crosshairLabel },
                   vertLine: { labelBackgroundColor: t.crosshairLabel } },
    });
  });
}

function drawSeries() {
  if (series) chart.removeSeries(series);
  const bars = pageData.history.slice(-rangeDays);

  if (chartType === "line") {
    series = chart.addLineSeries({
      color: "#0f9d6e", lineWidth: 2,
      priceLineVisible: false, lastValueVisible: true,
    });
    series.setData(bars.map((b) => ({ time: b.date, value: b.close })));
  } else {
    // Market-green candles for rising days, signal red for falling ones.
    series = chart.addCandlestickSeries({
      upColor: "#0f9d6e", borderUpColor: "#0f9d6e", wickUpColor: "#0f9d6e",
      downColor: "#d13c3c", borderDownColor: "#d13c3c", wickDownColor: "#d13c3c",
    });
    series.setData(bars.map((b) => ({
      time: b.date, open: b.open, high: b.high, low: b.low, close: b.close,
    })));
  }
  chart.timeScale().fitContent();
}

/* The two segmented controls above the chart. */
function wireSegGroup(groupId, onPick) {
  const group = document.getElementById(groupId);
  group.addEventListener("click", (e) => {
    const btn = e.target.closest(".seg");
    if (!btn) return;
    group.querySelectorAll(".seg").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    onPick(btn);
  });
}
wireSegGroup("range-group", (btn) => { rangeDays = Number(btn.dataset.days); drawSeries(); });
wireSegGroup("type-group", (btn) => { chartType = btn.dataset.type; drawSeries(); });

/* ── Statistics grid ─────────────────────────────────────────────────── */
function renderStats() {
  const s = pageData.stats;
  const cells = [
    ["Open", `$${s.open}`],
    ["High", `$${s.high}`],
    ["Low", `$${s.low}`],
    ["Prev close", `$${s.prev_close}`],
    ["52W high", `$${s.week52_high}`],
    ["52W low", `$${s.week52_low}`],
    ["Volume", fmt.format(s.volume)],
    ["Avg vol (30d)", fmt.format(s.avg_volume_30d)],
    ["Market cap", "—"],
    ["P/E", "—"],
  ];
  document.getElementById("stats-grid").innerHTML = cells
    .map(([label, value]) =>
      `<div class="stat"><span class="stat-label">${label}</span>
       <span class="stat-value">${value}</span></div>`)
    .join("");
}

/* ── News list ───────────────────────────────────────────────────────── */
function renderNews() {
  const items = pageData.news;
  const box = document.getElementById("news-list");
  if (!items.length) {
    box.innerHTML = `<p class="status-line">No headlines could be fetched right now.</p>`;
    return;
  }
  box.innerHTML = items
    .map((n) => `
      <a class="news-item" href="${esc(safeUrl(n.link))}" target="_blank" rel="noopener">
        <span class="news-title">${esc(n.title)}</span>
        <span class="news-meta">${esc(n.source)}${n.published ? " · " + esc(n.published.slice(0, 16)) : ""}</span>
      </a>`)
    .join("");
}

/* ── The deep dive (“Why this rating”) ───────────────────────────────── */
const ddButton = document.getElementById("deep-dive-btn");
const ddStatus = document.getElementById("deep-dive-status");

ddButton.addEventListener("click", async () => {
  ddButton.disabled = true;
  ddStatus.textContent = "Asking the AI for a full breakdown — takes ~20 seconds…";
  try {
    const res = await fetch(
      `/api/ticker/${encodeURIComponent(SYMBOL)}/deep-dive`, { method: "POST" });
    const data = await res.json();
    if (data.status === "ok") {
      ddStatus.textContent = "";
      renderDeepDive(data.deep_dive);
    } else {
      ddStatus.textContent = "⚠ " + data.message;
    }
  } catch (err) {
    ddStatus.textContent = "⚠ Could not reach the server: " + err.message;
  } finally {
    ddButton.disabled = false;
  }
});

function scoreRow(label, part) {
  // A labelled 0-10 score bar plus its plain-English explanation.
  return `
    <div class="score-row">
      <div class="score-row-head">
        <span class="score-row-label">${label}</span>
        <span class="score-row-num">${esc(part.score)}/10</span>
      </div>
      <div class="score-bar"><div class="score-bar-fill" style="width:${part.score * 10}%"></div></div>
      <p class="score-row-text">${esc(part.explanation)}</p>
      ${(part.evidence || [])
        .map((e) => `<p class="evidence">“${esc(e.headline)}” — ${esc(e.takeaway)}</p>`)
        .join("")}
    </div>`;
}

function renderDeepDive(dd) {
  const box = document.getElementById("deep-dive");
  if (!dd) {
    box.innerHTML = `<p class="status-line">No deep dive yet — press the button
      to have the AI explain this ticker's rating in plain English
      (one small AI request, then cached).</p>`;
    return;
  }
  ddButton.textContent = "Refresh deep dive";
  const screen = pageData.screen;
  box.innerHTML = `
    ${screen ? `<p class="dd-conviction">Quick-screen conviction:
      <span class="score-badge">${screen.conviction}/10</span> · verdict: ${esc(screen.verdict)}</p>` : ""}
    <p class="dd-overview">${esc(dd.overview)}</p>
    <p><strong>Why this score:</strong> ${esc(dd.rating_rationale)}</p>
    ${scoreRow("Technical", dd.technical)}
    ${scoreRow("Sentiment", dd.sentiment)}
    ${scoreRow("Fundamentals", dd.fundamentals)}
    <div class="dd-block"><strong>Main risks</strong>
      <ul>${dd.risks.map((r) => `<li>${esc(r)}</li>`).join("")}</ul></div>
    <div class="dd-block"><strong>What would change this rating:</strong>
      ${esc(dd.what_would_change)}</div>
    <p class="fine-print">Generated ${esc(dd.generated_at.replace("T", " "))}.
      Fundamentals come from the AI's general knowledge and may be a few
      months out of date.</p>`;
}

load();
