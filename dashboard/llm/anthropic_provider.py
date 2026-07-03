"""
anthropic_provider.py — talks to Claude directly via Anthropic's official API.

Not used until you switch LLM_PROVIDER=anthropic in .env, but built and ready
so the switch really is a two-line change. Uses Anthropic's official Python
library ("anthropic" in requirements.txt).
"""

import os

from .provider import MissingKeyError


class AnthropicProvider:
    def __init__(self):
        api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            raise MissingKeyError(
                "ANTHROPIC_API_KEY is missing. Get a key at console.anthropic.com, "
                "then paste it into the .env file."
            )
        # Import here (not at the top) so the app runs fine on OpenRouter even
        # if this library were ever missing.
        import anthropic
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")

    def complete(self, system, user, max_tokens=4000):
        """Send one prompt, return the model's reply text."""
        response = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        # The reply arrives as a list of blocks; stitch the text ones together.
        return "".join(
            block.text for block in response.content if block.type == "text"
        )
