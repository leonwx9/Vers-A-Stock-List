"""Tests for the AI Pivot Scanner — fake EDGAR client and fake AI provider,
so everything runs offline with no keys and no SEC traffic."""

import json

from dashboard.scanner.edgar import extract_ai_excerpts, is_tech_company
from dashboard.scanner.pivot_scanner import parse_analysis_response, run_scan

# ── The pure helpers ──────────────────────────────────────────────────────

def test_excerpt_extraction_finds_ai_passages():
    html = ("<html><style>p{color:red}</style><body><p>Boring intro.</p>"
            "<p>The company announced a major artificial intelligence "
            "initiative to transform its logistics arm.</p></body></html>")
    text = extract_ai_excerpts(html)
    assert "artificial intelligence" in text
    assert "color:red" not in text          # styles stripped
    assert "<p>" not in text                # tags stripped


def test_excerpt_extraction_returns_empty_when_no_ai_mentions():
    assert extract_ai_excerpts("<p>We sell agricultural equipment.</p>") == ""


def test_tech_filter_uses_owner_org_and_sic():
    tech_by_org = {"owner_org": "06 Technology", "sic": "1000"}
    tech_by_sic = {"owner_org": "", "sic": "7372"}
    non_tech = {"owner_org": "05 Real Estate & Construction", "sic": "1531"}
    assert is_tech_company(tech_by_org, ["Technology"])
    assert is_tech_company(tech_by_sic, ["Technology"])
    assert not is_tech_company(non_tech, ["Technology"])


def test_analysis_parser_clamps_hype_score():
    reply = json.dumps({"qualifies": True, "hype_score": 42})
    assert parse_analysis_response(reply)["hype_score"] == 10


# ── The full scan, wired with fakes ──────────────────────────────────────

class FakeEdgar:
    """Stands in for EDGAR: two companies, one tech and one non-tech."""

    def full_text_search(self, phrase, forms, startdt, enddt):
        return [
            {"_id": "0001-26-000001:doc1.htm",
             "_source": {"ciks": ["111"], "file_date": "2026-06-20",
                         "root_form": "8-K"}},
            {"_id": "0001-26-000002:doc2.htm",
             "_source": {"ciks": ["222"], "file_date": "2026-06-25",
                         "root_form": "8-K"}},
        ]

    def get_company_info(self, cik):
        if cik == "111":
            return {"name": "SoftCo Inc", "tickers": ["SFT"], "sic": "7372",
                    "sic_description": "Prepackaged Software",
                    "owner_org": "06 Technology"}
        return {"name": "Dirt Movers Corp", "tickers": ["DIRT"], "sic": "1531",
                "sic_description": "Operative Builders",
                "owner_org": "05 Real Estate & Construction"}

    def fetch_filing_excerpts(self, cik, doc_id):
        return ("…we are pivoting our earthmoving business into artificial "
                "intelligence-powered site surveying…",
                "https://example.com/filing.htm")


class FakeProvider:
    def complete(self, system, user, max_tokens=4000):
        return json.dumps({
            "qualifies": True,
            "disqualified_because": None,
            "what_they_announced": "An AI site-surveying push.",
            "announced_vs_executed": "Announcement only so far.",
            "funding_ability": "Thin cash position.",
            "red_flags": ["buzzword-heavy"],
            "hype_score": 8,
            "bottom_line": "Skepticism warranted.",
        })


RULES = {
    "scanner": {"max_market_cap": 1_000_000_000,
                "excluded_sectors": ["Technology"],
                "lookback_days": 30, "max_candidates": 8},
    "analysis": {"max_workers": 2},
}


def test_scan_excludes_tech_and_reports_the_rest(tmp_path, monkeypatch):
    import dashboard.storage as storage
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)

    result = run_scan(FakeProvider(), FakeEdgar(), rules=RULES)

    # The tech company was excluded before any AI request was spent on it.
    assert result["candidates_checked"] == 1
    excluded_names = [e["company"] for e in result["excluded"]]
    assert "SoftCo Inc" in excluded_names

    # The non-tech company qualified, with the skeptical fields present.
    assert len(result["hits"]) == 1
    hit = result["hits"][0]
    assert hit["company"] == "Dirt Movers Corp"
    assert hit["hype_score"] == 8
    assert hit["filing_url"].startswith("https://")
    assert (tmp_path / "scanner_latest.json").exists()


def test_scan_puts_non_qualifiers_in_excluded(tmp_path, monkeypatch):
    import dashboard.storage as storage
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)

    class SkepticalProvider:
        def complete(self, system, user, max_tokens=4000):
            return json.dumps({"qualifies": False,
                               "disqualified_because": "routine AI-tool mention"})

    result = run_scan(SkepticalProvider(), FakeEdgar(), rules=RULES)
    assert result["hits"] == []
    reasons = [e["reason"] for e in result["excluded"]]
    assert "routine AI-tool mention" in reasons
