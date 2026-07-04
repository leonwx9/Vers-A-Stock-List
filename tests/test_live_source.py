"""Tests for the live price source — canned Yahoo JSON, no network."""

from dashboard.datasources.live_source import (LiveSource, parse_chart,
                                               to_yahoo_symbol)

# A slimmed-down copy of what Yahoo's chart API really returns.
# Timestamps are 2026-06-29 .. 2026-07-02 (UTC), with one null bar.
CANNED_CHART = {"chart": {"result": [{
    "meta": {"symbol": "TEST", "regularMarketPrice": 103.5},
    "timestamp": [1782086400, 1782172800, 1782259200, 1782345600],
    "indicators": {"quote": [{
        "open":   [100.0, 101.0, None, 102.0],
        "high":   [101.5, 102.5, None, 104.0],
        "low":    [99.5, 100.5, None, 101.5],
        "close":  [101.0, 102.0, None, 103.5],
        "volume": [1000000, 1100000, None, 1200000],
    }]},
}]}}


def test_symbol_mapping_for_slash_tickers():
    assert to_yahoo_symbol("BRK/B") == "BRK-B"
    assert to_yahoo_symbol("AAPL") == "AAPL"


def test_parse_chart_produces_standard_bars():
    bars = parse_chart(CANNED_CHART)
    assert len(bars) == 3          # the null bar was skipped
    first = bars[0]
    assert set(first) == {"date", "open", "high", "low", "close", "volume"}
    assert first["close"] == 101.0
    assert bars[-1]["close"] == 103.5


def test_history_is_cached_between_calls():
    source = LiveSource()
    calls = []

    def fake_fetch(symbol):
        calls.append(symbol)
        return parse_chart(CANNED_CHART)

    source._fetch = fake_fetch
    source.get_history("TEST", 30)
    source.get_history("TEST", 5)   # within the cache window → no refetch
    assert calls == ["TEST"]


def test_get_history_slices_most_recent_days():
    source = LiveSource()
    source._fetch = lambda symbol: parse_chart(CANNED_CHART)
    assert len(source.get_history("TEST", 2)) == 2
    assert source.get_history("TEST", 2)[-1]["close"] == 103.5
