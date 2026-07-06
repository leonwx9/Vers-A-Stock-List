"""
stock_search.py — free-range stock lookup: ticker or company name → matches.

Uses Yahoo Finance's public search endpoint (same free, key-less family as
our price data, with the same mirror-host fallback). This is a plain
lookup — no AI involved — so browsing/searching costs nothing no matter
how many stocks the user looks at.
"""

import requests

SEARCH_URLS = [
    "https://query1.finance.yahoo.com/v1/finance/search",
    "https://query2.finance.yahoo.com/v1/finance/search",  # mirror
]

# Yahoo's codes for the US exchanges. "US-listed" means one of these —
# foreign listings and over-the-counter (PNK) results are filtered out.
US_EXCHANGES = {
    "NMS": "Nasdaq",   # Nasdaq Global Select
    "NGM": "Nasdaq",   # Nasdaq Global Market
    "NCM": "Nasdaq",   # Nasdaq Capital Market
    "NYQ": "NYSE",
    "ASE": "NYSE American",
    "PCX": "NYSE Arca",
    "BTS": "Cboe BZX",
}

# Yahoo's asset types → ours (anything else, e.g. futures/currencies, is
# dropped). A future "crypto" type would be one more line here.
TYPE_MAP = {"EQUITY": "stock", "ETF": "etf"}


def parse_search(payload):
    """Turn Yahoo's search JSON into our standard match list.

    Pure function so tests can feed it canned JSON. Each match:
      {"symbol", "name", "type", "exchange"}
    """
    matches = []
    for q in payload.get("quotes", []):
        asset_type = TYPE_MAP.get(q.get("quoteType"))
        exchange = US_EXCHANGES.get(q.get("exchange"))
        name = q.get("shortname") or q.get("longname")
        if not (asset_type and exchange and name and q.get("symbol")):
            continue
        matches.append({
            "symbol": q["symbol"],
            "name": name,
            "type": asset_type,
            "exchange": exchange,
        })
    return matches


def search_stocks(query, limit=8):
    """Search US-listed stocks/ETFs by ticker or company name.

    Raises RuntimeError if Yahoo can't be reached — the caller shows that
    as an error, which is more honest than pretending 'no results'.
    """
    last_error = None
    for url in SEARCH_URLS:
        try:
            response = requests.get(
                url,
                params={"q": query, "quotesCount": 20, "newsCount": 0},
                headers={"User-Agent": "Mozilla/5.0"},  # Yahoo rejects bare scripts
                timeout=10,
            )
            response.raise_for_status()
            return parse_search(response.json())[:limit]
        except Exception as e:
            last_error = e
    raise RuntimeError(f"Stock search is unavailable right now: {last_error}")
