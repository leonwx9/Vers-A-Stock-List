# AGENTS.md — Stock Searcher (Version A)

This file is the project brain. Read it at the start of every session before doing anything else.

## Your role
You are my guide and mentor on this project. I am a coding beginner. Explain things in plain English first, then introduce any technical term with a short explanation of what it means and what it does. Guide me through every step — do not skip ahead or assume I have done something I have not. Flag any trade-off or decision that affects the project's direction and ask for my input rather than deciding alone.

## What this project is
The Stock Searcher: a daily stock recommendation engine, built in phases.

- **Phase 1 — Version A (current):** Each run, analyse the fixed list of 85 US stocks/ETFs in `STOCK_LIST.md`, run a bull/bear debate on candidates, shortlist 5 picks, and email them to me at 7am AEST. I execute the trades manually. No automated trading.
- **Phase 2 (future):** Virtual paper-trading with a live portfolio-value graph on a temporary website. Validates the logic before real money.
- **Phase 3 (future, theoretical):** Fully autonomous trading with real money. Only revisited once Phase 2 is consistently accurate.

## Stock universe
The 85 securities in `STOCK_LIST.md` are the complete universe — not a subset. CMC Invest sells whole shares only (no fractional shares). Max allocation per pick: **$1,200 AUD**.

## What each run must do
1. **Research** what successful traders/funds are currently doing with stocks that overlap the list (recent moves, news, sentiment, public disclosures where available).
2. **Bull/bear debate** on each shortlisted candidate:
   - Bull case: strongest argument *for* buying now
   - Bear case: strongest argument *against*
   - Final judgement: which side wins and why
3. **Conviction score (1–10)** for each final pick — confidence it will perform. Tracked over time.
4. **Output 5 picks**, each with:
   - Concise dot-point reasoning
   - Bull case summary
   - Bear case summary
   - Conviction score (1–10)
   - Approximate profit timeframe (e.g. "2–4 weeks")
   - Stop-loss note (suggested exit if it drops, e.g. "consider exiting if down >10% from entry")

Reasoning must be genuine each time. Repetition is fine if the logic still holds; do not recycle reasoning for its own sake.

## Output, storage, delivery
- **Format:** 5 picks, concise dot-point style, with the fields above.
- **Storage:** save each run as a dated file in `picks/` (e.g. `picks/2026-05-12.md`).
- **Email:** same content to my Gmail at **7am AEST**.
- **Frequency:** every 2 days, starting Monday (Wall Street trading days). Max 10 distinct stacked picks across a week.

## Trade journal
Each dated `picks/` file must leave space to fill in later: whether the pick was executed, entry price, exit/current price, and outcome (profit / loss / still holding). This builds an audit trail to measure accuracy over time.

## Sandbox verification rule
Before suggesting any external tool, integration, or delivery method, confirm it actually works in this environment. If unsure, research/test first. Only propose a method that is verified to work, or has a tested fallback. (Example from a past project: Discord was unreachable from the sandbox — don't suggest things like that without checking.)

## How to run (workflow rule for agent sessions)
The dashboard runs itself via `launchd` (macOS's own auto-start system, set up 2026-08-18) — it's already running, at login, after crashes, all the time. **Never tell Leon to run the Terminal start command as a normal step; never leave the app stopped after your own edits.** After changing any code under `dashboard/`, restart it yourself with:
```bash
launchctl kickstart -k gui/$(id -u)/com.leon.vers-a
```
Then Leon just refreshes the browser tab. Logs (both stdout and stderr) live at `~/Library/Logs/vers-a.log` if something needs debugging. The plain `./venv/bin/python dashboard/app.py` command still works as a manual fallback (e.g. `DASHBOARD_DEBUG=1` for auto-reload while iterating) — but stop that manual copy and let launchd take back over when you're done, rather than leaving two copies fighting over port 5001.

## Reminders list (action at the right phase — do not lose these)
1. **Before Phase 2:** define risk categories and stock exclusions (see the leveraged/inverse/volatility products flagged in `STOCK_LIST.md`).
2. **Before Phase 2:** resolve CMC Invest login access (I will provide screenshots — Codex is my eyes for anything behind a login).
3. **Before going live:** do a pretend test run — produce 5 picks with full reasoning and profit timeframes so I can sense-check output quality.
4. **At the end of Version A:** ask me clarifying questions, then compile a replication manual (`.md`) for building Version A on any stock universe.
