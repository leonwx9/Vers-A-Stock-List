"""
searcher.py — the Stock Searcher engine.

One "run" does this:
  1. Load the universe (config/universe.yaml) and get prices for every ticker.
  2. Send the tickers to Claude in small batches, asking for a bull case,
     bear case, verdict, conviction score (1-10), stop-loss note and
     timeframe for each — as strict JSON we can parse.
  3. Rank everything by conviction and shortlist the top picks
     (excluding leveraged/inverse/volatility products, per rules.yaml).
  4. Save the result: a JSON file the web page reads, plus a dated
     markdown file in picks/ as the audit trail CLAUDE.md asks for.
"""

import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from ..config_loader import load_rules, load_universe
from ..storage import get_doc

# Where results are stored. data/ holds machine-readable JSON (gitignored);
# picks/ holds the human-readable dated audit files (committed).
PICKS_DIR = Path(__file__).parent.parent.parent / "picks"

SYSTEM_PROMPT = """\
You are the analysis engine inside a private paper-trading dashboard.
Nothing you write is investment advice; no real money is traded.
You respond ONLY with a JSON array — no prose before or after it."""

BATCH_PROMPT = """\
Analyze each security below for a short-term (weeks) paper-trading strategy.

{price_note}

For EACH security return one JSON object with exactly these keys:
  "ticker":     the symbol, unchanged
  "bull":       strongest case FOR buying now (1-2 sentences)
  "bear":       strongest case AGAINST (1-2 sentences)
  "verdict":    "bull" or "bear" — which side wins and why is implied by conviction
  "conviction": integer 1-10 (10 = highest confidence it performs)
  "stop_loss":  short exit note, e.g. "consider exiting if down >10% from entry"
  "timeframe":  approximate profit window, e.g. "2-4 weeks"

Respond with a JSON array containing one object per security, same order.

Securities:
{securities}"""


def _format_batch(assets, quotes):
    """Turn a batch of assets + their quotes into the text block for the prompt."""
    lines = []
    for asset in assets:
        q = quotes[asset["symbol"]]
        flags = f" [{', '.join(asset['flags'])}]" if asset["flags"] else ""
        lines.append(
            f"- {asset['symbol']} ({asset['name']}, {asset['type']}{flags}): "
            f"price ${q['price']}, 5-day {q['change_5d_pct']:+}%, "
            f"30-day {q['change_30d_pct']:+}%"
        )
    return "\n".join(lines)


def parse_batch_response(text, expected_tickers):
    """Pull the JSON array out of the AI's reply and sanity-check it.

    Models sometimes wrap JSON in ```json fences — strip those before parsing.
    Returns a dict keyed by ticker, containing only the tickers we asked about.
    """
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    # Grab from the first "[" to the last "]" in case any stray text remains.
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON array found in AI reply: {text[:200]}")
    items = json.loads(cleaned[start : end + 1])

    results = {}
    for item in items:
        ticker = item.get("ticker")
        if ticker not in expected_tickers:
            continue  # ignore anything we didn't ask about
        # Force conviction into a safe 1-10 integer even if the model strays.
        # A non-number (e.g. "high") becomes the minimum score rather than
        # crashing the whole (paid) run over one bad field.
        try:
            conviction = int(float(item.get("conviction", 1)))
        except (TypeError, ValueError):
            conviction = 1
        item["conviction"] = max(1, min(10, conviction))
        # Normalise the verdict ("Bull", " BEAR " → "bull"/"bear") so the
        # shortlist check below can rely on it.
        item["verdict"] = str(item.get("verdict", "")).strip().lower()
        results[ticker] = item
    return results


def run_analysis(provider, source, universe=None, rules=None, on_progress=None,
                 scope_name=None):
    """Run one full analysis. Returns the result dict (also saved to disk).

    provider — an LLM provider (from llm.provider.get_provider())
    source   — a PriceSource (SampleSource now, live later)
    universe/rules — injectable for tests; default to the config files
    on_progress — optional callback(batches_done, batches_total)
    scope_name — label for WHAT was analysed (e.g. one watchlist's name),
                 recorded in the result so the page can say so
    """
    universe = universe or load_universe()
    rules = rules or load_rules()
    batch_size = rules["analysis"]["batch_size"]

    # Tell the AI honestly what kind of prices it's looking at.
    data_source = rules.get("data", {}).get("price_source", "sample")
    price_note = (
        "The price figures are REAL recent market data (daily closes)."
        if data_source == "live" else
        "Important: the price figures are SIMULATED development data, not real "
        "market prices. Base your reasoning primarily on your general knowledge "
        "of each company/fund; treat the price trend only as illustrative "
        "momentum context."
    )

    # 1. Prices for everyone, plus the change-% for each period the table's
    #    dropdown offers (1D … All time).
    quotes = {a["symbol"]: source.get_quote(a["symbol"]) for a in universe}
    changes = {a["symbol"]: source.get_changes(a["symbol"]) for a in universe}

    # 2. Split the universe into batches and ask the AI about each batch.
    #    A thread pool runs a few requests at once so ~100 tickers don't take
    #    forever; max_workers in rules.yaml keeps it polite.
    batches = [universe[i : i + batch_size] for i in range(0, len(universe), batch_size)]
    done_count = 0

    batch_errors = []

    def analyze_batch(batch):
        tickers = {a["symbol"] for a in batch}
        prompt = BATCH_PROMPT.format(price_note=price_note,
                                     securities=_format_batch(batch, quotes))
        # One bad batch (provider hiccup, malformed reply) must not sink the
        # whole run — the other batches are already paid for. Its tickers
        # fall back to the honest "(no analysis returned)" rows below.
        try:
            reply = provider.complete(SYSTEM_PROMPT, prompt)
            return parse_batch_response(reply, tickers)
        except Exception as e:
            batch_errors.append(e)
            return {}

    analyses = {}
    with ThreadPoolExecutor(max_workers=rules["analysis"]["max_workers"]) as pool:
        for batch_result in pool.map(analyze_batch, batches):
            analyses.update(batch_result)
            done_count += 1
            if on_progress:
                on_progress(done_count, len(batches))

    # If literally EVERY batch failed, something systemic is wrong (key,
    # provider outage) — better a clear error than a run full of blanks.
    if batch_errors and not analyses:
        raise RuntimeError(
            f"All {len(batches)} AI batches failed — first error: {batch_errors[0]}")

    # 3. Stitch prices + analysis together into one row per ticker.
    rows = []
    for asset in universe:
        symbol = asset["symbol"]
        row = {**asset, **quotes[symbol], "changes": changes[symbol]}
        # If the AI skipped a ticker (rare), record that honestly.
        row.update(analyses.get(symbol, {
            "bull": "(no analysis returned)", "bear": "(no analysis returned)",
            "verdict": "bear", "conviction": 1,
            "stop_loss": "n/a", "timeframe": "n/a",
        }))
        rows.append(row)

    # 4. Shortlist: highest conviction first, skipping risk-flagged products
    #    and anything whose own analysis says the BEAR side wins — a high
    #    conviction score can't override the AI's own verdict.
    excluded = set(rules["portfolio"]["excluded_flags"])
    eligible = [r for r in rows
                if not (set(r["flags"]) & excluded) and r.get("verdict") == "bull"]
    eligible.sort(key=lambda r: r["conviction"], reverse=True)
    shortlist = [r["symbol"] for r in eligible[: rules["portfolio"]["shortlist_size"]]]

    result = {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "data_source": data_source,
        "scope": scope_name or "all watchlists",
        "batches_failed": len(batch_errors),
        "shortlist": shortlist,
        "rows": rows,
    }

    _save(result, rows, shortlist)
    return result


def _save(result, rows, shortlist):
    """Save everything one run produces:
      - analysis_latest — what the web page shows (file or cloud database)
      - analysis_history — one compact record per run EVER made: when, what
        scope, and each pick with its conviction and entry price. This is
        the raw material for a future track-record panel.
      - picks/ — a dated audit file PER RUN. The file name includes the time
        of day, so a second run on the same day gets its own file instead of
        overwriting the first (the audit trail must keep every run).
    """
    get_doc("analysis_latest").save(result)
    by_symbol = {r["symbol"]: r for r in rows}

    history_doc = get_doc("analysis_history")
    history = history_doc.load() or []
    history.append({
        "run_at": result["run_at"],
        "scope": result["scope"],
        "data_source": result["data_source"],
        "universe_size": len(rows),
        "shortlist": [{"symbol": s,
                       "conviction": by_symbol[s]["conviction"],
                       "price": by_symbol[s]["price"]} for s in shortlist],
    })
    history_doc.save(history)

    PICKS_DIR.mkdir(exist_ok=True)
    lines = [
        f"# Picks — {result['run_at'].replace('T', ' ')}",
        "",
        f"Scope: {result['scope']}. Data source: {result['data_source']}.",
        "",
    ]
    for symbol in shortlist:
        r = by_symbol[symbol]
        lines += [
            f"## {symbol} — {r['name']}",
            f"- Conviction: {r['conviction']}/10",
            f"- Bull: {r['bull']}",
            f"- Bear: {r['bear']}",
            f"- Timeframe: {r['timeframe']}",
            f"- Stop-loss: {r['stop_loss']}",
            "",
            "### Trade journal (fill in later)",
            "- Executed: ☐ yes / ☐ no",
            "- Entry price:",
            "- Exit / current price:",
            "- Outcome: profit / loss / still holding",
            "",
        ]
    markdown = "\n".join(lines)
    # "2026-07-07T14:30:05" → "2026-07-07-143005", a file-name-safe stamp.
    stamp = result["run_at"].replace("T", "-").replace(":", "")
    path = PICKS_DIR / f"{stamp}.md"
    suffix = 2
    while path.exists():  # two runs in the same second — keep both anyway
        path = PICKS_DIR / f"{stamp}-{suffix}.md"
        suffix += 1
    with open(path, "w") as f:
        f.write(markdown)
    # Also keep the audit trail in storage — on the cloud, the .md file
    # above lands on a disk that forgets, but the database doesn't.
    picks_doc = get_doc("picks")
    all_picks = picks_doc.load() or {}
    all_picks[result["run_at"]] = markdown
    picks_doc.save(all_picks)


def load_latest():
    """Return the last saved analysis, or None if no run has happened yet."""
    return get_doc("analysis_latest").load()
