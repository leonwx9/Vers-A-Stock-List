"""
base.py — the common "plug socket" every price source must fit.

The rest of the app only ever talks to this interface. Today the plug is
filled by SampleSource (fake data); in milestone 6 a live source slots in,
and later a crypto source can too — with zero changes to the UI or analysis.
"""

from abc import ABC, abstractmethod


class PriceSource(ABC):
    """What any price source must be able to do.

    "ABC" = abstract base class: Python's way of saying "this is a contract,
    not a working class — subclasses must fill in the methods below".
    """

    @abstractmethod
    def get_history(self, symbol, days):
        """Return daily price bars for a symbol, oldest first.

        Shape: a list of dicts, one per day:
          {"date": "YYYY-MM-DD", "open": float, "high": float,
           "low": float, "close": float, "volume": int}
        The symbol is just a string, so non-stock assets (crypto later)
        work through the same interface.
        """

    def get_quote(self, symbol):
        """Return the latest price plus short-term changes for one symbol.

        Built on top of get_history so subclasses get it for free.
        """
        history = self.get_history(symbol, days=31)
        latest = history[-1]["close"]

        def pct_change(days_back):
            # % move from `days_back` trading days ago to now.
            past = history[-(days_back + 1)]["close"]
            return round((latest - past) / past * 100, 2)

        return {
            "symbol": symbol,
            "price": round(latest, 2),
            "change_5d_pct": pct_change(5),
            "change_30d_pct": pct_change(30),
        }

    def get_stats(self, symbol):
        """Apple-Stocks-style statistics computed from the price history.

        Fundamental numbers (market cap, P/E) need a live data source, so
        they're not here — the detail page shows those from milestone 6.
        """
        history = self.get_history(symbol, days=365)
        today = history[-1]
        yesterday = history[-2]
        closes = [d["close"] for d in history]
        return {
            "open": today["open"],
            "high": today["high"],
            "low": today["low"],
            "prev_close": yesterday["close"],
            "day_change_pct": round(
                (today["close"] - yesterday["close"]) / yesterday["close"] * 100, 2
            ),
            "week52_high": round(max(closes), 2),
            "week52_low": round(min(closes), 2),
            "avg_volume_30d": int(
                sum(d["volume"] for d in history[-30:]) / 30
            ),
            "volume": today["volume"],
        }
