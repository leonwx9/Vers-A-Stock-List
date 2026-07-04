"""
live_source.py — REAL market prices, fitted to the same PriceSource socket
as the sample data. Milestone 6: because everything else talks to the
interface, swapping fake→real needed zero changes elsewhere.

Data comes from Yahoo Finance's public chart API — free, no key. Etiquette:
  - results are cached in memory for a few minutes, so redrawing a page
    doesn't re-download anything;
  - if Yahoo's main host hiccups, we retry once on its mirror host.

A symbol like BRK/B is written BRK-B in Yahoo's world — mapped here so the
rest of the app can keep using the CMC-style symbol.
"""

import time

import requests

from .base import PriceSource

CHART_URLS = [
    "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
    "https://query2.finance.yahoo.com/v8/finance/chart/{symbol}",  # mirror
]

CACHE_TTL_SECONDS = 300  # how long a downloaded series stays fresh (5 min)


def to_yahoo_symbol(symbol):
    """CMC writes BRK/B; Yahoo writes BRK-B."""
    return symbol.replace("/", "-")


def parse_chart(payload):
    """Turn Yahoo's chart JSON into our standard list of daily bars.

    Kept as a pure function so tests can feed it canned JSON. Yahoo
    occasionally has a null bar (halted day); those are skipped.
    """
    result = payload["chart"]["result"][0]
    timestamps = result["timestamp"]
    quote = result["indicators"]["quote"][0]

    history = []
    for i, ts in enumerate(timestamps):
        if quote["close"][i] is None:
            continue
        history.append({
            "date": time.strftime("%Y-%m-%d", time.gmtime(ts)),
            "open": round(quote["open"][i], 2),
            "high": round(quote["high"][i], 2),
            "low": round(quote["low"][i], 2),
            "close": round(quote["close"][i], 2),
            "volume": int(quote["volume"][i] or 0),
        })
    return history


class LiveSource(PriceSource):
    """Real daily prices from Yahoo Finance, behind the standard socket."""

    def __init__(self):
        self._cache = {}  # symbol -> (fetched_at, history)

    def _fetch(self, symbol):
        """Download ~1 year of daily bars for one symbol, trying the mirror
        host if the first fails."""
        last_error = None
        for url in CHART_URLS:
            try:
                response = requests.get(
                    url.format(symbol=to_yahoo_symbol(symbol)),
                    params={"range": "1y", "interval": "1d"},
                    headers={"User-Agent": "Mozilla/5.0"},  # Yahoo rejects bare scripts
                    timeout=15,
                )
                response.raise_for_status()
                return parse_chart(response.json())
            except Exception as e:
                last_error = e
        raise RuntimeError(f"Could not fetch live prices for {symbol}: {last_error}")

    def get_history(self, symbol, days):
        now = time.time()
        cached = self._cache.get(symbol)
        if cached is None or now - cached[0] > CACHE_TTL_SECONDS:
            self._cache[symbol] = (now, self._fetch(symbol))
        history = self._cache[symbol][1]
        return history[-days:]
