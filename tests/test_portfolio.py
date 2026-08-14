"""Tests for the paper-trading engine's order/fill model.

Orders are placed by place_orders() (what an analysis run does) and fill
themselves later via process_fills() against real trading-session bars —
no button, no instant buying. A ScriptedSource stands in for real prices
so each test can hand-craft the exact opens/highs/lows/closes it needs.
"""

import json
from datetime import datetime, timezone

from dashboard.portfolio.engine import PaperPortfolio

RULES = {"portfolio": {
    "starting_cash": 10000,
    "max_position_value": 800,
    "excluded_flags": ["leveraged", "inverse", "volatility"],
    "shortlist_size": 5,
    "stop_loss_pct": 10,
}}


class ScriptedSource:
    """A price source whose daily bars are exactly what the test hands
    it — unlike SampleSource's randomised walk, this gives full control
    over which sessions trigger which fills."""

    def __init__(self, bars_by_symbol):
        self.bars_by_symbol = bars_by_symbol  # {symbol: [bar, ...]} oldest-first

    def get_history(self, symbol, days):
        return self.bars_by_symbol.get(symbol, [])[-days:]

    def get_quote(self, symbol):
        bars = self.bars_by_symbol.get(symbol, [])
        price = bars[-1]["close"] if bars else 0
        return {"symbol": symbol, "price": price,
               "change_5d_pct": 0, "change_30d_pct": 0}


def bar(date_str, open_, high, low, close):
    return {"date": date_str, "open": open_, "high": high, "low": low,
           "close": close, "volume": 1_000_000}


def make_portfolio(tmp_path, bars_by_symbol):
    return PaperPortfolio(ScriptedSource(bars_by_symbol), rules=RULES,
                          state_path=tmp_path / "portfolio.json")


def _row(symbol, conviction=7, entry_price=100.0, stop_loss_pct=10, bull="good buy"):
    return {"symbol": symbol, "conviction": conviction, "bull": bull,
           "bear": "risk exists", "entry_price": entry_price,
           "stop_loss_pct": stop_loss_pct}


# Placement instant: 2026-01-05 22:00 UTC = 17:00 EST (after market close)
# → the order becomes eligible starting the NEXT session, 2026-01-06.
PLACE_NOW = datetime(2026, 1, 5, 22, 0, tzinfo=timezone.utc)
# A "check" instant comfortably after every test bar below, so every
# session in these tests counts as a completed one.
CHECK_NOW = datetime(2026, 1, 12, 15, 0, tzinfo=timezone.utc)


def test_starts_with_10k_cash_and_no_positions(tmp_path):
    pf = make_portfolio(tmp_path, {})
    assert pf.state["cash"] == 10000
    assert pf.state["positions"] == {}
    assert pf.total_value() == 10000


# ── Buy fills ─────────────────────────────────────────────────────────────

def test_buy_order_fills_when_a_later_session_dips_to_the_limit(tmp_path):
    bars = {"NVDA": [bar("2026-01-06", 130, 132, 127, 131)]}
    pf = make_portfolio(tmp_path, bars)
    pf.place_orders([_row("NVDA", entry_price=128)], ["NVDA"], {}, now=PLACE_NOW)
    pf.process_fills(now=CHECK_NOW)

    assert "NVDA" in pf.state["positions"]
    assert pf.state["positions"]["NVDA"]["avg_cost"] == 128  # filled AT the limit
    assert pf.state["positions"]["NVDA"]["shares"] == int(800 // 128)


def test_buy_order_does_not_fill_when_the_low_never_reaches_the_limit(tmp_path):
    bars = {"NVDA": [bar("2026-01-06", 130, 132, 127, 131)]}
    pf = make_portfolio(tmp_path, bars)
    pf.place_orders([_row("NVDA", entry_price=120)], ["NVDA"], {}, now=PLACE_NOW)
    pf.process_fills(now=CHECK_NOW)

    assert "NVDA" not in pf.state["positions"]
    assert pf.state["orders"][0]["status"] == "pending"


def test_buy_order_ignores_the_placement_days_own_bar(tmp_path):
    # A bar dated the SAME NY day the order was placed must never fill it,
    # even if its low would otherwise have triggered the fill.
    bars = {"NVDA": [bar("2026-01-05", 130, 132, 50, 131)]}
    pf = make_portfolio(tmp_path, bars)
    pf.place_orders([_row("NVDA", entry_price=128)], ["NVDA"], {}, now=PLACE_NOW)
    pf.process_fills(now=CHECK_NOW)

    assert "NVDA" not in pf.state["positions"]  # would have filled if 01-05 counted


def test_gap_down_fills_at_the_cheaper_open_not_the_limit(tmp_path):
    bars = {"NVDA": [bar("2026-01-06", 120, 125, 118, 122)]}
    pf = make_portfolio(tmp_path, bars)
    pf.place_orders([_row("NVDA", entry_price=128)], ["NVDA"], {}, now=PLACE_NOW)
    pf.process_fills(now=CHECK_NOW)

    assert pf.state["positions"]["NVDA"]["avg_cost"] == 120  # the open, not 128


# ── Sell fills ────────────────────────────────────────────────────────────

def test_sell_order_fills_at_next_sessions_open(tmp_path):
    bars = {"KO": [bar("2026-01-06", 64, 66, 63, 65)]}
    pf = make_portfolio(tmp_path, bars)
    pf.state["positions"]["KO"] = {"shares": 10, "avg_cost": 70,
                                   "opened_at": "2025-12-01", "stop_loss_pct": 10}
    pf._save()

    pf.place_orders([], [], {"KO": {"action": "sell", "reason": "bear thesis"}},
                    now=PLACE_NOW)
    pf.process_fills(now=CHECK_NOW)

    assert "KO" not in pf.state["positions"]
    sell = next(t for t in pf.state["trades"] if t["symbol"] == "KO")
    assert sell["price"] == 64             # the session's open
    assert sell["at"] == "2026-01-06"       # logged under the SESSION date


def test_same_session_sell_proceeds_fund_a_buy(tmp_path):
    bars = {
        "KO": [bar("2026-01-06", 100, 101, 99, 100)],
        "NVDA": [bar("2026-01-06", 90, 91, 88, 90)],
    }
    pf = make_portfolio(tmp_path, bars)
    pf.state["cash"] = 50  # not nearly enough for the NVDA buy on its own
    pf.state["positions"]["KO"] = {"shares": 5, "avg_cost": 90,
                                   "opened_at": "2025-12-01", "stop_loss_pct": 10}
    pf._save()

    pf.place_orders([_row("NVDA", entry_price=90)], ["NVDA"],
                    {"KO": {"action": "sell", "reason": "bear thesis"}},
                    now=PLACE_NOW)
    pf.process_fills(now=CHECK_NOW)

    assert "KO" not in pf.state["positions"]
    assert "NVDA" in pf.state["positions"]
    shares = pf.state["positions"]["NVDA"]["shares"]
    assert pf.state["cash"] == round(50 + 500 - shares * 90, 2)


# ── Stop-loss ─────────────────────────────────────────────────────────────

def test_stop_loss_triggers_on_a_close_below_its_own_percentage(tmp_path):
    bars = {"AAPL": [bar("2026-01-06", 95, 96, 80, 87)]}
    pf = make_portfolio(tmp_path, bars)
    # 10% stop from avg_cost 100 -> threshold 90; a close of 87 breaches it.
    pf.state["positions"]["AAPL"] = {"shares": 4, "avg_cost": 100,
                                     "opened_at": "2025-12-01", "stop_loss_pct": 10}
    pf._save()

    pf.process_fills(now=CHECK_NOW)

    assert "AAPL" not in pf.state["positions"]
    sell = next(t for t in pf.state["trades"] if t["symbol"] == "AAPL")
    assert sell["price"] == 87
    assert "stop-loss" in sell["reason"]


def test_intraday_dip_below_stop_loss_does_not_trigger_if_close_recovers(tmp_path):
    bars = {"AAPL": [bar("2026-01-06", 95, 96, 80, 95)]}  # low dips to 80, closes at 95
    pf = make_portfolio(tmp_path, bars)
    pf.state["positions"]["AAPL"] = {"shares": 4, "avg_cost": 100,
                                     "opened_at": "2025-12-01", "stop_loss_pct": 10}
    pf._save()

    pf.process_fills(now=CHECK_NOW)

    assert "AAPL" in pf.state["positions"]  # closed at 95, above the 90 threshold


def test_stop_loss_uses_the_positions_own_percentage_not_the_default(tmp_path):
    # Rules default is 10%; this position's OWN stop is 20% — a close only
    # 12% down must NOT trigger it (it would if the 10% default were used).
    bars = {"AAPL": [bar("2026-01-06", 90, 91, 85, 88)]}
    pf = make_portfolio(tmp_path, bars)
    pf.state["positions"]["AAPL"] = {"shares": 4, "avg_cost": 100,
                                     "opened_at": "2025-12-01", "stop_loss_pct": 20}
    pf._save()

    pf.process_fills(now=CHECK_NOW)

    assert "AAPL" in pf.state["positions"]


def test_old_position_without_stop_loss_pct_uses_the_rules_default(tmp_path):
    # Migration: a position saved before this feature existed has no
    # stop_loss_pct at all — it must fall back to the portfolio default.
    bars = {"AAPL": [bar("2026-01-06", 95, 96, 80, 87)]}
    pf = make_portfolio(tmp_path, bars)
    pf.state["positions"]["AAPL"] = {"shares": 4, "avg_cost": 100,
                                     "opened_at": "2025-12-01"}  # no stop_loss_pct
    pf._save()

    pf.process_fills(now=CHECK_NOW)

    assert "AAPL" not in pf.state["positions"]  # 87 breaches the 10% default


# ── Fill-time cash sizing ─────────────────────────────────────────────────

def test_higher_conviction_buy_fills_first_when_cash_is_tight(tmp_path):
    bars = {
        "HIGH": [bar("2026-01-06", 100, 101, 99, 100)],
        "LOW": [bar("2026-01-06", 30, 31, 29, 30)],
    }
    pf = make_portfolio(tmp_path, bars)
    pf.state["cash"] = 800
    pf._save()

    pf.place_orders(
        [_row("HIGH", conviction=9, entry_price=100),
         _row("LOW", conviction=3, entry_price=30)],
        ["HIGH", "LOW"], {}, now=PLACE_NOW)
    pf.process_fills(now=CHECK_NOW)

    assert "HIGH" in pf.state["positions"]      # took all $800 of cash
    assert "LOW" not in pf.state["positions"]   # nothing left — stays pending
    low_order = next(o for o in pf.state["orders"] if o["symbol"] == "LOW")
    assert low_order["status"] == "pending"


def test_lower_conviction_buy_shrinks_to_whatever_cash_remains(tmp_path):
    bars = {
        "HIGH": [bar("2026-01-06", 100, 101, 99, 100)],
        "LOW": [bar("2026-01-06", 30, 31, 29, 30)],
    }
    pf = make_portfolio(tmp_path, bars)
    pf.state["cash"] = 900  # $100 left over after HIGH takes $800
    pf._save()

    pf.place_orders(
        [_row("HIGH", conviction=9, entry_price=100),
         _row("LOW", conviction=3, entry_price=30)],
        ["HIGH", "LOW"], {}, now=PLACE_NOW)
    pf.process_fills(now=CHECK_NOW)

    assert pf.state["positions"]["HIGH"]["shares"] == 8   # full $800 budget
    assert pf.state["positions"]["LOW"]["shares"] == 3    # only $100 left ÷ $30
    assert pf.state["cash"] == 900 - 800 - 90


# ── Order lifecycle ───────────────────────────────────────────────────────

def test_a_new_run_replaces_still_pending_orders(tmp_path):
    bars = {"NVDA": [bar("2026-01-06", 130, 132, 127, 131)]}
    pf = make_portfolio(tmp_path, bars)
    first = pf.place_orders([_row("NVDA", entry_price=90)], ["NVDA"], {}, now=PLACE_NOW)

    pf.place_orders([_row("NVDA", entry_price=90)], ["NVDA"], {},
                    now=datetime(2026, 1, 6, 22, 0, tzinfo=timezone.utc))

    old_order = next(o for o in pf.state["orders"] if o["id"] == first[0]["id"])
    assert old_order["status"] == "replaced"
    assert sum(1 for o in pf.state["orders"] if o["status"] == "pending") == 1


def test_a_scoped_run_leaves_out_of_scope_pending_orders_alone(tmp_path):
    # This is the exact bug a narrowly-scoped run (e.g. the overnight
    # scheduler's price-watch-triggered run — see price_watches.py) must
    # never reintroduce: analysing ONE stock must not cancel another
    # stock's still-pending order from an earlier, broader run.
    bars = {"AAPL": [bar("2026-01-06", 190, 192, 188, 191)],
           "NVDA": [bar("2026-01-06", 130, 132, 127, 131)]}
    pf = make_portfolio(tmp_path, bars)
    # An earlier, full run placed a pending BUY for AAPL (price never
    # reached, so it's still sitting there).
    first = pf.place_orders([_row("AAPL", entry_price=90)], ["AAPL"], {}, now=PLACE_NOW)
    aapl_order_id = first[0]["id"]

    # A later run, scoped to JUST NVDA (a price watch firing on it),
    # must not touch AAPL's still-pending order.
    pf.place_orders([_row("NVDA", entry_price=90)], ["NVDA"], {},
                    now=datetime(2026, 1, 6, 22, 0, tzinfo=timezone.utc),
                    analyzed=["NVDA"])

    aapl_order = next(o for o in pf.state["orders"] if o["id"] == aapl_order_id)
    assert aapl_order["status"] == "pending"  # untouched, not "replaced"
    nvda_orders = [o for o in pf.state["orders"] if o["symbol"] == "NVDA"]
    assert any(o["status"] == "pending" for o in nvda_orders)


def test_a_scoped_run_still_replaces_its_own_prior_pending_order(tmp_path):
    # Scoping doesn't mean "never replace" — a symbol INSIDE the scope
    # still gets fresh thinking, exactly like an unscoped run.
    bars = {"NVDA": [bar("2026-01-06", 130, 132, 127, 131)]}
    pf = make_portfolio(tmp_path, bars)
    first = pf.place_orders([_row("NVDA", entry_price=90)], ["NVDA"], {}, now=PLACE_NOW)

    pf.place_orders([_row("NVDA", entry_price=95)], ["NVDA"], {},
                    now=datetime(2026, 1, 6, 22, 0, tzinfo=timezone.utc),
                    analyzed=["NVDA"])

    old_order = next(o for o in pf.state["orders"] if o["id"] == first[0]["id"])
    assert old_order["status"] == "replaced"


def test_never_buys_risk_flagged_products(tmp_path):
    # TQQQ is flagged leveraged in the real universe config.
    bars = {"TQQQ": [bar("2026-01-06", 70, 71, 69, 70)]}
    pf = make_portfolio(tmp_path, bars)
    orders = pf.place_orders([_row("TQQQ", entry_price=70)], ["TQQQ"], {}, now=PLACE_NOW)
    assert orders == []  # never even placed — flagged products are refused


def test_bad_entry_price_is_recorded_as_skipped_not_placed(tmp_path):
    pf = make_portfolio(tmp_path, {})
    row = _row("NVDA", entry_price=None)  # the parser already rejected this pick's price
    orders = pf.place_orders([row], ["NVDA"], {}, now=PLACE_NOW)
    assert orders[0]["status"] == "skipped_bad_price"
    assert "limit_price" not in orders[0]


def test_scoped_run_still_reviews_a_holding_outside_its_scope(tmp_path):
    # A run's shortlist can be scoped to one watchlist, but a SELL decision
    # for a holding outside that scope must still be actioned — the review
    # is passed in explicitly regardless of what's in `rows`/`shortlist`.
    pf = make_portfolio(tmp_path, {"MSFT": [bar("2026-01-06", 400, 401, 399, 400)]})
    pf.state["positions"]["MSFT"] = {"shares": 2, "avg_cost": 420,
                                     "opened_at": "2025-12-01", "stop_loss_pct": 10}
    pf._save()

    # This run's shortlist only concerns a totally different watchlist.
    pf.place_orders([_row("KO", entry_price=60)], ["KO"],
                    {"MSFT": {"action": "sell", "reason": "no longer favoured"}},
                    now=PLACE_NOW)
    pf.process_fills(now=CHECK_NOW)

    assert "MSFT" not in pf.state["positions"]


# ── Reset & summary ───────────────────────────────────────────────────────

def test_reset_wipes_everything(tmp_path):
    pf = make_portfolio(tmp_path, {})
    pf.state["positions"]["AAPL"] = {"shares": 1, "avg_cost": 100,
                                     "opened_at": "2025-12-01", "stop_loss_pct": 10}
    pf._save()
    pf.reset()
    assert pf.state["cash"] == 10000
    assert pf.state["positions"] == {}
    assert pf.state["orders"] == []


def test_summary_has_everything_the_page_needs(tmp_path):
    bars = {"AAPL": [bar("2026-01-06", 100, 101, 99, 100)]}
    pf = make_portfolio(tmp_path, bars)
    pf.state["positions"]["AAPL"] = {"shares": 2, "avg_cost": 90,
                                     "opened_at": "2025-12-01", "stop_loss_pct": 10}
    pf._save()

    s = pf.summary()
    assert s["total_value"] > 0
    assert len(s["holdings"]) == 1
    h = s["holdings"][0]
    for field in ("symbol", "shares", "avg_cost", "price", "value",
                  "pl", "pl_pct", "stop_loss_pct"):
        assert field in h
    assert "orders" in s


def test_viewing_the_summary_saves_at_most_once_a_day(tmp_path):
    pf = make_portfolio(tmp_path, {})
    saves = []
    pf._save = lambda: saves.append(1)
    pf.summary()   # first view today → adds today's point → one save
    pf.summary()   # same point, updated in memory → no save
    pf.summary()
    assert len(saves) == 1


def test_migration_old_portfolio_without_orders_key_loads_fine(tmp_path):
    path = tmp_path / "portfolio.json"
    path.write_text(json.dumps({
        "cash": 5000, "positions": {}, "trades": [], "history": [],
    }))  # no "orders" key — as a pre-feature save would look

    pf = PaperPortfolio(ScriptedSource({}), rules=RULES, state_path=path)
    assert pf.state["orders"] == []
    pf.process_fills()  # must not crash on old state


def test_order_ids_are_random_not_a_process_counter(tmp_path):
    # The cloud runs several server workers as separate processes, each
    # with its own memory — a counter-based id ("ord-143022-1") could be
    # handed out by two workers in the same second. Random bytes avoid
    # that entirely, so there's no per-process state to check — just that
    # ids come out unique and in the new shape.
    pf = make_portfolio(tmp_path, {})
    orders = pf.place_orders(
        [_row("AAA", entry_price=10), _row("BBB", entry_price=10)],
        ["AAA", "BBB"], {}, now=PLACE_NOW)
    ids = [o["id"] for o in orders]
    assert len(ids) == len(set(ids))                     # all unique
    assert all(o["id"].startswith("ord-") for o in orders)
    assert all(len(o["id"]) == len("ord-") + 8 for o in orders)  # 4 random bytes = 8 hex chars
