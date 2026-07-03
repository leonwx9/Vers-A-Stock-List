"""Tests for the fake price data: it must be stable, positive and consistent."""

from dashboard.datasources.sample_source import SampleSource


def test_same_ticker_always_gives_same_prices():
    a = SampleSource().get_history("AAPL", 30)
    b = SampleSource().get_history("AAPL", 30)
    assert a == b


def test_different_tickers_give_different_prices():
    aapl = SampleSource().get_history("AAPL", 30)
    msft = SampleSource().get_history("MSFT", 30)
    assert aapl != msft


def test_prices_are_always_positive():
    history = SampleSource().get_history("TMC", 400)  # cheapest base price
    assert all(day["close"] > 0 for day in history)


def test_short_and_long_requests_agree_on_recent_prices():
    # Asking for 30 days must return the same recent prices as asking for 120 —
    # otherwise the quote and the chart would contradict each other.
    short = SampleSource().get_history("NVDA", 30)
    long = SampleSource().get_history("NVDA", 120)
    assert short == long[-30:]


def test_quote_has_price_and_changes():
    quote = SampleSource().get_quote("MSFT")
    assert quote["price"] > 0
    assert "change_5d_pct" in quote and "change_30d_pct" in quote


def test_ohlc_bars_are_internally_consistent():
    # Every day's high must be the top of the bar and the low the bottom —
    # otherwise candlestick charts would draw nonsense.
    for day in SampleSource().get_history("AAPL", 120):
        assert day["high"] >= max(day["open"], day["close"])
        assert day["low"] <= min(day["open"], day["close"])
        assert day["low"] > 0
        assert day["volume"] > 0


def test_stats_cover_the_apple_stocks_fields():
    stats = SampleSource().get_stats("NVDA")
    for field in ("open", "high", "low", "prev_close", "day_change_pct",
                  "week52_high", "week52_low", "volume", "avg_volume_30d"):
        assert field in stats
    assert stats["week52_high"] >= stats["week52_low"]
