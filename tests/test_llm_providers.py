"""Tests for the Claude-account provider — routes AI requests through
Leon's own Claude subscription via headless Claude Code, instead of a
paid API key. Everything here is offline: subprocess.run and shutil.which
are monkeypatched, so no real `claude` process ever runs and no quota is
spent."""

import json
import subprocess

import pytest

from dashboard.llm.claude_code_provider import (ClaudeCliError,
                                                 ClaudeCodeProvider,
                                                 parse_cli_response)
from dashboard.llm.provider import MissingKeyError


# ── parse_cli_response (pure function) ────────────────────────────────────

def test_parse_cli_response_returns_the_result_field():
    text = json.dumps({"type": "result", "is_error": False, "result": "OK"})
    assert parse_cli_response(text) == "OK"


def test_parse_cli_response_raises_with_the_clis_own_error_message():
    # This is exactly how a Pro-plan usage-window limit surfaces — the
    # CLI's own explanation lands in "result" alongside is_error: true.
    text = json.dumps({
        "is_error": True,
        "result": "You've hit your usage limit — try again at 3:00pm.",
    })
    with pytest.raises(ClaudeCliError, match="usage limit"):
        parse_cli_response(text)


def test_parse_cli_response_raises_on_garbled_output():
    with pytest.raises(ClaudeCliError, match="wasn't JSON"):
        parse_cli_response("not json at all")


def test_parse_cli_response_raises_when_result_field_missing():
    text = json.dumps({"type": "result", "is_error": False})
    with pytest.raises(ClaudeCliError, match="no result field"):
        parse_cli_response(text)


# ── ClaudeCodeProvider ─────────────────────────────────────────────────────

def test_missing_binary_raises_a_friendly_mac_only_message(monkeypatch):
    import dashboard.llm.claude_code_provider as mod
    monkeypatch.setattr(mod.shutil, "which", lambda name: None)

    with pytest.raises(MissingKeyError, match="Mac"):
        ClaudeCodeProvider()


def test_complete_sends_prompt_via_stdin_and_blocks_all_tools(monkeypatch):
    import dashboard.llm.claude_code_provider as mod
    monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/local/bin/claude")
    monkeypatch.setenv("CLAUDE_CODE_MODEL", "opus")
    monkeypatch.setenv("CLAUDE_CODE_EFFORT", "medium")

    captured = {}

    class FakeCompletedProcess:
        stdout = json.dumps({"is_error": False, "result": "the reply"})

    def fake_run(command, input, capture_output, text, timeout):
        captured["command"] = command
        captured["input"] = input
        captured["timeout"] = timeout
        return FakeCompletedProcess()

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    provider = ClaudeCodeProvider()
    reply = provider.complete("system prompt", "user prompt here")

    assert reply == "the reply"
    # The prompt went in via stdin, NOT as a command-line argument.
    assert captured["input"] == "user prompt here"
    assert "user prompt here" not in captured["command"]
    command = captured["command"]
    assert command[0] == "claude"
    assert "-p" in command
    assert "--disallowedTools" in command
    assert command[command.index("--disallowedTools") + 1] == "*"
    assert "--system-prompt" in command
    assert command[command.index("--system-prompt") + 1] == "system prompt"
    assert "--model" in command
    assert command[command.index("--model") + 1] == "opus"
    assert "--effort" in command
    assert command[command.index("--effort") + 1] == "medium"
    assert "--output-format" in command
    assert command[command.index("--output-format") + 1] == "json"


def test_complete_defaults_to_sonnet_and_medium_effort_when_unset(monkeypatch):
    import dashboard.llm.claude_code_provider as mod
    monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/local/bin/claude")
    monkeypatch.delenv("CLAUDE_CODE_MODEL", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_EFFORT", raising=False)

    captured = {}

    class FakeCompletedProcess:
        stdout = json.dumps({"is_error": False, "result": "ok"})

    def fake_run(command, **kwargs):
        captured["command"] = command
        return FakeCompletedProcess()

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    ClaudeCodeProvider().complete("sys", "usr")
    command = captured["command"]
    assert command[command.index("--model") + 1] == "sonnet"
    assert command[command.index("--effort") + 1] == "medium"


def test_complete_raises_friendly_message_if_binary_vanishes_mid_call(monkeypatch):
    import dashboard.llm.claude_code_provider as mod
    monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/local/bin/claude")

    def fake_run(*args, **kwargs):
        raise FileNotFoundError()

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    provider = ClaudeCodeProvider()
    with pytest.raises(MissingKeyError, match="Mac"):
        provider.complete("sys", "usr")


def test_complete_raises_clear_message_on_timeout(monkeypatch):
    import dashboard.llm.claude_code_provider as mod
    monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/local/bin/claude")

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="claude", timeout=300)

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    provider = ClaudeCodeProvider()
    with pytest.raises(ClaudeCliError, match="300s"):
        provider.complete("sys", "usr")
