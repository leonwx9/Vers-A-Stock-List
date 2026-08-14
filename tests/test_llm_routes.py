"""Tests for the /api/llm routes — Leon's connect/disconnect toggle for
using his own Claude account instead of a paid API key."""

import pytest

from dashboard.app import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    import dashboard.storage as storage
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_get_llm_defaults_to_env_when_no_toggle_choice_made(client, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    res = client.get("/api/llm")
    data = res.get_json()
    assert data["status"] == "ok"
    assert data["provider"] == "openrouter"
    assert data["source"] == "env-default"


def test_post_llm_switches_to_claude_code(client):
    res = client.post("/api/llm", json={"provider": "claude_code"})
    data = res.get_json()
    assert data["status"] == "ok"
    assert data["provider"] == "claude_code"
    assert data["source"] == "toggle"

    # The choice sticks for later reads.
    again = client.get("/api/llm").get_json()
    assert again["provider"] == "claude_code"
    assert again["source"] == "toggle"


def test_post_llm_rejects_unknown_provider_with_friendly_400(client):
    res = client.post("/api/llm", json={"provider": "chatgpt"})
    assert res.status_code == 400
    data = res.get_json()
    assert data["status"] == "error"
    assert "Unknown provider" in data["message"]


def test_post_llm_rejects_missing_provider_field(client):
    res = client.post("/api/llm", json={})
    assert res.status_code == 400
    assert res.get_json()["status"] == "error"


def test_toggle_back_to_openrouter(client, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    client.post("/api/llm", json={"provider": "claude_code"})
    res = client.post("/api/llm", json={"provider": "openrouter"})
    data = res.get_json()
    assert data["provider"] == "openrouter"
    assert data["source"] == "toggle"  # a deliberate choice, not just the .env default
