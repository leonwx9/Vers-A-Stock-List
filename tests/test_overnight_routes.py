"""Tests for the /api/overnight routes — the toggle and adjustable times
for the overnight analysis scheduler."""

import pytest

from dashboard.app import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    import dashboard.storage as storage
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_get_overnight_defaults_to_off_and_rules_yaml_times(client):
    res = client.get("/api/overnight")
    data = res.get_json()
    assert data["status"] == "ok"
    assert data["settings"]["enabled"] is False
    assert len(data["effective_times_et"]) == 3


def test_post_overnight_toggles_enabled(client):
    res = client.post("/api/overnight", json={"enabled": True})
    data = res.get_json()
    assert data["status"] == "ok"
    assert data["settings"]["enabled"] is True

    again = client.get("/api/overnight").get_json()
    assert again["settings"]["enabled"] is True


def test_post_overnight_saves_custom_times(client):
    res = client.post("/api/overnight",
                      json={"times_et": ["09:45", "13:00", "15:45"]})
    data = res.get_json()
    assert data["status"] == "ok"
    assert data["effective_times_et"] == ["09:45", "13:00", "15:45"]

    again = client.get("/api/overnight").get_json()
    assert again["effective_times_et"] == ["09:45", "13:00", "15:45"]


def test_post_overnight_rejects_invalid_times_with_friendly_400(client):
    res = client.post("/api/overnight",
                      json={"times_et": ["06:00", "13:00", "15:45"]})
    assert res.status_code == 400
    data = res.get_json()
    assert data["status"] == "error"
    assert "trading session" in data["message"]

    # The bad value must NOT have been saved.
    after = client.get("/api/overnight").get_json()
    assert len(after["effective_times_et"]) == 3
    assert "06:00" not in after["effective_times_et"]


def test_post_overnight_rejects_duplicate_times(client):
    res = client.post("/api/overnight",
                      json={"times_et": ["09:45", "09:45", "15:45"]})
    assert res.status_code == 400
    assert "different" in res.get_json()["message"]


def test_post_overnight_can_set_enabled_and_times_together(client):
    res = client.post("/api/overnight", json={
        "enabled": True, "times_et": ["09:40", "12:00", "15:50"],
    })
    data = res.get_json()
    assert data["settings"]["enabled"] is True
    assert data["effective_times_et"] == ["09:40", "12:00", "15:50"]


def test_post_overnight_null_times_resets_to_rules_yaml_defaults(client):
    # Customise the times first...
    client.post("/api/overnight", json={"times_et": ["09:40", "12:00", "15:50"]})
    assert client.get("/api/overnight").get_json()["effective_times_et"] == \
        ["09:40", "12:00", "15:50"]

    # ...then the "Reset to default times" button sends times_et: null.
    res = client.post("/api/overnight", json={"times_et": None})
    data = res.get_json()
    assert data["status"] == "ok"
    assert data["settings"]["times_et"] is None
    default_times = data["effective_times_et"]
    assert len(default_times) == 3
    assert default_times != ["09:40", "12:00", "15:50"]

    again = client.get("/api/overnight").get_json()
    assert again["effective_times_et"] == default_times
