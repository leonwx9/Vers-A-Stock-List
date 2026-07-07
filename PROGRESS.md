# Progress

## Done
- **M1 — Plan approved** (2026-07-03): Python + Flask, OpenRouter (switchable to
  Anthropic via .env), $10,000 paper portfolio, modular config-driven structure.
- **M2 — Dashboard shell**: styled black/white/grey page on http://localhost:5001
  with the two sections.
- **M3 — Stock Searcher (code complete, awaiting API key)**:
  - `dashboard/config/universe.yaml` — all 85 tickers with risk flags
    (later expanded to 98 — see below)
  - `dashboard/config/rules.yaml` — portfolio + analysis + scanner rules
  - `dashboard/datasources/` — PriceSource interface + deterministic SampleSource
  - `dashboard/llm/` — provider switch (OpenRouter now / Anthropic later)
  - `dashboard/analysis/searcher.py` — batched bull/bear analysis, conviction
    scores, shortlist, saves to `data/` + dated `picks/` audit files
  - Front end: Run button, shortlist cards, clickable 85-row table
  - 13 automated tests pass (`./venv/bin/python -m pytest tests/`)

- **M3 confirmed** — first real analysis run done with Leon's OpenRouter key.
- **M3.5 — Ticker detail pages + UI overhaul** (Leon's request):
  - Every ticker now has its own page (`/ticker/AAPL`): price chart with
    1M/3M/6M/1Y ranges and a line ↔ candles toggle, Apple-Stocks-style
    statistics grid, live news headlines (Google News RSS, free/no key),
    and a plain-English "Why this rating" deep dive — Danelfin-style
    technical/sentiment/fundamentals scores where sentiment claims must cite
    the actual fetched headlines. Deep dives are cached; Refresh re-generates.
  - UI overhaul: sticky frosted header, hairline-bordered cards, segmented
    controls, score bars, table search + column sorting, skeleton loading.
    Charts via vendored TradingView Lightweight Charts™ (works offline).
  - Charts show sample prices until milestone 6 swaps in live data.

- **M4 — Paper Portfolio**: $10,000 pretend money. "Sync to shortlist" makes
  the portfolio mirror the latest shortlist (sells drops, sells >10%
  stop-loss losers, buys new picks — whole shares, ≤$800 each, never
  risk-flagged products). Total-value graph grows one point per day of use.
  Holdings table with P/L; every trade logged; Reset button starts over.
  Leon's feedback applied: Verdict column removed from the table.

- **Leon's UI requests**: sidebar navigation (Shortlist / Portfolio / Scanner)
  with active-section highlighting; collapsible ticker + holdings tables;
  Verdict column removed; emerald "market green" accent (#0f9d6e) on gains,
  scores, buttons, charts — palette unlocked by Leon.
- **M5 — AI Pivot Scanner**: searches EDGAR's full-text index (free, no key)
  for AI-pivot language in recent 8-Ks, filters out tech-sector filers via
  SEC's own classification, downloads each filing's AI passages, and runs a
  skeptical AI read per candidate: announced vs executed, funding ability,
  red flags, hype score 1-10. Non-qualifiers listed with reasons. Detection
  is strictly after public disclosure. Note: market-cap check is AI-judged
  until live data lands in M6. SEC rate-limit (403) and 5xx flakiness
  handled with backoff + keep-alive session.

- **M6 — LIVE PRICES**: `data.price_source: live` in rules.yaml switches the
  whole app to real daily market data from Yahoo Finance's free key-less
  chart API (mirror-host fallback, 5-min in-memory cache, BRK/B→BRK-B
  symbol mapping). Proven on one ticker (AAPL $308.63 real vs $230 sample),
  then 85/85 tickers in 3.5s. Flip back to `sample` any time for offline
  work. Charts, stats, portfolio and analysis all live automatically —
  nothing else changed, which was the whole point of the interface design.

- **Feedback round**: signal red (#d13c3c) for losses/falling candles; change
  column now a dropdown (1D/1W/1M/3M/1Y/5Y/All — live source pulls each
  stock's lifetime series, located by date); PWA layer (manifest + icons +
  iOS meta) and host=0.0.0.0 so Leon's phone can reach the dashboard via
  Tailscale or home Wi-Fi. Tailscale install steps handed to Leon.

- **Phone access working**: Tailscale + Add-to-Home-Screen confirmed on
  Leon's iPhone. Portrait fixes: safe-area padding, sticky section chips,
  hard width containment (page can no longer exceed the screen).
- **Cloud prep done**: optional login wall (DASHBOARD_PASSWORD), HTTPS-only
  cookies on Render, render.yaml blueprint, gunicorn; branch pushed to
  GitHub. Awaiting Leon's Render signup (free tier: naps when idle, files
  reset on restart — Mac copy stays the long-term record).

- **Cloud LIVE** (2026-07-03): Leon deployed the blueprint — the dashboard
  runs at https://vers-a.onrender.com behind the password wall (verified:
  pages redirect to /login, APIs return 401 until logged in). Pushes to the
  `dashboard` branch auto-deploy.

- **Universe expanded to 98** (2026-07-06, Leon's request): added SNDK, ASML,
  DELL, BB, NOK, ROK, MRVL, LITE, COHR, IBM, XNDU (Xanadu Quantum), SPCX
  (SpaceX) and SATL. MU and RKLB were already on the list, so 13 of the
  requested 15 were new — 98 total, not 100. Expansion = editing
  universe.yaml only, as designed. Bonus bug fix the newcomers exposed:
  quotes/stats now clamp to a stock's earliest bar, so a weeks-old listing
  like SPCX no longer crashes the quote code (regression test added).

- **Dark mode** (2026-07-06, Leon's request): ☾/☀ button in the header of
  every page. The choice is saved per browser (localStorage), applies before
  the page paints (no white flash), restyles the charts live, and flips the
  phone status-bar colour. Implementation: all colours were already CSS
  variables, so dark mode is one extra block of variable overrides in
  style.css plus a small theme.js.

- **M7 — Polish**: README.md written (what it is, how to run it, every
  setting explained), stale "sample data phase" footer fixed, hardcoded
  "85 tickers" wording made count-proof, comments audited. 45 tests pass.

- **M8 — Handover guide** (HANDOVER.md) and **replication manual**
  (REPLICATION.md, per CLAUDE.md reminder #4) written. Version A complete.

- **Watchlists** (2026-07-06, Leon's request — data model approved before
  building): the fixed universe is gone. New `dashboard/watchlists/` module
  with a music-library model: a stock CATALOGUE (each stock once, with its
  risk flags), WATCHLISTS (id + name + colour tag, unlimited), and
  membership (a symbol can sit in many lists, analysed once). Free-range
  search of any US-listed stock (Yahoo search endpoint, no key, no AI cost);
  any symbol gets a full ticker page. AI analysis runs ONLY on watchlisted
  stocks — costs scale with what's deliberately tracked. The old 98 tickers
  migrated automatically into a default "CMC Invest — Single Share List"
  watchlist, flags preserved; universe.yaml is now just that one-time seed.
  Tag stored as {kind, color} so icons/emojis later are a new kind, not a
  restructure. UI: Watchlists panel (search box with add-to-list dropdown,
  colour-dot/rename/delete cards, remove-chips), tickable watchlist chips
  on every ticker page, sidebar entry. 53 tests pass.

- **Watchlists UI round 2** (Leon's feedback): each watchlist is now a
  proper table (ticker / name / price from the latest analysis / remove ×)
  with a ▾/▸ collapse chevron remembered per list — not bubbles; the colour
  dot opens a 10-swatch popup picker instead of cycling; every watchlist
  has its own search box that adds stocks straight into that list (results
  already in the list say so); and the Stock Searcher table gained a
  watchlist filter dropdown next to the name filter.

- **Storage layer + Leon's feedback round** (2026-07-07):
  - `dashboard/storage.py` — every saved document (watchlists, portfolio,
    latest analysis/scan, deep-dive caches, picks audit) now goes through
    one interface: files in data/ by default, a free cloud Postgres
    database when DATABASE_URL is set. That's what lets the CLOUD copy
    remember across restarts (Leon signs up to Neon/Supabase, pastes one
    connection string into Render). Bonus fix: state is re-read before
    every operation, so the cloud's two server workers can no longer show
    stale data.
  - Analysis is now scoped BEFORE running: a watchlist dropdown sits next
    to the Run button; only that list (or all) is analysed, and the result
    records its scope.
  - Trade log: collapsible section in the Paper Portfolio panel showing
    every trade ever — timestamp, BUY/SELL badge, shares @ price, and the
    WHY in plain English (buys carry the pick's conviction + bull case;
    sells explain shortlist-drop or stop-loss with numbers).

## Next
- Leon: create the free Neon database and paste DATABASE_URL into Render.
- Phase 2 proper: scheduled runs + track-record panel (+ email?).

## How to run
```
cd ~/Vers-A-Stock-List
./venv/bin/python dashboard/app.py
# then open http://localhost:5001
```
