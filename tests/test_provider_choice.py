"""Tests for the runtime provider-choice layer — lets Leon flip between
his own Claude account and a paid API key from the dashboard toggle,
without editing .env. All storage is monkeypatched to a temp folder."""

import pytest

import dashboard.llm.provider as provider_module


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    import dashboard.storage as storage
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    yield


def test_no_toggle_choice_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    assert provider_module.current_provider_name() == "openrouter"
    assert provider_module.provider_source() == "env-default"


def test_toggle_choice_wins_over_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    provider_module.save_provider_choice("claude_code")
    assert provider_module.current_provider_name() == "claude_code"
    assert provider_module.provider_source() == "toggle"


def test_save_provider_choice_rejects_unknown_names():
    with pytest.raises(ValueError, match="Unknown provider"):
        provider_module.save_provider_choice("chatgpt")


def test_choice_round_trips_through_storage(monkeypatch):
    provider_module.save_provider_choice("anthropic")
    # A brand-new read (simulating a fresh request) sees the saved choice.
    assert provider_module.current_provider_name() == "anthropic"


def test_get_provider_builds_claude_code_when_toggled(monkeypatch):
    import dashboard.llm.claude_code_provider as ccp
    monkeypatch.setattr(ccp.shutil, "which", lambda name: "/usr/local/bin/claude")
    provider_module.save_provider_choice("claude_code")

    provider = provider_module.get_provider()
    assert isinstance(provider, ccp.ClaudeCodeProvider)


def test_get_provider_still_builds_openrouter_by_default(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    provider = provider_module.get_provider()
    assert type(provider).__name__ == "OpenRouterProvider"
