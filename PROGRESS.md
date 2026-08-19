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

- **Second-opinion review round** (2026-07-08): a fresh-eyes audit of the
  whole project found and fixed, with Leon's approval:
  - *Deep dive trusted live prices* — the prompt permanently said
    "simulated prices" (a leftover from before M6), making the AI distrust
    real market data. Now live/sample is stated honestly, like the searcher.
  - *Audit trail kept every run* — picks/ files were named by date only, so
    a same-day re-run overwrote the earlier one. Files are now timestamped
    per run, and a new `analysis_history` document records every run's
    scope + picks + entry prices (the seed for a future track-record panel).
  - *Scoped-sync trap* — syncing after a one-watchlist analysis used to
    sell EVERYTHING outside that list. Sync now only trades within what the
    run actually analysed (stop-loss still applies to all holdings).
  - *Security*: HTML-escaping in the browser code (news headlines, AI text
    and stock names can no longer inject scripts — "XSS"); session cookie
    marked SameSite=Lax (blocks cross-site forged requests); 1-second pause
    per wrong password (blunts brute-forcing); Flask's debugger now only
    runs bound to this Mac (DASHBOARD_DEBUG=1), never network-visible.
  - *Robustness*: one failed AI batch no longer sinks a whole run (and a
    junk conviction value no longer crashes parsing); a "bear" verdict can
    no longer be shortlisted on a high conviction score; only one paid
    run/scan at a time (second press gets "already running"); file saves
    are atomic (a crash mid-write can't corrupt saved data); viewing the
    portfolio no longer rewrites its file on every reload; EDGAR retries
    timeouts too.
  - *Housekeeping*: dead config keys removed (whole_shares_only,
    history_days), scanner market-cap ceiling actually wired to rules.yaml,
    all dependency versions pinned. Tests: 56 → 70, all offline.
  - Deliberately NOT changed (flagged for a future decision): the batch
    analysis still reasons mostly from momentum numbers — feeding real
    headlines into it is a feature choice for Leon, not a bug fix.

- **Pending-order engine** (2026-07-11, Leon's request — planned in
  PLAN-order-engine.md, approved before building): the instant "Sync to
  shortlist" button is gone. Every analysis run now PLACES ORDERS instead
  of trading immediately:
  - Each shortlisted pick gets a planned BUY at the AI's own entry price
    (sanity-checked — an unrealistic price means the pick is skipped this
    run, never silently substituted) and its own AI-chosen stop-loss %
    (5–25%, tailored to the stock's volatility).
  - Every stock the portfolio currently holds gets an explicit HOLD/SELL
    review EVERY run — even if it's outside the run's watchlist scope, so
    a position never goes unreviewed just because a different list was
    analysed. A SELL review places a sell order.
  - Orders then fill THEMSELVES — no button. Whenever the dashboard is
    opened, `process_fills()` checks real completed trading sessions since
    each order was placed (in `America/New_York` time, so an order can
    never fill in the session it was placed during): a BUY fills at the
    session's open if it gapped below the plan, or at the plan's own
    price if the session merely dipped to it; a SELL fills at the next
    session's open; every holding is also checked against its own
    stop-loss on the CLOSE (a brief intraday dip that recovers by the
    bell doesn't sell). Sells are processed before buys within a session,
    so sale proceeds can fund the same day's buys (fill-time cash sizing
    — budgets are caps, not reservations, so cash-tight days serve the
    highest-conviction pick first). A fresh analysis run replaces any
    still-pending orders — they live roughly 1-2 days, not forever.
  - New UI: a **Pending orders** section (planned price, budget, status —
    filled/replaced/skipped) and a **Sell decisions** section (every
    holding's HOLD/SELL call with the AI's full reasoning), both
    collapsible under the trade log. The holdings table gained a Stop
    column. `rules.yaml` gained `stop_loss_pct_min`/`_max` (the AI's
    per-stock number is clamped into this band, or falls back to
    `stop_loss_pct`).
  - Migration-safe: old portfolio saves (no `orders` key, positions
    without their own `stop_loss_pct`) load and behave exactly as before.
    test_portfolio.py (14→21) and test_searcher.py (10→16) rewritten
    around the order/fill model, using a scripted fake price source for
    deterministic date-based fill testing (a gap-down, a stop-loss close,
    two buys competing for tight cash, an order placed the day before a
    weekend, …). 70→86 tests total, all offline.

- **M0 — two review repairs** (2026-07-12, from a fresh-eyes review of the
  order engine): a scoped analysis run appends currently-held stocks so
  they get a HOLD/SELL review even when they're outside the chosen
  watchlist — but those appended stocks were then also competing for (and
  could win) a shortlist slot that belonged to the watchlist actually
  being analysed. `run_analysis()` gained a `review_only` set so an
  appended stock is reviewed but can never be shortlisted. Also: order
  ids switched from a per-process time+counter to random bytes
  (`secrets.token_hex`) — two cloud workers each running their own
  counter from zero could otherwise hand out the same id.

- **Event Strategy Lab** (2026-07-12, Leon's request — planned in
  PLAN-strategy-lab.md, approved before building): a new view inside the
  Event Scanner panel (renamed from "AI Pivot Scanner"), reached by a
  segmented toggle — `[ AI Pivots | Strategy Lab ]`, remembered per
  browser. Three parts, all information-only:
  - **My journal** (`dashboard/strategy_lab/journal.py`): Leon's own
    event-timing strategies (name, plain-English description, entry/exit
    triggers, affected sectors, risk notes, tags) — full add/edit/delete,
    saved permanently (file or the cloud database, same as everything
    else). Each entry's `origin` ("leon" or "ai") is stamped by the
    server, never accepted from the browser — editing an AI suggestion
    can't relabel it as Leon's own thinking.
  - **Brainstorm** (`brainstorm.py`): one AI request that reads the
    existing journal (to avoid duplicates) and suggests new patterns,
    saved badged `origin="ai"`. Malformed suggestions (missing a trigger)
    are dropped, not guessed at; capped at `rules.yaml`'s
    `lab.brainstorm_count`.
  - **Scan now** (`setup_scanner.py` + `datasources/events_source.py`):
    fetches current headlines (Google News RSS, free, no key, reusing the
    same parser the ticker pages already use) for each strategy's tags,
    then ONE AI request for the whole scan — never one per strategy — asks
    which patterns look currently in play. The AI can only cite evidence
    by NUMBER from a list the code supplies, so it can't reference a
    headline it wasn't actually given. `parse_scan_response()` enforces
    every guardrail structurally: a setup missing its counter-case,
    risks, or a valid strategy/source reference is DROPPED, not patched —
    there is no code path that produces a one-sided setup card. An
    optional once-a-day auto-scan (default OFF) can run in the background
    without blocking the page.
  - The Lab module never imports the portfolio, scanner, or analysis code
    — it can inform Leon but cannot place even a pretend trade. Cost:
    headlines free; brainstorm/scan ≈1-2¢ each (same Sonnet model the
    rest of the app already uses via OpenRouter).
  - 29 new tests (`test_strategy_lab.py`), including one that specifically
    proves a `null` AI-supplied counter_case can't slip past the guardrail
    as the literal string `"None"`. 117 tests total, all offline.

- **Lab review fixes, the daily fill scheduler, and the Fix bulletin**
  (2026-07-12, from a Fable 5 review of the Strategy Lab build; planned
  in PLAN-fixes-scheduler-bulletin.md):
  - Four fixes: the confidence note is now printed as visible text on a
    setup card instead of a hover tooltip (which a phone can never show);
    `derive_queries()` now collects tags ROUND-ROBIN across strategies
    instead of strategy-by-strategy, so a journal grown past
    `lab.max_queries` can't silently starve its oldest strategies of any
    news search at all; the page now polls `/api/lab` a couple of times
    after a background auto-scan starts, so the fresh result appears
    without a manual reload; and the daily-scan checkbox now reverts
    itself with a warning if saving the setting fails.
  - Smarter once-a-day guard: `should_auto_scan()` / `ran_today()`
    (`setup_scanner.py`) mean a scan Leon already ran BY HAND today
    satisfies the daily rule too — the automatic scan no longer fires on
    top of a manual one, and a background scan double-checks right
    before spending anything in case the cloud's other worker just
    finished one.
  - **Daily order-fill scheduler** (`dashboard/scheduler.py`, new,
    off by default): settles pending orders and records the day's
    portfolio-graph point once Sydney time passes `rules.yaml`'s
    `scheduler.fill_hour_sydney` (8am) — no AI involved, just the same
    free `process_fills()`/`snapshot()` every page view already
    triggers, guaranteed to happen once a day even if Leon doesn't open
    the dashboard. Runs as a background thread started only from
    `app.py`'s `__main__` block (never under gunicorn/Render — the cloud
    copy resets on restart anyway, and a thread per worker could
    double-fire). Toggle lives in the Paper Portfolio panel.
  - **Fix bulletin** (`dashboard/bulletin.py`, new): a collapsible note
    pinned to the right edge of the page, entirely Leon's own — plain
    text with three simple markers (`**bold**`, `_underline_`, `- ` for a
    dot point) rendered client-side. Seeded once with the review's own
    known housekeeping items (the ever-growing scan-history file, the
    malicious-headline risk, duplicate source links, the scheduler's
    Mac-only reach) so they're not lost, then entirely Leon's to edit.
  - 17 new tests (6 in `test_strategy_lab.py`, 7 in `test_scheduler.py`,
    4 in `test_bulletin.py`). 134 tests total, all offline.

- **AI on Leon's own Claude account, overnight analysis, price watches**
  (2026-08-14, planned in PLAN-claude-account-provider.md, approved same
  day): Fable 5 verified live on Leon's Mac that a Claude subscription
  isn't an API credit pool, but headless Claude Code (`claude -p`) IS a
  legitimate bridge — billed to whichever account is logged in, no API
  key involved. Sonnet and Opus (via `--model`) plus `--effort` all
  confirmed working before any code was written.
  - **`ClaudeCodeProvider`** (`dashboard/llm/claude_code_provider.py`,
    new): a fourth provider, same one-method interface as the other
    three. Shells out to `claude -p` with the prompt on stdin (not argv —
    analysis prompts are large), all tools disabled, model/effort from
    `CLAUDE_CODE_MODEL`/`CLAUDE_CODE_EFFORT` (Leon's choice: Opus at
    medium). Missing binary (e.g. the Render cloud copy, which has
    neither Claude Code nor a login) reuses `MissingKeyError` so every
    route's existing friendly-error handling already covers it with zero
    other changes.
  - **Runtime provider choice** (`provider.py`): a storage-backed
    "llm_settings" document, checked before falling back to `.env`'s
    `LLM_PROVIDER` — lets the dashboard's own toggle switch providers
    instantly, no restart, no file edit.
  - **The connect/disconnect toggle** (Stock Searcher panel):
    `GET`/`POST /api/llm` plus a checkbox — "Use my Claude account for AI
    (Pro plan — Mac only)" — with a status line saying plainly where AI
    runs right now. Saved choice is shared storage, so the cloud copy
    shows it too (and gets the provider's own Mac-only message if an AI
    button is pressed there while it's on).
  - **Overnight market-hours analysis** (`scheduler.py`, extended to run
    TWO background helpers on the existing 60-second thread): up to
    three analysis runs a night while the US market is open, at three
    ADJUSTABLE times (`rules.yaml`'s `scheduler.analysis_times_et`
    defaults to 09:35/12:30/15:30 ET — just after open, mid-session, just
    before close; Leon edits the actual times from the dashboard, with a
    live Sydney-time hint next to each ET input). Gated hard on the
    active provider being `claude_code` — an unattended loop must never
    spend a key Leon toggled away from. If the Mac was asleep through
    more than one slot, only ONE catch-up run fires (on the freshest
    data), but every missed slot is marked caught up so it can't re-fire
    minutes later. `/api/run-analysis`'s universe-building (pulling in
    held-but-out-of-scope stocks for review) was factored into a shared
    helper so the manual Run button and the overnight scheduler can't
    drift apart.
  - **Price watches** (`dashboard/price_watches.py`, new): one overnight
    "tell me if this reaches $X tonight" alert per stock, set from its
    own ticker page — direction (rising to, or falling to, the level) is
    worked out automatically from the price at the moment it's saved.
    Checked once, at the overnight scheduler's chronological MIDDLE run
    (`scheduler.is_middle_slot`, correct even if Leon saves his three
    times out of order): a fired watch dedicates that run to just the
    triggered stock(s) with a real buy/sell verdict, labelled "price
    watch: …" in the run history; watches are one-shot, cleared right
    after the run acts on them.
  - **Correctness fix found and closed before it could bite**: the
    plan flagged, and this build confirmed, that `place_orders()`
    unconditionally cancelled EVERY pending order on every call,
    regardless of scope — a narrowly-scoped run (exactly what a
    price-watch-triggered run is) would have silently wiped out an
    unrelated stock's still-pending order from earlier in the night.
    `place_orders()` now takes an optional `analyzed` set; orders for
    symbols outside it are left untouched. A dedicated regression test
    proves an out-of-scope pending order survives a scoped run.
  - 76 new tests across 9 new/extended files, all offline (a fake
    `subprocess.run`, monkeypatched storage, a fake AI provider — no real
    `claude` process, no quota spent during the build). 210 tests total.
    The one live spend: a single ~5-token "Reply with exactly: OK" through
    the real CLI, confirming the whole path end-to-end.

- **Settings restyle, always-on Mac app, shared Neon database, and
  viewer mode** (2026-08-18/19, planned in PLAN-settings-ui.md and
  PLAN-always-on-and-viewer.md):
  - **Settings restyle** (M0): the ⚙ Analysis-settings modal became a
    proper settings page — iOS-style toggle switches, title+description
    rows, sectioned with hairline dividers. Pure front-end restyle, IDs
    and behaviour unchanged. Added a "Reset to default times" control for
    the overnight schedule (`times_et: null` reverts to rules.yaml) + test.
  - **Always-on via launchd** (M1): `~/Library/LaunchAgents/com.leon.vers-a.plist`
    (machine config, not in git) runs the app at login and restarts it on
    crash — no more manual Terminal command. New workflow rule in
    CLAUDE.md/AGENTS.md: restart after edits with `launchctl kickstart -k
    gui/$(id -u)/com.leon.vers-a`.
  - **Shared Neon database** (M2): one free cloud Postgres now backs BOTH
    the Mac and the Render copy (same `DATABASE_URL` on each), so the
    phone/cloud shows real live data instead of resetting.
    `migrate_to_neon.py` (one-off, re-runnable) copied all 14 documents up.
    **Bug caught during M2**: setting `DATABASE_URL` in `.env` exposed
    that tests importing `dashboard.app` leaked it into the whole pytest
    process (app.py calls `load_dotenv()` at import), so tests that
    monkeypatch `storage.DATA_DIR` were silently hitting the REAL
    database. Root cause was one layer down — `dotenv`'s `override=False`
    only skips keys already PRESENT, so deleting the var let a later
    in-test `load_dotenv()` re-import it. Fixed in `tests/conftest.py`
    (set it to empty string, autouse) + two regression tests; real data
    restored via the migration script.
  - **Viewer mode** (M3): `VIEWER_MODE=1` on Render only. Now that both
    copies share one database, the cloud copy is locked read-only — a
    `before_request` guard 403s ten money-spending/Mac-only routes before
    the view runs, and the matching controls are hidden via a
    `body.viewer-mode` CSS class (chosen over DOM-removal so app.js's
    render helpers can't throw on missing nodes; the 403 is the real
    enforcement). Still allowed on the viewer: viewing, price watches,
    watchlist edits, journal notes, the Fix bulletin. 15 tests.
  - 21 new tests total across the four milestones; 231 tests, all offline.

## Next
- Try the new toggle and overnight scheduler for a while and see how the
  subscription's shared usage window holds up under three Opus-medium
  runs a night — Leon's own call on whether to dial it back (fewer runs,
  Sonnet instead of Opus) once there's real data on the weekly limit.
- A track-record panel (+ 7am AEST email?) — the fill scheduler settles
  orders daily now, but nothing summarizes performance over time yet.
- Decide: feed news headlines into the batch analysis so bull/bear cases
  rest on more than momentum (costs a bit more per run).
- Try the Strategy Lab: write a strategy (or press Brainstorm), then Scan
  now to see whether current news matches it. Also try the Fix bulletin
  (right-edge tab), "settle orders daily", and now the overnight analysis
  + price watch toggles.

## How to run
```
cd ~/Vers-A-Stock-List
./venv/bin/python dashboard/app.py
# then open http://localhost:5001
```
