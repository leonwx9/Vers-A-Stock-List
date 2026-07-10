"""Tests for the analysis engine — using a FAKE AI provider, so the tests are
free, instant, and don't need any API key."""

import json

import pytest

from dashboard.analysis.searcher import parse_batch_response, run_analysis
from dashboard.datasources.sample_source import SampleSource
from dashboard.storage import get_doc


class FakeProvider:
    """Stands in for the real AI: replies with valid canned JSON for whatever
    tickers appear in the prompt."""

    def complete(self, system, user, max_tokens=4000):
        # Pull the tickers out of the prompt lines that look like "- MSFT (".
        tickers = [
            line.split()[1] for line in user.splitlines() if line.startswith("- ")
        ]
        return json.dumps([
            {
                "ticker": t,
                "bull": f"Fake bull case for {t}.",
                "bear": f"Fake bear case for {t}.",
                "verdict": "bull",
                # Vary the score so the shortlist ranking is exercised.
                "conviction": (len(t) * 3) % 10 + 1,
                "stop_loss": "exit if down >10%",
                "timeframe": "2-4 weeks",
            }
            for t in tickers
        ])


TINY_UNIVERSE = [
    {"symbol": "AAPL", "name": "Apple", "type": "stock", "flags": []},
    {"symbol": "MSFT", "name": "Microsoft", "type": "stock", "flags": []},
    {"symbol": "NVDA", "name": "NVIDIA", "type": "stock", "flags": []},
    {"symbol": "TQQQ", "name": "UltraPro QQQ", "type": "etf", "flags": ["leveraged"]},
]

TINY_RULES = {
    "portfolio": {"excluded_flags": ["leveraged", "inverse", "volatility"],
                  "shortlist_size": 2},
    "analysis": {"batch_size": 2, "max_workers": 2},
}


def test_full_run_produces_rows_and_shortlist(tmp_path, monkeypatch):
    # Redirect the save locations into a temp folder so tests don't write
    # into the real data/ and picks/ directories.
    import dashboard.analysis.searcher as s
    import dashboard.storage as storage
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(s, "PICKS_DIR", tmp_path / "picks")

    result = run_analysis(FakeProvider(), SampleSource(),
                          universe=TINY_UNIVERSE, rules=TINY_RULES)

    assert len(result["rows"]) == 4
    assert len(result["shortlist"]) == 2
    # The leveraged product must never be shortlisted.
    assert "TQQQ" not in result["shortlist"]
    # Both save files must exist.
    assert (tmp_path / "data" / "analysis_latest.json").exists()
    assert list((tmp_path / "picks").glob("*.md"))


def test_parser_handles_code_fences():
    reply = '```json\n[{"ticker": "AAPL", "bull": "b", "bear": "b", ' \
            '"verdict": "bull", "conviction": 7, "stop_loss": "s", "timeframe": "t"}]\n```'
    parsed = parse_batch_response(reply, {"AAPL"})
    assert parsed["AAPL"]["conviction"] == 7


def test_parser_clamps_crazy_conviction_scores():
    reply = '[{"ticker": "AAPL", "bull": "b", "bear": "b", "verdict": "bull", ' \
            '"conviction": 99, "stop_loss": "s", "timeframe": "t"}]'
    parsed = parse_batch_response(reply, {"AAPL"})
    assert parsed["AAPL"]["conviction"] == 10


def test_parser_ignores_tickers_we_did_not_ask_about():
    reply = '[{"ticker": "HACK", "bull": "b", "bear": "b", "verdict": "bull", ' \
            '"conviction": 5, "stop_loss": "s", "timeframe": "t"}]'
    parsed = parse_batch_response(reply, {"AAPL"})
    assert parsed == {}


def test_parser_survives_junk_conviction_and_messy_verdict():
    # A non-numeric conviction must become the minimum score, not a crash,
    # and a messy verdict ("Bull ") must be normalised to "bull".
    reply = '[{"ticker": "AAPL", "bull": "b", "bear": "b", "verdict": " Bull ", ' \
            '"conviction": "high", "stop_loss": "s", "timeframe": "t"}]'
    parsed = parse_batch_response(reply, {"AAPL"})
    assert parsed["AAPL"]["conviction"] == 1
    assert parsed["AAPL"]["verdict"] == "bull"


def _redirect_saves(tmp_path, monkeypatch):
    """Point the save locations at a temp folder (shared test plumbing)."""
    import dashboard.analysis.searcher as s
    import dashboard.storage as storage
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(s, "PICKS_DIR", tmp_path / "picks")


def test_bear_verdict_never_shortlisted_even_on_high_conviction(tmp_path, monkeypatch):
    _redirect_saves(tmp_path, monkeypatch)

    class BearishOnNvda:
        """NVDA gets the HIGHEST conviction but a bear verdict — the AI's
        own verdict must keep it off the shortlist."""
        def complete(self, system, user, max_tokens=4000):
            tickers = [line.split()[1] for line in user.splitlines()
                       if line.startswith("- ")]
            return json.dumps([
                {"ticker": t, "bull": "b", "bear": "b",
                 "verdict": "bear" if t == "NVDA" else "bull",
                 "conviction": 10 if t == "NVDA" else 5,
                 "stop_loss": "s", "timeframe": "t"}
                for t in tickers
            ])

    result = run_analysis(BearishOnNvda(), SampleSource(),
                          universe=TINY_UNIVERSE, rules=TINY_RULES)
    assert "NVDA" not in result["shortlist"]
    assert len(result["shortlist"]) == 2  # the two bull-verdict stocks


def test_one_failed_batch_does_not_sink_the_run(tmp_path, monkeypatch):
    _redirect_saves(tmp_path, monkeypatch)

    class FlakyProvider(FakeProvider):
        """Fails the batch containing MSFT; answers the rest normally."""
        def complete(self, system, user, max_tokens=4000):
            if "MSFT" in user:
                raise RuntimeError("provider hiccup")
            return super().complete(system, user, max_tokens)

    result = run_analysis(FlakyProvider(), SampleSource(),
                          universe=TINY_UNIVERSE, rules=TINY_RULES)
    # The run completed, recorded the failure, and was honest about the
    # tickers it couldn't analyse.
    assert result["batches_failed"] == 1
    msft = next(r for r in result["rows"] if r["symbol"] == "MSFT")
    assert msft["bull"] == "(no analysis returned)"


def test_every_batch_failing_raises_a_clear_error(tmp_path, monkeypatch):
    _redirect_saves(tmp_path, monkeypatch)

    class DeadProvider:
        def complete(self, system, user, max_tokens=4000):
            raise RuntimeError("credit ran out")

    with pytest.raises(RuntimeError, match="All .* batches failed"):
        run_analysis(DeadProvider(), SampleSource(),
                     universe=TINY_UNIVERSE, rules=TINY_RULES)


def test_second_run_keeps_the_first_runs_picks_file(tmp_path, monkeypatch):
    # The picks/ audit trail must keep EVERY run — a same-day (even
    # same-second) re-run gets its own file instead of overwriting.
    _redirect_saves(tmp_path, monkeypatch)
    run_analysis(FakeProvider(), SampleSource(),
                 universe=TINY_UNIVERSE, rules=TINY_RULES)
    run_analysis(FakeProvider(), SampleSource(),
                 universe=TINY_UNIVERSE, rules=TINY_RULES)
    assert len(list((tmp_path / "picks").glob("*.md"))) == 2


def test_history_records_every_run_with_entry_prices(tmp_path, monkeypatch):
    _redirect_saves(tmp_path, monkeypatch)
    run_analysis(FakeProvider(), SampleSource(),
                 universe=TINY_UNIVERSE, rules=TINY_RULES, scope_name="Tech")
    run_analysis(FakeProvider(), SampleSource(),
                 universe=TINY_UNIVERSE, rules=TINY_RULES)

    history = get_doc("analysis_history").load()
    assert len(history) == 2
    assert history[0]["scope"] == "Tech"
    assert history[1]["scope"] == "all watchlists"
    for pick in history[0]["shortlist"]:
        assert set(pick) == {"symbol", "conviction", "price"}
