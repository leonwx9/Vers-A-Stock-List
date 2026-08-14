"""Route-level regression tests for /api/run-analysis — written when the
route's universe-building logic was factored out into
_augment_universe_with_held_stocks() (shared with the overnight
scheduler), to lock in that the refactor didn't change behaviour. Uses a
fake AI provider and real (but temp-file-backed) WatchlistStore/
PaperPortfolio instances — no network, no real subprocess, no quota."""

import json

import pytest

import dashboard.app as app_module
from dashboard.datasources.sample_source import SampleSource
from dashboard.portfolio.engine import PaperPortfolio
from dashboard.watchlists.store import WatchlistStore


class FakeProvider:
    """Canned bull/bull replies for whatever tickers appear in the prompt
    — same shape tests/test_searcher.py's FakeProvider uses."""

    def complete(self, system, user, max_tokens=4000):
        tickers = [
            line.split()[1] for line in user.splitlines() if line.startswith("- ")
        ]
        return json.dumps([
            {"ticker": t, "bull": "good", "bear": "risky", "verdict": "bull",
             "conviction": 7, "stop_loss": "exit if down >10%",
             "timeframe": "2-4 weeks"}
            for t in tickers
        ])


@pytest.fixture
def client(tmp_path, monkeypatch):
    import dashboard.analysis.searcher as searcher_module
    import dashboard.storage as storage
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    # run_analysis() also writes a dated picks/ audit file — redirect that
    # too, or a route test would write real files into the repo's picks/.
    monkeypatch.setattr(searcher_module, "PICKS_DIR", tmp_path / "picks")

    watchlists = WatchlistStore(
        state_path=tmp_path / "watchlists.json",
        seed_universe=[{"symbol": "AAPL", "name": "Apple", "type": "stock",
                        "flags": []}])
    portfolio = PaperPortfolio(SampleSource(),
                               state_path=tmp_path / "portfolio.json")
    monkeypatch.setattr(app_module, "watchlists", watchlists)
    monkeypatch.setattr(app_module, "portfolio", portfolio)
    monkeypatch.setattr(app_module, "prices", SampleSource())
    monkeypatch.setattr(app_module, "get_provider", lambda: FakeProvider())

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c


def test_run_analysis_all_watchlists_succeeds(client):
    res = client.post("/api/run-analysis", json={"watchlist": "all"})
    data = res.get_json()
    assert data["status"] == "ok"
    assert any(r["symbol"] == "AAPL" for r in data["rows"])
    assert "orders_placed" in data


def test_run_analysis_unknown_watchlist_returns_404(client):
    res = client.post("/api/run-analysis", json={"watchlist": "wl-doesnotexist"})
    assert res.status_code == 404
    assert res.get_json()["status"] == "error"


def test_run_analysis_empty_universe_returns_400(client, tmp_path, monkeypatch):
    import dashboard.storage as storage
    empty_watchlists = WatchlistStore(
        state_path=tmp_path / "empty-watchlists.json", seed_universe=[])
    monkeypatch.setattr(app_module, "watchlists", empty_watchlists)

    res = client.post("/api/run-analysis", json={"watchlist": "all"})
    assert res.status_code == 400
    assert "No stocks to analyse" in res.get_json()["message"]


def test_run_analysis_reviews_held_stocks_outside_scope(client, monkeypatch):
    # A stock the portfolio holds but that isn't in ANY watchlist must
    # still appear in the analysed rows (for its HOLD/SELL review) — the
    # exact behaviour _augment_universe_with_held_stocks exists to
    # preserve across the refactor.
    app_module.portfolio.state["positions"]["MSFT"] = {
        "shares": 5, "avg_cost": 300.0, "opened_at": "2026-01-01",
        "stop_loss_pct": 10,
    }
    app_module.portfolio._save()

    res = client.post("/api/run-analysis", json={"watchlist": "all"})
    data = res.get_json()
    assert data["status"] == "ok"
    symbols = {r["symbol"] for r in data["rows"]}
    assert {"AAPL", "MSFT"} <= symbols
