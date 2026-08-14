"""Tests for the overnight price-watch module — "tell me if this stock
reaches $X tonight." All storage is monkeypatched to a temp folder."""

import pytest

import dashboard.price_watches as price_watches


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    import dashboard.storage as storage
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    yield


# ── watch_triggered (pure function) ───────────────────────────────────────

def test_watch_triggered_fires_when_price_rises_to_a_level_set_below():
    watch = {"level": 150.0, "set_when_price": 140.0}
    assert not price_watches.watch_triggered(watch, 149.99)
    assert price_watches.watch_triggered(watch, 150.0)
    assert price_watches.watch_triggered(watch, 155.0)


def test_watch_triggered_fires_when_price_falls_to_a_level_set_above():
    watch = {"level": 150.0, "set_when_price": 160.0}
    assert not price_watches.watch_triggered(watch, 150.01)
    assert price_watches.watch_triggered(watch, 150.0)
    assert price_watches.watch_triggered(watch, 145.0)


def test_watch_triggered_false_when_not_crossed_either_way():
    rising = {"level": 150.0, "set_when_price": 140.0}
    assert not price_watches.watch_triggered(rising, 145.0)
    falling = {"level": 150.0, "set_when_price": 160.0}
    assert not price_watches.watch_triggered(falling, 155.0)


# ── CRUD round-trip ────────────────────────────────────────────────────────

def test_set_and_load_watch_round_trips():
    saved = price_watches.set_watch("AAPL", 200.0, 190.0)
    assert saved["level"] == 200.0
    assert saved["set_when_price"] == 190.0

    watches = price_watches.load()
    assert watches["AAPL"]["level"] == 200.0


def test_setting_a_new_watch_for_the_same_symbol_replaces_the_old_one():
    price_watches.set_watch("AAPL", 200.0, 190.0)
    price_watches.set_watch("AAPL", 210.0, 205.0)
    watches = price_watches.load()
    assert len(watches) == 1
    assert watches["AAPL"]["level"] == 210.0


def test_clear_watch_removes_it():
    price_watches.set_watch("AAPL", 200.0, 190.0)
    price_watches.clear_watch("AAPL")
    assert price_watches.load() == {}


def test_clear_watch_on_an_unwatched_symbol_is_a_quiet_no_op():
    price_watches.clear_watch("NVDA")  # never raises
    assert price_watches.load() == {}


# ── check_all ──────────────────────────────────────────────────────────────

def test_check_all_returns_only_fired_watches():
    price_watches.set_watch("AAPL", 200.0, 190.0)   # rising watch
    price_watches.set_watch("MSFT", 300.0, 310.0)   # falling watch
    price_watches.set_watch("NVDA", 500.0, 490.0)   # rising, not yet reached

    fired = price_watches.check_all({
        "AAPL": 201.0,   # crossed — fires
        "MSFT": 305.0,   # not yet crossed — doesn't fire
        "NVDA": 495.0,   # not yet crossed — doesn't fire
    })
    assert set(fired) == {"AAPL"}


def test_check_all_skips_symbols_with_no_price_supplied():
    price_watches.set_watch("AAPL", 200.0, 190.0)
    fired = price_watches.check_all({})  # no price given for AAPL at all
    assert fired == {}
