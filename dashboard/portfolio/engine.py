"""
engine.py — the paper-trading portfolio. PRETEND money only.

How it works, in plain English:
  - The portfolio starts with $10,000 of pretend cash (rules.yaml).
  - Every analysis run PLACES ORDERS instead of trading instantly:
      - a planned BUY (at the AI's own entry price, with its own per-stock
        stop-loss %) for each freshly-shortlisted pick not already held;
      - a SELL for any current holding the AI's review says to part with.
    Placing a new run's orders first cancels whatever was still pending
    from the run before — orders live for roughly 1-2 days, then are
    replaced by fresh thinking.
  - Orders then FILL THEMSELVES, with no button to press. Every time the
    dashboard is opened, process_fills() checks the real daily trading
    bars since each order was placed:
      - a BUY fills the first session whose price reaches the planned
        entry (at the session's OPEN if it gapped below the plan, or at
        the plan's own price if the session merely dipped to it);
      - a SELL fills at the next session's OPENING price;
      - every holding is ALSO checked against its own stop-loss percentage
        (chosen by the AI when it was bought) — a session that CLOSES
        more than that percentage below the purchase price sells it,
        regardless of what any order says.
    Because Leon is in Sydney, the US market is always closed while he's
    using the app — so "check what's happened since I last looked" is
    exactly the right way to run pretend trading without a real broker.
  - Every trade (buy or sell, whether from an order or a stop-loss) is
    logged with a plain-English reason, and the total value (cash +
    holdings at today's prices) is snapshotted once per day for the graph.

Everything lives in data/portfolio.json (gitignored — it's runtime data;
or the cloud database, if DATABASE_URL is set — see storage.py).
"""

import secrets
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from ..config_loader import load_rules, load_universe
from ..storage import FileDoc, get_doc

# All fill decisions are made in NEW YORK time, because that's the calendar
# the stock market itself runs on — not wherever this server happens to be.
NY_TZ = ZoneInfo("America/New_York")


def _new_order_id():
    # Random, not a counter: the cloud runs several server workers as
    # separate processes, each with its own memory — a per-process counter
    # could hand out the same id twice. Random bytes can't collide that way
    # (same trick as the watchlist ids).
    return "ord-" + secrets.token_hex(4)


def _eligible_from_date(placed_at_utc):
    """The first NY calendar date (YYYY-MM-DD) an order is allowed to fill
    against: the day AFTER the NY date it was placed on. This guarantees an
    order can never fill in the very session during which it was created —
    even if that session's bar isn't finished yet. Weekends need no special
    handling: there's simply no trading bar on those dates, so the order
    just waits until the next real session."""
    placed_ny_date = placed_at_utc.astimezone(NY_TZ).date()
    return (placed_ny_date + timedelta(days=1)).isoformat()


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
            "positions": {},   # symbol -> {shares, avg_cost, opened_at, stop_loss_pct}
            "orders": [],      # pending/filled/replaced orders — see place_orders()
            "trades": [],      # every buy/sell ever made, with the reason
            "history": [],     # daily {date, total_value} points for the graph
        }

    def _load(self):
        state = self.doc.load() or self._fresh_state()
        # Migration: portfolios saved before "orders" existed just don't
        # have the key yet — treat that as "nothing pending", not an error.
        state.setdefault("orders", [])
        return state

    def _refresh(self):
        """Re-read before acting — on the cloud, two server workers share
        one database, and each must see the other's trades/orders."""
        saved = self.doc.load()
        if saved is not None:
            saved.setdefault("orders", [])
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
    def _log_trade(self, action, symbol, shares, price, reason, at=None):
        """`at` lets a FILL log itself under the trading SESSION's date
        (e.g. "2026-07-08") rather than the moment process_fills happened
        to run — the trade log should say when it happened in the market,
        not when Leon's browser happened to ask."""
        self.state["trades"].append({
            "at": at or datetime.now().isoformat(timespec="seconds"),
            "action": action, "symbol": symbol, "shares": shares,
            "price": price, "reason": reason,
        })

    def current_positions(self):
        """{symbol: {avg_cost, shares}} for every current holding — the
        analysis uses this to know which stocks must get a HOLD/SELL
        review even if they're outside the run's watchlist scope."""
        self.process_fills()
        return {s: {"avg_cost": p["avg_cost"], "shares": p["shares"]}
                for s, p in self.state["positions"].items()}

    # ── Placing orders (after every analysis run) ────────────────────────
    def place_orders(self, rows, shortlist, held_reviews, now=None, analyzed=None):
        """Turn one analysis run into orders. Called right after
        run_analysis(). Returns the list of orders just created.

        rows — every analysed row (symbol, conviction, bull, entry_price,
               stop_loss_pct, …), used to look up shortlisted picks' details.
        shortlist — ranked list of symbols eligible to buy (already
               excludes flagged/bear-verdict rows — see searcher.py).
        held_reviews — {symbol: {"action": "hold"/"sell", "reason": ...}}
               for every currently-held stock this run reviewed.
        now — the placement instant (timezone-aware); defaults to real
               "now". Tests pass a fixed value for deterministic dates.
        analyzed — optional list/set of symbols THIS run actually
               analysed. None (the default) means "the whole universe" —
               every pending order gets replaced, exactly as before. Pass
               it when a run is narrowly scoped (e.g. the overnight
               scheduler's price-watch-triggered run, which analyses only
               the one or two stocks that reached their level) — a run
               that says nothing about a stock must never cancel that
               stock's still-pending order from an earlier, broader run.
        """
        now = now or datetime.now(timezone.utc)
        self.process_fills(now=now)  # settle anything outstanding first
        by_symbol = {r["symbol"]: r for r in rows}
        excluded = set(self.rules["excluded_flags"])
        flags_by_symbol = self.flags_source()
        placed_at = now.isoformat(timespec="seconds")
        eligible_from = _eligible_from_date(now)
        analyzed = set(analyzed) if analyzed is not None else None

        # A fresh run supersedes whatever was still pending FOR THE
        # SYMBOLS IT ACTUALLY ANALYSED — Leon's own mental model: settle
        # the past, review holdings, THEN place fresh orders for the next
        # session. Orders for symbols OUTSIDE a scoped run are left
        # exactly as they were; a scoped run has nothing new to say about
        # them, so it must not touch them.
        for order in self.state["orders"]:
            if order["status"] != "pending":
                continue
            if analyzed is not None and order["symbol"] not in analyzed:
                continue
            order["status"] = "replaced"

        new_orders = []

        # 1. SELL orders for holdings the AI's review says to part with.
        for symbol, review in held_reviews.items():
            if review.get("action") != "sell":
                continue
            if symbol not in self.state["positions"]:
                continue  # nothing to sell (already gone)
            new_orders.append({
                "id": _new_order_id(), "type": "sell", "symbol": symbol,
                "placed_at": placed_at, "eligible_from": eligible_from,
                "reason": review.get("reason") or "AI review: sell",
                "status": "pending",
            })

        # 2. BUY orders for freshly-shortlisted picks we don't already
        #    hold — highest conviction first, so if cash ever runs short
        #    at fill time, the strongest picks are served first.
        cap = self.rules["max_position_value"]
        default_slp = self.rules.get("stop_loss_pct", 10)
        ranked = sorted(shortlist,
                        key=lambda s: by_symbol.get(s, {}).get("conviction", 0),
                        reverse=True)
        for symbol in ranked:
            if symbol in self.state["positions"]:
                continue  # already own it — nothing new to buy
            if flags_by_symbol.get(symbol, set()) & excluded:
                continue  # belt-and-braces: never buy risk-flagged products
            row = by_symbol.get(symbol, {})
            reason = (f"conviction {row.get('conviction', '?')}/10 — "
                     f"bull case: {row.get('bull', '')}")
            entry_price = row.get("entry_price")
            if entry_price is None:
                # The AI's price failed the sanity check (see
                # searcher.parse_batch_response) — record that plainly
                # instead of silently dropping the pick or guessing a price.
                new_orders.append({
                    "id": _new_order_id(), "type": "buy", "symbol": symbol,
                    "placed_at": placed_at, "eligible_from": eligible_from,
                    "reason": reason, "status": "skipped_bad_price",
                })
                continue
            new_orders.append({
                "id": _new_order_id(), "type": "buy", "symbol": symbol,
                "limit_price": entry_price, "budget": cap,
                "conviction": row.get("conviction", 0),
                "stop_loss_pct": row.get("stop_loss_pct", default_slp),
                "placed_at": placed_at, "eligible_from": eligible_from,
                "reason": reason, "status": "pending",
            })

        self.state["orders"].extend(new_orders)
        self._save()
        return new_orders

    # ── Filling orders (self-driving — called before every page view) ───
    def process_fills(self, now=None):
        """Settle every pending order, and check every holding's
        stop-loss, against completed trading sessions since they became
        eligible. This is what makes the portfolio "trade" without a
        button: called at the top of current_positions(), place_orders(),
        and summary(), so by the time anything reads the state, it
        already reflects everything the market has done since last time.
        """
        self._refresh()
        now = now or datetime.now(timezone.utc)
        today_ny = now.astimezone(NY_TZ).date().isoformat()

        pending_orders = [o for o in self.state["orders"] if o["status"] == "pending"]
        if not pending_orders and not self.state["positions"]:
            return  # nothing that could possibly need settling

        # Fetch each symbol's history ONCE — every symbol with a pending
        # order, plus every symbol currently held (for stop-loss checks,
        # which aren't tied to any specific order).
        symbols = {o["symbol"] for o in pending_orders} | set(self.state["positions"])
        bars_by_symbol = {}
        for symbol in symbols:
            try:
                bars_by_symbol[symbol] = {
                    bar["date"]: bar for bar in self.source.get_history(symbol, days=400)
                }
            except Exception:
                bars_by_symbol[symbol] = {}  # a data hiccup shouldn't break the page

        # Only ever look at COMPLETED sessions — a bar dated today-in-NY
        # may still be forming (e.g. if this happens to run during market
        # hours), so it's excluded even though Leon's own routine means
        # that's not the normal case.
        all_dates = sorted({
            d for bars in bars_by_symbol.values() for d in bars if d < today_ny
        })

        excluded = set(self.rules["excluded_flags"])
        flags_by_symbol = self.flags_source()
        changed = False

        for session_date in all_dates:
            # 1. SELL orders due this session — fill at the OPEN.
            for order in pending_orders:
                if order["status"] != "pending" or order["type"] != "sell":
                    continue
                if session_date < order["eligible_from"]:
                    continue
                bar = bars_by_symbol.get(order["symbol"], {}).get(session_date)
                if not bar:
                    continue
                self._fill_sell(order, bar, session_date)
                changed = True

            # 2. Stop-loss: every CURRENT holding, using its OWN percentage
            #    (chosen by the AI at buy time; older positions fall back
            #    to the portfolio-wide default). Checked on the CLOSE, so a
            #    brief intraday dip that recovers by the bell doesn't sell.
            for symbol, pos in list(self.state["positions"].items()):
                if session_date <= pos["opened_at"]:
                    continue  # never check a bar from before we owned it
                bar = bars_by_symbol.get(symbol, {}).get(session_date)
                if not bar:
                    continue
                pct = pos.get("stop_loss_pct", self.rules.get("stop_loss_pct", 10))
                threshold = pos["avg_cost"] * (1 - pct / 100)
                if bar["close"] < threshold:
                    self._sell_position(
                        symbol, bar["close"], session_date,
                        f"stop-loss: closed at ${bar['close']}, more than "
                        f"{pct}% below the ${pos['avg_cost']} we paid")
                    changed = True

            # 3. BUY orders due this session — highest conviction first, so
            #    if cash is short, the strongest pick gets served first;
            #    a later one simply sizes smaller or stays pending.
            due_buys = [o for o in pending_orders
                       if o["status"] == "pending" and o["type"] == "buy"
                       and session_date >= o["eligible_from"]]
            due_buys.sort(key=lambda o: o.get("conviction", 0), reverse=True)
            for order in due_buys:
                bar = bars_by_symbol.get(order["symbol"], {}).get(session_date)
                if not bar:
                    continue
                if order["symbol"] in self.state["positions"]:
                    order["status"] = "replaced"  # already bought some other way
                    continue
                if flags_by_symbol.get(order["symbol"], set()) & excluded:
                    order["status"] = "replaced"  # newly flagged since placement
                    continue
                if self._fill_buy(order, bar, session_date):
                    changed = True

        if changed:
            self._save()

    def _fill_buy(self, order, bar, session_date):
        """Fill a pending BUY against one session's bar. A real limit
        order never pays MORE than its limit — if the session opened
        below the plan (a gap down), that cheaper open is the fill price;
        otherwise, if the session merely dipped down TO the limit, it
        fills at the limit itself. Returns True if a trade happened."""
        limit = order["limit_price"]
        if bar["open"] <= limit:
            price = bar["open"]
        elif bar["low"] <= limit:
            price = limit
        else:
            return False  # never reached the planned price this session

        # Fill-time sizing: budget is a CAP, not a reservation — size the
        # buy from whatever cash actually exists right now. Zero shares
        # means "not yet affordable" — the order stays pending and is
        # retried the next session.
        budget = min(order["budget"], self.state["cash"])
        shares = int(budget // price)
        if shares < 1:
            return False

        cost = round(shares * price, 2)
        self.state["cash"] = round(self.state["cash"] - cost, 2)
        self.state["positions"][order["symbol"]] = {
            "shares": shares, "avg_cost": price, "opened_at": session_date,
            "stop_loss_pct": order.get("stop_loss_pct",
                                       self.rules.get("stop_loss_pct", 10)),
        }
        order["status"] = "filled"
        order["filled_at"] = session_date
        order["filled_price"] = price
        self._log_trade("buy", order["symbol"], shares, price,
                        f"{order['reason']} — filled at ${price} "
                        f"(session {session_date})", at=session_date)
        return True

    def _fill_sell(self, order, bar, session_date):
        """Fill a pending SELL at the session's OPEN — a plain market
        order, since the decision to sell doesn't come with a price plan."""
        if order["symbol"] not in self.state["positions"]:
            # Already gone (e.g. a stop-loss beat this order to it) —
            # there's nothing left to sell; close the order out honestly.
            order["status"] = "cancelled"
            order["cancelled_reason"] = "already sold before this order's turn"
            return
        price = bar["open"]
        pos = self.state["positions"].pop(order["symbol"])
        self.state["cash"] = round(self.state["cash"] + pos["shares"] * price, 2)
        order["status"] = "filled"
        order["filled_at"] = session_date
        order["filled_price"] = price
        self._log_trade("sell", order["symbol"], pos["shares"], price,
                        f"{order['reason']} — filled at ${price} "
                        f"(session {session_date})", at=session_date)

    def _sell_position(self, symbol, price, session_date, reason):
        """A stop-loss sale — not tied to any order, since it's an
        automatic safety net that overrides whatever else was planned."""
        pos = self.state["positions"].pop(symbol)
        self.state["cash"] = round(self.state["cash"] + pos["shares"] * price, 2)
        self._log_trade("sell", symbol, pos["shares"], price, reason, at=session_date)

    # ── What the web page needs ─────────────────────────────────────────
    def summary(self):
        """Everything the portfolio panel displays, in one dict."""
        self.process_fills()
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
                "stop_loss_pct": pos.get("stop_loss_pct",
                                        self.rules.get("stop_loss_pct", 10)),
            })

        # Refresh today's graph point, but only WRITE when a new day starts.
        # summary() answers a page view — merely looking at the portfolio
        # shouldn't rewrite the saved state on every reload.
        total, new_day = self._update_history_point()
        if new_day:
            self._save()
        start = self.rules["starting_cash"]
        pending = [o for o in self.state["orders"] if o["status"] == "pending"]
        # The most recent ~15 non-pending orders, so the panel can show a
        # little history without the list growing forever.
        recent_other = [o for o in self.state["orders"] if o["status"] != "pending"][-15:]
        return {
            "cash": self.state["cash"],
            "total_value": total,
            "since_start_pct": round((total - start) / start * 100, 2),
            "holdings": holdings,
            "history": self.state["history"],
            "trades": self.state["trades"],  # the full log: when + what + why
            "orders": pending + recent_other,
        }
