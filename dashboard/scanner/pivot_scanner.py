"""
pivot_scanner.py — the AI Pivot Scanner engine.

One scan does this:
  1. Search EDGAR's full-text index for recent filings (last N days,
     rules.yaml) containing AI-pivot phrases.
  2. Deduplicate to one filing per company, drop companies in excluded
     sectors (Technology), cap how many we examine per scan.
  3. Download each remaining filing and pull the passages around its AI
     mentions — so the analysis reads what the company ACTUALLY said.
  4. Ask Claude for a SKEPTICAL read of each: is this a genuine, newly
     disclosed pivot by a small non-tech company — announced or actually
     executed, can they fund it, what are the red flags?
  5. Save everything to data/scanner_latest.json for the web page.

Detection is strictly AFTER public disclosure — we only read filings that
are already published on EDGAR. Never prediction.
"""

import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path

from ..config_loader import load_rules
from ..storage import get_doc
from .edgar import is_tech_company


# The disclosure language we hunt for. Editable without touching code logic.
# Checked against real EDGAR data (July 2026): "AI strategy" is what filers
# actually write; the longer phrases are rarer but catch the explicit cases.
SEARCH_PHRASES = [
    "AI strategy",
    "artificial intelligence strategy",
    "pivot to artificial intelligence",
    "pivot to AI",
    "artificial intelligence initiative",
    "expansion into artificial intelligence",
]

SYSTEM_PROMPT = """\
You are a deeply SKEPTICAL securities analyst inside a private research
dashboard. Nothing you write is investment advice. Companies announcing AI
pivots are often chasing a hot narrative — your job is to separate substance
from hype. Write plain English a beginner can follow.
You respond ONLY with a JSON object — no prose before or after it."""

ANALYSIS_PROMPT = """\
{name} (ticker: {ticker}; industry per SEC: {sic_description}) filed a
{form} with the SEC on {file_date}. Below are the passages of that filing
that mention AI:

{excerpts}

First decide whether this QUALIFIES as what we're scanning for — ALL three:
  a) plausibly a SMALL company (market cap under ~$1B — judge from your
     general knowledge; if genuinely unsure, qualify it and say so),
  b) NOT primarily a technology company,
  c) a NEWLY DISCLOSED pivot/expansion INTO AI-related business — not
     boilerplate risk-factor language, not routine mention of using AI
     tools, not an established AI business describing ongoing operations.

Return ONE JSON object with exactly these keys:
  "qualifies":            true or false
  "disqualified_because": null, or one short sentence if qualifies=false
  "what_they_announced":  1-2 plain sentences on the AI move they disclosed
  "announced_vs_executed": Have they actually DONE anything (products,
                          revenue, hires, contracts) or only announced
                          intentions? 1-2 sentences.
  "funding_ability":      Can a company like this realistically fund an AI
                          push (cash position, profitability, dilution risk
                          — from your general knowledge, flag if dated)?
                          1-2 sentences.
  "red_flags":            array of 1-4 short strings (e.g. "buzzword-heavy,
                          no named product", "history of pivots to hot
                          sectors")
  "hype_score":           integer 1-10 — 10 means pure hype, 1 means real
                          substance
  "bottom_line":          one skeptical plain-English sentence"""


def parse_analysis_response(text):
    """Pull the JSON object out of the AI's reply (stripping ``` fences)."""
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object found in AI reply: {text[:200]}")
    result = json.loads(cleaned[start : end + 1])
    result["hype_score"] = max(1, min(10, int(result.get("hype_score", 5))))
    return result


def _collect_candidates(edgar, rules):
    """Steps 1+2: search EDGAR, dedupe by company, filter sector, cap count."""
    scanner_rules = rules["scanner"]
    enddt = date.today().isoformat()
    startdt = (date.today() - timedelta(days=scanner_rules["lookback_days"])).isoformat()

    # Search every phrase; keep one (newest) filing per company.
    by_cik = {}
    for phrase in SEARCH_PHRASES:
        try:
            hits = edgar.full_text_search(phrase, forms=["8-K"],
                                          startdt=startdt, enddt=enddt)
        except Exception:
            continue  # one flaky phrase-search shouldn't sink the whole scan
        for hit in hits:
            source = hit.get("_source", {})
            ciks = source.get("ciks", [])
            if not ciks:
                continue
            cik = ciks[0]
            file_date = source.get("file_date", "") or source.get("period_ending", "")
            already = by_cik.get(cik)
            if already is None or file_date > already["file_date"]:
                by_cik[cik] = {
                    "cik": cik,
                    "doc_id": hit.get("_id", ""),
                    "form": source.get("root_form") or source.get("file_type", "8-K"),
                    "file_date": file_date,
                    "matched_phrase": phrase,
                }

    # Sector filter + cap. Newest filings first.
    candidates, excluded = [], []
    ordered = sorted(by_cik.values(), key=lambda c: c["file_date"], reverse=True)
    for cand in ordered:
        if len(candidates) >= scanner_rules["max_candidates"]:
            break
        info = edgar.get_company_info(cand["cik"])
        if is_tech_company(info, scanner_rules["excluded_sectors"]):
            excluded.append({
                "company": info["name"],
                "reason": f"technology sector ({info['sic_description'] or info['owner_org']})",
            })
            continue
        cand["company"] = info
        candidates.append(cand)
    return candidates, excluded


def run_scan(provider, edgar, rules=None, on_progress=None):
    """Run one full scan. Returns the result dict (also saved to disk)."""
    rules = rules or load_rules()
    candidates, excluded = _collect_candidates(edgar, rules)

    # Step 3: download each filing's AI passages (sequential — SEC politeness).
    for cand in candidates:
        try:
            cand["excerpts"], cand["filing_url"] = edgar.fetch_filing_excerpts(
                cand["cik"], cand["doc_id"])
        except Exception:
            cand["excerpts"], cand["filing_url"] = "", ""

    # Step 4: the skeptical AI read — a few at a time, like the searcher.
    def analyze(cand):
        info = cand["company"]
        prompt = ANALYSIS_PROMPT.format(
            name=info["name"],
            ticker=", ".join(info["tickers"]) or "unlisted/unknown",
            sic_description=info["sic_description"] or "unknown",
            form=cand["form"], file_date=cand["file_date"],
            excerpts=cand["excerpts"] or "(the filing text could not be fetched)",
        )
        try:
            return parse_analysis_response(
                provider.complete(SYSTEM_PROMPT, prompt, max_tokens=1500))
        except Exception as e:
            return {"qualifies": False,
                    "disqualified_because": f"analysis failed: {e}"}

    results = []
    if candidates:
        with ThreadPoolExecutor(max_workers=rules["analysis"]["max_workers"]) as pool:
            analyses = list(pool.map(analyze, candidates))
        for cand, analysis in zip(candidates, analyses):
            entry = {
                "company": cand["company"]["name"],
                "ticker": ", ".join(cand["company"]["tickers"]),
                "industry": cand["company"]["sic_description"],
                "form": cand["form"],
                "file_date": cand["file_date"],
                "filing_url": cand["filing_url"],
                "matched_phrase": cand["matched_phrase"],
                **analysis,
            }
            if analysis.get("qualifies"):
                results.append(entry)
            else:
                excluded.append({
                    "company": cand["company"]["name"],
                    "reason": analysis.get("disqualified_because") or "did not qualify",
                })
        if on_progress:
            on_progress(len(candidates), len(candidates))

    result = {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "lookback_days": rules["scanner"]["lookback_days"],
        "candidates_checked": len(candidates),
        "hits": sorted(results, key=lambda r: r["file_date"], reverse=True),
        "excluded": excluded,
    }

    get_doc("scanner_latest").save(result)
    return result


def load_latest():
    """Return the last saved scan, or None if no scan has happened yet."""
    return get_doc("scanner_latest").load()
