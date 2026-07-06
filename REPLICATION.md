# REPLICATION — rebuilding Version A on any stock universe

For future Leon. You've built this once; this is the recipe to build it
again with Claude Code on a different universe (all of Wall Street, another
broker's list, whatever), without re-learning the lessons the hard way.

## The short version

Version A is three swappable parts behind fixed interfaces:

1. **A universe** — one YAML file listing tickers. Everything else reads it.
2. **Data sources** — a `PriceSource` interface (get_history / get_quote /
   get_stats / get_changes) with two implementations: deterministic sample
   data and a live one. Plus a news source.
3. **An AI provider switch** — one `complete(system, user)` function,
   OpenRouter or Anthropic behind an .env flag.

The searcher, portfolio, scanner, and UI only ever talk to those three.
That's why swapping fake→live prices mid-project changed zero other files,
and why a new universe is a config change, not a rewrite.

## The brief to hand Claude Code

Copy, adjust the bracketed parts, paste as the opening message:

---

Build me a stock dashboard in this repo. Read CLAUDE.md first.

**What it does:** analyses the universe in `config/universe.yaml`
[describe your new universe and where the list comes from], runs a bull/bear
AI debate per ticker with a conviction score 1–10, shortlists the top
[5], and runs a $[10,000] paper-trading portfolio that mirrors the
shortlist (whole shares, max $[800] per position, [10]% stop-loss, never
buys leveraged/inverse/volatility-flagged products). Paper money only —
never real trading. Every analysis run saves a dated audit file to `picks/`.

**Architecture requirements (non-negotiable):**
- Config-driven: universe in `universe.yaml`, all tunable behaviour in
  `rules.yaml`. Changing the universe must never require code changes.
- A `PriceSource` abstract interface with TWO implementations: a
  deterministic offline sample source (build against this first) and a live
  source (its own milestone, prove it on one ticker before switching all).
- LLM behind a provider switch: OpenRouter now, direct Anthropic via a
  2-line .env change. Reject placeholder keys with a friendly error.
- Every external call fails gracefully (empty list / skipped item / honest
  "unavailable" note — never a crashed page).
- Automated tests that run offline using fakes, not real services.

**Process:** propose a milestone plan and wait for my approval. Small
logical git commits on a branch. Maintain PROGRESS.md. Secrets only in
.env (gitignored, with a .env.example). Ask before anything that costs
money, needs my login, or changes major structure — with reasoning per
option. I run my own logins; you never log in as me. Beginner-readable
comments throughout.

**Stack:** Python + Flask, plain HTML/CSS/JS, vendored chart library
(TradingView Lightweight Charts, Apache-2.0 — attribute it).

---

Then approve/adjust its milestone plan. The order that worked:
shell → searcher on sample data → ticker detail pages + UI → portfolio →
[scanner if you want it] → live data swap → phone/cloud → polish + docs.

## Universe-specific decisions to make up front

- **Where does the ticker list come from?** 98 hand-picked lines is fine to
  maintain by hand. "All of Wall Street" (~6,000) is not — have Claude Code
  build a small generator script that writes universe.yaml from a source
  (e.g. NASDAQ/NYSE listings files), and re-run it monthly.
- **Batch cost scales linearly.** ~100 tickers ≈ 10 AI requests per run.
  6,000 tickers ≈ 600 requests per run — decide whether you want a
  pre-filter (e.g. only analyse tickers passing a cheap screen) before
  paying for full AI analysis of everything.
- **Which products get risk flags?** Anything leveraged/inverse/volatility
  gets `flags:` so the portfolio can't buy it. On a big universe, flag by
  rule (ETF issuer/name patterns), not by hand.

## Gotchas that cost real time (tell Claude Code to check PROGRESS.md)

- **Yahoo Finance**: needs a browser User-Agent; use the query2 mirror as
  fallback; `range=max` silently coarsens monthly bars to quarterly, so
  locate historical bars **by date**, never by counting; brand-new IPOs
  have fewer bars than any lookback assumes — clamp to the earliest bar.
- **SEC EDGAR**: 403 means "slow down", not "blocked" — retry with backoff
  and a keep-alive session; set a contact User-Agent. Validate full-text
  search phrases against real EDGAR before trusting them ("AI strategy"
  found 14 hits where "pivot to artificial intelligence" found 0).
- **Flask dev server**: host/port changes need a real stop/start
  (`pkill -f app.py`) — the debug reloader keeps the old socket.
- **Yahoo's RSS is dead**; Google News RSS works for headlines.
- **iPhone PWA**: `viewport-fit=cover` + safe-area padding, and hard width
  containment (`minmax(0,1fr)`, `min-width:0`, `overflow-x:clip`) or
  portrait mode will overflow.
- **Sample data** must be deterministic (seed from the ticker string) and
  generated as one fixed series that gets sliced, or different page views
  disagree about yesterday's price.

## What to copy verbatim from this repo

`dashboard/datasources/` (the interfaces and both sources), `dashboard/llm/`
(the provider switch), `render.yaml`, `.env.example`, `.gitignore`, and the
login-wall block in `app.py` are universe-agnostic — reuse them as-is and
spend the effort on the universe generator and any new rules.
