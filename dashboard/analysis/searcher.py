"""
searcher.py — the Stock Searcher engine.

One "run" does this:
  1. Load the universe (config/universe.yaml, or a watchlist) and get
     prices for every ticker — PLUS every stock the paper portfolio
     currently holds, even ones outside this run's scope, because a
     position must never go unreviewed just because its watchlist wasn't
     the one analysed today.
  2. Send the tickers to Claude in small batches, asking for a bull case,
     bear case, verdict, conviction score (1-10), a stop-loss %, an entry
     price, and — for currently-held stocks — a HOLD/SELL decision.
  3. Rank everything by conviction and shortlist the top picks
     (excluding leveraged/inverse/volatility products and anything the
     AI itself calls a bear case, per rules.yaml).
  4. Save the result: a JSON file the web page reads, plus a dated
     markdown file in picks/ as the audit trail CLAUDE.md asks for.

The portfolio no longer buys/sells instantly from this result — see
dashboard/portfolio/engine.py's place_orders()/process_fills() for how a
shortlist here turns into pending orders that fill on their own later.
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

Securities marked "CURRENTLY HELD" are already owned in the paper portfolio.
For those, decide HOLD or SELL now — put your reasoning in bull (the case for
holding) / bear (the case for selling) as usual. For securities NOT currently
held, always set "action" to "n/a".

For EACH security return one JSON object with exactly these keys:
  "ticker":        the symbol, unchanged
  "bull":          strongest case FOR buying/holding now (1-2 sentences)
  "bear":          strongest case AGAINST (1-2 sentences)
  "verdict":       "bull" or "bear" — which side wins and why is implied by conviction
  "conviction":    integer 1-10 (10 = highest confidence it performs)
  "stop_loss":     short human-readable exit note, e.g. "exit if down >12%"
  "stop_loss_pct": integer {slp_min}-{slp_max} — the % drop from entry at which
                   THIS security should be automatically sold. Tailor it to how
                   volatile the security is: a steady blue-chip might warrant a
                   number near {slp_min}, a volatile small-cap nearer {slp_max}.
  "timeframe":     approximate profit window, e.g. "2-4 weeks"
  "entry_price":   the price you would actually place a BUY order at — a
                   realistic level reachable within the next 1-2 trading
                   sessions (at or slightly below the current price). Give
                   your genuine best number even for securities you wouldn't
                   personally shortlist.
  "action":        "hold", "sell", or "n/a" (see the CURRENTLY HELD note above)

Respond with a JSON array containing one object per security, same order.

Securities:
{securities}"""


def _format_batch(assets, quotes, holdings):
    """Turn a batch of assets + their quotes into the text block for the
    prompt. `holdings` is {symbol: avg_cost} — stocks the portfolio already
    owns get a "CURRENTLY HELD" marker so the AI knows to judge hold vs sell."""
    lines = []
    for asset in assets:
        symbol = asset["symbol"]
        q = quotes[symbol]
        flags = f" [{', '.join(asset['flags'])}]" if asset["flags"] else ""
        held_note = (f" — CURRENTLY HELD at ${holdings[symbol]:.2f} avg cost"
                    if symbol in holdings else "")
        lines.append(
            f"- {symbol} ({asset['name']}, {asset['type']}{flags}){held_note}: "
            f"price ${q['price']}, 5-day {q['change_5d_pct']:+}%, "
            f"30-day {q['change_30d_pct']:+}%"
        )
    return "\n".join(lines)


def parse_batch_response(text, expected_tickers, current_prices=None,
                         default_stop_loss_pct=10, stop_loss_pct_min=5,
                         stop_loss_pct_max=25):
    """Pull the JSON array out of the AI's reply and sanity-check every
    field — models occasionally slip (a dropped decimal, a stray word
    where a number belongs), and this is the one place that protects the
    rest of the app from trusting a bad value.

    current_prices — {ticker: price}, used to sanity-check entry_price.
    Returns a dict keyed by ticker, containing only the tickers we asked about.
    """
    current_prices = current_prices or {}
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

        # Conviction: force into a safe 1-10 integer even if the model
        # strays (e.g. "high") — becomes the minimum score rather than
        # crashing the whole (paid) run over one bad field.
        try:
            conviction = int(float(item.get("conviction", 1)))
        except (TypeError, ValueError):
            conviction = 1
        item["conviction"] = max(1, min(10, conviction))

        # Verdict: normalise messy casing/whitespace ("Bull " → "bull").
        item["verdict"] = str(item.get("verdict", "")).strip().lower()

        # Action: only "hold"/"sell" are meaningful; anything else (a typo,
        # a missing field, or the model's own "n/a" for a non-held stock)
        # becomes "n/a" — the safe default, since "n/a" triggers no order.
        action = str(item.get("action", "")).strip().lower()
        item["action"] = action if action in ("hold", "sell") else "n/a"

        # Stop-loss %: clamp into the configured band; anything invalid
        # falls back to the portfolio-wide default rather than block a buy
        # over one malformed number.
        try:
            slp = float(item.get("stop_loss_pct"))
            if not (stop_loss_pct_min <= slp <= stop_loss_pct_max):
                slp = default_stop_loss_pct
        except (TypeError, ValueError):
            slp = default_stop_loss_pct
        item["stop_loss_pct"] = slp

        # Entry price: only trust it if it's within a sane band around the
        # CURRENT price (85%-102%). A formatting slip (a dropped decimal, a
        # stale training-data price) outside that band means we skip
        # placing an order for this pick entirely — never clamp or
        # silently substitute a number the AI never actually reasoned
        # about; a garbage number means we don't trade on that pick.
        entry_price = None
        current = current_prices.get(ticker)
        try:
            candidate = float(item.get("entry_price"))
            if current and 0.85 * current <= candidate <= 1.02 * current:
                entry_price = round(candidate, 2)
        except (TypeError, ValueError):
            pass
        item["entry_price"] = entry_price  # None → no buy order this run

        results[ticker] = item
    return results


def run_analysis(provider, source, universe=None, rules=None, on_progress=None,
                 scope_name=None, holdings=None):
    """Run one full analysis. Returns the result dict (also saved to disk).

    provider — an LLM provider (from llm.provider.get_provider())
    source   — a PriceSource (SampleSource now, live later)
    universe/rules — injectable for tests; default to the config files
    on_progress — optional callback(batches_done, batches_total)
    scope_name — label for WHAT was analysed (e.g. one watchlist's name),
                 recorded in the result so the page can say so
    holdings — optional {symbol: avg_cost} for stocks the paper portfolio
               currently owns. Every held symbol gets a HOLD/SELL review
               (its own row must already be present in `universe` — the
               caller is responsible for adding any held-but-out-of-scope
               stock there first, so this function stays unaware of
               watchlists). The result's "held_reviews" key collects the
               outcome for the portfolio engine to act on.
    """
    universe = universe or load_universe()
    rules = rules or load_rules()
    holdings = holdings or {}
    batch_size = rules["analysis"]["batch_size"]
    slp_min = rules["portfolio"].get("stop_loss_pct_min", 5)
    slp_max = rules["portfolio"].get("stop_loss_pct_max", 25)
    default_slp = rules["portfolio"].get("stop_loss_pct", 10)

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

    current_prices = {symbol: q["price"] for symbol, q in quotes.items()}

    def analyze_batch(batch):
        tickers = {a["symbol"] for a in batch}
        prompt = BATCH_PROMPT.format(
            price_note=price_note, slp_min=slp_min, slp_max=slp_max,
            securities=_format_batch(batch, quotes, holdings))
        # One bad batch (provider hiccup, malformed reply) must not sink the
        # whole run — the other batches are already paid for. Its tickers
        # fall back to the honest "(no analysis returned)" rows below.
        try:
            reply = provider.complete(SYSTEM_PROMPT, prompt)
            return parse_batch_response(reply, tickers, current_prices=current_prices,
                                        default_stop_loss_pct=default_slp,
                                        stop_loss_pct_min=slp_min,
                                        stop_loss_pct_max=slp_max)
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
            "stop_loss": "n/a", "stop_loss_pct": default_slp,
            "timeframe": "n/a", "entry_price": None, "action": "n/a",
        }))
        rows.append(row)
    by_symbol = {r["symbol"]: r for r in rows}

    # 4. Shortlist: highest conviction first, skipping risk-flagged products
    #    and anything whose own analysis says the BEAR side wins — a high
    #    conviction score can't override the AI's own verdict.
    excluded = set(rules["portfolio"]["excluded_flags"])
    eligible = [r for r in rows
                if not (set(r["flags"]) & excluded) and r.get("verdict") == "bull"]
    eligible.sort(key=lambda r: r["conviction"], reverse=True)
    shortlist = [r["symbol"] for r in eligible[: rules["portfolio"]["shortlist_size"]]]

    # 5. Every currently-held stock gets its HOLD/SELL verdict collected
    #    here, for the portfolio engine to turn into a sell order (or not).
    held_reviews = {}
    for symbol in holdings:
        row = by_symbol.get(symbol)
        if not row or row.get("action") not in ("hold", "sell"):
            continue
        # bull = the case for holding; bear = the case for selling — the
        # same fields the shortlist debate already produces, reused here
        # rather than asking the AI for a third, redundant explanation.
        reason = row["bull"] if row["action"] == "hold" else row["bear"]
        held_reviews[symbol] = {"action": row["action"], "reason": reason}

    result = {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "data_source": data_source,
        "scope": scope_name or "all watchlists",
        "batches_failed": len(batch_errors),
        "shortlist": shortlist,
        "rows": rows,
        "held_reviews": held_reviews,
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
            f"- Stop-loss: {r['stop_loss']} ({r.get('stop_loss_pct', '?')}%)",
            f"- Planned entry price: "
            f"{'$' + str(r['entry_price']) if r.get('entry_price') is not None else 'AI price rejected — no order placed'}",
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
