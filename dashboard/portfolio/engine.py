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

import json
from datetime import date, datetime
from pathlib import Path

from ..config_loader import load_rules, load_universe

STATE_PATH = Path(__file__).parent.parent / "data" / "portfolio.json"


class PaperPortfolio:
    def __init__(self, source, rules=None, state_path=None):
        self.source = source                       # any PriceSource
        self.rules = (rules or load_rules())["portfolio"]
        self.state_path = Path(state_path or STATE_PATH)
        self.state = self._load()

    # ── State on disk ───────────────────────────────────────────────────
    def _load(self):
        if self.state_path.exists():
            with open(self.state_path) as f:
                return json.load(f)
        # A brand-new portfolio: all cash, no positions, no history yet.
        return {
            "cash": self.rules["starting_cash"],
            "positions": {},   # symbol -> {shares, avg_cost, opened_at}
            "trades": [],      # every buy/sell ever made
            "history": [],     # daily {date, total_value} points for the graph
        }

    def _save(self):
        self.state_path.parent.mkdir(exist_ok=True)
        with open(self.state_path, "w") as f:
            json.dump(self.state, f, indent=2)

    def reset(self):
        """Wipe everything and start over with fresh pretend cash."""
        self.state_path.unlink(missing_ok=True)
        self.state = self._load()
        self._save()

    # ── Valuation ───────────────────────────────────────────────────────
    def total_value(self):
        """Cash plus what every holding is worth at today's price."""
        value = self.state["cash"]
        for symbol, pos in self.state["positions"].items():
            value += pos["shares"] * self.source.get_quote(symbol)["price"]
        return round(value, 2)

    def snapshot(self):
        """Record today's total value for the graph — one point per day
        (calling it again the same day just updates that point)."""
        today = date.today().isoformat()
        value = self.total_value()
        history = self.state["history"]
        if history and history[-1]["date"] == today:
            history[-1]["total_value"] = value
        else:
            history.append({"date": today, "total_value": value})
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

    def sync_to_shortlist(self, shortlist):
        """Make the portfolio mirror the shortlist (the 3 steps up top).
        Returns the list of trades made this sync."""
        trades_before = len(self.state["trades"])
        excluded = set(self.rules["excluded_flags"])
        flags_by_symbol = {a["symbol"]: set(a["flags"]) for a in load_universe()}
        stop_loss = self.rules["stop_loss_pct"] / 100

        # 1 + 2: go through holdings and decide what to sell.
        for symbol in list(self.state["positions"].keys()):
            price = self.source.get_quote(symbol)["price"]
            pos = self.state["positions"][symbol]
            if symbol not in shortlist:
                self._sell(symbol, price, "dropped off shortlist")
            elif price < pos["avg_cost"] * (1 - stop_loss):
                self._sell(symbol, price, f"stop-loss: down >{self.rules['stop_loss_pct']}% from entry")

        # 3: buy shortlisted tickers we don't hold.
        for symbol in shortlist:
            if symbol in self.state["positions"]:
                continue
            if flags_by_symbol.get(symbol, set()) & excluded:
                continue  # belt-and-braces: never buy risk-flagged products
            self._buy(symbol, self.source.get_quote(symbol)["price"],
                      "on shortlist")

        self.snapshot()  # also saves
        return self.state["trades"][trades_before:]

    # ── What the web page needs ─────────────────────────────────────────
    def summary(self):
        """Everything the portfolio panel displays, in one dict."""
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

        total = self.snapshot()  # refresh today's graph point while we're here
        start = self.rules["starting_cash"]
        return {
            "cash": self.state["cash"],
            "total_value": total,
            "since_start_pct": round((total - start) / start * 100, 2),
            "holdings": holdings,
            "history": self.state["history"],
            "trades": self.state["trades"][-20:],  # the recent activity feed
        }
