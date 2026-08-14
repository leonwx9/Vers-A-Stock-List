"""
provider.py — picks which AI service to use.

Two ways to choose, checked in this order:
  1. A runtime choice Leon made from the dashboard's toggle (saved in
     storage as the "llm_settings" document) — lets him flip between his
     own Claude account and a paid API key without editing .env or
     restarting the app.
  2. The .env file's LLM_PROVIDER line — the original way, and still the
     default whenever no toggle choice has been made.

All three providers expose one identical method:

    complete(system, user, max_tokens) -> the AI's reply as a string
"""

import os

from dotenv import load_dotenv

from ..storage import get_doc

KNOWN_PROVIDERS = ("openrouter", "anthropic", "claude_code")


def _load_settings():
    """{"provider": <name> or None}. None means "no toggle choice made
    yet — fall back to .env"."""
    return get_doc("llm_settings").load() or {"provider": None}


def save_provider_choice(name):
    """Save Leon's runtime choice from the dashboard toggle. `name` must
    be one of KNOWN_PROVIDERS — raises ValueError otherwise, same spirit
    as the unknown-.env-value error below."""
    if name not in KNOWN_PROVIDERS:
        raise ValueError(
            f"Unknown provider '{name}' — use one of {', '.join(KNOWN_PROVIDERS)}.")
    get_doc("llm_settings").save({"provider": name})


def current_provider_name():
    """The EFFECTIVE provider name right now — the toggle's choice if
    Leon has made one, else .env's LLM_PROVIDER. Just the name (no
    instance), so callers that only need to know WHICH provider is active
    (e.g. the overnight scheduler's provider gate, or the toggle's status
    line) don't have to construct one."""
    settings = _load_settings()
    if settings.get("provider"):
        return settings["provider"]
    load_dotenv()
    return os.getenv("LLM_PROVIDER", "openrouter").strip().lower()


def provider_source():
    """"toggle" if Leon has made a runtime choice from the dashboard,
    else "env-default" (falling back to .env's LLM_PROVIDER) — lets the
    UI say honestly where today's choice is coming from."""
    return "toggle" if _load_settings().get("provider") else "env-default"


def get_provider():
    """Return a ready-to-use AI provider object for whichever provider is
    effective right now (see current_provider_name())."""
    load_dotenv()  # loads the .env file into environment variables (keys, etc.)
    name = current_provider_name()

    if name == "openrouter":
        from .openrouter_provider import OpenRouterProvider
        return OpenRouterProvider()
    if name == "anthropic":
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider()
    if name == "claude_code":
        from .claude_code_provider import ClaudeCodeProvider
        return ClaudeCodeProvider()

    raise ValueError(
        f"Unknown LLM_PROVIDER '{name}' in .env — use 'openrouter' or 'anthropic'."
    )


class MissingKeyError(Exception):
    """Raised when the needed API key isn't in .env yet (or, for the
    Claude-account provider, when Claude Code isn't installed/logged in
    on this machine).

    A dedicated error type lets the web app show a friendly 'paste your
    key' (or 'use the Mac') message instead of a scary crash page.
    """
