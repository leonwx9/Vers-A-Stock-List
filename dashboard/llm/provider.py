"""
provider.py — picks which AI service to use, based on the .env file.

This is the ONLY place that decides between OpenRouter and Anthropic.
Switching = edit two lines in .env (LLM_PROVIDER + the matching API key).
Both providers expose one identical method:

    complete(system, user, max_tokens) -> the AI's reply as a string
"""

import os

from dotenv import load_dotenv


def get_provider():
    """Read .env and return a ready-to-use AI provider object."""
    load_dotenv()  # loads the .env file into environment variables
    name = os.getenv("LLM_PROVIDER", "openrouter").strip().lower()

    if name == "openrouter":
        from .openrouter_provider import OpenRouterProvider
        return OpenRouterProvider()
    if name == "anthropic":
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider()

    raise ValueError(
        f"Unknown LLM_PROVIDER '{name}' in .env — use 'openrouter' or 'anthropic'."
    )


class MissingKeyError(Exception):
    """Raised when the needed API key isn't in .env yet.

    A dedicated error type lets the web app show a friendly 'paste your key'
    message instead of a scary crash page.
    """
