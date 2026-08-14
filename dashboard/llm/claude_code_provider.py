"""
claude_code_provider.py — routes AI requests through Leon's OWN Claude
account (his subscription), via headless Claude Code, instead of a paid
API key.

Plain English: a Claude subscription (claude.ai chat + Claude Code) is
NOT an API credit pool — no key exists that makes the app's normal HTTP
calls to Anthropic bill it. The one legitimate bridge is Claude Code
itself: `claude -p "prompt"` answers one prompt from the command line and
exits, billed to whichever account is logged in on THIS Mac. Verified
working on Leon's Mac on 2026-08-14 — no API key involved, checked the
environment first.

Because of that, this provider:
  - only works on the Mac where Claude Code is installed and logged in —
    never the Render cloud copy (see the friendly error below, which
    reuses MissingKeyError so every route already handles it the same
    way as "no API key configured": a clean message, not a crash);
  - spends Leon's subscription's SHARED usage window (the same 5-hour/
    weekly pool claude.ai chat draws from), not dollars — see the
    connect/disconnect toggle in the dashboard and HANDOVER.md.

Same one-method interface as every other provider, so nothing else in
the app needs to change:
    complete(system, user, max_tokens) -> the AI's reply as a string

The analysis engine can run up to `max_workers` (rules.yaml, currently 3)
batches at once via a thread pool — that means up to 3 of these `claude`
processes running side by side. That's fine: each is a fully independent
subprocess with its own stdin/stdout.
"""

import json
import os
import shutil
import subprocess

from .provider import MissingKeyError

# Generous on purpose — Opus at medium effort can genuinely take a while
# to think through a 10-ticker batch. Better to wait than to give up early
# on a request that was going to succeed.
CLI_TIMEOUT_SECONDS = 300

# Shown whenever the `claude` binary can't be found — on Render there is
# no Claude Code install and no login, so this is expected there, not a
# bug. Defined once so the constructor and a runtime FileNotFoundError
# (the binary vanishing mid-session — rare, but possible) say exactly the
# same thing.
NO_CLI_MESSAGE = (
    "Your Claude account can only be used on the Mac, where Claude Code "
    "is installed and logged in. On the cloud copy, switch the toggle to "
    "the OpenRouter key, or use the Mac."
)


class ClaudeCliError(RuntimeError):
    """Raised when the `claude` CLI ran but reported a problem — a
    malformed reply, or (most often in practice) a subscription usage
    limit. Keep the message human-readable: it's shown to Leon as-is, and
    for a rate limit it's literally the CLI's own explanation ("you've
    hit your limit — try again at ...")."""


def parse_cli_response(text):
    """Pull the reply text out of `claude -p --output-format json`'s
    stdout. A pure function so tests can feed canned CLI output without a
    real subprocess.

    `--output-format json` always prints ONE JSON object with (at least)
    a "result" field on success, and "is_error": true with the error
    explanation in "result" on failure — see the CLI's own docs for the
    full shape; those two fields are all this app needs.
    """
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        raise ClaudeCliError(
            f"Claude Code returned something that wasn't JSON: {text[:200]}")

    if data.get("is_error"):
        raise ClaudeCliError(data.get("result") or "Claude Code reported an error.")

    result = data.get("result")
    if result is None:
        raise ClaudeCliError(
            f"Claude Code's reply had no result field: {text[:200]}")
    return result


class ClaudeCodeProvider:
    def __init__(self):
        # Checked here (construction time), not on first complete() call,
        # so every route's existing `except MissingKeyError` handling
        # already covers "no Claude Code on this machine" the same way it
        # covers "no API key in .env" — a clean 400, not a crash. Reusing
        # MissingKeyError (rather than a new type) is what buys that for
        # free; its actual meaning here is "can't proceed without this
        # provider being usable," which is the same spirit as its name.
        if shutil.which("claude") is None:
            raise MissingKeyError(NO_CLI_MESSAGE)
        self.model = os.getenv("CLAUDE_CODE_MODEL", "sonnet").strip() or "sonnet"
        self.effort = os.getenv("CLAUDE_CODE_EFFORT", "medium").strip()

    def complete(self, system, user, max_tokens=4000):
        """Send one prompt through headless Claude Code, billed to Leon's
        own account. `max_tokens` is accepted — same signature as every
        other provider — but IGNORED: the CLI has no equivalent flag: it
        governs its own reply length."""
        command = [
            "claude", "-p", "--system-prompt", system,
            "--model", self.model, "--output-format", "json",
            # The app wants a plain text completion, not an agent poking
            # around the filesystem — Claude Code must not use any tools.
            "--disallowedTools", "*",
        ]
        if self.effort:
            command += ["--effort", self.effort]

        try:
            # The user prompt goes in via STDIN, not argv — analysis
            # prompts can be large (a batch of tickers' worth of data),
            # and command-line argument length has real OS limits.
            result = subprocess.run(
                command, input=user, capture_output=True, text=True,
                timeout=CLI_TIMEOUT_SECONDS,
            )
        except FileNotFoundError:
            raise MissingKeyError(NO_CLI_MESSAGE)
        except subprocess.TimeoutExpired:
            raise ClaudeCliError(
                f"Claude Code didn't answer within {CLI_TIMEOUT_SECONDS}s "
                "— it may be thinking hard, or the connection dropped. "
                "Try again.")

        return parse_cli_response(result.stdout)
