# PLAN — AI through Leon's Claude account, with a connect/disconnect toggle

Status: Approved by Leon on 2026-08-14. Execute top to bottom.

## The facts this plan is built on (read first — they shape everything)

Fable 5 verified all of this live on Leon's Mac on 2026-08-14:

1. **A Claude Pro subscription is not an API credit pool.** API keys
   (Anthropic Console) and OpenRouter keys bill their own separate credit
   balances. There is no key that makes the app's normal HTTP calls bill a
   Pro plan — that connection doesn't exist, from any provider.
2. **The one legitimate bridge is Claude Code.** Pro includes Claude Code,
   and its command line has a "headless" mode: `claude -p "prompt"` answers
   one prompt and exits, billing Leon's subscription. Verified working here:
   Claude Code v2.1.185 at `/Users/leonwu/.local/bin/claude`, JSON output
   parsed cleanly, no API key involved (checked the environment).
3. **Therefore this only works on the Mac.** The Render cloud copy has no
   Claude Code and no login, and copying account credentials to a server is
   neither supported nor allowed. On the cloud, AI buttons must show a
   friendly "AI runs on the Mac copy" message. Everything non-AI (prices,
   portfolio, watchlists, bulletin) keeps working there.
4. **Pro limits are shared with claude.ai chat** — roughly a 5-hour rolling
   window plus weekly caps. One analysis run ≈ 10 requests; a deep dive,
   Lab scan, or scanner candidate ≈ 1 each. A full run is a real bite out
   of a 5-hour window. That is exactly why Leon asked for the toggle: turn
   the dashboard OFF his account when he needs his chat quota.
5. **Leon's account serves both Sonnet and Opus headless** (verified:
   `--model sonnet` → claude-sonnet-4-6, `--model opus` → claude-opus-4-8,
   and `--effort medium` is accepted). Leon's choice: **Opus at medium
   effort**. Honest cost note: on a subscription, Opus drains the shared
   usage window several times faster than Sonnet — the toggle and the
   overnight timing are how Leon manages that, and that's his call.
   (There is no "Opus 5" — the current Opus is 4.8; the 5-generation
   models are Fable 5 and Sonnet 5, which Claude Code doesn't serve for
   this. What the app gets is claude-opus-4-8.)

## Process rules (same as every plan)

- Leon is a beginner learning by reading the code. Plain-English comments
  and docstrings, matching the house style.
- **Never spend during the build.** All tests use fakes (a fake
  `subprocess.run`, monkeypatched `storage.DATA_DIR`). The ONE live check
  is in M4 and costs a single ~5-token reply on Leon's plan.
- **Never edit `.env`** (Leon's secrets file). Only `.env.example`.
- Run the FULL test suite after each milestone; all 134+ existing tests
  stay green. Commit per milestone, plain-English message, ending with the
  Co-Authored-By line. Push at the end (auto-deploys Render).
- Delete this plan with `git rm PLAN-claude-account-provider.md` inside the
  FINAL docs commit, and say so in that commit's message.

---

## M1 — The Claude-account provider

New file `dashboard/llm/claude_code_provider.py` with the same one-method
interface the other two providers have (`complete(system, user,
max_tokens)`), so nothing else in the app changes:

- Build the command:
  `claude -p --system-prompt <system> --model <model> --effort <level>
  --output-format json --disallowedTools "*"`
  - The USER prompt goes in via **stdin** (not argv — analysis prompts are
    big and argv has a size limit).
  - `--disallowedTools "*"`: the app wants a plain text completion; Claude
    Code must not wander off running tools.
  - Model from env `CLAUDE_CODE_MODEL` (default `sonnet`), effort from env
    `CLAUDE_CODE_EFFORT` (default `medium`; omit the flag when unset).
    Leon will set `CLAUDE_CODE_MODEL=opus` — both values verified working
    on his account on 2026-08-14.
  - `subprocess.run(..., capture_output=True, timeout=300)` — generous,
    because Opus at medium can think for a while on a 10-ticker batch.
- Parse stdout as JSON; keep the parsing in a pure function
  (`parse_cli_response(text)`) so tests can feed canned output:
  - success → return the `result` field (the reply text);
  - `is_error: true` → raise with the CLI's own message (this is how rate
    limits surface: "you've hit your limit — try again at ...");
  - missing/garbled JSON → raise with the first 200 chars.
- Friendly failures, matching MissingKeyError's spirit:
  - `FileNotFoundError` (no `claude` binary — e.g. on Render) →
    "Your Claude account can only be used on the Mac, where Claude Code is
    installed and logged in. On the cloud copy, switch the toggle to the
    OpenRouter key or use the Mac."
  - timeout → clear message naming the 300s limit.
- `max_tokens` is accepted and ignored (the CLI governs its own output
  size) — say so honestly in a comment.
- Note in a comment: the analysis pool runs up to `max_workers` (3) CLI
  processes at once; that is fine, they are independent.

Tests (`tests/test_llm_providers.py`, new): parse success / is_error /
garbage; a monkeypatched `subprocess.run` proving the command shape
(stdin used, `--disallowedTools` present) and the FileNotFoundError
message. No real subprocess anywhere.

Commit M1.

## M2 — Runtime provider choice (no .env edit needed to switch)

- New storage document `llm_settings`: `{"provider": null}`. `null` means
  "no runtime choice made — fall back to `.env` `LLM_PROVIDER`", so
  existing behaviour is unchanged until Leon first uses the toggle.
- `dashboard/llm/provider.py` → `get_provider()`:
  1. read `get_doc("llm_settings")`; if its `provider` is set, use it;
  2. else fall back to env `LLM_PROVIDER` as today;
  3. `claude_code` → the new provider; `openrouter`/`anthropic` unchanged;
     unknown → the existing clear error.
- Add `save_provider_choice(name)` + `current_provider_name()` helpers in
  provider.py (storage-backed) so app.py stays thin.

Tests: doc set → wins; doc null → env fallback; round-trip through the
helpers with monkeypatched DATA_DIR.

Commit M2.

## M3 — The connect/disconnect toggle (Leon's ask)

- Routes in app.py:
  - `GET /api/llm` → `{"provider": <effective name>, "source": "toggle" |
    "env-default"}`.
  - `POST /api/llm` `{"provider": "claude_code" | "openrouter"}` → save,
    echo back. Reject anything else with a friendly 400.
- UI, in the Stock Searcher panel header (next to the Run controls): a
  `.checkbox-label` toggle worded
  **"Use my Claude account for AI (Pro plan — Mac only)"**.
  - Checked → provider `claude_code`. Unchecked → provider `openrouter`
    (the key in `.env`; currently out of credit, which its own error
    message already explains if pressed).
  - A status line under it says where AI runs right now, in plain English:
    "AI: your Claude account (uses your Pro plan's shared limits)" or
    "AI: OpenRouter key".
  - Same error-handling pattern as every other toggle: `try/catch`, revert
    the checkbox on any failure, message in the status line.
- The settings document is shared storage — on the cloud (Postgres) the
  cloud copy will SHOW the same choice; pressing an AI button there while
  set to `claude_code` gets the friendly Mac-only message from M1. That is
  correct behaviour, not a bug; comment it.

Tests: both routes (valid switch, invalid value, GET reflects POST) via the
Flask test client with monkeypatched DATA_DIR.

Commit M3.

## M4 — Overnight market-hours analysis (Leon's request, 2026-08-14)

Leon wants the analysis to happen while the US market is open (≈11:30pm–
6am Sydney) and he's asleep. Design agreed with Fable 5: **a few strategic
runs across the session, not continuous running** — one analysis run takes
~2 minutes, so "3 hours of work" literally would be ~60 runs of quota burn
and order churn for near-identical daily-bar data. Three runs (after open,
mid-session, before close) capture the session; the run count is config,
not code, so Leon can add slots later.

- `rules.yaml`, extending the existing scheduler section — these are the
  DEFAULTS; Leon adjusts the actual times in the dashboard (below):
  ```yaml
  scheduler:
    fill_hour_sydney: 8
    # Default times for the three overnight analysis runs, in US-market
    # time (ET) — DST-proof, because the market lives in ET.
    # 09:35 ET ≈ just after open, 12:30 ≈ mid-session, 15:30 ≈ before close.
    analysis_times_et: ["09:35", "12:30", "15:30"]
  ```
- New settings document `overnight`:
  `{"enabled": false, "times_et": null, "last_runs": {"<slot>": "<ET date>"},
  "last_error": null}`. Off by default, like every scheduler. `times_et:
  null` means "use the rules.yaml defaults"; once Leon edits the times in
  the dashboard, his three times are stored here.
- **Adjustable times in the dashboard** (Leon's request — exactly three
  runs for now): next to the overnight toggle, three small time inputs
  (`<input type="time">`) pre-filled with the effective times. Shown in
  ET with a computed Sydney-time hint beside each ("09:35 ET ≈ 11:35pm
  Sydney tonight") so Leon never has to do timezone maths. Saved via the
  same settings route; validate server-side (HH:MM format, within the
  09:30–16:00 ET session, three distinct values → friendly 400 otherwise);
  revert-on-failure pattern as always.
- Pure function in `dashboard/scheduler.py` (tested without Flask or
  clocks): `due_analysis_slot(settings, now_et, slots)` → the slot that
  should fire now, or None. Rules:
  - ET weekday only (Mon–Fri; US holidays are NOT checked — a holiday run
    wastes one run on stale closes, harmless, comment it honestly);
  - a slot is due when `now_et` is at or past it and it hasn't run for
    today's ET date;
  - if SEVERAL slots are due (Mac was asleep), fire ONE run and mark them
    all done — one catch-up run on the freshest data, not three stale ones.
    This also gives a nice morning behaviour: Mac asleep all night → the
    first dashboard open after 6am triggers one run on final closing data.
- Wire into the EXISTING scheduler thread's 60-second loop (same thread,
  second check — no new thread):
  - **Provider gate:** overnight analysis fires ONLY when the effective
    provider is `claude_code`. Reason, in a comment: an unattended loop
    must never silently spend API dollars on a key Leon toggled to; his
    subscription quota is the only thing he agreed to spend while asleep.
  - Respect `analysis_lock` (skip the slot if a manual run is in flight);
    scope = all watchlists; mark the slot done BEFORE running (same
    philosophy as the other schedulers); on ANY error (rate limit hit,
    provider hiccup) record it in `last_error` for the UI and move on —
    the next slot or the morning open is the retry.
- UI, Stock Searcher panel: a `.checkbox-label` toggle —
  "Analyse automatically while the US market is open (3 runs/night — uses
  your Claude account; the Mac must be awake)" — plus a status line with
  the last overnight run time and `last_error` if set. Same revert-on-
  failure error pattern as every toggle.
- Interplay to document: each run replaces the previous run's pending
  orders, so the morning portfolio reflects the LAST (near-close) run;
  earlier runs of the night stay in `analysis_history` and `picks/`. The
  8am fill scheduler then settles what the market actually did.
- Tests (all fakes): `due_analysis_slot` — weekend no; before first slot
  no; between slots exactly one; multiple missed slots → one run, all
  marked; per-ET-date reset; provider gate blocks when provider is
  openrouter; times validation (bad format / outside session / duplicates
  rejected); custom times override defaults; a full fake run stamps the
  doc and writes analysis output.

Commit M4.

## M5 — Price watches: the middle run reacts to a price Leon set

Leon's request: "IF the stock price reaches a certain point that night,
the middle run is dedicated to analysing that price and determining
whether it is a buy/sell."

- **Setting a watch**: on each ticker's detail page, a small "Overnight
  price watch" box — one price input + Save/Clear. One watch per symbol.
  Stored in a new `price_watches` document:
  `{"<symbol>": {"level": 152.5, "set_when_price": 148.2, "set_at": ...}}`.
  `set_when_price` (the price when Leon saved the watch) defines the
  direction automatically: price was BELOW the level when set → the watch
  fires when price rises to/through it; ABOVE → fires when it falls
  to/through it. That matches the plain meaning of "reaches". Pure
  function `watch_triggered(watch, current_price)` — tested both
  directions plus not-crossed.
- A small "Price watches" list in the Stock Searcher panel (symbol,
  level, direction arrow, remove ×) so active watches are visible without
  visiting each ticker page.
- **The middle run's behaviour** (only the middle slot changes):
  - At the middle slot, fetch current prices (the live source's daily bar
    updates during the session — Yahoo's price, a few minutes delayed,
    good enough; say so in a comment) and evaluate every watch.
  - If one or more watches fired → the middle run is **scoped to the
    triggered symbols only**: the AI analyses just those stocks at
    tonight's price and delivers its buy/sell verdict on each. The run is
    recorded in history/picks like any other, labelled with its trigger
    ("price watch: NVDA reached $152.50").
  - If no watch fired → the middle run is the normal full analysis,
    unchanged.
  - Fired watches are one-shot: cleared after the run, with the outcome
    visible in the run history and the panel status line.
- ⚠️ **Correctness requirement — verify before building**: a scoped run
  must NOT wipe the pending orders the open-run placed for OTHER stocks.
  Check the current order engine's scoped-run semantics first (the
  July-2026 fix made scoped runs leave out-of-scope holdings alone — the
  same must hold for out-of-scope PENDING ORDERS under the newer
  order-placing engine). If today's engine replaces all pending orders on
  every run, confine the replacement to in-scope symbols as part of this
  milestone, with a test proving an out-of-scope pending order survives a
  scoped middle run.
- Tests (all fakes): watch CRUD round-trip; trigger logic both
  directions; middle-slot dispatch (watch fired → scoped run on those
  symbols; none fired → full run); fired watch cleared afterwards; the
  out-of-scope pending-order survival test above.

Commit M5.

## M6 — Docs, live check, cleanup

- `README.md`: provider section becomes three options with one honest
  paragraph on what a subscription can and cannot do (facts 1–4 above);
  `.env` table gains `CLAUDE_CODE_MODEL` + `CLAUDE_CODE_EFFORT`; a short
  paragraph on the overnight scheduler (3 adjustable ET run times) and
  price watches.
- `.env.example`: add commented `CLAUDE_CODE_MODEL=` and
  `CLAUDE_CODE_EFFORT=` with one-line explanations (opus = smarter +
  drains the shared window faster; sonnet = lighter).
- `HANDOVER.md`:
  - Costs section: using your Claude account spends your subscription's
    SHARED 5-hour/weekly limits (the same pool as claude.ai chat) — flip
    the toggle off in heavy chat periods (that is what it's for); one
    analysis run ≈ 10 requests, and Opus drains the window several times
    faster than Sonnet. Three overnight runs at Opus-medium is a real
    nightly spend of that quota — that's the agreed design.
  - **Keeping the Mac awake overnight** (new routine section): the
    overnight runs only happen while the Mac app is running and the Mac
    is awake. Document the simple recipe: start the app with
    `caffeinate -is ./venv/bin/python dashboard/app.py` (macOS's built-in
    stay-awake command — the Mac won't sleep while the app runs), or set
    "Prevent automatic sleeping when the display is off" in System
    Settings → Energy (plugged in). Also state the graceful fallback: if
    the Mac slept anyway, the first dashboard open in the morning fires
    ONE catch-up run on final closing prices.
  - Breaks table: "AI says limit reached" → wait for the window to reset,
    or toggle back to a funded key; "Claude account errors on the cloud
    copy" → expected, Mac only; "No overnight run happened" → Mac was
    asleep or the app wasn't running — see the stay-awake recipe.
- `PROGRESS.md`: dated entry.
- **Live check** (the one allowed spend): with the app running locally,
  `POST /api/llm` to `claude_code`, then call the provider once with
  "Reply with exactly: OK" (≈5 tokens on Leon's plan) — NOT a full
  analysis. Then `GET /api/llm` on both settings, toggle back to whatever
  Leon had, and confirm `/api/analysis` etc. still 200.
- Final commit includes docs AND `git rm PLAN-claude-account-provider.md`;
  push everything.

## Explicitly OUT of scope (agreed constraints)

- Making the Render copy use the Pro plan — impossible legitimately; the
  cloud copy's AI needs a funded key (OpenRouter/Anthropic) or the Mac.
- Deleting the exhausted OpenRouter key from `.env`/Render — harmless to
  keep, useful if Leon ever tops it up; his manual call either way.
- Automatic fallback between providers (silently switching accounts when
  one hits a limit would spend money/quota Leon didn't choose to spend).
- More than three overnight run slots ("confine it to 3 runs" — Leon,
  2026-08-14; the times are adjustable, the count is not, for now).
- Real-time price alerts / push notifications — the watch is checked at
  the middle slot only, not continuously. Continuous monitoring is a
  future conversation (it needs a polling loop and a notification path).
