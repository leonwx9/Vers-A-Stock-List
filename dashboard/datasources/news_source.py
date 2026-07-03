"""
news_source.py — fetches recent news headlines for a ticker.

Uses Google News' free RSS feed (no API key needed). Like the price sources,
this sits behind a small interface so a different news provider can be
swapped in later without touching the rest of the app.

If the feed is unreachable, we return an empty list rather than crashing —
the deep-dive analysis then simply says sentiment evidence is unavailable.
"""

import xml.etree.ElementTree as ET

import requests

FEED_URL = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"


def parse_rss(xml_text, limit=8):
    """Turn RSS XML into a simple list of headline dicts.

    Kept as a separate pure function so tests can feed it canned XML
    without any network access.
    """
    root = ET.fromstring(xml_text)
    headlines = []
    for item in root.iter("item"):
        title = item.findtext("title", "").strip()
        if not title:
            continue
        # Google News titles end with " - Publisher"; split that out.
        source = item.findtext("source", "").strip()
        if not source and " - " in title:
            title, source = title.rsplit(" - ", 1)
        headlines.append({
            "title": title,
            "source": source,
            "link": item.findtext("link", "").strip(),
            "published": item.findtext("pubDate", "").strip(),
        })
        if len(headlines) >= limit:
            break
    return headlines


class GoogleNewsSource:
    """Recent headlines about a ticker, via Google News RSS."""

    def get_headlines(self, symbol, company_name, limit=8):
        # Search for the company name AND ticker to keep results on-topic
        # (searching bare "V" or "GE" alone would return junk).
        query = requests.utils.quote(f'"{company_name}" {symbol} stock')
        try:
            response = requests.get(
                FEED_URL.format(query=query),
                timeout=10,
                headers={"User-Agent": "Mozilla/5.0"},  # some feeds reject bare scripts
            )
            response.raise_for_status()
            return parse_rss(response.text, limit)
        except Exception:
            # No news is better than no page — the caller handles the empty list.
            return []
