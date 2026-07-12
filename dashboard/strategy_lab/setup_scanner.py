"""
setup_scanner.py — the Strategy Lab's "Scan now": checks whether real
news right now matches a saved strategy pattern.

One scan does this:
  1. Load Leon's saved strategies (journal.py). None saved yet → a
     friendly error rather than a scan of nothing.
  2. Turn each strategy's tags (or its name, if untagged) into a news
     search query — derive_queries().
  3. Fetch recent headlines for each query (events_source.py, free, no
     key), dedupe by title, cap how many we hand to the AI.
  4. ONE AI request for the whole scan (never one per strategy — the
     main cost control): the prompt lists every strategy and every
     headline (numbered), and asks which patterns, if any, look like
     they're currently in play. The AI can only point at evidence by
     NUMBER — the code, not the AI, resolves those numbers back into
     real title/link pairs, so a setup can never cite a headline it
     wasn't actually given.
  5. parse_scan_response() enforces every safety rule STRUCTURALLY: a
     setup missing its counter-case, its risks, or a genuine strategy
     match is DROPPED, not patched or trusted. There is no code path that
     produces a setup card without a counter-case.
  6. Save the result; append a compact record to setups_history (raw
     material for judging, months later, whether a flag meant anything).

Every setup is framed as an idea to research, never advice, and this
module never imports the portfolio, scanner, or analysis code — the Lab
cannot place a paper trade even by accident.
"""

import itertools
import json
import re
from datetime import datetime

from ..storage import get_doc

SYSTEM_PROMPT = """\
You are a deeply SKEPTICAL research assistant inside a private,
INFORMATION-ONLY dashboard. You are checking whether real, CURRENT news
matches a saved event-timing PATTERN — never giving investment advice,
never recommending a trade. Most days nothing genuinely matches; saying so
is a perfectly good answer. Never invent an event that isn't in the
headlines you were given. Every match you report MUST include its
strongest counter-argument and concrete risks — a one-sided report is not
acceptable. You respond ONLY with a JSON object — no prose before or after it."""

SCAN_PROMPT = """\
Here are Leon's saved event-timing patterns (id, name, description, entry
trigger, exit trigger, affected sectors):

{strategies_block}

Here are recent headlines, numbered:

{headlines_block}

Decide whether any headline(s) above suggest one of these patterns may be
CURRENTLY in play. Be skeptical: routine news, old news, or a vague
resemblance does NOT count — you need a credible, current, specific match.
It is normal and expected to find NOTHING; do not force a match.

Return ONE JSON object with exactly these keys:
  "setups": an array (may be EMPTY) of objects, each with:
    "strategy_id":     the exact id of the matching pattern from above
    "whats_happening": 1-3 plain sentences on the current situation
    "source_indexes":  array of the headline NUMBERS above that support
                       this (never cite a number not in the list above)
    "bull_case":       the case for why this could play out as the
                       pattern predicts
    "counter_case":    the STRONGEST argument this ISN'T really the
                       pattern, or won't play out — required, be
                       genuinely skeptical here
    "risks":           array of 1-4 short strings — concrete things that
                       could make this go wrong
    "confidence":      {{"level": "low"/"medium"/"high", "note": "1 short
                       sentence honestly explaining the uncertainty"}}
  "note": 1 short honest sentence summarizing the scan overall (e.g. "no
          patterns currently in play" is a fine answer)"""


def derive_queries(strategies, max_queries):
    """Turn strategies into a deduped list of news search terms: each
    strategy's own tags, or its name if it has no tags. Pure function so
    tests don't need a real journal or network.

    Collected ROUND-ROBIN — every strategy's FIRST tag before any
    strategy's second — not strategy-by-strategy. With a journal that's
    grown past max_queries, taking tags strategy-by-strategy would let the
    newest strategies use up the whole budget, leaving older ones with
    ZERO searches (and therefore no way to ever show up in a scan again,
    silently). Round-robin guarantees every strategy gets at least one
    query before any strategy gets a second.
    """
    term_lists = [
        [t.strip() for t in (strategy.get("tags") or [strategy["name"]]) if t.strip()]
        for strategy in strategies
    ]

    queries = []
    seen = set()
    for round_terms in itertools.zip_longest(*term_lists):
        for term in round_terms:
            if term is None:
                continue
            key = term.lower()
            if key not in seen:
                seen.add(key)
                queries.append(term)
                if len(queries) >= max_queries:
                    return queries
    return queries


def _text(value):
    """str(None) would produce the literal word "None" — which would then
    pass an `if counter_case:` truthiness check as if it were real content.
    Always route AI-supplied text through this instead of bare str()."""
    return str(value).strip() if value is not None else ""


def _valid_confidence(raw):
    level = _text((raw or {}).get("level")).lower()
    if level not in ("low", "medium", "high"):
        level = "low"  # the honest default when the model doesn't say
    return {"level": level, "note": _text((raw or {}).get("note"))}


def parse_scan_response(text, valid_strategy_ids, headlines):
    """Pull the scan result out of the AI's reply and enforce every
    guardrail STRUCTURALLY — a setup that fails any check is DROPPED, not
    patched or trusted:
      - strategy_id must be one we actually asked about;
      - whats_happening, counter_case, and risks must be non-empty (a
        setup literally cannot exist without its counter-case);
      - source_indexes must point at real headlines we supplied — a
        setup left with none once invalid indexes are stripped is
        dropped too (this is what stops the AI citing evidence it was
        never actually given).
    """
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object found in AI reply: {text[:200]}")
    raw = json.loads(cleaned[start : end + 1])

    setups = []
    for item in raw.get("setups", []) or []:
        if not isinstance(item, dict):
            continue
        strategy_id = item.get("strategy_id")
        if strategy_id not in valid_strategy_ids:
            continue

        whats_happening = _text(item.get("whats_happening"))
        counter_case = _text(item.get("counter_case"))
        risks = [_text(r) for r in (item.get("risks") or []) if _text(r)]
        if not (whats_happening and counter_case and risks):
            continue  # a setup card cannot exist without ALL of these

        # Resolve source_indexes → the REAL headline objects. An index
        # outside range (a hallucinated citation) is silently dropped; if
        # NONE survive, the whole setup is unsupported and dropped too.
        sources = []
        for idx in item.get("source_indexes") or []:
            try:
                i = int(idx) - 1  # the prompt numbers headlines from 1
            except (TypeError, ValueError):
                continue
            if 0 <= i < len(headlines):
                sources.append(headlines[i])
        if not sources:
            continue

        setups.append({
            "strategy_id": strategy_id,
            "whats_happening": whats_happening,
            "sources": sources,
            "bull_case": _text(item.get("bull_case")),
            "counter_case": counter_case,
            "risks": risks,
            "confidence": _valid_confidence(item.get("confidence")),
        })

    return {"setups": setups, "note": _text(raw.get("note"))}


def run_scan(provider, events_source, journal, rules):
    """Run one full scan. Returns the result dict (also saved to disk)."""
    strategies = journal.list()
    if not strategies:
        raise RuntimeError(
            "No saved strategies yet — write one or press Brainstorm first.")

    lab_rules = rules.get("lab", {})
    max_queries = lab_rules.get("max_queries", 8)
    per_query = lab_rules.get("headlines_per_query", 6)
    max_headlines = lab_rules.get("max_headlines", 40)

    queries = derive_queries(strategies, max_queries)
    raw_headlines = events_source.get_event_headlines(queries, per_query=per_query)

    # Dedupe by title (the same story often turns up under several
    # queries), then cap what we feed the AI — the main cost control.
    headlines, seen_titles = [], set()
    for h in raw_headlines:
        if h["title"] not in seen_titles:
            seen_titles.add(h["title"])
            headlines.append(h)
    headlines = headlines[:max_headlines]

    # No headlines at all → skip the AI call entirely (nothing to check
    # means nothing to spend money asking about) and say so honestly.
    if not headlines:
        result = {
            "run_at": datetime.now().isoformat(timespec="seconds"),
            "queries_used": queries, "headlines_examined": 0,
            "setups": [], "note": "No recent headlines found for these patterns.",
        }
        _save(result)
        return result

    strategies_block = "\n".join(
        f'- id={s["id"]} "{s["name"]}": {s["description"]} '
        f'(entry: {s["entry_trigger"]}; exit: {s["exit_trigger"]}; '
        f'assets: {", ".join(s["assets"]) or "unspecified"})'
        for s in strategies
    )
    headlines_block = "\n".join(
        f'{i + 1}. "{h["title"]}" ({h["source"] or "unknown source"}, {h["published"]})'
        for i, h in enumerate(headlines)
    )

    prompt = SCAN_PROMPT.format(strategies_block=strategies_block,
                                headlines_block=headlines_block)
    reply = provider.complete(SYSTEM_PROMPT, prompt, max_tokens=3000)
    parsed = parse_scan_response(reply, {s["id"] for s in strategies}, headlines)

    by_id = {s["id"]: s for s in strategies}
    for setup in parsed["setups"]:
        setup["strategy_name"] = by_id[setup["strategy_id"]]["name"]

    result = {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "queries_used": queries,
        "headlines_examined": len(headlines),
        "setups": parsed["setups"],
        "note": parsed["note"],
    }
    _save(result)
    return result


def _save(result):
    get_doc("setups_latest").save(result)

    history_doc = get_doc("setups_history")
    history = history_doc.load() or []
    history.append({
        "run_at": result["run_at"],
        "headlines_examined": result["headlines_examined"],
        "setups": [{"strategy_id": s["strategy_id"],
                   "strategy_name": s["strategy_name"],
                   "confidence": s["confidence"]["level"]} for s in result["setups"]],
    })
    history_doc.save(history)


def load_latest():
    """Return the last saved scan, or None if no scan has happened yet."""
    return get_doc("setups_latest").load()


def load_settings():
    """{"daily_scan": bool, "last_auto_scan_date": "YYYY-MM-DD" or None}.
    daily_scan defaults to OFF — the Lab never spends money on its own
    until Leon deliberately opts in."""
    return get_doc("lab_settings").load() or {"daily_scan": False,
                                              "last_auto_scan_date": None}


def save_settings(settings):
    get_doc("lab_settings").save(settings)


def ran_today(latest, today):
    """True if the saved scan `latest` (from load_latest()) happened on
    `today` (a "YYYY-MM-DD" string). A manual "Scan now" counts exactly
    the same as an automatic one here — either way, today already has a
    scan, so there's nothing further to check."""
    return bool(latest and (latest.get("run_at") or "")[:10] == today)


def should_auto_scan(settings, latest, today):
    """Should the once-a-day automatic scan fire right now? No, if: the
    feature is off; the automatic scan already ran today; or ANY scan —
    including one Leon ran by hand with "Scan now" — already covered
    today. Pure function (no clock, no I/O) so it's testable without
    Flask or a real journal."""
    if not settings.get("daily_scan"):
        return False
    if settings.get("last_auto_scan_date") == today:
        return False
    return not ran_today(latest, today)
