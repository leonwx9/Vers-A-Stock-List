# PLAN — Lab review fixes, the fill scheduler, and the Fix bulletin board

Approved by Leon on 2026-07-12. Execute top to bottom. This plan follows a
Fable 5 review of the Strategy Lab build: four review fixes, a smarter
once-a-day scan guard, a new (free, AI-less) order-fill scheduler, and an
editable "Fix bulletin" panel.

## Process rules (same as every plan)

- Leon is a beginner learning by reading the code. Plain-English comments
  and docstrings, matching the house style already in the repo.
- **Never spend Leon's AI credit.** Nothing in this plan needs an AI call
  at all — if you find yourself about to make one, stop; something is wrong.
- Tests use fakes only (FakeProvider, monkeypatched storage.DATA_DIR,
  canned data) — no network, no real files outside tmp_path.
- Run the FULL test suite after each milestone. All 117 existing tests
  must stay green; add new ones as specified.
- Commit per milestone with a plain-English message ending in the
  Co-Authored-By line. Push at the end (the push auto-deploys Render).
- **Deleting this plan file**: do it with `git rm PLAN-fixes-scheduler-bulletin.md`
  inside the FINAL docs commit, and mention the deletion in that commit's
  message. (Last time a staged deletion got silently swept into an
  unrelated commit — don't repeat that.)

---

## M1 — The four review fixes

### M1.1 Confidence note must be visible on the setup card (phone included)

`renderLabSetups` in `dashboard/static/app.js` currently puts the AI's
one-sentence uncertainty explanation in the badge's `title` attribute — a
hover tooltip that can never appear on an iPhone. The honest-uncertainty
note is one of the Lab's non-negotiable guardrails, so it must be visible.

- Render `s.confidence.note` as a small always-visible line of text on the
  card (e.g. an italic/muted line directly under the card header, styled
  like the existing `.fine-print` or a new `.confidence-note` class in
  `style.css`). Keep it `esc()`d. Only render the line when the note is
  non-empty. Drop the `title` attribute or keep it — visible text is what
  matters.

### M1.2 Round-robin query derivation — no strategy left unscanned

`derive_queries` in `dashboard/strategy_lab/setup_scanner.py` currently
takes ALL of the newest strategy's tags, then the next strategy's, until
`max_queries` (8) is hit — so once the journal grows, the oldest
strategies contribute ZERO news searches and silently can never match.

- Change to round-robin: first tag of every strategy (in the order given),
  then every second tag, then every third… still deduping (case-insensitive,
  keep first spelling) and still capping at `max_queries`. Keep the
  name-as-fallback for untagged strategies. Keep it a pure function.
- Update the docstring to explain WHY round-robin (every strategy gets a
  voice before any strategy gets two).
- Tests (`tests/test_strategy_lab.py`): 3 strategies × 3 tags with cap 5
  → the result starts with each strategy's first tag; existing
  derive_queries tests updated if their expected order changes.

### M1.3 Show the daily auto-scan's results without a manual reload

When `GET /api/lab` kicks off the background daily scan, the page shows
"Running today's automatic scan in the background…" forever and never
displays the finished result.

- In `app.js`: when `data.daily_scan_running` is true, schedule follow-up
  checks (e.g. `setTimeout` at ~30 s and ~90 s) that fetch `/api/lab`
  again; if the returned `setups.run_at` differs from what's on screen
  (or setups was previously null), re-render via the existing render
  functions and replace the "running…" status with the normal "Last
  scan: …" line. If it's still not done after the last check, say so
  honestly ("still running — reload in a minute").
- Re-fetching `/api/lab` is free (it reads saved files; the once-a-day
  guard means it can't start a second scan).

### M1.4 The daily-scan checkbox must not lie when the server is unreachable

The `labDailyToggle` change handler has no `try/catch` — if the fetch
itself fails, the checkbox stays flipped even though nothing was saved
(every other Lab button already handles this case).

- Wrap the handler in `try/catch` like the scan/brainstorm buttons: on
  ANY failure (network error or non-ok JSON), revert the checkbox and put
  a "⚠ Could not save the setting — …" message in `lab-scan-status`.

Commit M1.

---

## M2 — Smarter once-a-day scan guard ("already scanned today = done")

Today's guard only tracks the AUTO scan date, so: (a) the cloud's two
worker processes can each fire one auto scan, and (b) an auto scan fires
even if Leon already pressed "Scan now" earlier the same day. Leon's
requested rule: **if any scan has already happened today, the auto scan
must not run.**

- In `api_lab` (`dashboard/app.py`), before starting the background
  thread: load the latest saved scan (`setup_scanner.load_latest()`). If
  it exists and its `run_at` date equals today, just set
  `last_auto_scan_date = today`, save settings, and do NOT start a scan
  (and don't report `daily_scan_running`). A manual scan now counts as
  "today's scan".
- Add a second cheap re-check INSIDE the background thread, right after
  acquiring `lab_lock`: re-load the latest scan; if one from today has
  appeared in the meantime (the other cloud worker won the race), release
  and return without scanning. Comment honestly: this shrinks the
  two-worker race window to near zero but a perfectly simultaneous pair
  could in theory still double-scan (~2¢, harmless — second result
  overwrites an identical first).
- Extract the "should the auto scan fire?" decision into a small pure
  function (e.g. `should_auto_scan(settings, latest, today)` in
  `setup_scanner.py`) so it can be unit-tested without Flask.
- Tests: disabled → no; already auto-ran today → no; manual scan already
  today → no; enabled + no scan today → yes.

Commit M2.

---

## M3 — The order-fill scheduler (free — no AI involved)

Right now pending orders only settle when someone opens the dashboard.
Leon wants a switchable scheduler that settles them automatically.
Decisions made with Leon:

- **Scope: order fills ONLY.** No AI analysis, no Lab scan — zero AI cost.
  It also records the day's portfolio-graph point (a nice side effect:
  the graph grows daily even on days Leon doesn't open the app).
- **Lives inside the Mac app**: a background thread started when
  `dashboard/app.py` runs directly. If the app isn't running, nothing
  happens (and nothing is owed).
- **Fires at 8:00am Sydney time** — always after the US close, year-round.
- **Off by default**, toggled from the dashboard.

Implementation:

- `rules.yaml`: add a commented `scheduler:` section with
  `fill_hour_sydney: 8` (the hour, Sydney time, after which the daily
  fill-run becomes due).
- New settings document `scheduler` via `get_doc("scheduler")`:
  `{"enabled": False, "last_run_date": None}`. Load/save helpers can live
  in a tiny new module `dashboard/scheduler.py` — keep it out of
  `engine.py` (the engine shouldn't know clocks exist).
- `dashboard/scheduler.py`:
  - `should_run(settings, now)` — PURE function: enabled, AND `now`
    (Sydney time, via `zoneinfo.ZoneInfo("Australia/Sydney")`) is at or
    past the configured hour, AND `last_run_date` != today's Sydney date.
    Using "at or past 8am" (not "exactly 8am") means an app started at
    3pm still catches up that day.
  - `run_once(portfolio)` — calls `portfolio.process_fills()` then
    `portfolio.snapshot()` (settles due orders + records the graph
    point), then saves `last_run_date`. Set `last_run_date` BEFORE the
    work, same reasoning as the Lab's daily scan; a failed run just
    means "try again tomorrow" (the next dashboard open settles fills
    anyway — this scheduler is a convenience, not the only path).
  - `start_scheduler_thread(portfolio)` — daemon thread looping every
    ~60 s: reload settings, check `should_run`, act. Swallow-and-continue
    on errors (comment why: a flaky price fetch at 8am must not kill the
    thread for the rest of the app's life).
- Start the thread in `app.py`'s `if __name__ == "__main__":` block only
  (so the Mac gets it; Render/gunicorn deliberately does not — that was
  Leon's choice, and it also sidesteps the two-worker question entirely).
  Guard against the debug reloader's double process: when
  `DASHBOARD_DEBUG=1`, only start the thread in the reloader child
  (`os.environ.get("WERKZEUG_RUN_MAIN") == "true"`).
- Concurrency note (comment, no machinery): the thread's `process_fills`
  can overlap a browser request's — identical inputs produce identical
  fills and whole-document saves, the same overlap two browser tabs can
  already cause today.
- Routes: fold current scheduler settings into the `/api/portfolio`
  response (read the doc in the route — don't touch `engine.py`), and add
  `POST /api/scheduler` accepting `{"enabled": bool}`.
- UI: a `.checkbox-label` toggle in the Paper Portfolio panel, worded
  like: "Settle orders daily at 8am (while the app is running) — free, no
  AI". Same error-handling pattern as M1.4 (revert on failure). Show
  "Last auto-settle: <date>" when available.
- Tests (`tests/test_scheduler.py`, all offline with a frozen/fake `now`):
  `should_run` — disabled → no; before 8am Sydney → no; already ran today
  → no; after 8am + not yet run → yes. `run_once` with the existing fake
  price source — settles a due order, records a history point, stamps
  `last_run_date`.

Commit M3.

---

## M4 — The "Fix bulletin" board (collapsible, right side, Leon-editable)

A small collapsible panel pinned to the right side of the dashboard where
Leon keeps his own list of future work items. Plain-text with three
formatting powers: **bold**, underline, and dot points.

- **Storage**: new document `bulletin` → `{"text": "..."}`. When empty,
  seed it with the known future items (this seed is the whole point —
  don't skip it):
  - The scan-history file grows forever — add a size cap someday.
  - News headlines are outside text: malicious wording could steer the
    AI's phrasing (contained by the citation/counter-case guardrails,
    but worth remembering).
  - Duplicate source links appear if the AI cites the same headline twice.
  - The 8am scheduler only fires while the Mac app is running — revisit
    (launchd or cloud cron) if that ever isn't enough.
- **Routes**: `GET /api/bulletin` (returns text, seeding on first load)
  and `POST /api/bulletin` `{"text": str}` (length-cap it, e.g. 20k
  chars, with a friendly 400).
- **Markers → display** (view mode), in this exact order to stay
  XSS-safe: `esc()` the WHOLE text FIRST, then apply markers:
  `**bold**` → `<strong>`, `_underline_` → `<u>`, and consecutive lines
  starting `- ` become a `<ul>` of `<li>`. Other lines are paragraphs;
  blank lines separate them. Keep the renderer a small pure JS function.
- **Edit mode**: an Edit button swaps the rendered view for a `<textarea>`
  with a mini toolbar — **B** wraps the current selection in `**…**`,
  **U** wraps it in `_…_`, **•** inserts `- ` at the start of the current
  line — plus Save (POST, re-render, handle failure like M1.4) and Cancel.
  Use `selectionStart`/`selectionEnd` on the textarea; no `contenteditable`,
  no `execCommand`.
- **Panel behaviour**: fixed to the right edge on wide screens with a
  header ("Fix bulletin") that collapses/expands it; collapsed state in
  `localStorage` (start collapsed on first visit so it never ambushes the
  layout). On narrow/phone screens it must not cover content — either
  slide over with a high z-index and an obvious close, or fall into the
  normal page flow; match the project's existing responsive patterns.
- Tests: the two routes' behaviour is app-level; test the seeding + save
  round-trip at whatever level the suite already tests docs (a
  `load_bulletin()` helper with monkeypatched storage is fine). The JS
  renderer has no test harness — verify by hand: bold, underline,
  bullets, a line containing `<script>` stays inert text.

Commit M4.

---

## M5 — Docs, verification, cleanup

- `README.md`: mention the scheduler setting and the bulletin panel
  briefly; update the test count.
- `HANDOVER.md`:
  - Clarify in the Lab section that "once a day" means "the first time
    the dashboard is opened each day" (no scheduler for the SCAN — only
    fills are scheduled), and that a manual scan counts as the day's scan.
  - Add the fill scheduler to the routine/costs sections (free; only
    while the app runs; off by default).
  - One line on the Fix bulletin (what it's for, where it saves).
- `PROGRESS.md`: dated entry for this round; refresh the "Next" list
  (scan-history cap and headline-steering now live ON the bulletin).
- Full test suite green. Live check WITHOUT AI spend: start the server,
  curl `/api/bulletin` (seeded), POST a text edit and read it back, POST
  the scheduler toggle on→off, confirm `/api/lab` still 200, and leave
  all real data as found (bulletin seed text may remain — it's meant to).
- Final commit includes the docs AND `git rm PLAN-fixes-scheduler-bulletin.md`;
  push everything.

## Explicitly OUT of scope (Leon's calls)

- Deduping repeated source links on a setup card — Leon doesn't care.
- Capping the scan-history file — future item, lives on the bulletin.
- Any scheduled AI call (analysis or Lab scan) — fills only, by choice.
