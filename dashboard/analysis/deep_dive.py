"""
deep_dive.py — the in-depth, per-ticker rating explanation.

Where searcher.py gives every ticker a quick verdict, this module produces
the full story for ONE ticker, in the spirit of Danelfin's published ratings
but in plain English: technical / sentiment / fundamentals scores, each with
an explanation a beginner can follow, and — crucially — the sentiment claims
must point at the actual news headlines we fetched, not vague hand-waving.

Results are cached (one document per symbol — file or cloud database, see
storage.py) so revisiting a page is free and instant; the Refresh button
forces a new AI call.
"""

import json
import re
from datetime import datetime

from ..storage import get_doc

SYSTEM_PROMPT = """\
You are the analysis engine inside a private paper-trading dashboard.
Nothing you write is investment advice; no real money is traded.
Write in PLAIN ENGLISH for a beginner: short sentences, no unexplained
jargon (if a technical term is unavoidable, explain it in brackets).
You respond ONLY with a JSON object — no prose before or after it."""

DEEP_DIVE_PROMPT = """\
Produce an in-depth rating explanation for {symbol} ({name}), a {type}{flags_note}.

Context from the latest quick screen (simulated prices — treat the trend only
as illustrative momentum): price ${price}, 5-day {change_5d_pct:+}%,
30-day {change_30d_pct:+}%, conviction score {conviction}/10.

Recent real news headlines fetched just now:
{headlines_block}

Rules for honesty:
- SENTIMENT claims must be grounded in the headlines above. In "evidence",
  quote the exact headline titles you are drawing on and say what each one
  tells us. If no headlines were provided, say sentiment evidence is
  unavailable right now — do not invent articles.
- FUNDAMENTALS come from your general knowledge of the company, which may be
  months out of date — say so where it matters.
- Do not mention the simulated prices as if they were real market data.

Return ONE JSON object with exactly these keys:
  "overview":         2-3 plain-English sentences: what this company/fund
                      actually does and where it stands right now
  "rating_rationale": 2-4 sentences: WHY it earned conviction {conviction}/10,
                      in plain English
  "technical":    {{"score": 1-10, "explanation": "2-3 sentences on price
                   momentum/trend, plain English"}}
  "sentiment":    {{"score": 1-10, "explanation": "2-3 sentences on the mood
                   around the stock and WHY it is that way",
                   "evidence": [{{"headline": "exact title", "takeaway":
                   "what this article tells us, 1 sentence"}}]}}
  "fundamentals": {{"score": 1-10, "explanation": "2-3 sentences on the
                   business itself: is it making money, growing, moat"}}
  "risks":            array of 2-4 short strings — the main things that could
                      go wrong
  "what_would_change": 1-2 sentences: what news or events would make this
                      rating go up or down"""


def _cache_doc(symbol):
    # BRK/B → deepdive_BRK-B (slashes can't appear in document names).
    return get_doc(f"deepdive_{symbol.replace('/', '-')}")


def load_cached(symbol):
    """Return the saved deep dive for a symbol, or None."""
    return _cache_doc(symbol).load()


def parse_deep_dive_response(text):
    """Pull the JSON object out of the AI's reply (stripping ``` fences)."""
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object found in AI reply: {text[:200]}")
    return json.loads(cleaned[start : end + 1])


def run_deep_dive(provider, asset, quote, headlines, conviction):
    """Generate, cache and return the deep dive for one asset."""
    if headlines:
        headlines_block = "\n".join(
            f'- "{h["title"]}" ({h["source"]}, {h["published"]})'
            for h in headlines
        )
    else:
        headlines_block = "(none could be fetched right now)"

    flags_note = (
        f" flagged as {', '.join(asset['flags'])} — a complex high-risk product"
        if asset["flags"] else ""
    )

    prompt = DEEP_DIVE_PROMPT.format(
        symbol=asset["symbol"], name=asset["name"], type=asset["type"],
        flags_note=flags_note, price=quote["price"],
        change_5d_pct=quote["change_5d_pct"], change_30d_pct=quote["change_30d_pct"],
        conviction=conviction, headlines_block=headlines_block,
    )

    reply = provider.complete(SYSTEM_PROMPT, prompt, max_tokens=2000)
    result = parse_deep_dive_response(reply)
    result["symbol"] = asset["symbol"]
    result["generated_at"] = datetime.now().isoformat(timespec="seconds")

    _cache_doc(asset["symbol"]).save(result)
    return result
