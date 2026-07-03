"""
openrouter_provider.py — talks to Claude through OpenRouter.

OpenRouter is a relay service: we send it a standard chat request over HTTPS
and it forwards it to Anthropic's Claude for us, billed to the OpenRouter
account. Its API follows the common "chat completions" format.
"""

import os

import requests

from .provider import MissingKeyError

API_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterProvider:
    def __init__(self):
        self.api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        # Reject the placeholder text from .env.example, not just an empty value.
        if not self.api_key or self.api_key.startswith("paste-your"):
            raise MissingKeyError(
                "OPENROUTER_API_KEY is missing. Get a key at openrouter.ai → Keys, "
                "then paste it into the .env file."
            )
        # Which model OpenRouter should route to. Overridable in .env.
        self.model = os.getenv("OPENROUTER_MODEL", "anthropic/claude-sonnet-5")

    def complete(self, system, user, max_tokens=4000):
        """Send one prompt, return the model's reply text."""
        response = requests.post(
            API_URL,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "max_tokens": max_tokens,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            timeout=180,  # analysis replies can take a while — don't give up early
        )
        response.raise_for_status()  # turn HTTP errors (bad key, etc.) into exceptions
        data = response.json()
        return data["choices"][0]["message"]["content"]
