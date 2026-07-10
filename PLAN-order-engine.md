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
   `entry_price`. If it fails the sanity check (see parser rules below),
   the pick is SKIPPED this run — no order — recorded visibly in the
   orders list (status "skipped_bad_price"). Never clamp, never silently
   substitute: a garbage number means we don't trade on that pick.
2. **Expiry: the next analysis run replaces all pending orders.** Old
   unfilled orders are cancelled (status "replaced") when a run completes.
   Orders therefore live ~1–2 days. Leon's mental model, verbatim shape:
   each run first settles what filled since last time, then reviews
   holdings (hold/sell), then places fresh orders for the next session.
3. **Sells: AI verdict per holding + stop-loss net.** Every run reviews
   each CURRENT HOLDING (even when the run is scoped to a watchlist that
   doesn't contain it — holdings are always appended to the analysis) and
   returns HOLD or SELL with a reason. SELL = market order, fills at next
   session's open.
4. **Stop-loss: AI-chosen percentage PER STOCK, triggered on the CLOSE.**
   The analysis returns a structured `stop_loss_pct` for each pick; it's
   stored on the position at buy time and that position is sold when a
   completed session CLOSES more than its own pct below avg_cost (intraday
   dips don't trigger — Leon chose the forgiving style). Clamp the pct to
   [5, 25]; missing/invalid → the rules.yaml default (10).
5. **Cash: fill-time sizing, sells settle first.** Budgets are caps, not
   reservations. Within each session, SELL fills (at the open) are
   processed before BUY fills, so sale proceeds fund the same day's buys.
   A buy sizes itself from the cash available at its fill moment (whole
   shares, ≤ its budget cap); if that's under one share it stays pending.
   When cash can't serve every pick at placement, higher conviction wins.
6. **Gap fills: the better of open or limit.** If a session OPENS below a
   buy's limit, the fill price is the open (a real limit order never pays
   above its limit and takes the gap discount). Otherwise, if the session's
   LOW touches the limit, it fills at the limit.
7. **Execution: self-updating on page load.** `/api/portfolio` calls the
   fill engine before summarising. No scheduler in this milestone.

## Design

### Analysis side (`dashboard/analysis/searcher.py`)
- `run_analysis(...)` gains a `holdings` parameter:
  `[{symbol, avg_cost, shares}]` (pass from app.py: `portfolio` state).
  Held symbols not already in the analysed universe are appended to the
  batch prompts with a marker like `(CURRENTLY HELD at $X avg cost)`.
- The batch prompt asks for three new keys per stock:
  - `entry_price`: for shortlist-worthy stocks — the price the AI would
    buy at ("a realistic level within the next 1–2 sessions; may be at or
    slightly below the current price").
  - `stop_loss_pct`: the percentage drop (from entry) at which this
    particular stock should be cut — the AI tailors it to the stock's
    volatility (a staid dividend stock might warrant 6, a volatile
    small-cap 20). Keep the existing human-readable `stop_loss` note too.
  - `action`: only meaningful for held stocks — `"hold"` or `"sell"` plus
    the existing reasoning fields.
- `parse_batch_response` validation (never trust the model):
  - `entry_price`: float; sane iff within [0.85 × current, 1.02 × current].
    Outside the band, missing, or non-numeric → the pick is SKIPPED (no
    order placed; surfaced as status "skipped_bad_price"). Why check at
    all? Models make formatting slips — a dropped decimal turns $128 into
    $12.8 — and an order at a nonsense price would silently never fill.
  - `stop_loss_pct`: float clamped into [5, 25]; missing/invalid → the
    rules.yaml `stop_loss_pct` default.
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
  3. For each shortlisted pick not already held and not risk-flagged, in
     conviction order (highest first): place a BUY with the AI's
     entry_price and stop_loss_pct. Budget = min(cap, cash available at
     placement) as a CAP — actual affordability is re-checked at fill
     time (fill-time sizing). A pick whose entry_price was rejected gets
     a "skipped_bad_price" record instead of an order.
- `process_fills()` — called at the top of `summary()` (so every page view
  settles the past) and after `place_orders`:
  - Walk sessions in DATE ORDER, and within each session process SELLS
    first (they fill at the open), THEN stop-loss checks, THEN buys — so
    sale proceeds are available to fund the same session's buys.
  - An order is only checked against sessions with
    `bar.date >= order.eligible_from` (see timezone rule below).
  - BUY: if the session OPEN <= limit → fill at the open (gap discount);
    else if the session LOW <= limit → fill at the limit. Fill price
    `p`; `shares = int(min(budget, cash_now) // p)`; zero shares → stays
    pending. Log the trade with the stored reason plus
    "filled at $X (session YYYY-MM-DD)".
  - SELL fills at the FIRST eligible session's `open`.
  - Stop-loss: per holding, using ITS OWN `stop_loss_pct` (stored on the
    position at buy time; older positions without one use the rules
    default): if a session's `close < avg_cost × (1 − pct/100)` → sell at
    that close, reason names the pct and the numbers.
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
- New collapsible **"Sell decisions"** section directly UNDER the Trade
  Log (Leon asked for this explicitly): for every holding the latest
  analysis reviewed, show a HOLD or SELL badge (SELL in signal red), the
  stock, and the AI's full reasoning sentence — so Leon can read WHY
  selling (or keeping) was judged best, not just see the resulting trade.
  Data comes from `result["held_reviews"]` — persist the latest reviews
  (e.g. store them on the portfolio state or read analysis_latest in the
  portfolio panel's JS) so the section survives reloads. Same collapse
  pattern as everything else, default hidden. Stop-loss sells aren't AI
  decisions — the trade log entry's reason covers those.
- Panel subtitle/status wording: explain that orders fill automatically
  against completed sessions ("checked whenever the dashboard loads").

### Tests (offline, use fakes — follow existing patterns)
Craft a fake PriceSource whose `get_history` returns hand-written bars:
- buy fills at limit when a later session's low crosses it; does NOT fill
  when the low stays above; does NOT fill on the placement day's own bar.
- gap-down: session opens below the limit → fills at the OPEN, not limit.
- sell fills at next session's open; same-session sell proceeds fund a
  buy later that session (sells-before-buys ordering).
- stop-loss triggers on a close below the position's OWN stop_loss_pct;
  a position without one uses the rules default; an intraday low below
  the stop but a close above it does NOT trigger.
- fill-time sizing: two pending buys + not enough cash for both → the
  one that fills first gets the cash; the other shrinks or stays pending.
- new analysis run replaces pending orders.
- parser: out-of-band entry_price → pick skipped (skipped_bad_price);
  stop_loss_pct clamped to [5, 25] with default fallback; action
  normalisation ("Bull"/" SELL " etc.).
- migration: portfolio.json without "orders" loads fine; old positions
  without stop_loss_pct still stop out at the default.

### Config (`dashboard/config/rules.yaml`)
- `portfolio.stop_loss_pct` becomes the DEFAULT/fallback stop (used when
  the AI didn't supply a valid per-stock one) — update its comment to say
  so. Add `stop_loss_pct_min: 5` / `stop_loss_pct_max: 25` for the clamp
  so the band is config, not magic numbers.

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
