# Vers A — Stock Searcher & AI Pivot Scanner

A private dashboard that does two things:

1. **Stock Searcher** — analyses a fixed universe of 98 US stocks/ETFs
   (see `dashboard/config/universe.yaml`), runs a bull-vs-bear AI debate on
   each, scores conviction 1–10, shortlists the top 5, and manages a
   **$10,000 paper-trading portfolio** that mirrors the shortlist. Pretend
   money only — this app never trades for real.
2. **AI Pivot Scanner** — searches SEC EDGAR for small-cap, non-tech
   companies that have *just* disclosed an "AI pivot" in a filing, then reads
   the filing with deliberate skepticism: announced vs actually executed,
   can they fund it, red flags, hype score 1–10.

Everything is plain-English and beginner-readable on purpose — the code is
the documentation.

> **Not investment advice.** This is a learning project with pretend money.

## How to run it

```bash
cd ~/Vers-A-Stock-List

# One-time setup
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
cp .env.example .env        # then edit .env and paste your API key in

# Every time
./venv/bin/python dashboard/app.py
# → open http://localhost:5001
```

The only key you *need* is one AI key (OpenRouter or Anthropic — see below).
Prices (Yahoo Finance) and SEC filings (EDGAR) are free, no key.

## The .env file (settings & secrets)

Copy `.env.example` to `.env` and fill it in. `.env` is gitignored — keys
never reach GitHub.

| Setting | What it does |
|---|---|
| `LLM_PROVIDER` | `openrouter` or `anthropic` — which AI service to use |
| `OPENROUTER_API_KEY` / `ANTHROPIC_API_KEY` | the matching key |
| `OPENROUTER_MODEL` / `ANTHROPIC_MODEL` | which Claude model (already set) |
| `DASHBOARD_PASSWORD` | set = every page needs a password (cloud); empty = open (local) |
| `FLASK_SECRET_KEY` | keeps you logged in across restarts (any long random string) |
| `SEC_EDGAR_CONTACT` | optional "Name email" our EDGAR requests identify as |

**Switching AI provider is two lines**: change `LLM_PROVIDER=openrouter` to
`anthropic` and fill in `ANTHROPIC_API_KEY`. Nothing else changes.

## The config files (behaviour, no code edits needed)

- `dashboard/config/universe.yaml` — the full ticker list. **Adding a stock =
  adding one line here.** Risk flags (`leveraged` / `inverse` / `volatility`)
  keep a product out of the shortlist and portfolio while still analysed.
- `dashboard/config/rules.yaml` — everything tunable:
  - `data.price_source`: `live` (Yahoo Finance) or `sample` (offline fake
    data for development — deterministic, no internet needed)
  - portfolio rules: starting cash, max $ per position, stop-loss %, …
  - scanner rules: market-cap ceiling, excluded sectors, lookback days, …

## Phone & cloud

- **Phone (private)**: install Tailscale on the Mac and the phone, run the
  app, open `http://<mac-tailscale-name>:5001` in Safari → Share →
  **Add to Home Screen**. Works anywhere; traffic stays private.
- **Cloud**: the repo contains `render.yaml` — a Render.com free-tier
  blueprint. Deploys automatically on every push to the `dashboard` branch.
  Set `DASHBOARD_PASSWORD` there so the internet sees a login wall.
  Free-tier caveats: ~50 s wake-up after idle, and saved files (portfolio
  history, analysis runs) reset on restart — the Mac copy is the permanent
  record.

## Tests

45 automated tests, all offline (external services are faked):

```bash
./venv/bin/python -m pytest tests/
```

## Project layout

```
dashboard/
  app.py               Flask server — routes and the login wall
  config/              universe.yaml (tickers) + rules.yaml (behaviour)
  config_loader.py     reads the two YAML files
  datasources/         PriceSource interface; sample + live (Yahoo) + news
  llm/                 AI provider switch (OpenRouter ↔ Anthropic)
  analysis/            searcher (bull/bear/conviction) + per-ticker deep dive
  portfolio/           the $10,000 paper-trading engine
  scanner/             EDGAR client + the skeptical AI-pivot scanner
  static/              CSS, JS, icons, vendored chart library
  templates/           the HTML pages
  data/                saved runs & portfolio state (gitignored)
picks/                 dated audit file per analysis run (committed)
tests/                 pytest suite — fakes, no network
render.yaml            cloud deployment blueprint (Render.com)
PROGRESS.md            milestone-by-milestone build history
HANDOVER.md            plain-English guide to owning this project
```

Charts by [TradingView Lightweight Charts™](https://www.tradingview.com/lightweight-charts/)
(Apache-2.0), served locally.
