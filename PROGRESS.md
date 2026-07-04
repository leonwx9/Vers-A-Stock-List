# Progress

## Done
- **M1 — Plan approved** (2026-07-03): Python + Flask, OpenRouter (switchable to
  Anthropic via .env), $10,000 paper portfolio, modular config-driven structure.
- **M2 — Dashboard shell**: styled black/white/grey page on http://localhost:5001
  with the two sections.
- **M3 — Stock Searcher (code complete, awaiting API key)**:
  - `dashboard/config/universe.yaml` — all 85 tickers with risk flags
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

## Next
- Phone access: Tailscale + PWA (Leon has iPhone; Mac often asleep —
  needs keep-awake setting; cloud hosting is a clean later migration).
- M7/M8: polish, README, handover guide.

## How to run
```
cd ~/Vers-A-Stock-List
./venv/bin/python dashboard/app.py
# then open http://localhost:5001
```
