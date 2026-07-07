"""Tests for the news parser and the deep-dive engine — all offline:
canned RSS XML and a fake AI provider, so no network and no API key."""

import json

from dashboard.analysis.deep_dive import (parse_deep_dive_response,
                                          run_deep_dive)
from dashboard.datasources.news_source import parse_rss

CANNED_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Apple unveils new chip - Reuters</title>
    <link>https://example.com/1</link>
    <pubDate>Thu, 02 Jul 2026 10:00:00 GMT</pubDate>
    <source url="https://reuters.com">Reuters</source>
  </item>
  <item>
    <title>Analysts split on iPhone demand - Bloomberg</title>
    <link>https://example.com/2</link>
    <pubDate>Wed, 01 Jul 2026 09:00:00 GMT</pubDate>
  </item>
</channel></rss>"""


def test_rss_parser_extracts_headlines():
    items = parse_rss(CANNED_RSS)
    assert len(items) == 2
    assert items[0]["title"] == "Apple unveils new chip - Reuters"
    assert items[0]["source"] == "Reuters"
    assert items[0]["link"] == "https://example.com/1"


def test_rss_parser_splits_publisher_from_title_when_no_source_tag():
    items = parse_rss(CANNED_RSS)
    # Second item has no <source> tag, so the publisher comes off the title.
    assert items[1]["title"] == "Analysts split on iPhone demand"
    assert items[1]["source"] == "Bloomberg"


def test_rss_parser_respects_limit():
    assert len(parse_rss(CANNED_RSS, limit=1)) == 1


FAKE_DEEP_DIVE = {
    "overview": "Apple makes phones.",
    "rating_rationale": "Strong brand.",
    "technical": {"score": 7, "explanation": "Uptrend."},
    "sentiment": {"score": 8, "explanation": "Positive coverage.",
                  "evidence": [{"headline": "Apple unveils new chip",
                                "takeaway": "Product momentum."}]},
    "fundamentals": {"score": 9, "explanation": "Very profitable."},
    "risks": ["Regulation", "China exposure"],
    "what_would_change": "A weak iPhone launch.",
}


class FakeProvider:
    def complete(self, system, user, max_tokens=4000):
        return "```json\n" + json.dumps(FAKE_DEEP_DIVE) + "\n```"


def test_deep_dive_parser_strips_code_fences():
    reply = "```json\n" + json.dumps(FAKE_DEEP_DIVE) + "\n```"
    assert parse_deep_dive_response(reply)["technical"]["score"] == 7


def test_run_deep_dive_saves_cache(tmp_path, monkeypatch):
    import dashboard.storage as storage
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)

    asset = {"symbol": "BRK/B", "name": "Berkshire", "type": "stock", "flags": []}
    quote = {"price": 465.0, "change_5d_pct": 1.2, "change_30d_pct": 3.4}

    result = run_deep_dive(FakeProvider(), asset, quote, headlines=[], conviction=7)

    assert result["symbol"] == "BRK/B"
    assert "generated_at" in result
    # The slash in BRK/B must be made file-safe.
    assert (tmp_path / "deepdive_BRK-B.json").exists()
