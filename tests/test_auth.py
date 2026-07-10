"""Tests for the login wall. It must be OFF with no password configured
(local mode) and airtight when one is set (cloud mode)."""

import pytest

from dashboard.app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_no_password_means_open_local_mode(client, monkeypatch):
    monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)
    assert client.get("/").status_code == 200


def test_password_set_redirects_pages_to_login(client, monkeypatch):
    monkeypatch.setenv("DASHBOARD_PASSWORD", "hunter2")
    response = client.get("/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_password_set_gives_api_calls_clear_401(client, monkeypatch):
    monkeypatch.setenv("DASHBOARD_PASSWORD", "hunter2")
    response = client.get("/api/analysis")
    assert response.status_code == 401
    assert response.get_json()["status"] == "error"


def test_wrong_password_rejected_right_password_admits(client, monkeypatch):
    monkeypatch.setenv("DASHBOARD_PASSWORD", "hunter2")
    bad = client.post("/login", data={"password": "nope"})
    assert "Wrong password" in bad.get_data(as_text=True)

    good = client.post("/login", data={"password": "hunter2"})
    assert good.status_code == 302
    assert client.get("/").status_code == 200      # now logged in
    assert client.get("/api/analysis").status_code == 200


def test_logout_locks_the_door_again(client, monkeypatch):
    monkeypatch.setenv("DASHBOARD_PASSWORD", "hunter2")
    client.post("/login", data={"password": "hunter2"})
    client.get("/logout")
    assert client.get("/").status_code == 302


def test_session_cookie_blocks_cross_site_requests():
    # SameSite=Lax stops other websites firing authenticated POSTs at our
    # API with the visitor's login cookie ("cross-site request forgery").
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
