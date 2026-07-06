"""Tests for watchlists (the music-library model) and free-range search."""

import pytest

from dashboard.datasources.stock_search import parse_search
from dashboard.watchlists.store import DEFAULT_LIST_NAME, WatchlistStore

# A tiny stand-in for universe.yaml so tests never touch the real config.
SEED = [
    {"symbol": "AAPL", "name": "Apple", "type": "stock", "flags": []},
    {"symbol": "SOXL", "name": "Semis Bull 3X", "type": "etf", "flags": ["leveraged"]},
]


def make_store(tmp_path):
    return WatchlistStore(state_path=tmp_path / "watchlists.json", seed_universe=SEED)


def test_first_run_migrates_universe_into_default_watchlist(tmp_path):
    store = make_store(tmp_path)
    summary = store.summary()
    assert len(summary["watchlists"]) == 1
    default = summary["watchlists"][0]
    assert default["name"] == DEFAULT_LIST_NAME
    assert default["symbols"] == ["AAPL", "SOXL"]
    assert default["tag"]["kind"] == "color"      # future-proof tag shape
    # Risk flags survive the migration, attached to the stock itself.
    assert summary["stocks"]["SOXL"]["flags"] == ["leveraged"]


def test_state_survives_a_restart(tmp_path):
    store = make_store(tmp_path)
    store.create("Space")
    reloaded = make_store(tmp_path)   # same file, fresh object
    assert [w["name"] for w in reloaded.summary()["watchlists"]] == [
        DEFAULT_LIST_NAME, "Space"]


def test_a_stock_can_sit_in_many_watchlists(tmp_path):
    store = make_store(tmp_path)
    space = store.create("Space")
    chips = store.create("Chips")
    rklb = {"symbol": "RKLB", "name": "Rocket Lab", "type": "stock"}
    store.add_stock(space["id"], rklb)
    store.add_stock(chips["id"], rklb)

    assert set(store.lists_containing("RKLB")) == {space["id"], chips["id"]}
    # ...but it's analysed once: the union dedupes.
    tracked = [a["symbol"] for a in store.all_tracked_assets()]
    assert tracked.count("RKLB") == 1

    # Removing from ONE list keeps it tracked; removing from both untracks.
    store.remove_stock(space["id"], "RKLB")
    assert "RKLB" in [a["symbol"] for a in store.all_tracked_assets()]
    store.remove_stock(chips["id"], "RKLB")
    assert "RKLB" not in [a["symbol"] for a in store.all_tracked_assets()]


def test_flags_are_remembered_across_remove_and_readd(tmp_path):
    store = make_store(tmp_path)
    default_id = store.summary()["watchlists"][0]["id"]
    store.remove_stock(default_id, "SOXL")
    # Re-add with NO flags supplied (like a search result would) — the
    # catalogue still remembers it's leveraged.
    store.add_stock(default_id, {"symbol": "SOXL", "name": "Semis Bull 3X"})
    assert store.get_stock("SOXL")["flags"] == ["leveraged"]
    assert store.flags_by_symbol()["SOXL"] == {"leveraged"}


def test_rename_and_recolour_keep_the_id(tmp_path):
    store = make_store(tmp_path)
    wl = store.create("Temp name")
    store.update(wl["id"], name="Space stocks",
                 tag={"kind": "color", "value": "#3b82d6"})
    updated = [w for w in store.summary()["watchlists"] if w["id"] == wl["id"]][0]
    assert updated["name"] == "Space stocks"
    assert updated["tag"]["value"] == "#3b82d6"


def test_deleting_a_list_keeps_stocks_in_other_lists(tmp_path):
    store = make_store(tmp_path)
    extra = store.create("Extra")
    store.add_stock(extra["id"], {"symbol": "AAPL", "name": "Apple"})
    store.delete(extra["id"])
    # AAPL is still in the default list, so still tracked.
    assert "AAPL" in [a["symbol"] for a in store.all_tracked_assets()]
    with pytest.raises(KeyError):
        store.update(extra["id"], name="ghost")


def test_empty_watchlist_name_is_rejected(tmp_path):
    store = make_store(tmp_path)
    with pytest.raises(ValueError):
        store.create("   ")


# ── Free-range search parsing ────────────────────────────────────────────

CANNED_SEARCH = {
    "quotes": [
        {"symbol": "RKLB", "shortname": "Rocket Lab Corporation",
         "quoteType": "EQUITY", "exchange": "NMS"},
        {"symbol": "SMH", "shortname": "VanEck Semiconductor ETF",
         "quoteType": "ETF", "exchange": "PCX"},
        {"symbol": "7JT0.F", "shortname": "RocketDNA Ltd.",
         "quoteType": "EQUITY", "exchange": "FRA"},      # foreign → dropped
        {"symbol": "RKLB26.MX", "shortname": "Rocket Lab",
         "quoteType": "EQUITY", "exchange": "MEX"},      # foreign → dropped
        {"symbol": "BTC-USD", "shortname": "Bitcoin USD",
         "quoteType": "CRYPTOCURRENCY", "exchange": "CCC"},  # not a stock → dropped
    ]
}


def test_parse_search_keeps_only_us_stocks_and_etfs():
    matches = parse_search(CANNED_SEARCH)
    assert [m["symbol"] for m in matches] == ["RKLB", "SMH"]
    assert matches[0] == {"symbol": "RKLB", "name": "Rocket Lab Corporation",
                          "type": "stock", "exchange": "Nasdaq"}
    assert matches[1]["type"] == "etf"
