"""Tests for the config layer: the universe file must stay complete and sane."""

from dashboard.config_loader import load_rules, load_universe


def test_universe_has_all_85_tickers():
    assets = load_universe()
    assert len(assets) == 85


def test_universe_symbols_are_unique():
    assets = load_universe()
    symbols = [a["symbol"] for a in assets]
    assert len(symbols) == len(set(symbols))


def test_seven_products_carry_risk_flags():
    # These are the leveraged/inverse/volatility products from STOCK_LIST.md.
    assets = load_universe()
    flagged = {a["symbol"] for a in assets if a["flags"]}
    assert flagged == {"SOXL", "SQQQ", "TMF", "TQQQ", "VXX", "MSTU", "TSLL"}


def test_rules_have_expected_portfolio_settings():
    rules = load_rules()
    assert rules["portfolio"]["starting_cash"] == 10000
    assert rules["portfolio"]["whole_shares_only"] is True
    assert rules["portfolio"]["shortlist_size"] == 5
