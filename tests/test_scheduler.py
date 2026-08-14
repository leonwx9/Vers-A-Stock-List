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


# ── The overnight analysis scheduler ────────────────────────────────────

ET = ZoneInfo("America/New_York")
SLOTS = ["09:35", "12:30", "15:30"]


def et(y, m, d, h, mi):
    return datetime(y, m, d, h, mi, tzinfo=ET)


# ── is_middle_slot ─────────────────────────────────────────────────────

def test_is_middle_slot_identifies_the_chronological_middle():
    assert scheduler_module.is_middle_slot("12:30", SLOTS)
    assert not scheduler_module.is_middle_slot("09:35", SLOTS)
    assert not scheduler_module.is_middle_slot("15:30", SLOTS)


def test_is_middle_slot_correct_even_if_times_saved_out_of_order():
    # Leon could save his three times in any order — the middle is
    # chronological, not positional.
    assert scheduler_module.is_middle_slot("12:30", ["15:30", "09:35", "12:30"])
    assert not scheduler_module.is_middle_slot("09:35", ["15:30", "09:35", "12:30"])


def test_is_middle_slot_false_when_not_exactly_three_slots():
    assert not scheduler_module.is_middle_slot("12:30", ["09:35", "12:30"])


# ── validate_analysis_times ──────────────────────────────────────────────

def test_validate_analysis_times_accepts_three_distinct_session_times():
    scheduler_module.validate_analysis_times(["09:35", "12:30", "15:30"])  # no raise


def test_validate_analysis_times_rejects_wrong_count():
    import pytest
    with pytest.raises(ValueError, match="exactly three"):
        scheduler_module.validate_analysis_times(["09:35", "12:30"])


def test_validate_analysis_times_rejects_bad_format():
    import pytest
    with pytest.raises(ValueError, match="valid"):
        scheduler_module.validate_analysis_times(["9:35am", "12:30", "15:30"])


def test_validate_analysis_times_rejects_outside_session():
    import pytest
    with pytest.raises(ValueError, match="trading session"):
        scheduler_module.validate_analysis_times(["06:00", "12:30", "15:30"])


def test_validate_analysis_times_rejects_duplicates():
    import pytest
    with pytest.raises(ValueError, match="different"):
        scheduler_module.validate_analysis_times(["09:35", "09:35", "15:30"])


# ── effective_analysis_times ─────────────────────────────────────────────

def test_effective_times_falls_back_to_rules_defaults():
    rules = {"scheduler": {"analysis_times_et": ["10:00", "13:00", "15:00"]}}
    times = scheduler_module.effective_analysis_times({"times_et": None}, rules=rules)
    assert times == ["10:00", "13:00", "15:00"]


def test_effective_times_prefers_leons_custom_times():
    rules = {"scheduler": {"analysis_times_et": ["10:00", "13:00", "15:00"]}}
    settings = {"times_et": ["09:30", "11:00", "15:55"]}
    assert scheduler_module.effective_analysis_times(settings, rules=rules) == \
        ["09:30", "11:00", "15:55"]


# ── due_analysis_slot ─────────────────────────────────────────────────────

def test_due_analysis_slot_none_on_a_weekend():
    settings = {"last_runs": {}}
    saturday = et(2026, 8, 15, 10, 0)
    assert scheduler_module.due_analysis_slot(settings, saturday, SLOTS) is None


def test_due_analysis_slot_none_before_the_first_slot():
    settings = {"last_runs": {}}
    now = et(2026, 8, 10, 9, 0)  # Monday, before 09:35
    assert scheduler_module.due_analysis_slot(settings, now, SLOTS) is None


def test_due_analysis_slot_fires_exactly_one_between_slots():
    settings = {"last_runs": {}}
    now = et(2026, 8, 10, 10, 0)  # after 09:35, before 12:30
    assert scheduler_module.due_analysis_slot(settings, now, SLOTS) == "09:35"


def test_due_analysis_slot_already_run_today_returns_none():
    settings = {"last_runs": {"09:35": "2026-08-10"}}
    now = et(2026, 8, 10, 10, 0)
    assert scheduler_module.due_analysis_slot(settings, now, SLOTS) is None


def test_due_analysis_slot_resets_on_a_new_et_date():
    # Ran for 09:35 yesterday — a NEW day's 09:35 slot is due again.
    settings = {"last_runs": {"09:35": "2026-08-07"}}
    now = et(2026, 8, 10, 10, 0)
    assert scheduler_module.due_analysis_slot(settings, now, SLOTS) == "09:35"


def test_due_analysis_slot_multiple_missed_slots_fires_only_the_latest():
    # The Mac was asleep all morning and just woke up mid-afternoon —
    # both 09:35 and 12:30 are overdue, but only ONE catch-up run happens.
    settings = {"last_runs": {}}
    now = et(2026, 8, 10, 14, 0)  # after 09:35 AND 12:30, before 15:30
    assert scheduler_module.due_analysis_slot(settings, now, SLOTS) == "12:30"


# ── should_run_overnight_analysis (adds the enabled + provider gate) ────

def test_should_run_overnight_analysis_off_when_disabled():
    settings = {"enabled": False, "last_runs": {}}
    now = et(2026, 8, 10, 10, 0)
    assert scheduler_module.should_run_overnight_analysis(
        settings, now, SLOTS, "claude_code") is None


def test_should_run_overnight_analysis_blocked_when_provider_isnt_claude_code():
    # The whole point of the gate: an unattended loop must never spend an
    # API key Leon didn't choose to spend while asleep.
    settings = {"enabled": True, "last_runs": {}}
    now = et(2026, 8, 10, 10, 0)
    assert scheduler_module.should_run_overnight_analysis(
        settings, now, SLOTS, "openrouter") is None


def test_should_run_overnight_analysis_fires_when_enabled_and_on_claude_code():
    settings = {"enabled": True, "last_runs": {}}
    now = et(2026, 8, 10, 10, 0)
    assert scheduler_module.should_run_overnight_analysis(
        settings, now, SLOTS, "claude_code") == "09:35"


# ── run_overnight_once ────────────────────────────────────────────────────

def test_run_overnight_once_does_nothing_when_not_due(tmp_path, monkeypatch):
    import dashboard.storage as storage
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)

    settings = {"enabled": True, "last_runs": {}, "last_error": None}
    now = et(2026, 8, 10, 9, 0)  # before the first slot
    calls = []
    ran = scheduler_module.run_overnight_once(
        settings, now, SLOTS, "claude_code", lambda slot: calls.append(slot))
    assert ran is False
    assert calls == []


def test_run_overnight_once_stamps_last_runs_and_calls_the_fn(tmp_path, monkeypatch):
    import dashboard.storage as storage
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)

    settings = {"enabled": True, "last_runs": {}, "last_error": None}
    now = et(2026, 8, 10, 10, 0)
    calls = []
    ran = scheduler_module.run_overnight_once(
        settings, now, SLOTS, "claude_code", lambda slot: calls.append(slot))

    assert ran is True
    assert calls == ["09:35"]
    saved = scheduler_module.load_overnight_settings()
    assert saved["last_runs"]["09:35"] == "2026-08-10"
    assert saved["last_error"] is None


def test_run_overnight_once_marks_every_missed_slot_not_just_the_one_fired(
        tmp_path, monkeypatch):
    import dashboard.storage as storage
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)

    settings = {"enabled": True, "last_runs": {}, "last_error": None}
    now = et(2026, 8, 10, 14, 0)  # both 09:35 and 12:30 overdue
    calls = []
    scheduler_module.run_overnight_once(
        settings, now, SLOTS, "claude_code", lambda slot: calls.append(slot))

    assert calls == ["12:30"]  # only the latest one actually RUNS
    saved = scheduler_module.load_overnight_settings()
    # But BOTH missed slots are marked caught up for today — no repeat
    # catch-up run five minutes later for the 09:35 slot.
    assert saved["last_runs"]["09:35"] == "2026-08-10"
    assert saved["last_runs"]["12:30"] == "2026-08-10"


def test_run_overnight_once_records_a_failed_runs_error(tmp_path, monkeypatch):
    import dashboard.storage as storage
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)

    settings = {"enabled": True, "last_runs": {}, "last_error": None}
    now = et(2026, 8, 10, 10, 0)

    def boom(slot):
        raise RuntimeError("hit the usage limit — try again at 3pm")

    scheduler_module.run_overnight_once(settings, now, SLOTS, "claude_code", boom)

    saved = scheduler_module.load_overnight_settings()
    assert "usage limit" in saved["last_error"]
    # The slot is still marked done — a failed run means "try again next
    # slot," not an endless retry loop against the same one.
    assert saved["last_runs"]["09:35"] == "2026-08-10"
