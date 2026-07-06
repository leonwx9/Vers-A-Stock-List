/* app.js — the browser-side logic for the main dashboard page.
   1. On page load, fetch the last saved analysis and draw it.
   2. "Run analysis" asks the server for a fresh run.
   3. The table can be filtered (search box) and sorted (click a header),
      and clicking any row or shortlist card opens that ticker's own page. */

const statusLine = document.getElementById("analysis-status");
const runButton = document.getElementById("run-analysis-btn");

let currentRows = [];                       // the rows currently displayed
let sortState = { key: "conviction", dir: -1 };  // default: best score first
let filterText = "";

// Collapse preferences survive page reloads via localStorage (a tiny
// key-value store the browser keeps per site).
let tableCollapsed = localStorage.getItem("collapse-tickers") === "1";
let holdingsCollapsed = localStorage.getItem("collapse-holdings") === "1";

// Which period the change column shows (1D … All time), remembered per browser.
const CHANGE_RANGES = ["1D", "1W", "1M", "3M", "1Y", "5Y", "ALL"];
let changeRange = localStorage.getItem("change-range") || "1M";

/* The change-% of a row for the selected period. Old saved runs (before the
   dropdown existed) only have the 30-day number — reuse it for 1M. */
function rowChange(r) {
  if (r.changes && r.changes[changeRange] !== undefined) return r.changes[changeRange];
  if (changeRange === "1M") return r.change_30d_pct;
  return null;
}

/* ── 1. Load whatever analysis already exists ─────────────────────────── */
async function loadExisting() {
  const res = await fetch("/api/analysis");
  const data = await res.json();
  if (data.status === "ok") {
    render(data);
  } else {
    statusLine.textContent = "No analysis yet — press “Run analysis” to do the first one.";
  }
}

/* ── 2. Run a fresh analysis when the button is pressed ───────────────── */
runButton.addEventListener("click", async () => {
  runButton.disabled = true;
  statusLine.textContent = "Running analysis of the full universe — this takes a minute or two…";
  showSkeletons();
  try {
    const res = await fetch("/api/run-analysis", { method: "POST" });
    const data = await res.json();
    if (data.status === "ok") {
      render(data);
    } else {
      statusLine.textContent = "⚠ " + data.message;
      clearSkeletons();
    }
  } catch (err) {
    statusLine.textContent = "⚠ Could not reach the server: " + err.message;
    clearSkeletons();
  } finally {
    runButton.disabled = false;
  }
});

/* Grey shimmer placeholders while the AI works. */
function showSkeletons() {
  document.getElementById("shortlist").innerHTML =
    `<div class="pick-grid">` +
    `<div class="skeleton" style="height:150px"></div>`.repeat(5) +
    `</div>`;
  document.getElementById("analysis-table").innerHTML =
    `<div class="skeleton" style="height:300px;margin-top:1rem"></div>`;
}
function clearSkeletons() {
  document.getElementById("shortlist").innerHTML = "";
  document.getElementById("analysis-table").innerHTML = "";
}

/* ── Navigation helper ────────────────────────────────────────────────── */
function openTicker(symbol) {
  // encodeURIComponent keeps symbols like BRK/B safe inside a URL.
  window.location.href = `/ticker/${encodeURIComponent(symbol)}`;
}

/* ── Drawing ──────────────────────────────────────────────────────────── */
function render(data) {
  statusLine.textContent =
    `Last run: ${data.run_at.replace("T", " ")} · data source: ${data.data_source}`;
  currentRows = data.rows;
  renderShortlist(data);
  renderTable();
}

function renderShortlist(data) {
  const bySymbol = Object.fromEntries(data.rows.map((r) => [r.symbol, r]));
  const cards = data.shortlist.map((symbol) => {
    const r = bySymbol[symbol];
    return `
      <div class="pick-card" data-symbol="${r.symbol}">
        <div class="pick-head">
          <span class="pick-symbol">${r.symbol}</span>
          <span class="score-badge">${r.conviction}/10</span>
        </div>
        <div class="pick-name">${r.name}</div>
        <div class="pick-detail"><strong>Bull:</strong> ${r.bull}</div>
        <div class="pick-detail"><strong>Bear:</strong> ${r.bear}</div>
        <div class="pick-meta">$${r.price} · ${r.timeframe} · ${r.stop_loss}</div>
      </div>`;
  });
  const box = document.getElementById("shortlist");
  box.innerHTML =
    `<h3 class="subheading">Shortlist — top ${data.shortlist.length} picks</h3>
     <div class="pick-grid">${cards.join("")}</div>`;
  box.querySelectorAll(".pick-card").forEach((card) =>
    card.addEventListener("click", () => openTicker(card.dataset.symbol)));
}

function renderTable() {
  // When collapsed, show just the heading with a "Show" button.
  if (tableCollapsed) {
    document.getElementById("analysis-table").innerHTML = `
      <div class="panel-header" style="margin-top:1rem">
        <h3 class="subheading">All ${currentRows.length} tickers</h3>
        <button id="toggle-table" class="mini-btn">Show</button>
      </div>`;
    wireTableToggle();
    return;
  }

  // Apply the search filter, then the current sort.
  const text = filterText.toLowerCase();
  currentRows.forEach((r) => { r.change_sel = rowChange(r) ?? -Infinity; });
  const rows = currentRows
    .filter((r) =>
      r.symbol.toLowerCase().includes(text) || r.name.toLowerCase().includes(text))
    .sort((a, b) => {
      const va = a[sortState.key], vb = b[sortState.key];
      const cmp = typeof va === "string" ? va.localeCompare(vb) : va - vb;
      return cmp * sortState.dir;
    });

  const arrow = (key) =>
    sortState.key === key ? (sortState.dir === 1 ? " ↑" : " ↓") : "";

  const body = rows
    .map((r) => {
      const flags = r.flags.map((f) => `<span class="flag-tag">${f}</span>`).join("");
      const chg = rowChange(r);
      const changeCell = chg === null
        ? `<td class="hint">—</td>`
        : `<td class="${chg >= 0 ? "up" : "down"}">${chg >= 0 ? "+" : ""}${chg}%</td>`;
      return `
      <tr class="main-row" data-symbol="${r.symbol}">
        <td><strong>${r.symbol}</strong>${flags}</td>
        <td class="col-name">${r.name}</td>
        <td>$${r.price}</td>
        ${changeCell}
        <td>
          <div class="cell-score">
            <div class="score-bar"><div class="score-bar-fill" style="width:${r.conviction * 10}%"></div></div>
            ${r.conviction}
          </div>
        </td>
        <td class="row-chevron">›</td>
      </tr>`;
    })
    .join("");

  document.getElementById("analysis-table").innerHTML = `
    <div class="panel-header" style="margin-top:1rem">
      <h3 class="subheading">All ${rows.length} tickers <span class="hint">(click a row to open its page)</span></h3>
      <div class="btn-row">
        <input id="filter-input" class="filter-input" type="search"
               placeholder="Filter by ticker or name…" value="${filterText}">
        <button id="toggle-table" class="mini-btn">Hide</button>
      </div>
    </div>
    <table>
      <thead>
        <tr>
          <th data-sort="symbol">Ticker${arrow("symbol")}</th>
          <th data-sort="name" class="col-name">Name${arrow("name")}</th>
          <th data-sort="price">Price${arrow("price")}</th>
          <th data-sort="change_sel">
            <select id="range-select" class="range-select" title="Change period">
              ${CHANGE_RANGES.map((p) =>
                `<option value="${p}" ${p === changeRange ? "selected" : ""}>${p === "ALL" ? "All" : p}</option>`).join("")}
            </select>${arrow("change_sel")}
          </th>
          <th data-sort="conviction">Score${arrow("conviction")}</th>
          <th></th>
        </tr>
      </thead>
      <tbody>${body}</tbody>
    </table>`;

  // Rows open the ticker's own page.
  document.querySelectorAll(".main-row").forEach((row) =>
    row.addEventListener("click", () => openTicker(row.dataset.symbol)));

  // Headers sort; clicking the same header again flips the direction.
  document.querySelectorAll("th[data-sort]").forEach((th) =>
    th.addEventListener("click", () => {
      const key = th.dataset.sort;
      sortState = {
        key,
        dir: sortState.key === key ? -sortState.dir : -1,
      };
      renderTable();
    }));

  // The filter box re-renders as you type. Re-focus it afterwards, because
  // re-drawing the table replaces the input element.
  const filterInput = document.getElementById("filter-input");
  filterInput.addEventListener("input", () => {
    filterText = filterInput.value;
    renderTable();
    const el = document.getElementById("filter-input");
    el.focus();
    el.setSelectionRange(el.value.length, el.value.length);
  });

  const rangeSelect = document.getElementById("range-select");
  rangeSelect.addEventListener("click", (e) => e.stopPropagation());
  rangeSelect.addEventListener("change", () => {
    changeRange = rangeSelect.value;
    localStorage.setItem("change-range", changeRange);
    renderTable();
  });

  wireTableToggle();
}

/* The Hide/Show button for the big ticker table. */
function wireTableToggle() {
  document.getElementById("toggle-table").addEventListener("click", () => {
    tableCollapsed = !tableCollapsed;
    localStorage.setItem("collapse-tickers", tableCollapsed ? "1" : "0");
    renderTable();
  });
}

loadExisting();

/* ── Paper Portfolio panel ────────────────────────────────────────────── */
const pfStatus = document.getElementById("portfolio-status");
let pfChart = null;
let pfSeries = null;

async function loadPortfolio() {
  const res = await fetch("/api/portfolio");
  renderPortfolio(await res.json());
}

document.getElementById("sync-btn").addEventListener("click", async () => {
  pfStatus.textContent = "Syncing the portfolio to the shortlist…";
  const res = await fetch("/api/portfolio/sync", { method: "POST" });
  const data = await res.json();
  if (data.status === "ok") {
    const n = data.trades_made.length;
    pfStatus.textContent = n
      ? `Done — ${n} trade${n > 1 ? "s" : ""}: ` +
        data.trades_made.map((t) => `${t.action} ${t.shares} ${t.symbol}`).join(", ")
      : "Done — already in sync, no trades needed.";
    renderPortfolio(data);
  } else {
    pfStatus.textContent = "⚠ " + data.message;
  }
});

document.getElementById("reset-btn").addEventListener("click", async () => {
  // confirm() pops the browser's built-in "are you sure?" box.
  if (!confirm("Reset the paper portfolio back to $10,000 cash? " +
               "All pretend holdings and history will be wiped.")) return;
  const res = await fetch("/api/portfolio/reset", { method: "POST" });
  pfStatus.textContent = "Portfolio reset.";
  renderPortfolio(await res.json());
});

function renderPortfolio(data) {
  // The big number + change since the $10,000 start.
  document.getElementById("pf-value").textContent =
    "$" + data.total_value.toLocaleString("en-US", { minimumFractionDigits: 2 });
  const changeEl = document.getElementById("pf-change");
  changeEl.textContent =
    `${data.since_start_pct >= 0 ? "+" : ""}${data.since_start_pct}% since start · ` +
    `$${data.cash.toLocaleString("en-US", { minimumFractionDigits: 2 })} cash`;
  changeEl.className = "ticker-change " + (data.since_start_pct >= 0 ? "up" : "down");

  drawPortfolioChart(data.history);
  renderHoldings(data.holdings);
}

function drawPortfolioChart(history) {
  const box = document.getElementById("pf-chart");
  if (!pfChart) {
    // chartThemeColors() (from theme.js) returns the current light/dark
    // greys, because the chart canvas can't read CSS variables itself.
    const theme = chartThemeColors();
    pfChart = LightweightCharts.createChart(box, {
      height: 220,
      layout: { background: { color: "transparent" }, textColor: theme.text,
                fontFamily: getComputedStyle(document.body).fontFamily },
      grid: { vertLines: { visible: false }, horzLines: { color: theme.grid } },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false },
    });
    // When the ☾/☀ button is pressed, re-read the colours and restyle.
    window.addEventListener("themechange", () => {
      const t = chartThemeColors();
      pfChart.applyOptions({
        layout: { textColor: t.text },
        grid: { horzLines: { color: t.grid } },
      });
    });
    // A market-green line with a soft green wash underneath.
    pfSeries = pfChart.addAreaSeries({
      lineColor: "#0f9d6e", lineWidth: 2,
      topColor: "rgba(15,157,110,0.16)", bottomColor: "rgba(15,157,110,0.0)",
      priceLineVisible: false,
    });
    new ResizeObserver(() => pfChart.applyOptions({ width: box.clientWidth }))
      .observe(box);
  }
  pfSeries.setData(history.map((p) => ({ time: p.date, value: p.total_value })));
  pfChart.timeScale().fitContent();

  // One data point can't draw a line — explain that instead of looking broken.
  document.getElementById("pf-chart").title =
    history.length < 2 ? "The graph grows a point per day the app is used." : "";
}

function renderHoldings(holdings) {
  const box = document.getElementById("pf-holdings");
  if (!holdings.length) {
    box.innerHTML = `<p class="status-line">No holdings yet — run an analysis,
      then press “Sync to shortlist” to invest the pretend cash.</p>`;
    return;
  }

  const toggleBtn = `<button id="toggle-holdings" class="mini-btn">
    ${holdingsCollapsed ? "Show" : "Hide"}</button>`;

  // When collapsed, show just the heading with a "Show" button.
  if (holdingsCollapsed) {
    box.innerHTML = `
      <div class="panel-header">
        <h3 class="subheading">Holdings (${holdings.length})</h3>
        ${toggleBtn}
      </div>`;
    wireHoldingsToggle(holdings);
    return;
  }

  const rows = holdings.map((h) => `
    <tr class="main-row" data-symbol="${h.symbol}">
      <td><strong>${h.symbol}</strong></td>
      <td>${h.shares}</td>
      <td>$${h.avg_cost}</td>
      <td>$${h.price}</td>
      <td>$${h.value.toLocaleString("en-US")}</td>
      <td class="${h.pl >= 0 ? "up" : "down"}">
        ${h.pl >= 0 ? "+" : ""}$${h.pl.toLocaleString("en-US")} (${h.pl_pct >= 0 ? "+" : ""}${h.pl_pct}%)
      </td>
      <td class="row-chevron">›</td>
    </tr>`).join("");

  box.innerHTML = `
    <div class="panel-header">
      <h3 class="subheading">Holdings (${holdings.length})</h3>
      ${toggleBtn}
    </div>
    <table>
      <thead><tr>
        <th>Ticker</th><th>Shares</th><th>Paid</th><th>Now</th><th>Value</th><th>P / L</th><th></th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>`;

  box.querySelectorAll(".main-row").forEach((row) =>
    row.addEventListener("click", () => openTicker(row.dataset.symbol)));
  wireHoldingsToggle(holdings);
}

/* The Hide/Show button for the holdings table. */
function wireHoldingsToggle(holdings) {
  document.getElementById("toggle-holdings").addEventListener("click", () => {
    holdingsCollapsed = !holdingsCollapsed;
    localStorage.setItem("collapse-holdings", holdingsCollapsed ? "1" : "0");
    renderHoldings(holdings);
  });
}

loadPortfolio();

/* ── Sidebar: highlight the section currently on screen ──────────────── */
/* An IntersectionObserver tells us when each section crosses a band near
   the top of the viewport; the matching sidebar link turns black. */
const sideLinks = [...document.querySelectorAll(".side-link")];
const observer = new IntersectionObserver(
  (entries) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return;
      sideLinks.forEach((link) =>
        link.classList.toggle(
          "active",
          link.getAttribute("href") === `#${entry.target.id}`,
        ));
    });
  },
  { rootMargin: "-20% 0px -70% 0px" }, // the "reading band" near the top
);
["stock-searcher", "portfolio", "pivot-scanner"].forEach((id) =>
  observer.observe(document.getElementById(id)));

/* ── AI Pivot Scanner panel ───────────────────────────────────────────── */
const scanStatus = document.getElementById("scanner-status");
const scanButton = document.getElementById("scan-btn");

async function loadScanner() {
  const res = await fetch("/api/scanner");
  const data = await res.json();
  if (data.status === "ok") {
    renderScanner(data);
  } else {
    scanStatus.textContent =
      "No scan yet — press “Scan EDGAR” to search recent SEC filings.";
  }
}

scanButton.addEventListener("click", async () => {
  scanButton.disabled = true;
  scanStatus.textContent =
    "Scanning EDGAR and reading filings — this takes a minute or two…";
  document.getElementById("scanner-results").innerHTML =
    `<div class="skeleton" style="height:180px"></div>`;
  try {
    const res = await fetch("/api/scan", { method: "POST" });
    const data = await res.json();
    if (data.status === "ok") {
      renderScanner(data);
    } else {
      scanStatus.textContent = "⚠ " + data.message;
      document.getElementById("scanner-results").innerHTML = "";
    }
  } catch (err) {
    scanStatus.textContent = "⚠ Could not reach the server: " + err.message;
    document.getElementById("scanner-results").innerHTML = "";
  } finally {
    scanButton.disabled = false;
  }
});

function renderScanner(data) {
  scanStatus.textContent =
    `Last scan: ${data.run_at.replace("T", " ")} · last ${data.lookback_days} days ` +
    `· ${data.candidates_checked} filings examined · ${data.hits.length} qualified`;

  const cards = data.hits.map((h) => `
    <div class="scan-card">
      <div class="scan-head">
        <div>
          <span class="pick-symbol">${h.company}</span>
          ${h.ticker ? `<span class="flag-tag">${h.ticker}</span>` : ""}
          <div class="pick-name">${h.industry} · ${h.form} filed ${h.file_date}</div>
        </div>
        <span class="hype-badge" title="10 = pure hype, 1 = real substance">
          hype ${h.hype_score}/10</span>
      </div>
      <p><strong>What they announced:</strong> ${h.what_they_announced}</p>
      <p><strong>Announced vs executed:</strong> ${h.announced_vs_executed}</p>
      <p><strong>Can they fund it:</strong> ${h.funding_ability}</p>
      <div class="dd-block"><strong>Red flags</strong>
        <ul>${h.red_flags.map((r) => `<li>${r}</li>`).join("")}</ul></div>
      <p class="scan-bottom">${h.bottom_line}</p>
      <a class="filing-link" href="${h.filing_url}" target="_blank" rel="noopener">
        View the filing on SEC EDGAR →</a>
    </div>`).join("");

  // Companies that were checked but didn't qualify, tucked into a
  // <details> element (a built-in HTML collapsible).
  const excluded = data.excluded.length
    ? `<details class="excluded-list">
         <summary>${data.excluded.length} filings examined but excluded</summary>
         <ul>${data.excluded.map((e) =>
           `<li><strong>${e.company}</strong> — ${e.reason}</li>`).join("")}</ul>
       </details>`
    : "";

  document.getElementById("scanner-results").innerHTML =
    (cards || `<p class="status-line">No qualifying AI pivots found in the
       last ${data.lookback_days} days — small-cap non-tech pivots are
       genuinely rare, which is rather the point.</p>`) + excluded;
}

loadScanner();
