/* app.js — the browser-side logic for the main dashboard page.
   1. On page load, fetch the last saved analysis and draw it.
   2. "Run analysis" asks the server for a fresh run.
   3. The table can be filtered (search box) and sorted (click a header),
      and clicking any row or shortlist card opens that ticker's own page. */

/* esc() makes text safe to drop into our HTML template strings by turning
   the special characters into their harmless display forms ("<" → "&lt;").
   Without it, a news headline or company name containing HTML would be
   EXECUTED by the browser instead of displayed — the classic "XSS" attack.
   Rule of thumb: every ${...} that isn't a number we computed ourselves
   goes through esc(). (Same helper lives in ticker.js — each page's script
   is deliberately self-contained.) */
function esc(text) {
  return String(text ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

/* Links that came from outside (news articles, SEC filings) go through
   safeUrl(): only real web addresses pass; anything else (for example a
   "javascript:" URL, which would run code when clicked) becomes "#". */
function safeUrl(url) {
  return /^https?:\/\//i.test(url || "") ? url : "#";
}

const statusLine = document.getElementById("analysis-status");
const runButton = document.getElementById("run-analysis-btn");

let currentRows = [];                       // the rows currently displayed
let sortState = { key: "conviction", dir: -1 };  // default: best score first
let filterText = "";
let wlFilter = "all";                       // which watchlist the table shows

// The latest analysis's HOLD/SELL review of each currently-held stock, and
// the portfolio's own list of what it currently holds — the "Sell
// decisions" panel needs BOTH (one loads from /api/analysis, the other
// from /api/portfolio, independently and in either order), so it re-draws
// itself whichever one finishes loading last.
let heldReviews = {};
let currentHoldingSymbols = [];

// Collapse preferences survive page reloads via localStorage (a tiny
// key-value store the browser keeps per site).
// Everything hideable starts HIDDEN (the "!== '0'" pattern): folded unless
// the user has explicitly opened it before (which saves "0"). This keeps a
// freshly-opened dashboard — especially the cloud one on a phone — tidy.
let tableCollapsed = localStorage.getItem("collapse-tickers") !== "0";
let holdingsCollapsed = localStorage.getItem("collapse-holdings") !== "0";

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
/* The dropdown NEXT TO the button decides what gets analysed — one
   watchlist, or all of them. Chosen first, then Run. */
const scopeSelect = document.getElementById("analyze-scope");
scopeSelect.addEventListener("change", () =>
  localStorage.setItem("analyze-scope", scopeSelect.value));

function fillScopeOptions() {
  // The saved choice can only be applied once the options exist.
  const saved = localStorage.getItem("analyze-scope") || "all";
  scopeSelect.innerHTML = `<option value="all">All watchlists</option>` +
    wlData.watchlists.map((w) =>
      `<option value="${esc(w.id)}">${esc(w.name)}</option>`).join("");
  // Keep the previous choice if that list still exists.
  scopeSelect.value =
    [...scopeSelect.options].some((o) => o.value === saved) ? saved : "all";
}

runButton.addEventListener("click", async () => {
  runButton.disabled = true;
  const scopeName = scopeSelect.selectedOptions[0].textContent;
  statusLine.textContent =
    `Running analysis of ${scopeName} — this takes a minute or two…`;
  showSkeletons();
  try {
    const res = await fetch("/api/run-analysis", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ watchlist: scopeSelect.value }),
    });
    const data = await res.json();
    if (data.status === "ok") {
      render(data);
      loadPortfolio();  // this run may have just placed orders — show them
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
  const orderNote = data.orders_placed
    ? ` · ${data.orders_placed.length} order${data.orders_placed.length === 1 ? "" : "s"} placed`
    : "";
  statusLine.textContent =
    `Last run: ${data.run_at.replace("T", " ")} · analysed: ${data.scope || "all watchlists"}` +
    ` · data source: ${data.data_source}${orderNote}`;
  currentRows = data.rows;
  renderShortlist(data);
  renderTable();
  renderWatchlists();  // fresh analysis prices → fill the Price columns
  heldReviews = data.held_reviews || {};
  renderSellDecisions();
}

function renderShortlist(data) {
  const bySymbol = Object.fromEntries(data.rows.map((r) => [r.symbol, r]));
  const cards = data.shortlist.map((symbol) => {
    const r = bySymbol[symbol];
    return `
      <div class="pick-card" data-symbol="${esc(r.symbol)}">
        <div class="pick-head">
          <span class="pick-symbol">${esc(r.symbol)}</span>
          <span class="score-badge">${r.conviction}/10</span>
        </div>
        <div class="pick-name">${esc(r.name)}</div>
        <div class="pick-detail"><strong>Bull:</strong> ${esc(r.bull)}</div>
        <div class="pick-detail"><strong>Bear:</strong> ${esc(r.bear)}</div>
        <div class="pick-meta">$${r.price} · ${esc(r.timeframe)} · ${esc(r.stop_loss)}</div>
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

  // Apply the watchlist filter, then the search filter, then the sort.
  const chosen = wlData.watchlists.find((w) => w.id === wlFilter);
  const inChosen = chosen ? new Set(chosen.symbols) : null;
  const text = filterText.toLowerCase();
  currentRows.forEach((r) => { r.change_sel = rowChange(r) ?? -Infinity; });
  const rows = currentRows
    .filter((r) => !inChosen || inChosen.has(r.symbol))
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
      const flags = r.flags.map((f) => `<span class="flag-tag">${esc(f)}</span>`).join("");
      const chg = rowChange(r);
      const changeCell = chg === null
        ? `<td class="hint">—</td>`
        : `<td class="${chg >= 0 ? "up" : "down"}">${chg >= 0 ? "+" : ""}${chg}%</td>`;
      return `
      <tr class="main-row" data-symbol="${esc(r.symbol)}">
        <td><strong>${esc(r.symbol)}</strong>${flags}</td>
        <td class="col-name">${esc(r.name)}</td>
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
      <h3 class="subheading">${chosen ? esc(chosen.name) : "All"} — ${rows.length} tickers <span class="hint">(click a row to open its page)</span></h3>
      <div class="btn-row">
        <select id="wl-table-filter" class="range-select" title="Show one watchlist only">
          <option value="all">All watchlists</option>
          ${wlData.watchlists.map((w) =>
            `<option value="${esc(w.id)}" ${w.id === wlFilter ? "selected" : ""}>${esc(w.name)}</option>`).join("")}
        </select>
        <input id="filter-input" class="filter-input" type="search"
               placeholder="Filter by ticker or name…" value="${esc(filterText)}">
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

  // The watchlist dropdown narrows the table to one list.
  const wlSelect = document.getElementById("wl-table-filter");
  wlSelect.addEventListener("change", () => {
    wlFilter = wlSelect.value;
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
  // Every call settles any orders that became due since the last look —
  // there's no "sync" button any more, the portfolio updates itself.
  const res = await fetch("/api/portfolio");
  renderPortfolio(await res.json());
}

document.getElementById("reset-btn").addEventListener("click", async () => {
  // confirm() pops the browser's built-in "are you sure?" box.
  if (!confirm("Reset the paper portfolio back to $10,000 cash? " +
               "All pretend holdings, orders, and history will be wiped.")) return;
  const res = await fetch("/api/portfolio/reset", { method: "POST" });
  pfStatus.textContent = "Portfolio reset.";
  renderPortfolio(await res.json());
});

/* ── The optional daily order-fill scheduler ──────────────────────────── */
/* Settles pending orders (and records the day's graph point) once past
   8am Sydney time, for as long as the Mac app keeps running — no AI
   involved. Off by default; this just flips the setting on/off. */
const schedulerToggle = document.getElementById("scheduler-toggle");
const schedulerStatus = document.getElementById("scheduler-status");

function renderScheduler(settings) {
  if (!settings) return;  // /api/portfolio/reset doesn't echo it back
  schedulerToggle.checked = !!settings.enabled;
  schedulerStatus.textContent = settings.last_run_date
    ? `Last auto-settle: ${settings.last_run_date}`
    : "Not run yet — turn on to settle orders automatically each morning.";
}

schedulerToggle.addEventListener("change", async () => {
  const wanted = schedulerToggle.checked;
  try {
    const res = await fetch("/api/scheduler", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: wanted }),
    });
    const data = await res.json();
    if (data.status === "ok") {
      renderScheduler(data.scheduler);
    } else {
      schedulerToggle.checked = !wanted;
      schedulerStatus.textContent = "⚠ " + (data.message || "Could not save the setting.");
    }
  } catch (err) {
    schedulerToggle.checked = !wanted;
    schedulerStatus.textContent = "⚠ Could not reach the server: " + err.message;
  }
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
  renderOrders(data.orders || []);
  renderTrades(data.trades || []);
  currentHoldingSymbols = data.holdings.map((h) => h.symbol);
  renderSellDecisions();
  renderScheduler(data.scheduler);
}

/* ── The trade log: every trade, when it happened, and WHY ────────────── */
let tradesCollapsed = localStorage.getItem("collapse-trades") !== "0"; // default: folded

function renderTrades(trades) {
  const box = document.getElementById("pf-trades");
  const toggleBtn = `<button id="toggle-trades" class="mini-btn">
    ${tradesCollapsed ? "Show" : "Hide"}</button>`;
  const head = `
    <div class="panel-header" style="margin-top:1rem">
      <h3 class="subheading">Trade log (${trades.length})
        <span class="hint">fills happen automatically — see Pending orders below</span></h3>
      ${toggleBtn}
    </div>`;

  if (tradesCollapsed || !trades.length) {
    box.innerHTML = head + (trades.length ? "" :
      `<p class="status-line">No trades yet — run an analysis to place some orders.</p>`);
    wireTradesToggle(trades);
    return;
  }

  // Newest first, like a message log.
  const items = [...trades].reverse().map((t) => `
    <div class="trade-item">
      <span class="trade-when">${esc(t.at.replace("T", " "))}</span>
      <span class="trade-badge ${esc(t.action)}">${esc(t.action.toUpperCase())}</span>
      <span class="trade-what">${t.shares} × ${esc(t.symbol)} @ $${t.price}</span>
      <span class="trade-why">${esc(t.reason)}</span>
    </div>`).join("");

  box.innerHTML = head + `<div class="trade-log">${items}</div>`;
  wireTradesToggle(trades);
}

function wireTradesToggle(trades) {
  document.getElementById("toggle-trades").addEventListener("click", () => {
    tradesCollapsed = !tradesCollapsed;
    localStorage.setItem("collapse-trades", tradesCollapsed ? "1" : "0");
    renderTrades(trades);
  });
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
    box.innerHTML = `<p class="status-line">No holdings yet — run an analysis
      to place orders; they'll buy in on their own once the market reaches
      the planned price.</p>`;
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
    <tr class="main-row" data-symbol="${esc(h.symbol)}">
      <td><strong>${esc(h.symbol)}</strong></td>
      <td>${h.shares}</td>
      <td>$${h.avg_cost}</td>
      <td>$${h.price}</td>
      <td>$${h.value.toLocaleString("en-US")}</td>
      <td class="${h.pl >= 0 ? "up" : "down"}">
        ${h.pl >= 0 ? "+" : ""}$${h.pl.toLocaleString("en-US")} (${h.pl_pct >= 0 ? "+" : ""}${h.pl_pct}%)
      </td>
      <td class="hint">-${h.stop_loss_pct}%</td>
      <td class="row-chevron">›</td>
    </tr>`).join("");

  box.innerHTML = `
    <div class="panel-header">
      <h3 class="subheading">Holdings (${holdings.length})</h3>
      ${toggleBtn}
    </div>
    <table>
      <thead><tr>
        <th>Ticker</th><th>Shares</th><th>Paid</th><th>Now</th><th>Value</th><th>P / L</th>
        <th title="Auto-sells if a session closes this far below cost">Stop</th><th></th>
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

/* ── Pending orders: what's planned, and what happened to older ones ──── */
/* An order plans a BUY at a limit price, or a plain SELL — see
   PLAN-order-engine.md for the fill rules. This just displays whatever
   the server hands back: pending orders first, then a little history of
   what was filled/replaced/skipped, so Leon can see what happened to his
   last run's picks even after they've resolved. */
let ordersCollapsed = localStorage.getItem("collapse-orders") !== "0"; // default: folded

const ORDER_STATUS_LABEL = {
  pending: "Pending", filled: "Filled", replaced: "Replaced",
  cancelled: "Cancelled", skipped_bad_price: "Skipped (bad price)",
};

function renderOrders(orders) {
  const box = document.getElementById("pf-orders");
  const toggleBtn = `<button id="toggle-orders" class="mini-btn">
    ${ordersCollapsed ? "Show" : "Hide"}</button>`;
  const pendingCount = orders.filter((o) => o.status === "pending").length;
  const head = `
    <div class="panel-header" style="margin-top:1rem">
      <h3 class="subheading">Pending orders (${pendingCount})
        <span class="hint">fill on their own once a real session reaches the plan</span></h3>
      ${toggleBtn}
    </div>`;

  if (ordersCollapsed || !orders.length) {
    box.innerHTML = head + (orders.length ? "" :
      `<p class="status-line">No orders yet — run an analysis to place some.</p>`);
    wireOrdersToggle(orders);
    return;
  }

  // Pending orders first (most actionable), then everything else newest-ish.
  const sorted = [...orders].sort((a, b) =>
    (a.status === "pending") === (b.status === "pending") ? 0 :
    a.status === "pending" ? -1 : 1);

  const items = sorted.map((o) => {
    const plan = o.type === "buy"
      ? (o.limit_price !== undefined ? `$${o.limit_price} or better` : "—")
      : "next session's open";
    const detail = o.status === "filled"
      ? `filled at $${o.filled_price} (session ${esc(o.filled_at)})`
      : o.status === "cancelled"
      ? esc(o.cancelled_reason || "")
      : esc(o.reason || "");
    return `
      <div class="trade-item ${o.status !== "pending" ? "muted" : ""}">
        <span class="trade-badge ${esc(o.type)}">${esc(o.type.toUpperCase())}</span>
        <span class="trade-what">${esc(o.symbol)} · ${plan}</span>
        <span class="hint">${esc(ORDER_STATUS_LABEL[o.status] || o.status)}</span>
        <span class="trade-why">${detail}</span>
      </div>`;
  }).join("");

  box.innerHTML = head + `<div class="trade-log">${items}</div>`;
  wireOrdersToggle(orders);
}

function wireOrdersToggle(orders) {
  document.getElementById("toggle-orders").addEventListener("click", () => {
    ordersCollapsed = !ordersCollapsed;
    localStorage.setItem("collapse-orders", ordersCollapsed ? "1" : "0");
    renderOrders(orders);
  });
}

/* ── Sell decisions: the AI's HOLD/SELL call on every current holding ──── */
/* Fed by TWO independent loaders (the analysis panel's held_reviews, and
   the portfolio panel's list of what's actually still held) — re-drawn
   from both, so it settles correctly no matter which finishes loading
   first. Only holdings we STILL own are shown, so a stock already sold
   doesn't linger here. */
let sellDecisionsCollapsed = localStorage.getItem("collapse-sell-decisions") !== "0";

function renderSellDecisions() {
  const box = document.getElementById("pf-sell-decisions");
  const rows = currentHoldingSymbols
    .filter((symbol) => heldReviews[symbol])
    .map((symbol) => ({ symbol, ...heldReviews[symbol] }));

  const toggleBtn = `<button id="toggle-sell-decisions" class="mini-btn">
    ${sellDecisionsCollapsed ? "Show" : "Hide"}</button>`;
  const head = `
    <div class="panel-header" style="margin-top:1rem">
      <h3 class="subheading">Sell decisions (${rows.length})
        <span class="hint">why the latest analysis said HOLD or SELL on each holding</span></h3>
      ${toggleBtn}
    </div>`;

  if (sellDecisionsCollapsed || !rows.length) {
    box.innerHTML = head + (rows.length ? "" :
      `<p class="status-line">No reviewed holdings yet — run an analysis.</p>`);
    wireSellDecisionsToggle();
    return;
  }

  const items = rows.map((r) => `
    <div class="trade-item">
      <span class="trade-badge ${r.action === "sell" ? "sell" : "hold-badge"}">
        ${esc(r.action.toUpperCase())}</span>
      <span class="trade-what">${esc(r.symbol)}</span>
      <span class="trade-why">${esc(r.reason)}</span>
    </div>`).join("");

  box.innerHTML = head + `<div class="trade-log">${items}</div>`;
  wireSellDecisionsToggle();
}

function wireSellDecisionsToggle() {
  document.getElementById("toggle-sell-decisions").addEventListener("click", () => {
    sellDecisionsCollapsed = !sellDecisionsCollapsed;
    localStorage.setItem("collapse-sell-decisions", sellDecisionsCollapsed ? "1" : "0");
    renderSellDecisions();
  });
}

loadPortfolio();

/* ── Watchlists panel ─────────────────────────────────────────────────── */
/* The playlist model: stocks live once in a catalogue; each watchlist is a
   named, coloured list of symbols; the same stock can sit in many lists. */
const wlStatus = document.getElementById("watchlists-status");
const WL_PALETTE = ["#0f9d6e", "#3b82d6", "#d13c3c", "#c98a12", "#8b5cd6",
                    "#d6569c", "#12a5a5", "#8a8f3c", "#e0762e", "#6b6b6b"];
let wlData = { watchlists: [], stocks: {} };

async function loadWatchlists() {
  const res = await fetch("/api/watchlists");
  wlData = await res.json();
  renderWatchlists();
  fillScopeOptions();                     // the analyse-this dropdown
  if (currentRows.length) renderTable();  // (re)fill the watchlist filter
}

/* Any endpoint that changes watchlists answers with the fresh summary —
   store it and redraw. */
function updateWatchlists(data) {
  if (data.watchlists) {
    wlData = data;
    renderWatchlists();
    fillScopeOptions();
    if (currentRows.length) renderTable();
  }
}

/* The latest analysis knows each stock's price — reuse it in the watchlist
   tables so they look like the main table (blank before the first run). */
function priceCell(symbol) {
  const row = currentRows.find((r) => r.symbol === symbol);
  return row ? `$${row.price}` : "—";
}

function renderWatchlists() {
  const swatches = WL_PALETTE.map((c) =>
    `<button class="swatch" data-color="${c}" style="background:${c}"></button>`).join("");

  const cards = wlData.watchlists.map((wl) => {
    const collapsed = localStorage.getItem(`wl-collapsed-${wl.id}`) !== "0";
    const rows = wl.symbols.map((s) => {
      const info = wlData.stocks[s] || {};
      const flags = (info.flags || [])
        .map((f) => `<span class="flag-tag">${esc(f)}</span>`).join("");
      return `
        <tr class="main-row" data-symbol="${esc(s)}">
          <td><strong>${esc(s)}</strong>${flags}</td>
          <td class="col-name">${esc(info.name || s)}</td>
          <td>${priceCell(s)}</td>
          <td class="row-x"><button class="chip-x" data-list="${esc(wl.id)}"
              data-symbol="${esc(s)}" title="Remove from ${esc(wl.name)}">×</button></td>
        </tr>`;
    }).join("");

    return `
      <div class="wl-card" data-id="${esc(wl.id)}">
        <div class="wl-head">
          <button class="wl-chev" title="${collapsed ? "Show" : "Hide"} this list">
            ${collapsed ? "▸" : "▾"}</button>
          <span class="wl-dot-wrap">
            <button class="wl-dot" style="background:${esc(wl.tag.value)}"
                    title="Change colour"></button>
            <span class="color-pop" hidden>${swatches}</span>
          </span>
          <span class="wl-name">${esc(wl.name)}</span>
          <span class="hint">(${wl.count})</span>
          <span class="wl-spacer"></span>
          <button class="mini-btn wl-rename">Rename</button>
          <button class="mini-btn wl-delete">Delete</button>
        </div>
        <div class="wl-body" ${collapsed ? "hidden" : ""}>
          <!-- Each list has its own search: results add straight into it. -->
          <div class="search-box wl-search">
            <input class="filter-input wl-search-input" type="search"
                   placeholder="Add a stock to this list — ticker or name…">
            <div class="search-results" hidden></div>
          </div>
          ${wl.symbols.length ? `
          <div class="table-wrap">
            <table>
              <thead><tr><th>Ticker</th><th class="col-name">Name</th>
                <th>Price</th><th></th></tr></thead>
              <tbody>${rows}</tbody>
            </table>
          </div>` : `<p class="hint">Empty — search above to add stocks.</p>`}
        </div>
      </div>`;
  }).join("");

  const box = document.getElementById("watchlist-cards");
  box.innerHTML = cards ||
    `<div class="empty-state">No watchlists yet — press “New watchlist”.</div>`;

  // Rows open the stock's page; the × removes it from that list.
  box.querySelectorAll(".main-row").forEach((row) =>
    row.addEventListener("click", () => openTicker(row.dataset.symbol)));
  box.querySelectorAll(".chip-x").forEach((x) =>
    x.addEventListener("click", async (e) => {
      e.stopPropagation();  // don't also open the ticker page
      const res = await fetch(`/api/watchlists/${x.dataset.list}/stocks/` +
                              encodeURIComponent(x.dataset.symbol),
                              { method: "DELETE" });
      updateWatchlists(await res.json());
    }));

  box.querySelectorAll(".wl-card").forEach((card) => {
    const id = card.dataset.id;
    const wl = wlData.watchlists.find((w) => w.id === id);

    // ▾/▸ collapses the list (remembered per list, like the big tables).
    card.querySelector(".wl-chev").addEventListener("click", () => {
      const collapsed = localStorage.getItem(`wl-collapsed-${id}`) !== "0";
      localStorage.setItem(`wl-collapsed-${id}`, collapsed ? "0" : "1");
      renderWatchlists();
    });

    // The colour dot toggles a little swatch popup: click to open,
    // click the same dot again (or anywhere else) to close.
    const pop = card.querySelector(".color-pop");
    card.querySelector(".wl-dot").addEventListener("click", (e) => {
      e.stopPropagation();
      const wasOpen = !pop.hidden;
      document.querySelectorAll(".color-pop").forEach((p) => { p.hidden = true; });
      pop.hidden = wasOpen;
    });
    pop.querySelectorAll(".swatch").forEach((sw) =>
      sw.addEventListener("click", async (e) => {
        e.stopPropagation();
        const res = await fetch(`/api/watchlists/${id}`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ tag: { kind: "color", value: sw.dataset.color } }),
        });
        if ((await res.json()).status === "ok") loadWatchlists();
      }));

    card.querySelector(".wl-rename").addEventListener("click", async () => {
      const name = prompt("New name for this watchlist:", wl.name);
      if (!name) return;
      const res = await fetch(`/api/watchlists/${id}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      if ((await res.json()).status === "ok") loadWatchlists();
    });
    card.querySelector(".wl-delete").addEventListener("click", async () => {
      if (!confirm(`Delete the watchlist “${wl.name}”? The stocks stay in ` +
                   `any other lists they're in.`)) return;
      await fetch(`/api/watchlists/${id}`, { method: "DELETE" });
      loadWatchlists();
    });

    // This list's own search box: click a result → added right here.
    wireListSearch(card, wl);
  });
}

/* The per-watchlist search box: same free lookup, but one click adds the
   stock straight into THAT list (no dropdown-picking needed). */
function wireListSearch(card, wl) {
  const input = card.querySelector(".wl-search-input");
  const drop = card.querySelector(".wl-search .search-results");
  let timer = null;

  input.addEventListener("input", () => {
    clearTimeout(timer);
    const q = input.value.trim();
    if (!q) { drop.hidden = true; return; }
    timer = setTimeout(async () => {
      const res = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
      const data = await res.json();
      if (data.status !== "ok") {
        drop.innerHTML = `<div class="search-row hint">⚠ ${esc(data.message)}</div>`;
      } else if (!data.results.length) {
        drop.innerHTML = `<div class="search-row hint">No US-listed matches.</div>`;
      } else {
        drop.innerHTML = data.results.map((r) => {
          const already = wl.symbols.includes(r.symbol);
          return `
            <div class="search-row add-row ${already ? "muted" : ""}"
                 data-symbol="${esc(r.symbol)}" data-name="${esc(r.name)}" data-type="${esc(r.type)}">
              <span class="search-main"><strong>${esc(r.symbol)}</strong> ${esc(r.name)}
                <span class="flag-tag">${esc(r.exchange)}</span></span>
              <span class="hint">${already ? "already in list" : "+ add"}</span>
            </div>`;
        }).join("");
        drop.querySelectorAll(".add-row:not(.muted)").forEach((row) =>
          row.addEventListener("click", async () => {
            const res = await fetch(`/api/watchlists/${wl.id}/stocks`, {
              method: "POST", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ symbol: row.dataset.symbol,
                                     name: row.dataset.name,
                                     type: row.dataset.type }),
            });
            const data = await res.json();
            if (data.status === "ok") {
              wlStatus.textContent = `Added ${row.dataset.symbol} to “${wl.name}”.`;
              updateWatchlists(data);
            } else {
              wlStatus.textContent = "⚠ " + data.message;
            }
          }));
      }
      drop.hidden = false;
    }, 300);
  });
}

document.getElementById("new-watchlist-btn").addEventListener("click", async () => {
  const name = prompt("Name for the new watchlist:");
  if (!name) return;
  const res = await fetch("/api/watchlists", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  const data = await res.json();
  if (data.status === "ok") loadWatchlists();
  else wlStatus.textContent = "⚠ " + data.message;
});

/* ── Free-range search box ────────────────────────────────────────────── */
/* Plain lookup (no AI): type, see US-listed matches, click one to open its
   page, or add it straight into a watchlist. Debounced so we only search
   after the user pauses typing. */
const searchInput = document.getElementById("stock-search");
const searchResults = document.getElementById("search-results");
let searchTimer = null;

searchInput.addEventListener("input", () => {
  clearTimeout(searchTimer);
  const q = searchInput.value.trim();
  if (!q) { searchResults.hidden = true; return; }
  searchTimer = setTimeout(() => runSearch(q), 300);
});

async function runSearch(q) {
  const res = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
  const data = await res.json();
  if (data.status !== "ok") {
    searchResults.innerHTML = `<div class="search-row hint">⚠ ${esc(data.message)}</div>`;
    searchResults.hidden = false;
    return;
  }
  if (!data.results.length) {
    searchResults.innerHTML =
      `<div class="search-row hint">No US-listed matches for “${esc(q)}”.</div>`;
    searchResults.hidden = false;
    return;
  }

  const listOptions = wlData.watchlists
    .map((wl) => `<option value="${esc(wl.id)}">${esc(wl.name)}</option>`).join("");
  searchResults.innerHTML = data.results.map((r) => `
    <div class="search-row" data-symbol="${esc(r.symbol)}" data-name="${esc(r.name)}"
         data-type="${esc(r.type)}">
      <span class="search-main">
        <strong>${esc(r.symbol)}</strong> ${esc(r.name)}
        <span class="flag-tag">${esc(r.exchange)}</span>
      </span>
      <select class="range-select add-select" title="Add to a watchlist">
        <option value="">+ Add…</option>${listOptions}
      </select>
    </div>`).join("");
  searchResults.hidden = false;

  searchResults.querySelectorAll(".search-main").forEach((main) =>
    main.addEventListener("click", () =>
      openTicker(main.parentElement.dataset.symbol)));
  searchResults.querySelectorAll(".add-select").forEach((sel) =>
    sel.addEventListener("change", async () => {
      if (!sel.value) return;
      const row = sel.parentElement;
      const res = await fetch(`/api/watchlists/${sel.value}/stocks`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol: row.dataset.symbol,
                               name: row.dataset.name, type: row.dataset.type }),
      });
      const data = await res.json();
      if (data.status === "ok") {
        const wl = wlData.watchlists.find((w) => w.id === sel.value) || {};
        wlStatus.textContent = `Added ${row.dataset.symbol} to “${wl.name}”.`;
        updateWatchlists(data);
      } else {
        wlStatus.textContent = "⚠ " + data.message;
      }
      sel.value = "";
    }));
}

/* Clicking anywhere else closes open dropdowns and the colour popup. */
document.addEventListener("click", (e) => {
  if (!e.target.closest(".search-box")) {
    document.querySelectorAll(".search-results").forEach((d) => { d.hidden = true; });
  }
  if (!e.target.closest(".wl-dot-wrap")) {
    document.querySelectorAll(".color-pop").forEach((p) => { p.hidden = true; });
  }
});

loadWatchlists();

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
["watchlists", "stock-searcher", "portfolio", "pivot-scanner"].forEach((id) =>
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
          <span class="pick-symbol">${esc(h.company)}</span>
          ${h.ticker ? `<span class="flag-tag">${esc(h.ticker)}</span>` : ""}
          <div class="pick-name">${esc(h.industry)} · ${esc(h.form)} filed ${esc(h.file_date)}</div>
        </div>
        <span class="hype-badge" title="10 = pure hype, 1 = real substance">
          hype ${h.hype_score}/10</span>
      </div>
      <p><strong>What they announced:</strong> ${esc(h.what_they_announced)}</p>
      <p><strong>Announced vs executed:</strong> ${esc(h.announced_vs_executed)}</p>
      <p><strong>Can they fund it:</strong> ${esc(h.funding_ability)}</p>
      <div class="dd-block"><strong>Red flags</strong>
        <ul>${h.red_flags.map((r) => `<li>${esc(r)}</li>`).join("")}</ul></div>
      <p class="scan-bottom">${esc(h.bottom_line)}</p>
      <a class="filing-link" href="${esc(safeUrl(h.filing_url))}" target="_blank" rel="noopener">
        View the filing on SEC EDGAR →</a>
    </div>`).join("");

  // Companies that were checked but didn't qualify, tucked into a
  // <details> element (a built-in HTML collapsible).
  const excluded = data.excluded.length
    ? `<details class="excluded-list">
         <summary>${data.excluded.length} filings examined but excluded</summary>
         <ul>${data.excluded.map((e) =>
           `<li><strong>${esc(e.company)}</strong> — ${esc(e.reason)}</li>`).join("")}</ul>
       </details>`
    : "";

  document.getElementById("scanner-results").innerHTML =
    (cards || `<p class="status-line">No qualifying AI pivots found in the
       last ${data.lookback_days} days — small-cap non-tech pivots are
       genuinely rare, which is rather the point.</p>`) + excluded;
}

loadScanner();

/* ── Event Scanner view toggle: AI Pivots ↔ Strategy Lab ───────────────── */
const scannerSubtitle = document.getElementById("scanner-subtitle");
const pivotView = document.getElementById("pivot-view");
const labView = document.getElementById("lab-view");

const PIVOT_SUBTITLE = "Small-cap non-tech companies newly disclosing AI pivots · SEC EDGAR · skeptical analysis";
const LAB_SUBTITLE = "Event-timing patterns to research · not investment advice";

function setScannerView(view) {
  const isLab = view === "lab";
  pivotView.hidden = isLab;
  labView.hidden = !isLab;
  scanButton.hidden = isLab;  // "Scan EDGAR" only makes sense in the pivots view
  scannerSubtitle.textContent = isLab ? LAB_SUBTITLE : PIVOT_SUBTITLE;
  document.querySelectorAll("#scanner-view-group .seg").forEach((b) =>
    b.classList.toggle("active", b.dataset.view === view));
  localStorage.setItem("scanner-view", view);
}

document.getElementById("scanner-view-group").addEventListener("click", (e) => {
  const btn = e.target.closest(".seg");
  if (btn) setScannerView(btn.dataset.view);
});

setScannerView(localStorage.getItem("scanner-view") || "pivots");

/* ── Strategy Lab ─────────────────────────────────────────────────────── */
/* Three parts: Leon's own journal of event-timing patterns, an AI
   "brainstorm" that adds more (clearly badged AI vs MINE — see
   journal.py for why that badge can't be faked), and a "Scan now" that
   checks current headlines against the journal. Framed everywhere as
   ideas to research — never advice — and this code has no path that
   could ever place even a pretend trade. */
let labStrategies = [];
let labEditingId = null;   // which strategy the open form is editing, or null = new

const labScanStatus = document.getElementById("lab-scan-status");
const labJournalStatus = document.getElementById("lab-journal-status");
const labScanBtn = document.getElementById("lab-scan-btn");
const labDailyToggle = document.getElementById("lab-daily-toggle");

async function loadLab() {
  const res = await fetch("/api/lab");
  const data = await res.json();
  labStrategies = data.strategies;
  renderLabSetups(data.setups);
  renderLabStrategies();
  labDailyToggle.checked = !!data.settings.daily_scan;
  if (data.daily_scan_running) {
    labScanStatus.textContent = "Running today's automatic scan in the background…";
    pollForAutoScanResult(data.setups ? data.setups.run_at : null);
  }
}

/* The background daily scan has no button to press when it finishes, so
   the page checks back on its own a couple of times (free — this just
   re-reads the saved file, it can't start a second scan) and swaps in the
   fresh result the moment it's ready, instead of leaving "running…" on
   screen until Leon happens to reload. */
function pollForAutoScanResult(previousRunAt, attempt = 0) {
  const delays = [30000, 90000];
  if (attempt >= delays.length) {
    labScanStatus.textContent = "Still running — reload in a minute to see the result.";
    return;
  }
  setTimeout(async () => {
    const res = await fetch("/api/lab");
    const data = await res.json();
    if (data.setups && data.setups.run_at !== previousRunAt) {
      labStrategies = data.strategies;
      renderLabSetups(data.setups);
      renderLabStrategies();
    } else {
      pollForAutoScanResult(previousRunAt, attempt + 1);
    }
  }, delays[attempt]);
}

labDailyToggle.addEventListener("change", async () => {
  const wanted = labDailyToggle.checked;
  try {
    const res = await fetch("/api/lab/settings", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ daily_scan: wanted }),
    });
    const data = await res.json();
    if (data.status !== "ok") {
      labDailyToggle.checked = !wanted;  // revert — the server didn't save it
      labScanStatus.textContent = "⚠ " + (data.message || "Could not save the setting.");
    }
  } catch (err) {
    labDailyToggle.checked = !wanted;  // revert — we don't know if it saved
    labScanStatus.textContent = "⚠ Could not reach the server: " + err.message;
  }
});

labScanBtn.addEventListener("click", async () => {
  labScanBtn.disabled = true;
  labScanStatus.textContent = "Checking current headlines against your journal…";
  document.getElementById("lab-setups").innerHTML =
    `<div class="skeleton" style="height:140px"></div>`;
  try {
    const res = await fetch("/api/lab/scan", { method: "POST" });
    const data = await res.json();
    if (data.status === "ok") {
      renderLabSetups(data);
    } else {
      labScanStatus.textContent = "⚠ " + data.message;
      document.getElementById("lab-setups").innerHTML = "";
    }
  } catch (err) {
    labScanStatus.textContent = "⚠ Could not reach the server: " + err.message;
    document.getElementById("lab-setups").innerHTML = "";
  } finally {
    labScanBtn.disabled = false;
  }
});

function renderLabSetups(data) {
  const box = document.getElementById("lab-setups");
  if (!data) {
    labScanStatus.textContent = "No scan yet — press “Scan now” to check current headlines.";
    box.innerHTML = "";
    return;
  }
  labScanStatus.textContent =
    `Last scan: ${data.run_at.replace("T", " ")} · ${data.headlines_examined} ` +
    `headlines examined · ${data.setups.length} setup${data.setups.length === 1 ? "" : "s"}`;

  const cards = data.setups.map((s) => `
    <div class="scan-card">
      <div class="scan-head">
        <div>
          <span class="pick-symbol">${esc(s.strategy_name)}</span>
          <div class="pick-name">${esc(s.whats_happening)}</div>
        </div>
        <span class="confidence-badge conf-${esc(s.confidence.level)}">
          confidence: ${esc(s.confidence.level)}</span>
      </div>
      ${s.confidence.note ? `<p class="confidence-note">${esc(s.confidence.note)}</p>` : ""}
      <p><strong>Bull case:</strong> ${esc(s.bull_case)}</p>
      <p class="scan-bottom"><strong>Counter-case:</strong> ${esc(s.counter_case)}</p>
      <div class="dd-block"><strong>Risks</strong>
        <ul>${s.risks.map((r) => `<li>${esc(r)}</li>`).join("")}</ul></div>
      <div class="lab-sources">${s.sources.map((src) => `
        <a class="filing-link" href="${esc(safeUrl(src.link))}" target="_blank" rel="noopener">
          ${esc(src.title)}${src.source ? " · " + esc(src.source) : ""} →</a>`).join("")}</div>
      <p class="fine-print">Idea to research — not investment advice.</p>
    </div>`).join("");

  box.innerHTML = cards ||
    `<p class="status-line">${esc(data.note) || "No setups currently in play."}</p>`;
}

function renderLabStrategies() {
  const box = document.getElementById("lab-strategies");
  if (!labStrategies.length) {
    box.innerHTML = `<p class="status-line">No strategies yet — write one, or press “Brainstorm ideas”.</p>`;
    return;
  }
  box.innerHTML = labStrategies.map((s) => `
    <div class="scan-card" data-id="${esc(s.id)}">
      <div class="scan-head">
        <div>
          <span class="pick-symbol">${esc(s.name)}</span>
          <span class="lab-badge ${s.origin === "ai" ? "ai" : "mine"}">
            ${s.origin === "ai" ? "AI" : "MINE"}</span>
          <div class="pick-name">${esc(s.description)}</div>
        </div>
        <div class="btn-row">
          <button class="mini-btn lab-edit-btn">Edit</button>
          <button class="mini-btn lab-delete-btn">Delete</button>
        </div>
      </div>
      ${s.entry_trigger ? `<p><strong>Entry:</strong> ${esc(s.entry_trigger)}</p>` : ""}
      ${s.exit_trigger ? `<p><strong>Exit:</strong> ${esc(s.exit_trigger)}</p>` : ""}
      ${s.assets.length ? `<p><strong>Assets:</strong> ${s.assets.map(esc).join(", ")}</p>` : ""}
      ${s.risk_notes ? `<p><strong>Risk notes:</strong> ${esc(s.risk_notes)}</p>` : ""}
      <div class="lab-tags">${s.tags.map((t) => `<span class="flag-tag">${esc(t)}</span>`).join("")}</div>
    </div>`).join("");

  box.querySelectorAll(".lab-edit-btn").forEach((btn) =>
    btn.addEventListener("click", (e) => {
      const id = e.target.closest(".scan-card").dataset.id;
      openLabForm(labStrategies.find((s) => s.id === id));
    }));
  box.querySelectorAll(".lab-delete-btn").forEach((btn) =>
    btn.addEventListener("click", async (e) => {
      const id = e.target.closest(".scan-card").dataset.id;
      const s = labStrategies.find((x) => x.id === id);
      if (!confirm(`Delete the strategy “${s.name}”?`)) return;
      const res = await fetch(`/api/lab/strategies/${id}`, { method: "DELETE" });
      if ((await res.json()).status === "ok") loadLab();
    }));
}

document.getElementById("lab-new-btn").addEventListener("click", () => openLabForm(null));

function openLabForm(strategy) {
  labEditingId = strategy ? strategy.id : null;
  const box = document.getElementById("lab-strategy-form");
  box.hidden = false;
  box.className = "scan-card lab-form";
  box.innerHTML = `
    <h3 class="subheading">${strategy ? "Edit strategy" : "New strategy"}</h3>
    <label>Name</label>
    <input id="lab-f-name" value="${esc(strategy ? strategy.name : "")}">
    <label>Description (plain English)</label>
    <textarea id="lab-f-description">${esc(strategy ? strategy.description : "")}</textarea>
    <label>Entry trigger — what would make you consider buying</label>
    <input id="lab-f-entry" value="${esc(strategy ? strategy.entry_trigger : "")}">
    <label>Exit trigger — what would make you consider selling</label>
    <input id="lab-f-exit" value="${esc(strategy ? strategy.exit_trigger : "")}">
    <label>Affected assets/sectors (comma-separated)</label>
    <input id="lab-f-assets" value="${esc(strategy ? strategy.assets.join(", ") : "")}">
    <label>Risk notes</label>
    <textarea id="lab-f-risks">${esc(strategy ? strategy.risk_notes : "")}</textarea>
    <label>Tags (comma-separated)</label>
    <input id="lab-f-tags" value="${esc(strategy ? strategy.tags.join(", ") : "")}">
    <div class="btn-row">
      <button id="lab-f-save" class="action-btn">Save</button>
      <button id="lab-f-cancel" class="action-btn ghost-btn">Cancel</button>
    </div>`;
  box.scrollIntoView({ behavior: "smooth", block: "center" });

  document.getElementById("lab-f-cancel").addEventListener("click", closeLabForm);
  document.getElementById("lab-f-save").addEventListener("click", saveLabForm);
}

function closeLabForm() {
  const box = document.getElementById("lab-strategy-form");
  box.hidden = true;
  box.innerHTML = "";
  labEditingId = null;
}

function _splitList(value) {
  return value.split(",").map((s) => s.trim()).filter(Boolean);
}

async function saveLabForm() {
  const fields = {
    name: document.getElementById("lab-f-name").value,
    description: document.getElementById("lab-f-description").value,
    entry_trigger: document.getElementById("lab-f-entry").value,
    exit_trigger: document.getElementById("lab-f-exit").value,
    assets: _splitList(document.getElementById("lab-f-assets").value),
    risk_notes: document.getElementById("lab-f-risks").value,
    tags: _splitList(document.getElementById("lab-f-tags").value),
  };
  const url = labEditingId ? `/api/lab/strategies/${labEditingId}` : "/api/lab/strategies";
  const res = await fetch(url, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(fields),
  });
  const data = await res.json();
  if (data.status === "ok") {
    closeLabForm();
    loadLab();
  } else {
    labJournalStatus.textContent = "⚠ " + data.message;
  }
}

document.getElementById("lab-brainstorm-btn").addEventListener("click", async (e) => {
  const btn = e.currentTarget;
  btn.disabled = true;
  labJournalStatus.textContent = "Asking the AI for new patterns — takes a few seconds…";
  try {
    const res = await fetch("/api/lab/brainstorm", { method: "POST" });
    const data = await res.json();
    if (data.status === "ok") {
      const n = data.strategies.length;
      labJournalStatus.textContent =
        n ? `Added ${n} new AI-suggested pattern${n === 1 ? "" : "s"}.`
          : "The AI didn't return any usable suggestions this time — try again.";
      loadLab();
    } else {
      labJournalStatus.textContent = "⚠ " + data.message;
    }
  } catch (err) {
    labJournalStatus.textContent = "⚠ Could not reach the server: " + err.message;
  } finally {
    btn.disabled = false;
  }
});

loadLab();

/* ── Fix bulletin: Leon's own editable "things to fix later" note ────── */
/* Plain text with three simple markers — **bold**, _underline_, and "- "
   for a dot point — deliberately not a rich-text editor, so the saved
   file stays one readable string. Display is XSS-safe by construction:
   the WHOLE text is escaped first, and only THEN do the markers turn
   into <strong>/<u>/<li> tags — a marker can never inject real HTML. */
const bulletinPanel = document.getElementById("bulletin-panel");
const bulletinView = document.getElementById("bulletin-view");
const bulletinEditor = document.getElementById("bulletin-editor");
const bulletinTextarea = document.getElementById("bulletin-textarea");
const bulletinStatus = document.getElementById("bulletin-status");
let bulletinText = "";

function renderBulletinMarkup(text) {
  const lines = esc(text).split("\n");
  let html = "";
  let inList = false;
  for (const line of lines) {
    const isBullet = line.startsWith("- ");
    if (isBullet && !inList) { html += "<ul>"; inList = true; }
    if (!isBullet && inList) { html += "</ul>"; inList = false; }
    const formatted = (isBullet ? line.slice(2) : line)
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/_(.+?)_/g, "<u>$1</u>");
    if (isBullet) {
      html += `<li>${formatted}</li>`;
    } else if (formatted.trim()) {
      html += `<p>${formatted}</p>`;
    }
  }
  if (inList) html += "</ul>";
  return html;
}

function renderBulletinView() {
  bulletinView.innerHTML = bulletinText.trim()
    ? renderBulletinMarkup(bulletinText)
    : `<p class="status-line">Nothing here yet — press Edit to add your own notes.</p>`;
}

async function loadBulletin() {
  const res = await fetch("/api/bulletin");
  const data = await res.json();
  bulletinText = data.text || "";
  renderBulletinView();
}

document.getElementById("bulletin-toggle").addEventListener("click", () => {
  const expanded = bulletinPanel.classList.toggle("expanded");
  localStorage.setItem("bulletin-expanded", expanded ? "1" : "0");
});
if (localStorage.getItem("bulletin-expanded") === "1") {
  bulletinPanel.classList.add("expanded");
}

document.getElementById("bulletin-edit-btn").addEventListener("click", () => {
  bulletinTextarea.value = bulletinText;
  bulletinView.hidden = true;
  bulletinEditor.hidden = false;
});

document.getElementById("bulletin-cancel-btn").addEventListener("click", () => {
  bulletinEditor.hidden = true;
  bulletinView.hidden = false;
});

/* Wraps the textarea's current selection in a marker (or, with nothing
   selected, inserts a placeholder word already wrapped) — using
   selectionStart/selectionEnd, not execCommand/contenteditable, so the
   saved text stays plain and predictable. */
function _wrapSelection(marker) {
  const ta = bulletinTextarea;
  const start = ta.selectionStart, end = ta.selectionEnd;
  const selected = ta.value.slice(start, end) || "text";
  ta.value = ta.value.slice(0, start) + marker + selected + marker + ta.value.slice(end);
  ta.focus();
  ta.selectionStart = start + marker.length;
  ta.selectionEnd = start + marker.length + selected.length;
}

document.getElementById("bulletin-bold-btn").addEventListener("click", () => _wrapSelection("**"));
document.getElementById("bulletin-underline-btn").addEventListener("click", () => _wrapSelection("_"));
document.getElementById("bulletin-bullet-btn").addEventListener("click", () => {
  const ta = bulletinTextarea;
  const start = ta.selectionStart;
  const lineStart = ta.value.lastIndexOf("\n", start - 1) + 1;
  ta.value = ta.value.slice(0, lineStart) + "- " + ta.value.slice(lineStart);
  ta.focus();
  ta.selectionStart = ta.selectionEnd = start + 2;
});

document.getElementById("bulletin-save-btn").addEventListener("click", async () => {
  try {
    const res = await fetch("/api/bulletin", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: bulletinTextarea.value }),
    });
    const data = await res.json();
    if (data.status === "ok") {
      bulletinText = data.text;
      renderBulletinView();
      bulletinEditor.hidden = true;
      bulletinView.hidden = false;
      bulletinStatus.textContent = "";
    } else {
      bulletinStatus.textContent = "⚠ " + (data.message || "Could not save.");
    }
  } catch (err) {
    bulletinStatus.textContent = "⚠ Could not reach the server: " + err.message;
  }
});

loadBulletin();
