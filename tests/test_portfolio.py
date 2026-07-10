"""Tests for the paper-trading engine — deterministic sample prices and a
temp state file, so nothing touches the real portfolio."""

from dashboard.datasources.sample_source import SampleSource
from dashboard.portfolio.engine import PaperPortfolio

RULES = {"portfolio": {
    "starting_cash": 10000,
    "max_position_value": 800,
    "excluded_flags": ["leveraged", "inverse", "volatility"],
    "shortlist_size": 5,
    "stop_loss_pct": 10,
}}


def make_portfolio(tmp_path):
    return PaperPortfolio(SampleSource(), rules=RULES,
                          state_path=tmp_path / "portfolio.json")


def test_starts_with_10k_cash_and_no_positions(tmp_path):
    pf = make_portfolio(tmp_path)
    assert pf.state["cash"] == 10000
    assert pf.state["positions"] == {}
    assert pf.total_value() == 10000


def test_sync_buys_shortlist_with_whole_shares_under_cap(tmp_path):
    pf = make_portfolio(tmp_path)
    trades = pf.sync_to_shortlist(["AAPL", "KO"])

    assert {t["symbol"] for t in trades} == {"AAPL", "KO"}
    for symbol in ("AAPL", "KO"):
        pos = pf.state["positions"][symbol]
        cost = pos["shares"] * pos["avg_cost"]
        assert pos["shares"] == int(pos["shares"])  # whole shares only
        assert cost <= 800                          # per-pick cap respected
    # Cash went down by exactly what was spent.
    spent = sum(p["shares"] * p["avg_cost"] for p in pf.state["positions"].values())
    assert abs(pf.state["cash"] - (10000 - spent)) < 0.01


def test_sync_sells_what_dropped_off_the_shortlist(tmp_path):
    pf = make_portfolio(tmp_path)
    pf.sync_to_shortlist(["AAPL", "KO"])
    trades = pf.sync_to_shortlist(["KO"])  # AAPL dropped off

    sells = [t for t in trades if t["action"] == "sell"]
    assert len(sells) == 1 and sells[0]["symbol"] == "AAPL"
    assert "AAPL" not in pf.state["positions"]
    assert "KO" in pf.state["positions"]


def test_stop_loss_sells_a_big_loser_even_if_still_shortlisted(tmp_path):
    pf = make_portfolio(tmp_path)
    pf.sync_to_shortlist(["AAPL"])
    # Pretend we paid far more than today's price — a >10% loss.
    pf.state["positions"]["AAPL"]["avg_cost"] *= 2
    pf._save()  # sync re-reads saved state, so the tampering must be saved

    trades = pf.sync_to_shortlist(["AAPL"])
    actions = [(t["action"], t["symbol"]) for t in trades]
    # Sold on stop-loss, then re-bought fresh because it's still shortlisted.
    assert actions[0] == ("sell", "AAPL")
    assert "stop-loss" in trades[0]["reason"]


def test_never_buys_risk_flagged_products(tmp_path):
    pf = make_portfolio(tmp_path)
    # TQQQ is flagged leveraged in the real universe config.
    pf.sync_to_shortlist(["TQQQ", "KO"])
    assert "TQQQ" not in pf.state["positions"]
    assert "KO" in pf.state["positions"]


def test_snapshot_keeps_one_point_per_day(tmp_path):
    pf = make_portfolio(tmp_path)
    pf.snapshot()
    pf.snapshot()  # same day → update, not append
    assert len(pf.state["history"]) == 1


def test_reset_wipes_everything(tmp_path):
    pf = make_portfolio(tmp_path)
    pf.sync_to_shortlist(["AAPL"])
    pf.reset()
    assert pf.state["cash"] == 10000
    assert pf.state["positions"] == {}
    assert pf.state["trades"] == []


def test_summary_has_everything_the_page_needs(tmp_path):
    pf = make_portfolio(tmp_path)
    pf.sync_to_shortlist(["AAPL"])
    s = pf.summary()
    assert s["total_value"] > 0
    assert len(s["holdings"]) == 1
    h = s["holdings"][0]
    for field in ("symbol", "shares", "avg_cost", "price", "value", "pl", "pl_pct"):
        assert field in h


def test_scoped_sync_leaves_unanalyzed_holdings_alone(tmp_path):
    # A run scoped to one watchlist says NOTHING about other holdings —
    # they must not be sold for "missing" a shortlist that never
    # considered them.
    pf = make_portfolio(tmp_path)
    pf.sync_to_shortlist(["AAPL", "KO"])                      # full run
    trades = pf.sync_to_shortlist(["MSFT"], analyzed=["MSFT", "NVDA"])

    assert "AAPL" in pf.state["positions"]   # out of scope → untouched
    assert "KO" in pf.state["positions"]     # out of scope → untouched
    assert "MSFT" in pf.state["positions"]   # in scope + shortlisted → bought
    assert all(t["symbol"] == "MSFT" for t in trades)


def test_scoped_sync_still_sells_an_in_scope_drop(tmp_path):
    pf = make_portfolio(tmp_path)
    pf.sync_to_shortlist(["AAPL", "KO"])
    # Scoped run DID analyse AAPL and left it off the shortlist → sell it.
    pf.sync_to_shortlist(["MSFT"], analyzed=["MSFT", "AAPL"])
    assert "AAPL" not in pf.state["positions"]
    assert "KO" in pf.state["positions"]     # still out of scope → kept


def test_viewing_the_summary_saves_at_most_once_a_day(tmp_path):
    # summary() answers a page view — looking at the portfolio shouldn't
    # rewrite the saved file on every reload, only when a new day's graph
    # point appears.
    pf = make_portfolio(tmp_path)
    saves = []
    pf._save = lambda: saves.append(1)
    pf.summary()   # first view today → adds today's point → one save
    pf.summary()   # second view → same point updated in memory → no save
    pf.summary()
    assert len(saves) == 1
