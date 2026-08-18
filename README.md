# Vers A — Stock Searcher & Event Scanner

A private dashboard that does four things:

1. **Watchlists + free search** — search any US-listed stock (plain lookup,
   no AI cost) and organise stocks into unlimited named, colour-tagged
   watchlists. A stock can sit in many lists at once. The original
   98-ticker CMC list lives on as the default watchlist.
2. **Stock Searcher** — runs a bull-vs-bear AI debate on every *watchlisted*
   stock (only what you deliberately track costs AI money), scores
   conviction 1–10, and places **planned orders** in a $10,000 pretend
   **paper-trading portfolio**: a BUY at the AI's own entry price for each
   fresh shortlisted pick, and a HOLD/SELL call on every stock already
   held. Orders fill themselves against real trading sessions — nothing
   to press, and nothing is ever real money.
3. **AI Pivot Scanner** — searches SEC EDGAR for small-cap, non-tech
   companies that have *just* disclosed an "AI pivot" in a filing, then reads
   the filing with deliberate skepticism: announced vs actually executed,
   can they fund it, red flags, hype score 1–10.
4. **Event Strategy Lab** — a notebook for event-timing patterns ("when a
   key oil chokepoint closes, energy-exposed assets tend to spike") rather
   than stock picks: write your own strategies, ask the AI to brainstorm
   more (clearly badged AI vs yours), and press "Scan now" to check
   whether current news matches a saved pattern. Every match always shows
   its counter-case, risks, sources, and an honest confidence level.
   **Ideas to research, never advice — no automated or real trading.**

An optional **daily order-fill scheduler** (off by default) settles
pending paper-trade orders each morning even if you don't open the
dashboard — no AI involved, it's free. And a collapsible **Fix bulletin**
(right edge of the page) is your own editable sticky note for future
to-dos, with simple bold/underline/dot-point formatting.

AI can run on YOUR OWN Claude subscription instead of a paid API key — a
toggle in the Stock Searcher panel switches between them any time (Mac
only; a subscription's usage window is shared with claude.ai chat, so
the toggle is how you protect that quota during a heavy chat day). With
it on, an optional **overnight scheduler** runs up to three analyses a
night while the US market is open and you're asleep, at three adjustable
times (default: just after open, mid-session, just before close). One
of those — the middle run — checks any **price watches** you've set
("tell me if this stock reaches $X tonight") and, if one fired, gives
that stock a dedicated buy/sell verdict instead of the usual full sweep.

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

On Leon's Mac this now happens automatically via `launchd` — see
HANDOVER.md's "Keeping it running" section. The manual command above is
still the right way to run it the first time, or on any other machine.

The only key you *need* is one AI key (OpenRouter or Anthropic — see below).
Prices (Yahoo Finance) and SEC filings (EDGAR) are free, no key. Your own
Claude subscription is a fourth, key-less option — see below.

## The .env file (settings & secrets)

Copy `.env.example` to `.env` and fill it in. `.env` is gitignored — keys
never reach GitHub.

| Setting | What it does |
|---|---|
| `LLM_PROVIDER` | `openrouter`, `anthropic`, or `claude_code` — which AI service to use by default (the dashboard's own toggle can override this without touching `.env` — see below) |
| `OPENROUTER_API_KEY` / `ANTHROPIC_API_KEY` | the matching key |
| `OPENROUTER_MODEL` / `ANTHROPIC_MODEL` | which Claude model (already set) |
| `CLAUDE_CODE_MODEL` | `sonnet` (default) or `opus` — which model your OWN Claude subscription runs, via headless Claude Code. Opus is smarter but drains your subscription's shared usage window several times faster |
| `CLAUDE_CODE_EFFORT` | `low` / `medium` (default) / `high` / `xhigh` / `max` — how hard that model thinks. Higher = better answers, more of your usage window spent |
| `DASHBOARD_PASSWORD` | set = every page needs a password (cloud); empty = open (local) |
| `FLASK_SECRET_KEY` | keeps you logged in across restarts (any long random string) |
| `DASHBOARD_DEBUG` | `1` = auto-reload on code edits + rich error pages, but reachable from THIS Mac only (the debugger can run code, so it must never face the network). Empty = normal mode, phone can connect |
| `SEC_EDGAR_CONTACT` | optional "Name email" our EDGAR requests identify as |
| `DATABASE_URL` | optional free cloud Postgres — set it and saved data (watchlists, portfolio…) lives there instead of local files, so the cloud copy survives restarts |

**Switching AI provider is two lines**: change `LLM_PROVIDER=openrouter` to
`anthropic` and fill in `ANTHROPIC_API_KEY`. Nothing else changes.

**Using your own Claude account instead** needs no `.env` edit at all —
flip the toggle in the Stock Searcher panel. It shells out to Claude
Code (`claude -p`) on THIS Mac, billed to whichever account is logged in
there — so it only works locally, never on the cloud copy (which has no
login). It spends your subscription's own usage window, not a paid key.

## The config files (behaviour, no code edits needed)

- `dashboard/config/universe.yaml` — the one-time migration seed: on first
  run it becomes the default watchlist. After that, **add/remove stocks in
  the dashboard itself** (search box + watchlists). Risk flags
  (`leveraged` / `inverse` / `volatility`) live on each stock in the
  catalogue and keep a product out of the shortlist and portfolio while
  still analysed.
- `dashboard/config/rules.yaml` — everything tunable:
  - `data.price_source`: `live` (Yahoo Finance) or `sample` (offline fake
    data for development — deterministic, no internet needed)
  - portfolio rules: starting cash, max $ per position, the fallback
    stop-loss % and its `_min`/`_max` band (the AI picks its own per-stock
    stop-loss within that band), …
  - scanner rules: market-cap ceiling, excluded sectors, lookback days, …
  - `lab` rules: news searches per scan, headlines per search, the cap on
    what one scan feeds the AI, and how many patterns "Brainstorm" suggests
  - `scheduler.fill_hour_sydney`: the Sydney hour after which the optional
    daily order-fill run becomes due (only matters if you turn it on)
  - `scheduler.analysis_times_et`: the three DEFAULT overnight analysis
    times, in US-market time — adjustable from the dashboard itself
    without touching this file (only matters with the overnight toggle on)

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

A suite of automated tests (210 and growing), all offline — external
services are faked:

```bash
./venv/bin/python -m pytest tests/
```

## Project layout

```
dashboard/
  app.py               Flask server — routes and the login wall
  config/              universe.yaml (migration seed) + rules.yaml (behaviour)
  config_loader.py     reads the two YAML files
  watchlists/          the watchlist store (catalogue + lists + membership)
  datasources/         PriceSource interface; sample + live (Yahoo) + news + search
  llm/                 AI provider switch (OpenRouter / Anthropic / your own
                       Claude account via headless Claude Code)
  analysis/            searcher (bull/bear/conviction) + per-ticker deep dive
  portfolio/           the $10,000 paper-trading engine
  scanner/             EDGAR client + the skeptical AI-pivot scanner
  strategy_lab/        journal + brainstorm + news-based setup scanner
                       (information only — never imports the portfolio)
  scheduler.py         two optional background runs: daily order fills (no
                       AI) and overnight analysis (your Claude account only)
  price_watches.py     "tell me if this reaches $X tonight" — checked once,
                       at the overnight scheduler's middle run
  bulletin.py          the Fix bulletin — Leon's own editable to-do note
  static/              CSS, JS, icons, vendored chart library
  templates/           the HTML pages
  data/                saved runs & portfolio state (gitignored)
picks/                 timestamped audit file per analysis run (committed)
tests/                 pytest suite — fakes, no network
render.yaml            cloud deployment blueprint (Render.com)
PROGRESS.md            milestone-by-milestone build history
HANDOVER.md            plain-English guide to owning this project
```

Charts by [TradingView Lightweight Charts™](https://www.tradingview.com/lightweight-charts/)
(Apache-2.0), served locally.
