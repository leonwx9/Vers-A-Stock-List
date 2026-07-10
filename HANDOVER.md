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
2. **Run analysis** (Stock Searcher panel) — the AI debates every
   watchlisted stock, scores conviction, shortlists 5. Takes a minute or
   two. Each run also writes a dated audit file into `picks/`.
3. **Sync to shortlist** (Paper Portfolio panel) — the pretend $10,000
   mirrors the new shortlist: sells drops, sells anything down more than
   10% (stop-loss), buys the new picks. Every trade is logged. (Heads-up:
   removing a stock from ALL watchlists drops it from the next analysis,
   so the next full sync sells it.) If the last analysis was scoped to ONE
   watchlist, syncing only trades within that list — holdings the run
   never looked at are left alone (stop-loss still applies to everything).
4. **Scan EDGAR** (AI Pivot Scanner panel) — whenever you're curious.
   Finding *nothing* is normal; genuine small-cap non-tech AI pivots are
   rare, which is rather the point.
5. Click any ticker for its chart, statistics, news, and a "why this
   rating" deep dive (one AI request, then cached — press Refresh for a
   fresh one).

The portfolio graph grows one point per day the app is used — it needs
weeks of routine before it says anything meaningful.

## What it costs

- **AI requests** are the only cost: one analysis run ≈ 10 requests, a
  deep dive or scanner candidate ≈ 1 each. On OpenRouter you can watch
  spend at openrouter.ai → Activity. A few dollars a month at hobby usage.
- Prices (Yahoo) and filings (EDGAR) are free. Render and Tailscale are on
  free tiers.

## When something breaks

| Symptom | Likely cause | Fix |
|---|---|---|
| "API key" error in the app | key missing/typo in `.env` | fix `.env`, restart the app |
| Analysis fails mid-run | AI provider hiccup or credit ran out | check openrouter.ai, try again |
| "already running" when you press Run | another run is in progress (maybe from another tab/device) | wait for it — this guard protects your AI credit |
| Prices look stale | 5-minute cache | wait 5 min, reload |
| No news headlines on a ticker | Google News hiccup | harmless; try later |
| Scanner shows fewer results than expected | SEC throttled us (it retries politely) | run the scan again in a minute |
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
  per position, stop-loss %, shortlist size, scanner market-cap ceiling…
  each line is commented.
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

## Where the bodies are buried

- Secrets: `.env` (never committed) and Render's Environment tab.
- Saved runs & portfolio: `dashboard/data/` (gitignored, Mac only).
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
