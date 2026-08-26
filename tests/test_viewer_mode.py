"""Tests for viewer mode — the read-only cloud copy that shares the Mac's
database but must never spend AI money or wipe the shared portfolio.

The security is the server-side 403 (before_request), which fires BEFORE
the view runs — so every "blocked" test here is safe: it can never reach
a real AI call or a real reset. VIEWER_MODE is always restored afterwards
(the Flask `app` is a shared singleton — a leaked flag would break other
test files).

The watchlists/portfolio singletons are explicitly replaced (not just
storage.DATA_DIR redirected) because a couple of these tests exercise
routes that are ALLOWED even in viewer mode (watchlist create, bulletin
save) — conftest.py stops those routes' own get_doc() calls from ever
reaching a real database, but app.py's `watchlists` object is built once
at import and won't re-check the env, so it needs replacing directly too
(see conftest.py's docstring for the full story, including the real
"From the phone" watchlists this exact gap wrote into production once)."""

import pytest

import dashboard.app as app_module
from dashboard.app import app, VIEWER_BLOCKED_ENDPOINTS
from dashboard.watchlists.store import WatchlistStore

# Every blocked endpoint's actual URL + method, so we exercise the real
# routing, not just the name set.
BLOCKED_CALLS = [
    ("post", "/api/run-analysis"),
    ("post", "/api/scan"),
    ("post", "/api/lab/brainstorm"),
    ("post", "/api/lab/scan"),
    ("post", "/api/ticker/AAPL/deep-dive"),
    ("post", "/api/llm"),
    ("post", "/api/overnight"),
    ("post", "/api/scheduler"),
    ("post", "/api/lab/settings"),
    ("post", "/api/portfolio/reset"),
]


@pytest.fixture
def client(tmp_path, monkeypatch):
    import dashboard.storage as storage
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(app_module, "watchlists", WatchlistStore(
        state_path=tmp_path / "watchlists.json"))
    app.config["TESTING"] = True
    original = app.config.get("VIEWER_MODE", False)
    with app.test_client() as c:
        yield c
    app.config["VIEWER_MODE"] = original  # never leak into other test files


def test_every_blocked_call_has_a_route_for_each_named_endpoint():
    # Guard against the two lists drifting apart: if someone adds an
    # endpoint to VIEWER_BLOCKED_ENDPOINTS they must add a call here too.
    # Uses Flask's own URL matcher so parametrised routes (e.g. the
    # deep-dive URL with a <symbol> in it) resolve to their endpoint name.
    adapter = app.url_map.bind("localhost")
    tested = {adapter.match(path, method=method.upper())[0]
              for method, path in BLOCKED_CALLS}
    assert tested == VIEWER_BLOCKED_ENDPOINTS


@pytest.mark.parametrize("method,path", BLOCKED_CALLS)
def test_blocked_routes_return_403_in_viewer_mode(client, method, path):
    app.config["VIEWER_MODE"] = True
    res = getattr(client, method)(path, json={})
    assert res.status_code == 403
    assert res.get_json()["status"] == "error"


def test_scheduler_toggle_works_when_not_in_viewer_mode(client):
    # The safe half of the on/off pair: with viewer OFF, a blocked route's
    # real logic runs normally (this one is free — no AI, no network).
    app.config["VIEWER_MODE"] = False
    res = client.post("/api/scheduler", json={"enabled": False})
    assert res.status_code == 200
    assert res.get_json()["status"] == "ok"


def test_watchlist_edits_still_work_in_viewer_mode(client):
    # Free, Leon's-own-data actions stay allowed even on the viewer — the
    # Mac's overnight run honours a watchlist curated from the phone.
    app.config["VIEWER_MODE"] = True
    res = client.post("/api/watchlists", json={"name": "From the phone"})
    assert res.status_code == 200
    assert res.get_json()["status"] == "ok"


def test_bulletin_save_still_works_in_viewer_mode(client):
    app.config["VIEWER_MODE"] = True
    res = client.post("/api/bulletin", json={"text": "- a note from the couch"})
    assert res.status_code == 200
    assert res.get_json()["status"] == "ok"


def test_home_page_carries_the_viewer_marker_only_in_viewer_mode(client):
    app.config["VIEWER_MODE"] = True
    on = client.get("/").get_data(as_text=True)
    assert "viewer-mode" in on          # <body class="viewer-mode">
    assert "Viewer · read-only" in on   # the header badge

    app.config["VIEWER_MODE"] = False
    off = client.get("/").get_data(as_text=True)
    assert "viewer-mode" not in off
