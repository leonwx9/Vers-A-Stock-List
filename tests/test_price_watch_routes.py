"""Tests for the overnight price-watch routes, and the overnight
scheduler's middle-slot dispatch: a normal full analysis, unless a price
watch has fired tonight, in which case a run dedicated to just the
triggered stock(s). All offline — a fake AI provider, SampleSource for
prices, and isolated WatchlistStore/PaperPortfolio instances."""

import json

import pytest

import dashboard.app as app_module
import dashboard.price_watches as price_watches
import dashboard.scheduler as scheduler
from dashboard.datasources.sample_source import SampleSource
from dashboard.portfolio.engine import PaperPortfolio
from dashboard.watchlists.store import WatchlistStore

SEED = [{"symbol": "AAPL", "name": "Apple", "type": "stock", "flags": []},
       {"symbol": "MSFT", "name": "Microsoft", "type": "stock", "flags": []}]


@pytest.fixture
def client(tmp_path, monkeypatch):
    import dashboard.storage as storage
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(app_module, "prices", SampleSource())
    monkeypatch.setattr(app_module, "watchlists", WatchlistStore(
        state_path=tmp_path / "watchlists.json", seed_universe=SEED))
    monkeypatch.setattr(app_module, "portfolio", PaperPortfolio(
        SampleSource(), state_path=tmp_path / "portfolio.json"))
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c


# ── /api/ticker/<symbol>/watch and /api/watches ───────────────────────────

def test_set_watch_saves_direction_from_current_price(client):
    res = client.post("/api/ticker/AAPL/watch", json={"level": 999999})
    data = res.get_json()
    assert data["status"] == "ok"
    assert data["watch"]["level"] == 999999
    assert data["watch"]["set_when_price"] > 0


def test_set_watch_rejects_a_non_numeric_level(client):
    res = client.post("/api/ticker/AAPL/watch", json={"level": "not a number"})
    assert res.status_code == 400


def test_set_watch_rejects_zero_or_negative(client):
    res = client.post("/api/ticker/AAPL/watch", json={"level": 0})
    assert res.status_code == 400


def test_get_watches_lists_everything_saved(client):
    client.post("/api/ticker/AAPL/watch", json={"level": 300})
    client.post("/api/ticker/MSFT/watch", json={"level": 400})
    data = client.get("/api/watches").get_json()
    assert set(data["watches"]) == {"AAPL", "MSFT"}


def test_clear_watch_removes_it(client):
    client.post("/api/ticker/AAPL/watch", json={"level": 300})
    client.delete("/api/ticker/AAPL/watch")
    assert client.get("/api/watches").get_json()["watches"] == {}


def test_ticker_page_data_includes_the_watch(client):
    client.post("/api/ticker/AAPL/watch", json={"level": 300})
    data = client.get("/api/ticker/AAPL").get_json()
    assert data["watch"]["level"] == 300


def test_ticker_page_watch_is_null_when_none_set(client):
    data = client.get("/api/ticker/MSFT").get_json()
    assert data["watch"] is None


# ── Middle-slot dispatch (no Flask needed — plain function calls) ────────

@pytest.fixture
def dispatch_env(tmp_path, monkeypatch):
    """Everything _run_overnight_analysis needs, isolated to a temp
    folder, with the two branches it can call replaced by recording
    fakes so we can see which one fired without doing a real AI call."""
    import dashboard.storage as storage
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(app_module, "prices", SampleSource())
    scheduler.save_overnight_settings(
        {"enabled": True, "times_et": None, "last_runs": {}, "last_error": None})

    calls = []
    monkeypatch.setattr(app_module, "_run_full_overnight_analysis",
                        lambda slot: calls.append(("full", slot)))
    monkeypatch.setattr(app_module, "_run_price_watch_analysis",
                        lambda fired: calls.append(("watch", fired)))
    return calls


def test_dispatch_runs_full_analysis_on_a_non_middle_slot(dispatch_env):
    price_watches.set_watch("AAPL", level=0.01, current_price=0.001)  # would fire...
    app_module._run_overnight_analysis("09:35")  # ...but this is the OPEN slot
    assert dispatch_env == [("full", "09:35")]


def test_dispatch_runs_full_analysis_on_middle_slot_when_nothing_fires(dispatch_env):
    app_module._run_overnight_analysis("12:30")  # the default middle slot
    assert dispatch_env == [("full", "12:30")]


def test_dispatch_runs_price_watch_analysis_when_middle_slot_fires(dispatch_env):
    # A watch whose level is trivially already reached (way below any
    # real price), so it's guaranteed to fire regardless of SampleSource's
    # randomised-but-positive price for AAPL.
    price_watches.set_watch("AAPL", level=0.01, current_price=0.001)
    app_module._run_overnight_analysis("12:30")
    assert len(dispatch_env) == 1
    kind, payload = dispatch_env[0]
    assert kind == "watch"
    assert "AAPL" in payload


# ── _run_price_watch_analysis end-to-end (fake AI provider) ─────────────

class FakeProvider:
    def complete(self, system, user, max_tokens=4000):
        tickers = [line.split()[1] for line in user.splitlines()
                  if line.startswith("- ")]
        return json.dumps([
            {"ticker": t, "bull": "good", "bear": "risky", "verdict": "bull",
             "conviction": 8, "stop_loss": "exit if down >10%",
             "timeframe": "2-4 weeks"}
            for t in tickers
        ])


def test_price_watch_analysis_scopes_the_run_and_clears_the_watch(
        tmp_path, monkeypatch):
    import dashboard.analysis.searcher as searcher_module
    import dashboard.storage as storage
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(searcher_module, "PICKS_DIR", tmp_path / "picks")
    monkeypatch.setattr(app_module, "prices", SampleSource())
    monkeypatch.setattr(app_module, "watchlists", WatchlistStore(
        state_path=tmp_path / "watchlists.json", seed_universe=SEED))
    monkeypatch.setattr(app_module, "portfolio", PaperPortfolio(
        SampleSource(), state_path=tmp_path / "portfolio.json"))
    monkeypatch.setattr(app_module, "get_provider", lambda: FakeProvider())

    price_watches.set_watch("AAPL", level=0.01, current_price=0.001)
    fired = price_watches.check_all({"AAPL": 100.0})
    assert "AAPL" in fired  # sanity: the watch really is triggered

    app_module._run_price_watch_analysis(fired)

    # One-shot: the watch is gone after the run, win or lose.
    assert price_watches.load() == {}

    latest = searcher_module.load_latest()
    assert latest["scope"].startswith("price watch:")
    # ONLY the triggered symbol was analysed — MSFT never entered it.
    assert {r["symbol"] for r in latest["rows"]} == {"AAPL"}


def test_price_watch_analysis_never_touches_other_pending_orders(
        tmp_path, monkeypatch):
    import dashboard.analysis.searcher as searcher_module
    import dashboard.storage as storage
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(searcher_module, "PICKS_DIR", tmp_path / "picks")
    monkeypatch.setattr(app_module, "prices", SampleSource())
    monkeypatch.setattr(app_module, "watchlists", WatchlistStore(
        state_path=tmp_path / "watchlists.json", seed_universe=SEED))
    portfolio = PaperPortfolio(SampleSource(), state_path=tmp_path / "portfolio.json")
    monkeypatch.setattr(app_module, "portfolio", portfolio)
    monkeypatch.setattr(app_module, "get_provider", lambda: FakeProvider())

    # An earlier (open-session) run left a pending BUY for MSFT.
    order = portfolio.place_orders(
        [{"symbol": "MSFT", "conviction": 7, "bull": "x", "bear": "y",
          "entry_price": 1.0, "stop_loss_pct": 10}],
        ["MSFT"], {})
    assert order[0]["status"] == "pending"

    price_watches.set_watch("AAPL", level=0.01, current_price=0.001)
    fired = price_watches.check_all({"AAPL": 100.0})
    app_module._run_price_watch_analysis(fired)

    msft_order = next(o for o in portfolio.state["orders"] if o["symbol"] == "MSFT")
    assert msft_order["status"] == "pending"  # untouched by the AAPL-only run
