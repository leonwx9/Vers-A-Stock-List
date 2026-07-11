"""Tests for the Event Strategy Lab — journal, brainstorm, and the setup
scanner. All offline: fake AI providers, canned RSS, no keys, no network."""

import json

import pytest

from dashboard.datasources.events_source import EventNewsSource
from dashboard.strategy_lab.brainstorm import parse_brainstorm_response, run_brainstorm
from dashboard.strategy_lab.journal import StrategyJournal
from dashboard.strategy_lab.setup_scanner import (derive_queries,
                                                  parse_scan_response, run_scan)

RULES = {"lab": {"max_queries": 8, "headlines_per_query": 6,
                 "max_headlines": 40, "brainstorm_count": 4}}


def make_journal(tmp_path):
    return StrategyJournal(state_path=tmp_path / "strategies.json")


STRATEGY_FIELDS = {
    "name": "Oil chokepoint closure",
    "description": "Conflict closes a key shipping strait; energy spikes.",
    "entry_trigger": "credible closure/threat of a major chokepoint",
    "exit_trigger": "ceasefire or confirmed reopening",
    "assets": ["energy sector", "tanker shipping"],
    "risk_notes": "spikes fade fast; the retrace is the hard part",
    "tags": ["oil", "geopolitics", "shipping"],
}


# ── Journal ───────────────────────────────────────────────────────────────

def test_create_requires_name_and_description(tmp_path):
    journal = make_journal(tmp_path)
    with pytest.raises(ValueError):
        journal.create({"name": "", "description": "x"}, origin="leon")
    with pytest.raises(ValueError):
        journal.create({"name": "x", "description": "  "}, origin="leon")


def test_create_stores_every_field_and_stamps_origin(tmp_path):
    journal = make_journal(tmp_path)
    strategy = journal.create(STRATEGY_FIELDS, origin="leon")
    assert strategy["origin"] == "leon"
    assert strategy["name"] == "Oil chokepoint closure"
    assert strategy["assets"] == ["energy sector", "tanker shipping"]
    assert strategy["tags"] == ["oil", "geopolitics", "shipping"]
    assert "id" in strategy and "created_at" in strategy


def test_state_survives_a_reload(tmp_path):
    journal = make_journal(tmp_path)
    journal.create(STRATEGY_FIELDS, origin="leon")
    reloaded = StrategyJournal(state_path=tmp_path / "strategies.json")
    assert len(reloaded.list()) == 1
    assert reloaded.list()[0]["name"] == "Oil chokepoint closure"


def test_update_edits_fields_but_never_the_origin(tmp_path):
    journal = make_journal(tmp_path)
    strategy = journal.create(STRATEGY_FIELDS, origin="ai")
    updated = journal.update(strategy["id"], {
        "name": "Renamed", "origin": "leon",  # sneaking origin in must be ignored
    })
    assert updated["name"] == "Renamed"
    assert updated["origin"] == "ai"  # unchanged — editing doesn't relabel it


def test_update_rejects_blanking_the_name(tmp_path):
    journal = make_journal(tmp_path)
    strategy = journal.create(STRATEGY_FIELDS, origin="leon")
    with pytest.raises(ValueError):
        journal.update(strategy["id"], {"name": "   "})


def test_delete_removes_the_strategy(tmp_path):
    journal = make_journal(tmp_path)
    strategy = journal.create(STRATEGY_FIELDS, origin="leon")
    journal.delete(strategy["id"])
    assert journal.list() == []
    with pytest.raises(KeyError):
        journal.delete(strategy["id"])


def test_create_rejects_an_invalid_origin(tmp_path):
    journal = make_journal(tmp_path)
    with pytest.raises(ValueError):
        journal.create(STRATEGY_FIELDS, origin="anonymous")


# ── derive_queries ────────────────────────────────────────────────────────

def test_derive_queries_collects_and_dedupes_tags():
    strategies = [
        {"name": "A", "tags": ["oil", "geopolitics"]},
        {"name": "B", "tags": ["geopolitics", "shipping"]},  # "geopolitics" repeats
    ]
    assert derive_queries(strategies, max_queries=8) == ["oil", "geopolitics", "shipping"]


def test_derive_queries_falls_back_to_name_when_untagged():
    strategies = [{"name": "Election surprise", "tags": []}]
    assert derive_queries(strategies, max_queries=8) == ["Election surprise"]


def test_derive_queries_caps_at_max_queries():
    strategies = [{"name": "A", "tags": [f"tag{i}" for i in range(20)]}]
    assert len(derive_queries(strategies, max_queries=5)) == 5


# ── parse_scan_response ───────────────────────────────────────────────────

HEADLINES = [
    {"title": "Strait closure reported", "source": "Reuters", "link": "https://x/1",
     "published": "…", "query": "oil"},
    {"title": "Unrelated sports news", "source": "ESPN", "link": "https://x/2",
     "published": "…", "query": "oil"},
]


def test_parse_scan_drops_setup_missing_counter_case():
    reply = json.dumps({"setups": [
        {"strategy_id": "strat-1", "whats_happening": "x", "source_indexes": [1],
         "bull_case": "b", "counter_case": "", "risks": ["r"],
         "confidence": {"level": "low"}},
    ], "note": "n"})
    result = parse_scan_response(reply, {"strat-1"}, HEADLINES)
    assert result["setups"] == []


def test_parse_scan_drops_setup_missing_risks():
    reply = json.dumps({"setups": [
        {"strategy_id": "strat-1", "whats_happening": "x", "source_indexes": [1],
         "bull_case": "b", "counter_case": "c", "risks": [],
         "confidence": {"level": "low"}},
    ], "note": "n"})
    assert parse_scan_response(reply, {"strat-1"}, HEADLINES)["setups"] == []


def test_parse_scan_drops_unknown_strategy_id():
    reply = json.dumps({"setups": [
        {"strategy_id": "strat-does-not-exist", "whats_happening": "x",
         "source_indexes": [1], "bull_case": "b", "counter_case": "c",
         "risks": ["r"], "confidence": {"level": "low"}},
    ], "note": "n"})
    assert parse_scan_response(reply, {"strat-1"}, HEADLINES)["setups"] == []


def test_parse_scan_strips_invalid_source_indexes():
    reply = json.dumps({"setups": [
        {"strategy_id": "strat-1", "whats_happening": "x",
         "source_indexes": [1, 99, "not-a-number"],  # 99 and the string are bogus
         "bull_case": "b", "counter_case": "c", "risks": ["r"],
         "confidence": {"level": "medium"}},
    ], "note": "n"})
    result = parse_scan_response(reply, {"strat-1"}, HEADLINES)
    assert len(result["setups"]) == 1
    assert result["setups"][0]["sources"] == [HEADLINES[0]]  # only index 1 survived


def test_parse_scan_drops_setup_left_with_zero_valid_sources():
    reply = json.dumps({"setups": [
        {"strategy_id": "strat-1", "whats_happening": "x",
         "source_indexes": [99],  # entirely out of range
         "bull_case": "b", "counter_case": "c", "risks": ["r"],
         "confidence": {"level": "low"}},
    ], "note": "n"})
    assert parse_scan_response(reply, {"strat-1"}, HEADLINES)["setups"] == []


def test_parse_scan_normalises_junk_confidence_to_low():
    reply = json.dumps({"setups": [
        {"strategy_id": "strat-1", "whats_happening": "x", "source_indexes": [1],
         "bull_case": "b", "counter_case": "c", "risks": ["r"],
         "confidence": {"level": "extremely certain!!"}},
    ], "note": "n"})
    result = parse_scan_response(reply, {"strat-1"}, HEADLINES)
    assert result["setups"][0]["confidence"]["level"] == "low"


def test_parse_scan_handles_a_null_note_without_crashing_or_faking_text():
    # str(None) would silently become the literal word "None" — a subtle
    # trap this parser must not fall into for any AI-supplied field.
    reply = json.dumps({"setups": [], "note": None})
    result = parse_scan_response(reply, {"strat-1"}, HEADLINES)
    assert result["note"] == ""


def test_parse_scan_a_null_counter_case_does_not_pass_as_valid():
    reply = json.dumps({"setups": [
        {"strategy_id": "strat-1", "whats_happening": "x", "source_indexes": [1],
         "bull_case": "b", "counter_case": None, "risks": ["r"],
         "confidence": {"level": "low"}},
    ], "note": "n"})
    result = parse_scan_response(reply, {"strat-1"}, HEADLINES)
    assert result["setups"] == []  # a null counter_case must NOT slip through


def test_parse_scan_accepts_a_well_formed_setup():
    reply = json.dumps({"setups": [
        {"strategy_id": "strat-1", "whats_happening": "Strait tensions rising.",
         "source_indexes": [1], "bull_case": "Energy could spike.",
         "counter_case": "Tensions have de-escalated before without incident.",
         "risks": ["fast reversal", "thin evidence so far"],
         "confidence": {"level": "medium", "note": "one source only"}},
    ], "note": "One live setup."})
    result = parse_scan_response(reply, {"strat-1"}, HEADLINES)
    assert len(result["setups"]) == 1
    setup = result["setups"][0]
    assert setup["whats_happening"] == "Strait tensions rising."
    assert setup["confidence"] == {"level": "medium", "note": "one source only"}
    assert result["note"] == "One live setup."


# ── run_scan, end to end ──────────────────────────────────────────────────

class FakeEventsSource:
    def __init__(self, headlines=None, fail=False):
        self._headlines = headlines if headlines is not None else HEADLINES
        self._fail = fail

    def get_event_headlines(self, queries, per_query=6):
        if self._fail:
            raise RuntimeError("news feed unreachable")
        return self._headlines


def _matching_provider(strategy_id):
    class Provider:
        def complete(self, system, user, max_tokens=4000):
            return json.dumps({"setups": [
                {"strategy_id": strategy_id, "whats_happening": "Something is happening.",
                 "source_indexes": [1], "bull_case": "b",
                 "counter_case": "the strongest reason to doubt it",
                 "risks": ["risk one"], "confidence": {"level": "low", "note": "thin"}},
            ], "note": "One setup found."})
    return Provider()


def test_run_scan_saves_latest_and_appends_history(tmp_path, monkeypatch):
    import dashboard.storage as storage
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)

    journal = make_journal(tmp_path)
    strategy = journal.create(STRATEGY_FIELDS, origin="leon")
    provider = _matching_provider(strategy["id"])

    result = run_scan(provider, FakeEventsSource(), journal, RULES)
    assert len(result["setups"]) == 1
    assert result["setups"][0]["strategy_name"] == "Oil chokepoint closure"
    assert (tmp_path / "setups_latest.json").exists()

    from dashboard.strategy_lab.setup_scanner import load_latest
    assert load_latest()["headlines_examined"] == 2

    history_doc = storage.get_doc("setups_history")
    history = history_doc.load()
    assert len(history) == 1
    assert history[0]["setups"][0]["confidence"] == "low"


def test_run_scan_with_no_strategies_raises_a_clear_error(tmp_path, monkeypatch):
    import dashboard.storage as storage
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    journal = make_journal(tmp_path)
    with pytest.raises(RuntimeError, match="No saved strategies"):
        run_scan(_matching_provider("whatever"), FakeEventsSource(), journal, RULES)


def test_run_scan_skips_the_ai_call_when_no_headlines_are_found(tmp_path, monkeypatch):
    import dashboard.storage as storage
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    journal = make_journal(tmp_path)
    journal.create(STRATEGY_FIELDS, origin="leon")

    class ExplodingProvider:
        def complete(self, system, user, max_tokens=4000):
            raise AssertionError("should never be called with zero headlines")

    result = run_scan(ExplodingProvider(), FakeEventsSource(headlines=[]), journal, RULES)
    assert result["setups"] == []
    assert result["headlines_examined"] == 0


# ── Brainstorm ────────────────────────────────────────────────────────────

def test_brainstorm_parser_extracts_the_array():
    reply = '```json\n[{"name": "A"}, {"name": "B"}]\n```'
    assert len(parse_brainstorm_response(reply)) == 2


class BrainstormProvider:
    """Returns 5 suggestions: 4 complete, 1 missing its exit_trigger."""
    def complete(self, system, user, max_tokens=4000):
        good = [{
            "name": f"Pattern {i}", "description": "desc",
            "entry_trigger": "entry", "exit_trigger": "exit",
            "assets": ["sector"], "risk_notes": "notes", "tags": ["tag"],
        } for i in range(4)]
        bad = [{"name": "Incomplete", "description": "desc",
               "entry_trigger": "entry", "exit_trigger": ""}]  # dropped
        return json.dumps(good + bad)


def test_brainstorm_saves_created_entries_badged_ai(tmp_path):
    journal = make_journal(tmp_path)
    created = run_brainstorm(BrainstormProvider(), journal, RULES)
    assert len(created) == 4
    assert all(s["origin"] == "ai" for s in created)
    assert len(journal.list()) == 4


def test_brainstorm_drops_incomplete_suggestions(tmp_path):
    journal = make_journal(tmp_path)
    run_brainstorm(BrainstormProvider(), journal, RULES)
    assert not any(s["name"] == "Incomplete" for s in journal.list())


def test_brainstorm_caps_at_the_configured_count(tmp_path):
    class OverGenerousProvider:
        def complete(self, system, user, max_tokens=4000):
            return json.dumps([{
                "name": f"P{i}", "description": "d", "entry_trigger": "e",
                "exit_trigger": "x", "assets": [], "risk_notes": "", "tags": [],
            } for i in range(10)])

    journal = make_journal(tmp_path)
    tight_rules = {"lab": {**RULES["lab"], "brainstorm_count": 2}}
    created = run_brainstorm(OverGenerousProvider(), journal, tight_rules)
    assert len(created) == 2


# ── Events source ─────────────────────────────────────────────────────────

CANNED_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Strait tensions escalate - Reuters</title>
    <link>https://example.com/1</link>
    <pubDate>Thu, 02 Jul 2026 10:00:00 GMT</pubDate>
  </item>
</channel></rss>"""


class FakeResponse:
    def __init__(self, text=""):
        self.text = text

    def raise_for_status(self):
        pass


def test_events_source_parses_headlines_and_tags_the_query(monkeypatch):
    import dashboard.datasources.events_source as events_module
    monkeypatch.setattr(events_module.requests, "get",
                        lambda *a, **k: FakeResponse(CANNED_RSS))

    source = EventNewsSource()
    headlines = source.get_event_headlines(["oil"], per_query=6)
    assert len(headlines) == 1
    assert headlines[0]["title"] == "Strait tensions escalate"
    assert headlines[0]["query"] == "oil"


def test_events_source_raises_when_every_query_fails(monkeypatch):
    import dashboard.datasources.events_source as events_module

    def _boom(*a, **k):
        raise ConnectionError("no network")
    monkeypatch.setattr(events_module.requests, "get", _boom)

    source = EventNewsSource()
    with pytest.raises(RuntimeError):
        source.get_event_headlines(["oil", "shipping"], per_query=6)


def test_events_source_one_failed_query_does_not_sink_the_others(monkeypatch):
    import dashboard.datasources.events_source as events_module
    calls = []

    def _get(url, **kwargs):
        calls.append(url)
        if len(calls) == 1:
            raise ConnectionError("flaky")
        return FakeResponse(CANNED_RSS)
    monkeypatch.setattr(events_module.requests, "get", _get)

    source = EventNewsSource()
    headlines = source.get_event_headlines(["oil", "shipping"], per_query=6)
    assert len(headlines) == 1  # the second query's result survived
