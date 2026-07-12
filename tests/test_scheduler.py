"""Tests for the optional daily order-fill scheduler — settles pending
paper-trade orders even if Leon never opens the dashboard that day. No AI
involved; uses a frozen Sydney "now" and the same ScriptedSource fake
price feed test_portfolio.py uses, so everything here is deterministic."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import dashboard.scheduler as scheduler_module
from dashboard.portfolio.engine import PaperPortfolio

from test_portfolio import RULES, ScriptedSource, bar

SYDNEY = ZoneInfo("Australia/Sydney")


# ── should_run ────────────────────────────────────────────────────────────

def test_should_run_false_when_disabled():
    settings = {"enabled": False, "last_run_date": None}
    now = datetime(2026, 7, 12, 9, 0, tzinfo=SYDNEY)
    assert not scheduler_module.should_run(settings, now, fill_hour=8)


def test_should_run_false_before_the_fill_hour():
    settings = {"enabled": True, "last_run_date": None}
    now = datetime(2026, 7, 12, 7, 30, tzinfo=SYDNEY)
    assert not scheduler_module.should_run(settings, now, fill_hour=8)


def test_should_run_false_if_already_run_today():
    settings = {"enabled": True, "last_run_date": "2026-07-12"}
    now = datetime(2026, 7, 12, 9, 0, tzinfo=SYDNEY)
    assert not scheduler_module.should_run(settings, now, fill_hour=8)


def test_should_run_true_after_the_fill_hour_and_not_yet_run():
    settings = {"enabled": True, "last_run_date": "2026-07-11"}
    now = datetime(2026, 7, 12, 8, 5, tzinfo=SYDNEY)
    assert scheduler_module.should_run(settings, now, fill_hour=8)


def test_should_run_true_at_exactly_the_fill_hour():
    # "at or past" the hour, not "exactly" — 8:00 sharp already counts.
    settings = {"enabled": True, "last_run_date": "2026-07-11"}
    now = datetime(2026, 7, 12, 8, 0, tzinfo=SYDNEY)
    assert scheduler_module.should_run(settings, now, fill_hour=8)


# ── run_once ──────────────────────────────────────────────────────────────

def test_run_once_settles_a_due_order_and_records_last_run_date(tmp_path, monkeypatch):
    import dashboard.storage as storage
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)

    bars = {"AAA": [
        bar("2026-07-10", 100, 101, 99, 100),
        bar("2026-07-11", 100, 101, 99, 100),
    ]}
    portfolio = PaperPortfolio(ScriptedSource(bars), rules=RULES,
                              state_path=tmp_path / "portfolio.json")
    place_now = datetime(2026, 7, 9, 22, 0, tzinfo=timezone.utc)
    portfolio.place_orders(
        rows=[{"symbol": "AAA", "conviction": 8, "bull": "x", "bear": "y",
              "entry_price": 100.0, "stop_loss_pct": 10}],
        shortlist=["AAA"], held_reviews={}, now=place_now)

    # 2026-07-12 08:05 Sydney (AEST, UTC+10) = 2026-07-11 22:05 UTC =
    # 2026-07-11 18:05 New York — puts the session boundary just past the
    # 2026-07-10 bar (which is what fills the order) while 07-11 is still
    # "today" and therefore not yet a completed session.
    now_sydney = datetime(2026, 7, 12, 8, 5, tzinfo=SYDNEY)
    settings = {"enabled": True, "last_run_date": None}
    scheduler_module.run_once(portfolio, settings, now_sydney)

    assert "AAA" in portfolio.state["positions"]
    assert scheduler_module.load_settings()["last_run_date"] == "2026-07-12"
    assert portfolio.state["history"]  # snapshot() recorded a point


def test_run_once_marks_the_date_done_even_if_nothing_was_due(tmp_path, monkeypatch):
    import dashboard.storage as storage
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)

    portfolio = PaperPortfolio(ScriptedSource({}), rules=RULES,
                              state_path=tmp_path / "portfolio.json")
    now_sydney = datetime(2026, 7, 12, 8, 5, tzinfo=SYDNEY)
    settings = {"enabled": True, "last_run_date": None}
    scheduler_module.run_once(portfolio, settings, now_sydney)

    assert settings["last_run_date"] == "2026-07-12"
    assert scheduler_module.load_settings()["last_run_date"] == "2026-07-12"
