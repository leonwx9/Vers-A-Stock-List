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

## Next
- M5: AI Pivot Scanner (SEC EDGAR + skeptical analysis).
- M6: swap sample prices for live data (one ticker first).
- M7/M8: polish, README, handover guide.

## How to run
```
cd ~/Vers-A-Stock-List
./venv/bin/python dashboard/app.py
# then open http://localhost:5001
```
