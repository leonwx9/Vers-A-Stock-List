# HANDOVER — owning Vers A in plain English

This is the guide to *living with* the dashboard: what you have, how to use
it day to day, what to do when something breaks, and how to change things
yourself. (For install commands and settings, see README.md.)

## What you have

One dashboard, three doors into it:

| Door | When to use it | Remembers data? |
|---|---|---|
| `http://localhost:5001` on the Mac | building & tinkering | ✅ yes — the permanent record |
| Tailscale icon on your iPhone | on the couch, Mac awake | ✅ same data as the Mac |
| `https://vers-a.onrender.com` | anywhere, Mac off | ⚠️ resets when the free server restarts |

The Mac copy is the source of truth. The cloud copy is a viewer that
occasionally forgets; that's the price of the free tier, and it's fine —
your portfolio history and picks live on the Mac (and in git).

## The routine

1. **Curate your watchlists** (Watchlists panel) — search any US stock
   (free, no AI cost) and add it to a list; make as many lists as you like.
   Only watchlisted stocks get the paid AI treatment.
2. **Run analysis** (Stock Searcher panel) — pick a watchlist (or "All
   watchlists") from the dropdown next to the button first, THEN press
   Run. The AI debates every stock in that scope, scores conviction, and
   shortlists 5 — but it ALSO reviews every stock the portfolio currently
   holds for HOLD or SELL, even ones outside today's chosen scope, so a
   position is never skipped just because you picked a narrower list.
   Takes a minute or two. Each run writes a dated audit file into `picks/`
   and places fresh orders in the Paper Portfolio (see below) — replacing
   whatever was still pending from the last run.
3. **Nothing to press for the portfolio.** There is no "Sync" button any
   more. An analysis run plans a BUY (at the AI's own entry price, with
   its own stop-loss %) for each fresh pick, and a SELL for any holding
   the review said to part with. Those orders then fill **on their own**:
   every time you open the dashboard, it checks real trading sessions
   since the order was placed and fills it the moment the market actually
   reaches the planned price (or sells at the next session's open). Every
   holding is also watched against its own stop-loss automatically. Look
   at **Pending orders** to see what's still waiting, and **Sell
   decisions** to read the AI's reasoning for every HOLD/SELL call.
4. **Scan EDGAR** (Event Scanner panel → AI Pivots view) — whenever you're
   curious. Finding *nothing* is normal; genuine small-cap non-tech AI
   pivots are rare, which is rather the point.
5. **Strategy Lab** (same panel → Strategy Lab view, a segmented toggle
   next to the header) — write down event-timing patterns you notice
   ("when X happens, Y sector tends to move"): a name, plain-English
   description, what would make you consider buying, what would make you
   consider selling, affected sectors, risk notes, tags. Press
   **Brainstorm ideas** any time you want the AI to suggest more (always
   badged AI, never mistaken for your own). Press **Scan now** whenever
   you're curious whether current news matches something in your
   journal — every match shows what's happening, its sources, the bull
   case, the counter-case, the risks, and an honest confidence level.
   This is purely for research; nothing here can buy or sell anything,
   pretend or real. "Once a day" (the optional auto-scan toggle) means
   the FIRST time you open the dashboard each day — there's no scheduler
   for this part, so if you never open the app that day, no scan
   happens; and pressing **Scan now** yourself any time that day counts
   as the day's scan too, so the automatic one won't also fire on top of it.
6. Click any ticker for its chart, statistics, news, and a "why this
   rating" deep dive (one AI request, then cached — press Refresh for a
   fresh one).
7. **Settle orders daily** (checkbox in the Paper Portfolio panel, off by
   default) — if you turn this on, pending orders settle themselves at
   8am Sydney time even if you never open the dashboard that day, as
   long as the Mac app itself is running. No AI cost — it's the exact
   same free settling step every page view already does, just guaranteed
   to happen once a day on its own.
8. **Fix bulletin** (the tab pinned to the right edge of the page) — your
   own running list of things to fix or revisit later. Press the tab to
   open it, Edit to change it; the B/U/• buttons insert simple markers
   (`**bold**`, `_underline_`, a dot point) into your own plain text. It
   starts with a few housekeeping notes from the Strategy Lab's build —
   edit or delete them like anything else you write there.

The portfolio graph grows one point per day the app is used — it needs
weeks of routine before it says anything meaningful. Because you check the
dashboard from Sydney, US market hours have always finished by the time
you look — so "check what's happened since I last opened it" is exactly
the same thing a real broker would tell you the next morning.

## What it costs

- **AI requests** are the only cost: one analysis run ≈ 10 requests, a
  deep dive or scanner candidate ≈ 1 each, a Strategy Lab **Brainstorm**
  or **Scan now** ≈ 1 request each (roughly 1-2¢ apiece). On OpenRouter
  you can watch spend at openrouter.ai → Activity. A few dollars a month
  at hobby usage. The Lab's optional once-a-day auto-scan is OFF by
  default — turning it on adds ≈1-2¢/day, nothing until you flip it on.
- Prices (Yahoo), filings (EDGAR), and news headlines are free. Render and
  Tailscale are on free tiers.
- The daily **order-fill scheduler** and the **Fix bulletin** cost nothing
  — neither one ever calls the AI.

## When something breaks

| Symptom | Likely cause | Fix |
|---|---|---|
| "API key" error in the app | key missing/typo in `.env` | fix `.env`, restart the app |
| Analysis fails mid-run | AI provider hiccup or credit ran out | check openrouter.ai, try again |
| "already running" when you press Run | another run is in progress (maybe from another tab/device) | wait for it — this guard protects your AI credit |
| An order sits "pending" for days | its planned price was never reached | normal — either wait, or run a fresh analysis to replace it with new thinking |
| A pick shows "Skipped (bad price)" in Pending orders | the AI's entry price failed the sanity check (rare — a formatting slip) | no order was placed for it this run; it may get a fresh entry price next run |
| Prices look stale | 5-minute cache | wait 5 min, reload |
| No news headlines on a ticker | Google News hiccup | harmless; try later |
| Scanner shows fewer results than expected | SEC throttled us (it retries politely) | run the scan again in a minute |
| Strategy Lab scan finds nothing | normal and honest — genuine event-timing setups are rare on most days | not a bug; try again another day, or after big news |
| A Lab strategy suggestion looks incomplete/never appears | the AI's suggestion was missing a required field (rare) | dropped automatically, not saved — press Brainstorm again |
| "Settle orders daily" didn't fill something overnight | the Mac app wasn't running at 8am that day | no harm — it settles the moment you next open the dashboard, or automatically the next day the app is running |
| Fix bulletin edit didn't save | a network hiccup while pressing Save | the status line under the note says so — try Save again |
| Phone can't reach the Mac copy | Mac asleep or Tailscale off | wake the Mac, check the Tailscale menu-bar icon |
| Cloud copy slow to load | free server waking up | wait ~50 s, it's normal |
| Cloud copy forgot the portfolio | free server restarted | expected — the Mac copy remembers |
| Changed the code but nothing changed | server needs a real restart | `pkill -f dashboard/app.py`, start it again |

If the page shows a long technical error, read the last line first — it
usually says what's wrong in nearly-plain English.

## Changing things yourself (no programming needed)

- **Add/remove a stock**: the search box and watchlist chips in the
  dashboard — no files involved. Risky products carry flags (`leveraged` /
  `inverse` / `volatility`) in the catalogue (`dashboard/data/`
  `watchlists.json`) so the portfolio refuses to buy them; newly-added
  stocks start unflagged.
- **Trading rules**: `dashboard/config/rules.yaml` — starting cash, max $
  per position, shortlist size, scanner market-cap ceiling… each line is
  commented. `stop_loss_pct` is only the FALLBACK: the AI picks its own
  stop-loss per stock (tailored to how volatile it is), clamped into
  `stop_loss_pct_min`–`_max`.
- **Switch AI provider**: in `.env`, set `LLM_PROVIDER=anthropic` and fill
  `ANTHROPIC_API_KEY`. Two lines, nothing else.
- **Work offline**: in `rules.yaml`, set `data.price_source: sample`.
- **Dark mode**: the ☾ button in the header. Each device remembers its own
  choice.
- **Change the cloud password**: Render dashboard → vers-a → Environment →
  `DASHBOARD_PASSWORD`, then "Save & deploy".

## Publishing changes

Work happens on the `dashboard` branch. Any push to GitHub redeploys the
cloud copy automatically in a few minutes:

```bash
git add -A && git commit -m "what changed" && git push
```

## Honest limitations (by design, not by accident)

- **No real trading, ever.** The portfolio is pretend money for measuring
  whether the picks are any good.
- Market cap and P/E on ticker pages show "—": the free price feed has no
  fundamentals. A paid/fuller data source is a future upgrade.
- The AI's fundamental knowledge can be months out of date; that's why deep
  dives must cite real fetched headlines for sentiment claims, and say so
  when they can't.
- Conviction scores are opinions, not predictions. The `picks/` audit trail
  exists precisely so you can check, months later, whether they were worth
  listening to.
- **Orders settle when you open the dashboard, or once a day if you've
  turned the scheduler on** — either way, the check only ever looks at
  FINISHED trading sessions, never a still-forming one, so opening the
  app mid-session (if you ever travel, say) can't fill an order against a
  half-finished day. The scheduler only runs inside the Mac app's own
  process — it can't fire if the app isn't running, and it never runs on
  the cloud copy at all.
- **The Strategy Lab is information-only, on purpose.** It cannot place
  an order — pretend or real — no matter what a scan finds; the module is
  built so it never even imports the code that could. A "setup" is a
  starting point for your own research, not a signal.

## Where the bodies are buried

- Secrets: `.env` (never committed) and Render's Environment tab.
- Saved runs, portfolio, Strategy Lab journal/scans, the scheduler's own
  setting, and the Fix bulletin's text: all in `dashboard/data/`
  (gitignored, Mac only — or the cloud database if DATABASE_URL is set).
- Audit trail of every analysis: `picks/` (committed).
- Build history & decisions: `PROGRESS.md`; project rules: `CLAUDE.md`.

## What's next, when you're ready

The architecture was built so these are additions, not rewrites:
- **Bigger universe** (all of Wall Street): a better `universe.yaml`
  generator + the same code.
- **Crypto**: a new `type: crypto` in the universe + a crypto PriceSource.
- **Fundamentals** (market cap, P/E): one new data-source class.
- **Cloud persistence**: Render's paid disk, if the cloud copy should ever
  become the permanent record.
