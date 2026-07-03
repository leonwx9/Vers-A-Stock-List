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
  statusLine.textContent = "Running analysis of all 85 tickers — this takes a minute or two…";
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
  // Apply the search filter, then the current sort.
  const text = filterText.toLowerCase();
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
      const changeClass = r.change_30d_pct >= 0 ? "up" : "down";
      return `
      <tr class="main-row" data-symbol="${r.symbol}">
        <td><strong>${r.symbol}</strong>${flags}</td>
        <td class="col-name">${r.name}</td>
        <td>$${r.price}</td>
        <td class="${changeClass}">${r.change_30d_pct >= 0 ? "+" : ""}${r.change_30d_pct}%</td>
        <td>${r.verdict}</td>
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
      <input id="filter-input" class="filter-input" type="search"
             placeholder="Filter by ticker or name…" value="${filterText}">
    </div>
    <table>
      <thead>
        <tr>
          <th data-sort="symbol">Ticker${arrow("symbol")}</th>
          <th data-sort="name" class="col-name">Name${arrow("name")}</th>
          <th data-sort="price">Price${arrow("price")}</th>
          <th data-sort="change_30d_pct">30d${arrow("change_30d_pct")}</th>
          <th data-sort="verdict">Verdict${arrow("verdict")}</th>
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
}

loadExisting();
