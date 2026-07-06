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
            # % move from `days_back` trading days ago to now. A stock
            # younger than the period (a recent IPO like SPCX) doesn't have
            # that many bars — clamp to its earliest one instead of crashing.
            past = history[max(0, len(history) - 1 - days_back)]["close"]
            return round((latest - past) / past * 100, 2)

        return {
            "symbol": symbol,
            "price": round(latest, 2),
            "change_5d_pct": pct_change(5),
            "change_30d_pct": pct_change(30),
        }

    # The change periods the UI offers, measured in trading days (markets
    # trade ~21 days a month, ~250 a year). "ALL" means "since the earliest
    # bar this source has".
    CHANGE_PERIODS = {"1D": 1, "1W": 5, "1M": 21, "3M": 63, "1Y": 250, "5Y": 1250}

    def get_changes(self, symbol):
        """% price change over each standard period, e.g. {"1D": -0.4, ...}.

        If a period reaches further back than the available history, the
        earliest bar is used instead (better an honest approximation than
        a blank). Subclasses with deeper archives can override (LiveSource
        does, for 5Y and ALL).
        """
        history = self.get_history(symbol, days=1300)
        latest = history[-1]["close"]

        def pct_from(bars_back):
            past = history[max(0, len(history) - 1 - bars_back)]["close"]
            return round((latest - past) / past * 100, 2)

        changes = {name: pct_from(n) for name, n in self.CHANGE_PERIODS.items()}
        changes["ALL"] = pct_from(len(history))  # clamps to the first bar
        return changes

    def get_stats(self, symbol):
        """Apple-Stocks-style statistics computed from the price history.

        Fundamental numbers (market cap, P/E) need a live data source, so
        they're not here — the detail page shows those from milestone 6.
        """
        history = self.get_history(symbol, days=365)
        today = history[-1]
        # A stock that listed yesterday has no "previous close" — fall back
        # to its only bar (day change reads 0%) rather than crash.
        yesterday = history[-2] if len(history) > 1 else history[-1]
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
                # Average over however many of the last 30 days exist.
                sum(d["volume"] for d in history[-30:]) / len(history[-30:])
            ),
            "volume": today["volume"],
        }
