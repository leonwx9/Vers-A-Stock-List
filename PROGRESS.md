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

## Next
- Leon pastes his OpenRouter key into `.env`, then we do the first real
  analysis run and confirm M3 on screen.
- M4: paper-trading portfolio + total-value graph (sample data).
- M5: AI Pivot Scanner (SEC EDGAR + skeptical analysis).
- M6: swap sample prices for live data (one ticker first).
- M7/M8: polish, README, handover guide.

## How to run
```
cd ~/Vers-A-Stock-List
./venv/bin/python dashboard/app.py
# then open http://localhost:5001
```
