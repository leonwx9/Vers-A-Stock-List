"""
edgar.py — talks to SEC EDGAR, the US regulator's free public filing system.

Three jobs, all key-less:
  1. full_text_search()   — find recent filings containing a phrase
                            (the API behind efts.sec.gov full-text search)
  2. get_company_info()   — a company's sector and tickers
                            (the data.sec.gov submissions API)
  3. fetch_filing_excerpts() — download a filing and pull out the text
                            around its AI mentions, so the AI analyst reads
                            what the company ACTUALLY said

SEC etiquette: they ask every script to identify itself via the User-Agent
header and to stay well under 10 requests/second — hence the contact string
and the small sleep between calls.
"""

import os
import re
import time

import requests

FTS_URL = "https://efts.sec.gov/LATEST/search-index"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:0>10}.json"
FILING_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{filename}"

# SIC codes (the SEC's industry classification) that mean "technology" —
# the fallback when a company's ownerOrg field is missing.
TECH_SIC_CODES = {
    "3571", "3572", "3575", "3577", "3578",  # computers & storage
    "3661", "3663", "3669", "3672", "3674", "3675", "3677", "3678", "3679",  # electronics/semis
    "7370", "7371", "7372", "7373", "7374", "7375", "7377", "7378", "7379",  # software & IT services
}


def _headers():
    # SEC asks for a descriptive User-Agent with contact details.
    # Set SEC_EDGAR_CONTACT in .env (e.g. "your-name you@email.com").
    contact = os.getenv("SEC_EDGAR_CONTACT", "Vers-A-Dashboard personal-use")
    return {"User-Agent": contact}


# One shared connection that gets reused across requests ("keep-alive") —
# both faster and friendlier to SEC's servers than reconnecting every time.
_session = requests.Session()


def _get(url, **kwargs):
    """One polite GET: identified, rate-limited, 20s timeout.

    Two EDGAR quirks handled here:
      - the search API occasionally returns a 5xx for a query that works
        seconds later, and
      - SEC answers bursts of requests with 403 (their rate-limit signal),
        which clears after a short cool-down.
    Both get retried with growing pauses before we give up.
    """
    last_error = None
    for attempt in range(4):
        time.sleep(0.4 + attempt * 3)  # polite pacing + backoff on retries
        try:
            response = _session.get(url, headers=_headers(), timeout=20, **kwargs)
            response.raise_for_status()
            return response
        except requests.HTTPError as e:
            last_error = e
            status = e.response.status_code
            if status < 500 and status != 403:
                raise      # a genuine client error; retrying won't help
    raise last_error


class EdgarClient:
    def full_text_search(self, phrase, forms, startdt, enddt):
        """Filings from the date window whose text contains the exact phrase.
        Returns the raw hit list from EDGAR's search API."""
        response = _get(FTS_URL, params={
            "q": f'"{phrase}"',      # quotes = exact-phrase search
            "forms": ",".join(forms),
            "startdt": startdt,
            "enddt": enddt,
        })
        return response.json().get("hits", {}).get("hits", [])

    def get_company_info(self, cik):
        """Sector and ticker info for one company (by its SEC id, the CIK)."""
        data = _get(SUBMISSIONS_URL.format(cik=int(cik))).json()
        return {
            "name": data.get("name", ""),
            "tickers": data.get("tickers", []),
            "sic": data.get("sic", ""),
            "sic_description": data.get("sicDescription", ""),
            # ownerOrg looks like "06 Technology" — SEC's own sector bucket.
            "owner_org": data.get("ownerOrg") or "",
        }

    def fetch_filing_excerpts(self, cik, doc_id, max_chars=3000):
        """Download a filing document and return the text around its AI
        mentions. doc_id comes from search hits, shaped
        'accession-number:filename.htm'."""
        accession, filename = doc_id.split(":", 1)
        url = FILING_URL.format(
            cik=int(cik),
            accession=accession.replace("-", ""),
            filename=filename,
        )
        html = _get(url).text
        return extract_ai_excerpts(html, max_chars), url


def is_tech_company(info, excluded_sectors):
    """True if this company belongs to a sector we exclude (e.g. Technology).

    Primary check: SEC's ownerOrg bucket. Fallback: the SIC code list above.
    """
    for sector in excluded_sectors:
        if sector.lower() in info["owner_org"].lower():
            return True
    return info["sic"] in TECH_SIC_CODES


def extract_ai_excerpts(html, max_chars=3000):
    """Strip a filing's HTML down to plain text, then return the passages
    around each AI mention (a pure function, so tests can feed it canned HTML)."""
    # Remove scripts/styles wholesale, then all remaining tags.
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;|&#160;", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    # Find each mention of AI and grab ~700 characters around it.
    pattern = re.compile(r"artificial intelligence|\bA\.?I\.?\b", re.IGNORECASE)
    excerpts, covered_to = [], 0
    for match in pattern.finditer(text):
        start = max(0, match.start() - 350)
        end = min(len(text), match.end() + 350)
        if start < covered_to:      # overlaps the previous excerpt — skip
            continue
        excerpts.append("…" + text[start:end] + "…")
        covered_to = end
        if sum(len(e) for e in excerpts) >= max_chars:
            break
    return "\n\n".join(excerpts)[:max_chars]
