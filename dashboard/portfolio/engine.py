"""
engine.py — the paper-trading portfolio. PRETEND money only.

How it works, in plain English:
  - The portfolio starts with $10,000 of pretend cash (rules.yaml).
  - "Sync" makes the portfolio mirror the latest shortlist:
      1. SELL any holding that fell off the shortlist.
      2. SELL any holding that's down more than the stop-loss % from what
         we paid — the discipline the stop-loss notes suggest.
      3. BUY each shortlisted ticker we don't hold yet: as many whole shares
         as fit under the per-pick cap (~$800, mirroring CMC's rule) and the
         remaining cash.
  - Every trade is logged, and the total value (cash + holdings at today's
    prices) is snapshotted once per day — that's the line the graph draws.

Everything lives in data/portfolio.json (gitignored — it's runtime data).
"""

from datetime import date, datetime

from ..config_loader import load_rules, load_universe
from ..storage import FileDoc, get_doc


class PaperPortfolio:
    def __init__(self, source, rules=None, state_path=None, flags_source=None):
        self.source = source                       # any PriceSource
        self.rules = (rules or load_rules())["portfolio"]
        # state_path — tests point this at a temp file; normally the
        # document lives wherever storage.py says (file, or cloud database).
        self.doc = FileDoc(state_path) if state_path else get_doc("portfolio")
        # Where to ask "which risk flags does this symbol carry?" — the app
        # passes the watchlist catalogue; the default (the old fixed
        # universe file) keeps existing tests working unchanged.
        self.flags_source = flags_source or (
            lambda: {a["symbol"]: set(a["flags"]) for a in load_universe()})
        self.state = self._load()

    # ── Saved state ─────────────────────────────────────────────────────
    def _fresh_state(self):
        # A brand-new portfolio: all cash, no positions, no history yet.
        return {
            "cash": self.rules["starting_cash"],
            "positions": {},   # symbol -> {shares, avg_cost, opened_at}
            "trades": [],      # every buy/sell ever made, with the reason
            "history": [],     # daily {date, total_value} points for the graph
        }

    def _load(self):
        return self.doc.load() or self._fresh_state()

    def _refresh(self):
        """Re-read before acting — on the cloud, two server workers share
        one database, and each must see the other's trades."""
        saved = self.doc.load()
        if saved is not None:
            self.state = saved

    def _save(self):
        self.doc.save(self.state)

    def reset(self):
        """Wipe everything and start over with fresh pretend cash."""
        self.state = self._fresh_state()
        self._save()

    # ── Valuation ───────────────────────────────────────────────────────
    def total_value(self):
        """Cash plus what every holding is worth at today's price."""
        value = self.state["cash"]
        for symbol, pos in self.state["positions"].items():
            value += pos["shares"] * self.source.get_quote(symbol)["price"]
        return round(value, 2)

    def _update_history_point(self):
        """Refresh today's total-value point in memory (no saving here).
        Returns (value, new_day) — new_day is True the first time each day."""
        today = date.today().isoformat()
        value = self.total_value()
        history = self.state["history"]
        if history and history[-1]["date"] == today:
            history[-1]["total_value"] = value
            return value, False
        history.append({"date": today, "total_value": value})
        return value, True

    def snapshot(self):
        """Record today's total value for the graph — one point per day
        (calling it again the same day just updates that point)."""
        value, _ = self._update_history_point()
        self._save()
        return value

    # ── Trading ─────────────────────────────────────────────────────────
    def _log_trade(self, action, symbol, shares, price, reason):
        self.state["trades"].append({
            "at": datetime.now().isoformat(timespec="seconds"),
            "action": action, "symbol": symbol, "shares": shares,
            "price": price, "reason": reason,
        })

    def _sell(self, symbol, price, reason):
        pos = self.state["positions"].pop(symbol)
        self.state["cash"] = round(self.state["cash"] + pos["shares"] * price, 2)
        self._log_trade("sell", symbol, pos["shares"], price, reason)

    def _buy(self, symbol, price, reason):
        # Spend at most the per-pick cap, and never more cash than we have.
        budget = min(self.rules["max_position_value"], self.state["cash"])
        shares = int(budget // price)  # whole shares only — CMC's rule
        if shares < 1:
            return  # can't afford even one share; skip quietly
        cost = round(shares * price, 2)
        self.state["cash"] = round(self.state["cash"] - cost, 2)
        self.state["positions"][symbol] = {
            "shares": shares,
            "avg_cost": price,
            "opened_at": date.today().isoformat(),
        }
        self._log_trade("buy", symbol, shares, price, reason)

    def sync_to_shortlist(self, shortlist, why=None, analyzed=None):
        """Make the portfolio mirror the shortlist (the 3 steps up top).
        Returns the list of trades made this sync.

        why — optional {symbol: reason text} from the analysis (conviction,
        bull case) so the trade log can explain each buy in plain English.

        analyzed — optional list of symbols the run actually looked at.
        When the analysis was scoped to ONE watchlist, holdings outside that
        scope are left alone — the run said nothing about them, so "not on
        the shortlist" is no reason to sell. (Without this, analysing a
        3-stock list and syncing would liquidate the whole portfolio.)
        Stop-loss discipline still applies to every holding. None means the
        run covered everything.
        """
        why = why or {}
        analyzed = set(analyzed) if analyzed is not None else None
        self._refresh()
        trades_before = len(self.state["trades"])
        excluded = set(self.rules["excluded_flags"])
        flags_by_symbol = self.flags_source()
        stop_loss = self.rules["stop_loss_pct"] / 100

        # 1 + 2: go through holdings and decide what to sell.
        for symbol in list(self.state["positions"].keys()):
            price = self.source.get_quote(symbol)["price"]
            pos = self.state["positions"][symbol]
            in_scope = analyzed is None or symbol in analyzed
            if in_scope and symbol not in shortlist:
                self._sell(symbol, price,
                           "dropped off the shortlist — the latest analysis "
                           "no longer ranks it in the top picks")
            elif price < pos["avg_cost"] * (1 - stop_loss):
                self._sell(symbol, price,
                           f"stop-loss: fell more than "
                           f"{self.rules['stop_loss_pct']}% below the "
                           f"${pos['avg_cost']} we paid")

        # 3: buy shortlisted tickers we don't hold.
        for symbol in shortlist:
            if symbol in self.state["positions"]:
                continue
            if flags_by_symbol.get(symbol, set()) & excluded:
                continue  # belt-and-braces: never buy risk-flagged products
            self._buy(symbol, self.source.get_quote(symbol)["price"],
                      why.get(symbol, "on the shortlist"))

        self.snapshot()  # also saves
        return self.state["trades"][trades_before:]

    # ── What the web page needs ─────────────────────────────────────────
    def summary(self):
        """Everything the portfolio panel displays, in one dict."""
        self._refresh()
        holdings = []
        for symbol, pos in sorted(self.state["positions"].items()):
            price = self.source.get_quote(symbol)["price"]
            value = round(pos["shares"] * price, 2)
            pl = round(value - pos["shares"] * pos["avg_cost"], 2)
            holdings.append({
                "symbol": symbol,
                "shares": pos["shares"],
                "avg_cost": pos["avg_cost"],
                "price": price,
                "value": value,
                "pl": pl,
                "pl_pct": round(pl / (pos["shares"] * pos["avg_cost"]) * 100, 2),
            })

        # Refresh today's graph point, but only WRITE when a new day starts.
        # summary() answers a page view — merely looking at the portfolio
        # shouldn't rewrite the saved state on every reload.
        total, new_day = self._update_history_point()
        if new_day:
            self._save()
        start = self.rules["starting_cash"]
        return {
            "cash": self.state["cash"],
            "total_value": total,
            "since_start_pct": round((total - start) / start * 100, 2),
            "holdings": holdings,
            "history": self.state["history"],
            "trades": self.state["trades"],  # the full log: when + what + why
        }
