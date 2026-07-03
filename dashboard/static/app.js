/* app.js — the browser-side logic for the Stock Searcher section.
   It does two things:
   1. On page load, fetch the last saved analysis and draw it.
   2. When "Run analysis" is clicked, ask the server for a fresh run. */

const statusLine = document.getElementById("analysis-status");
const runButton = document.getElementById("run-analysis-btn");

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
  try {
    const res = await fetch("/api/run-analysis", { method: "POST" });
    const data = await res.json();
    if (data.status === "ok") {
      render(data);
    } else {
      statusLine.textContent = "⚠ " + data.message;
    }
  } catch (err) {
    statusLine.textContent = "⚠ Could not reach the server: " + err.message;
  } finally {
    runButton.disabled = false;
  }
});

/* ── Drawing ──────────────────────────────────────────────────────────── */
function render(data) {
  statusLine.textContent =
    `Last run: ${data.run_at.replace("T", " ")} · data source: ${data.data_source}`;
  renderShortlist(data);
  renderTable(data.rows);
}

function renderShortlist(data) {
  const bySymbol = Object.fromEntries(data.rows.map((r) => [r.symbol, r]));
  const cards = data.shortlist.map((symbol) => {
    const r = bySymbol[symbol];
    return `
      <div class="pick-card">
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
  document.getElementById("shortlist").innerHTML =
    `<h3 class="subheading">Shortlist — top ${data.shortlist.length} picks</h3>
     <div class="pick-grid">${cards.join("")}</div>`;
}

function renderTable(rows) {
  // One table row per ticker; clicking it toggles a detail row underneath
  // with the full bull/bear text.
  const body = rows
    .map((r, i) => {
      const flags = r.flags.length ? ` <span class="flag-tag">${r.flags.join(", ")}</span>` : "";
      const changeClass = r.change_30d_pct >= 0 ? "up" : "down";
      return `
      <tr class="main-row" data-i="${i}">
        <td><strong>${r.symbol}</strong>${flags}</td>
        <td class="col-name">${r.name}</td>
        <td>$${r.price}</td>
        <td class="${changeClass}">${r.change_30d_pct >= 0 ? "+" : ""}${r.change_30d_pct}%</td>
        <td>${r.verdict}</td>
        <td><span class="score-badge">${r.conviction}/10</span></td>
      </tr>
      <tr class="detail-row" id="detail-${i}" hidden>
        <td colspan="6">
          <p><strong>Bull:</strong> ${r.bull}</p>
          <p><strong>Bear:</strong> ${r.bear}</p>
          <p><strong>Stop-loss:</strong> ${r.stop_loss} · <strong>Timeframe:</strong> ${r.timeframe}</p>
        </td>
      </tr>`;
    })
    .join("");

  document.getElementById("analysis-table").innerHTML = `
    <h3 class="subheading">All ${rows.length} tickers <span class="hint">(click a row for details)</span></h3>
    <table>
      <thead>
        <tr><th>Ticker</th><th class="col-name">Name</th><th>Price</th><th>30d</th><th>Verdict</th><th>Score</th></tr>
      </thead>
      <tbody>${body}</tbody>
    </table>`;

  // Wire the click-to-expand behaviour.
  document.querySelectorAll(".main-row").forEach((row) => {
    row.addEventListener("click", () => {
      const detail = document.getElementById(`detail-${row.dataset.i}`);
      detail.hidden = !detail.hidden;
    });
  });
}

loadExisting();
