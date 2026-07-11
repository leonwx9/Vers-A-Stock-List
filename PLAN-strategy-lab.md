# PLAN — Event Strategy Lab (+ two order-engine repairs first)

**Status: approved by Leon, not yet built.** This file is the complete brief
for the implementing session. Read CLAUDE.md first (project rules), then
this. Delete this file in the final commit when everything below is done.

## What this is, in one paragraph

A new "Strategy Lab" view inside the existing AI Pivot Scanner panel,
behind a segmented toggle. It helps Leon capture and research TIMING
patterns around real-world events (wars, chokepoints, elections,
commodities) — *when* to invest, not which stock. Three parts: a
**journal** of his own strategy ideas (full add/edit/delete, saved
forever), an **AI brainstorm** button that suggests more patterns
(clearly badged AI vs MINE), and a **news checker** ("Scan now") that
fetches current headlines and asks the AI — in ONE call — whether
anything happening right now matches a journal pattern, producing
"active setup" cards that ALWAYS carry a counter-case, risks, source
links, and an honest confidence note. Information only: framed as ideas
to research, never advice, and structurally incapable of trading.

## M0 — repair two review findings BEFORE building the Lab

1. **Scoped-shortlist leak.** `api_run_analysis` appends currently-held
   stocks to the analysed universe so they get HOLD/SELL reviews — but
   those appended out-of-scope stocks then compete for shortlist slots.
   Fix: `run_analysis()` gains a `review_only` parameter (set of symbols);
   app.py passes exactly the held symbols it appended (held symbols
   already inside the chosen scope stay shortlist-eligible, as before).
   The shortlist eligibility filter in searcher.py step 4 additionally
   requires `r["symbol"] not in review_only`. held_reviews behaviour is
   unchanged. Test: a scoped run holding a high-conviction out-of-scope
   stock → it appears in held_reviews and rows, but NOT in the shortlist,
   and doesn't consume a slot (the shortlist still has 5 in-scope picks
   when 5 qualify).
2. **Order IDs.** `_new_order_id()` uses time-of-day + a per-process
   counter — two cloud workers can collide. Replace with
   `"ord-" + secrets.token_hex(4)` (the watchlist-id pattern); delete the
   global counter.

## The Lab — data model

Think: the journal is a **recipe book** (a strategy = a repeatable
recipe); an active setup is **tonight's dinner** — one current, concrete
instance of a recipe, pointing back at it via `strategy_id`. Recipes are
permanent; setups are dated snapshots that go stale.

All documents go through `storage.get_doc()` (so they're files locally
and Postgres rows on the cloud automatically — persistence is free).

`strategies` doc:
```json
{"strategies": [
  {"id": "strat-8f2a", "origin": "leon",
   "name": "Oil chokepoint closure",
   "description": "Conflict closes a key shipping strait…",
   "entry_trigger": "credible closure/threat of a major chokepoint",
   "exit_trigger": "ceasefire or confirmed reopening",
   "assets": ["energy sector", "tanker shipping"],
   "risk_notes": "spikes fade fast; the retrace is the hard part",
   "tags": ["oil", "geopolitics", "shipping"],
   "created_at": "…", "updated_at": "…"}
]}
```
- `origin` is `"leon"` or `"ai"` and is set SERVER-SIDE only (journal API
  hardcodes "leon"; brainstorm hardcodes "ai") — the badge can't be
  spoofed or edited, and editing an AI entry does NOT change its origin.
- Validation: `name` and `description` required non-empty; strings
  trimmed; `assets`/`tags` are lists of strings.

`setups_latest` doc (the last scan's full result):
```json
{"run_at": "…", "queries_used": ["Strait of Hormuz", "…"],
 "headlines_examined": 34,
 "setups": [
   {"strategy_id": "strat-8f2a", "strategy_name": "Oil chokepoint closure",
    "whats_happening": "…",
    "sources": [{"title": "…", "link": "…", "source": "…", "published": "…"}],
    "bull_case": "…", "counter_case": "…", "risks": ["…", "…"],
    "confidence": {"level": "low", "note": "single unconfirmed report …"}}
 ],
 "note": "honest summary, e.g. 'no patterns currently in play'"}
```

`setups_history` doc: append one compact record per scan ever
(`run_at`, `headlines_examined`, and per setup: strategy_id/name +
confidence level) — the raw material for judging, months later, whether
the Lab's flags preceded real moves.

`lab_settings` doc: `{"daily_scan": false, "last_auto_scan_date": null}`.

New `rules.yaml` section (config, not magic numbers):
```yaml
lab:
  max_queries: 8          # news searches per scan
  headlines_per_query: 6
  max_headlines: 40       # cap on what one scan feeds the AI
  brainstorm_count: 4     # suggestions per brainstorm press
```

## Module boundaries

- `dashboard/strategy_lab/` — new package, self-contained.
  **It must not import the portfolio, scanner, or analysis modules** —
  the Lab is information-only by construction.
  - `journal.py` — `StrategyJournal`: `list() / create(fields, origin) /
    update(id, fields) / delete(id)`, with the same `_refresh()`-before-
    every-operation pattern as WatchlistStore (two cloud workers share
    one database).
  - `brainstorm.py` — `run_brainstorm(provider, journal, rules)`: one AI
    call. The prompt includes the existing strategies (compact) so the AI
    builds on rather than duplicates them, and asks for
    `brainstorm_count` NEW patterns as a JSON array with the same fields
    a journal entry has. Parse + validate: entries missing
    name/description/entry_trigger/exit_trigger are dropped; cap at
    `brainstorm_count`; each saved via `journal.create(..., origin="ai")`.
    Returns the created entries.
  - `setup_scanner.py` — `run_scan(provider, events_source, journal,
    rules)` (flow below) plus the pure functions `derive_queries()` and
    `parse_scan_response()` so tests can hit them directly.
- `dashboard/datasources/events_source.py` — `EventNewsSource` with one
  method: `get_event_headlines(queries, per_query)` returning
  `[{title, link, source, published, query}]`. Implementation: **Google
  News RSS** — free, no key, already proven in this codebase (it powers
  the ticker-page headlines; reuse `news_source.parse_rss`). One failed
  query is skipped; ALL queries failing raises RuntimeError (an honest
  error beats a fake "no news"). This class sits behind the same
  pluggable-source idea as prices: a future GDELT version (or a crypto
  events feed) swaps in without touching the Lab.

## The scan flow, step by step

1. Load strategies. None → friendly error ("write or brainstorm a
   strategy first").
2. `derive_queries(strategies, max_queries)` — pure function: collect
   each strategy's tags (deduped, order-preserving), fall back to the
   strategy name for an untagged entry, cap at `max_queries`.
3. Fetch headlines per query from the events source; dedupe by title;
   cap at `max_headlines`.
4. **One** `provider.complete()` call for the whole scan (the main
   cost-control decision — never one call per strategy). The prompt
   contains the compact strategies + the headlines as a NUMBERED list,
   and demands JSON: `{"setups": [...], "note": "..."}` where each setup
   references its evidence as `source_indexes` (numbers into the supplied
   list). Numbers-not-URLs is the anti-hallucination trick: the AI can
   only cite headlines we actually gave it, because the code — not the
   AI — resolves indexes back to the real title/link objects.
   Honesty rules in the prompt: skeptical framing; "no matching setups"
   is a perfectly good answer; every setup MUST include the strongest
   counter-case, concrete risks, and an uncertainty note; never invent
   events not present in the headlines; ideas to research, not advice.
5. `parse_scan_response()` — pure function, enforces the guardrails
   STRUCTURALLY (drop, don't trust):
   - unknown `strategy_id` → setup dropped;
   - missing/empty `whats_happening`, `counter_case`, or `risks` →
     setup dropped (a card literally cannot exist without its
     counter-case);
   - invalid source indexes removed; a setup left with zero valid
     sources → dropped;
   - `confidence.level` normalised to low/medium/high; anything else →
     "low" (the honest default); missing note → "" is allowed but the
     level still shows.
6. Save `setups_latest`, append to `setups_history`, return the result.

Cost: headlines free; one Sonnet call ≈ 1–2¢ (the dashboard already runs
`anthropic/claude-sonnet-5` via OpenRouter — no model change needed).
Brainstorm: one call, same ballpark.

## App wiring (`dashboard/app.py`)

- `GET  /api/lab` → `{strategies, setups (latest), settings}` in one call.
- `POST /api/lab/strategies` (create), `POST /api/lab/strategies/<id>`
  (edit — origin not editable), `DELETE /api/lab/strategies/<id>`.
- `POST /api/lab/brainstorm` and `POST /api/lab/scan` — both behind one
  shared `lab_lock` (same turnstile pattern as analysis/scan locks) and
  both need the provider (friendly MissingKeyError message like the
  others).
- `POST /api/lab/settings` `{daily_scan: bool}`.
- **Daily auto-scan (L4, default OFF):** on `GET /api/lab`, if
  `daily_scan` is on, a provider key exists, and `last_auto_scan_date`
  != today → set `last_auto_scan_date` immediately (prevents double-fire
  from two tabs), then run the scan in a background `threading.Thread`
  guarded by `lab_lock`, so the page never blocks. The response includes
  a "daily scan running" flag for the status line. Known small gap: the
  cloud's two workers could in theory both fire (worker-local locks) —
  worst case one wasted ~2¢ scan; note it in a comment, don't engineer
  around it.

## UI (`index.html`, `app.js`, `style.css`)

- The scanner panel header gains a seg-group toggle —
  `[ AI Pivots | Strategy Lab ]` — the existing `.seg-group/.seg` pill
  pattern, remembered in localStorage (`scanner-view`). The panel's
  current content wraps in `#pivot-view`; the Lab renders in `#lab-view`
  (one hidden at a time). Sidebar link text: "AI Pivot Scanner" →
  **"Event Scanner"** (same anchor).
- Panel subtitle while the Lab is shown: "event-timing patterns · ideas
  to research — not investment advice".
- Lab layout, top to bottom (all collapsible, default hidden, the
  standard pattern):
  1. **Active setups** — "Scan now" action button, last-scan status line
     ("Last scan: … · 34 headlines · 1 setup"), the daily-scan checkbox
     (label says it costs ~1–2¢/day), and the setup cards. Card contents,
     always all six: pattern name (badge-linked to the journal entry),
     what's happening, source links (via `safeUrl`, `target=_blank`),
     bull case, counter-case (visually distinct — reuse the scan-card
     bottom-line style), risks list, confidence badge (low/med/high, ink
     not green — confidence is a warning-grade fact, not a win) + its
     uncertainty note. Plus the not-advice line on every card footer.
  2. **My journal** — "New strategy" button opening an inline form
     (name, description, entry trigger, exit trigger, assets
     comma-separated, risk notes, tags comma-separated); strategy cards
     with MINE/AI badge, tag chips, Edit (re-opens the form pre-filled)
     and Delete (confirm()). A "Brainstorm ideas" button sits in this
     section's header.
- Everything third-party or AI-written goes through `esc()`; links
  through `safeUrl()`. New CSS: `.lab-badge.mine` / `.lab-badge.ai`,
  confidence badge tints — reuse existing tokens; keep additions small.

## Tests (offline, fakes — follow existing patterns)

New `tests/test_strategy_lab.py`:
- journal: create/edit/delete + persistence across a reload; origin is
  forced server-side (create via API path sets "leon"; editing an AI
  entry keeps "ai"); empty name rejected.
- `derive_queries`: tags collected/deduped/capped; untagged strategy
  falls back to its name.
- `parse_scan_response`: drops a setup missing its counter_case; drops
  unknown strategy_id; strips invalid source indexes and drops a setup
  with none left; normalises junk confidence to "low".
- `run_scan` end-to-end with FakeProvider + a FakeEventsSource: saves
  `setups_latest` + appends `setups_history`; empty journal → clear error.
- brainstorm: created entries badged "ai"; malformed suggestions dropped;
  count capped.
- events_source: canned RSS payload parses (reuse the news_source test
  style); all-queries-failed raises.
- M0: the scoped-shortlist test described above; an order-id uniqueness
  sanity test.

## Docs (same commits as the code)

- PROGRESS.md entry (M0 repairs + Lab).
- README.md: the dashboard now does FOUR things — add the Lab bullet
  (with the not-advice line); project layout gains `strategy_lab/`.
- HANDOVER.md: routine gains a Lab paragraph; costs section gains
  brainstorm/scan lines; "when something breaks" gains a row ("scan
  found nothing" → normal and honest, most days nothing matches).

## Process requirements (from CLAUDE.md — non-negotiable)

- Small logical commits on `dashboard`; beginner-readable comments;
  `./venv/bin/python -m pytest tests/` all green before every commit;
  verify against the live local server with curl after each milestone.
- Local server: `pkill -f dashboard/app.py` then
  `nohup ./venv/bin/python dashboard/app.py > /tmp/versa-server.log 2>&1 &`
  (no auto-reload by default — restart after edits).
- Never spend Leon's AI credit in testing — fakes only. The one
  permitted live check: a single real "Scan now" at the very end, ONLY
  if Leon says yes when asked.
- Build order: M0 → L1 journal (usable same-day, no AI) → L2 brainstorm
  → L3 events source + scan + setup cards → L4 daily checkbox + docs.
- Push when done (auto-deploys the cloud copy).
