"""Tests for the analysis engine — using a FAKE AI provider, so the tests are
free, instant, and don't need any API key."""

import json

from dashboard.analysis.searcher import parse_batch_response, run_analysis
from dashboard.datasources.sample_source import SampleSource


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
    "analysis": {"batch_size": 2, "history_days": 60, "max_workers": 2},
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
