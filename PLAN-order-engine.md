# PLAN — Pending-order engine for the Paper Portfolio

**Status: approved by Leon, not yet built.** This file is the complete brief
for the implementing session. Read CLAUDE.md first (project rules), then
this. Delete this file in the final commit when everything below is done.

## What changes, in one paragraph

Today the portfolio buys instantly at the current price when Leon presses
"Sync to shortlist". That button dies. Instead, every analysis run *places
pending orders*: a planned BUY (with an AI-chosen limit price, usually a
small dip below current) for each shortlisted stock, and an explicit
HOLD or SELL verdict for every stock the portfolio already holds. Orders
then fill **by themselves** against completed trading sessions — whenever
the dashboard loads, the engine checks the daily bars since each order was
placed: if a session's LOW touched a buy's limit price, that buy filled at
the limit; SELLs fill at the next session's OPEN. No button, no scheduler.
Leon is in Sydney: when he's awake the US market is closed, so evaluating
completed sessions retroactively is exactly correct — never fill an order
in the session during which it was placed, only strictly later ones.

## Decisions already made with Leon (don't re-ask)

1. **Buy prices: the AI sets them.** Each pick's analysis includes an
   `entry_price` — sanity-clamp it server-side (see below).
2. **Expiry: the next analysis run replaces all pending orders.** Old
   unfilled orders are cancelled (status "replaced") when a run completes.
   Reserved cash is freed. Orders therefore live ~1–2 days.
3. **Sells: AI verdict per holding + the 10% stop-loss stays.** Every run
   reviews each CURRENT HOLDING (even when the run is scoped to a watchlist
   that doesn't contain it — holdings are always appended to the analysis)
   and returns HOLD or SELL with a reason. SELL = market order, fills at
   next session's open. Stop-loss (close more than 10% below avg_cost)
   remains as an automatic safety net, checked per completed session.
4. **Execution: self-updating on page load.** `/api/portfolio` (and sync
   of fills before any summary) calls the fill engine first. No scheduler
   in this milestone.

## Design

### Analysis side (`dashboard/analysis/searcher.py`)
- `run_analysis(...)` gains a `holdings` parameter:
  `[{symbol, avg_cost, shares}]` (pass from app.py: `portfolio` state).
  Held symbols not already in the analysed universe are appended to the
  batch prompts with a marker like `(CURRENTLY HELD at $X avg cost)`.
- The batch prompt asks for two new keys per stock:
  - `entry_price`: for shortlist-worthy stocks — the price the AI would
    buy at ("a realistic level within the next 1–2 sessions; may be at or
    slightly below the current price").
  - `action`: only meaningful for held stocks — `"hold"` or `"sell"` plus
    the existing reasoning fields.
- `parse_batch_response` validation (never trust the model):
  - `entry_price`: float; clamp into [0.85 × current, 1.02 × current].
    Missing/invalid → fall back to current price (a market-ish order).
  - `action`: normalise to "hold"/"sell"; anything else → "hold" (the
    safe default — never sell on a parsing accident).
- Result rows carry `entry_price` and `action`; `result["held_reviews"]` =
  `{symbol: {action, reason}}` for the app to hand to the portfolio.

### Portfolio side (`dashboard/portfolio/engine.py`)
New state key `orders` (default `[]` via `.get` for migration — existing
portfolio.json files must keep working):

```json
{"id": "ord-3f2a", "type": "buy", "symbol": "NVDA",
 "limit_price": 128.0, "budget": 800.0,
 "placed_at": "2026-07-08T11:30:00", "eligible_from": "2026-07-08",
 "reason": "conviction 8/10 — bull case: …",
 "status": "pending"}
```

- `place_orders(picks, held_reviews)` — called after every analysis run:
  1. Cancel all still-pending orders (status → "replaced").
  2. For each held symbol with action "sell": place a SELL order
     (type "sell", no limit — fills at next session's open).
  3. For each shortlisted pick not already held and not risk-flagged:
     place a BUY with the AI's entry_price. Budget = min(cap, cash −
     already-reserved). Skip (don't place) if that's under one share.
  - **Reserved cash** = sum of pending buy budgets; computed, not stored.
    total_value() counts reserved cash as cash (it isn't spent yet).
- `process_fills()` — called at the top of `summary()` (so every page view
  settles the past) and after `place_orders`:
  - For each pending order, fetch daily bars and consider only sessions
    with `bar.date >= order.eligible_from` **and** `bar.date` strictly
    after the placement session (see timezone rule below).
  - BUY fills when `bar.low <= limit_price` → fill at `limit_price`,
    `shares = int(budget // limit_price)`; log the trade with the stored
    reason plus "filled at planned $X (session YYYY-MM-DD)".
  - SELL fills at the FIRST eligible session's `open`.
  - Stop-loss: for every holding, walk eligible sessions; if a session's
    `close < avg_cost × 0.9` → sell at that close, reason says so.
  - Orders that fill are status "filled" (+ fill details); the fill trade
    is appended to `trades` with the session date, not "now".
- **Timezone rule** (`zoneinfo`, stdlib): `eligible_from` = the next US
  trading date after the placement moment in `America/New_York`. Concretely:
  convert `placed_at` to ET; the order is eligible for sessions strictly
  after that ET calendar date. (Leon places orders while the market is
  closed, so this is both correct and simple. Weekends need no special
  code — there are simply no bars on those dates.)
- `sync_to_shortlist` is deleted (and its `analyzed` parameter machinery).
  Keep `reset()`. Update/replace its tests rather than deleting coverage.

### App wiring (`dashboard/app.py`)
- `api_run_analysis`: pass current holdings into `run_analysis`; after a
  successful run call `portfolio.place_orders(...)`. The response includes
  the placed orders so the UI can show them immediately.
- `/api/portfolio/sync` route: delete. `/api/portfolio` now triggers
  `process_fills()` via `summary()`.
- Keep the analysis/scan locks as they are.

### UI (`dashboard/static/app.js`, `index.html`)
- Remove the "Sync to shortlist" button. Keep Reset.
- New collapsible **"Pending orders"** section in the portfolio panel
  (same collapse pattern as the others, default hidden): each order shows
  BUY/SELL badge, symbol, planned price ("$128.00 or better" / "next
  open"), budget, placed time, and status. Recently replaced/filled orders
  show greyed at the bottom (last ~10).
- Trade log unchanged in shape — fills arrive there with their reasons.
- Panel subtitle/status wording: explain that orders fill automatically
  against completed sessions ("checked whenever the dashboard loads").

### Tests (offline, use fakes — follow existing patterns)
Craft a fake PriceSource whose `get_history` returns hand-written bars:
- buy fills at limit when a later session's low crosses it; does NOT fill
  when the low stays above; does NOT fill on the placement day's own bar.
- sell fills at next session's open.
- stop-loss triggers on a close 10% under avg_cost.
- new analysis run replaces pending orders and frees reserved cash.
- budget: reserved cash can't be double-spent across two pending buys.
- entry_price clamping and action normalisation in the parser.
- migration: portfolio.json without "orders" loads fine.

### Docs (same commit as the code they describe)
- PROGRESS.md entry; README "what it does" tweak (orders, no sync);
  HANDOVER.md routine section rewrite (no more Sync step; explain how
  fills happen and that stop-loss is automatic).

## Process requirements (from CLAUDE.md — non-negotiable)
- Small logical commits on the `dashboard` branch; beginner-readable
  comments; run `./venv/bin/python -m pytest tests/` (all green) before
  every commit; verify against the live local server with curl.
- Local server: `pkill -f dashboard/app.py` then
  `nohup ./venv/bin/python dashboard/app.py > /tmp/versa-server.log 2>&1 &`
  (the debug reloader is OFF by default now — restart after edits).
- Never run a real paid analysis to test — use the fakes.
- Push when done (auto-deploys the cloud copy at vers-a.onrender.com).
