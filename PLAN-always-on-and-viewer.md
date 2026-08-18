# PLAN — Always-on Mac app + phone viewer via a shared cloud database

**Status:** drafted 2026-08-17 from Leon's three decisions (launchd
auto-start; Neon shared DB — guided setup; viewer mode that blocks AI
spend but allows price watches & watchlist edits). Awaiting Leon's
approval. Any model may execute; each milestone is self-contained.

## What Leon wants (plain English)

1. **Never retype the Terminal commands again.** The dashboard should
   just *be running* on the Mac — after login, after crashes, after
   Claude edits code — so checking live changes means refreshing the
   browser, nothing more.
2. **See overnight results on the phone, from anywhere.** The Render
   copy should show the SAME analysis/portfolio the Mac produced — but
   as a *viewer*: nothing on it can spend AI money. Setting price
   watches and curating watchlists from the phone IS allowed (they're
   free, and the Mac's overnight run honours a watch set from bed).

## Verified foundations (checked, not assumed)

- `dashboard/storage.py` already speaks Postgres when `DATABASE_URL` is
  set ([storage.py:105](dashboard/storage.py#L105)); `psycopg2-binary`
  is pinned in requirements.txt. Neon is just "a free Postgres" — no new
  code concept. (Fallback if Neon signup misbehaves: Supabase, same
  connection-string idea.)
- `launchd` is macOS's native keep-alive system — no new software.
- render.yaml + auto-deploy on push to `dashboard` already work.

## Milestones

### M0 — Ship the pending UI work
Leon eyeballs the restyled ⚙ modal once more (reset button, hidden
section behaviour). Then: commit the current working tree (modal
restyle + reset-times route + tests), `git rm PLAN-settings-ui.md`
(executed), push. Render redeploys; nothing else changes yet.

### M1 — launchd: the app runs itself
- Write `~/Library/LaunchAgents/com.leon.vers-a.plist` (NOT in the
  repo — it's machine config; a copy of its contents goes in HANDOVER):
  - `ProgramArguments`: `/Users/leonwu/Vers-A-Stock-List/venv/bin/python
    dashboard/app.py`
  - `WorkingDirectory`: `/Users/leonwu/Vers-A-Stock-List` (so `.env`
    and relative paths resolve)
  - `RunAtLoad` + `KeepAlive`: true — starts at login, restarts on exit
  - Logs → `~/Library/Logs/vers-a.log` (both stdout and stderr)
- Load it: `launchctl bootstrap gui/$(id -u) <plist>`; verify the app
  answers on :5001 without any Terminal window.
- **New workflow rule for Claude sessions** (record in CLAUDE.md §
  "How to run"): after code changes, restart with
  `launchctl kickstart -k gui/$(id -u)/com.leon.vers-a` — Leon just
  refreshes the tab. Never leave the app stopped.
- Normal (non-debug) mode stays: phone on Tailscale/home Wi-Fi can
  still reach the Mac copy; the overnight scheduler thread now runs
  whenever the Mac is awake, automatically.
- Docs: HANDOVER "keeping it running" section rewritten (replaces the
  bare Terminal instructions as the primary path; Terminal stays as
  the fallback).

### M2 — Neon: one database both copies share
- **Leon's part (guided, ~5 min):** create free account at neon.tech
  (no card), create a project (pick the Sydney/ap-southeast-2 region if
  offered), copy the connection string (`postgresql://…sslmode=require`).
  It's a secret: it goes ONLY into the Mac's `.env` and Render's
  Environment tab — never into git.
- **Migration (one-off script, run once, kept in repo for the record):**
  enumerate every saved document in `dashboard/data/` (watchlists,
  portfolio, analysis latest + history, deep-dive caches, scanner
  latest, lab journal/scans/settings, scheduler + overnight settings,
  llm_settings if present, price watches, bulletin, picks index) and
  write each through the storage layer with `DATABASE_URL` set.
  IMPORTANT implementation check: `WatchlistStore` / `PaperPortfolio`
  take `state_path` args — verify they route through `storage.get_doc`
  when `DATABASE_URL` is set (README says so; confirm in code before
  trusting) and migrate accordingly.
- Set `DATABASE_URL` in the Mac's `.env`; restart; verify the dashboard
  reads/writes the DB (edit a watchlist, see it in the DB, files in
  `dashboard/data/` untouched from that moment = stale backup — note
  this in HANDOVER's "where the bodies are buried").
- Leon pastes the same `DATABASE_URL` into Render → Save & deploy.
  Verify the cloud copy now shows the Mac's real portfolio/analysis.
- Caveats to record: Render free tier still sleeps (~50s wake);
  `picks/*.md` audit files remain Mac-only (they're git files, not DB).

### M3 — Viewer mode on Render
- New env switch `VIEWER_MODE=1`, set ONLY on Render.
- **Same UI, not a stripped-down mobile page — Leon confirmed this
  explicitly (2026-08-17).** The Mac and the viewer render the EXACT
  SAME templates and the EXACT SAME `style.css` — same layout, same
  panels, same navigation, same look in light/dark mode. Nothing is
  redesigned or simplified for viewer mode. The ONLY difference: a
  handful of specific AI-spending controls (Run analysis button, Scan
  button, Brainstorm button, deep-dive Refresh, the AI-provider/
  overnight toggles) are absent from the DOM — not greyed out, not
  disabled-look, genuinely not rendered — via one `{% if not
  viewer_mode %}` guard per control in the existing templates. No new
  template files, no separate "mobile.html", no CSS fork.
- **Server-side enforcement** (belt and braces — not just hidden
  buttons): when on, these return 403 with a friendly message:
  - `/api/run-analysis` (AI spend)
  - the AI-pivot scanner run route (AI spend)
  - Strategy Lab brainstorm + scan routes (AI spend)
  - deep-dive generate/refresh (AI spend; cached deep dives still VIEW)
  - `POST /api/llm` and `POST /api/overnight` (these now steer the
    MAC's spending through the shared DB — Mac-only decisions)
  - portfolio reset (destructive)
- **Still allowed:** every GET/view; price watch set/clear; watchlist
  create/rename/delete/add/remove; Strategy Lab journal add/edit/delete
  (free, Leon's own notes); Fix bulletin save. — Leon may veto any of
  these at review.
- **UI:** Flask passes the flag into templates; JS hides the blocked
  buttons/toggles entirely on the viewer (no dead controls). The ⚙
  modal on the viewer shows watches (+ a note that AI/overnight
  settings live on the Mac).
- **Tests (all offline, monkeypatched env):** blocked routes 403 in
  viewer mode and still 200 without it; watch set/clear still works in
  viewer mode; served HTML omits the Run button when the flag is on.
- Leon sets `VIEWER_MODE=1` in Render's Environment tab.

### M4 — Docs, verify live, close out
- README (.env table: `DATABASE_URL` now "the thing that makes the
  phone viewer work", `VIEWER_MODE`), HANDOVER (three-doors table
  rewritten: Mac = full control, always running; phone/Render = live
  viewer of the same data), PROGRESS entry.
- Live verification: phone (or curl with the password) against
  vers-a.onrender.com — sees the Mac's latest analysis; run-analysis
  returns 403; setting a watch from the viewer appears on the Mac.
- Delete this plan file in the final commit; push.

## Cost / safety notes
- Neon free tier: far more than enough for these small JSON documents.
  No card, no spend.
- No new AI cost anywhere in this plan. Viewer mode strictly *reduces*
  the ways money can be spent.
- The shared DB means the phone could previously-unthinkable things
  (e.g. flip the Mac's AI provider) — that's exactly why `POST
  /api/llm` / `/api/overnight` are blocked on the viewer.
- launchd only runs while the Mac is awake — unchanged from today; the
  caffeinate / Energy-settings advice in HANDOVER still applies for
  overnight runs.
