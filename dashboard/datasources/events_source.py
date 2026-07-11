"""
events_source.py — fetches recent news headlines about real-world EVENTS
(wars, chokepoints, elections, commodities) rather than one company.

Same free Google News RSS feed as news_source.py (no key), reusing its
parser — only the query changes. Kept as its own small class behind its
own method so the Strategy Lab's setup scanner never talks to raw HTTP
directly: a future upgrade (GDELT, or a crypto-events feed) swaps in here
without touching the Lab's code, the same pattern PriceSource/LLM provider
already use in this project.
"""

import requests

from .news_source import FEED_URL, parse_rss


class EventNewsSource:
    """Recent headlines about a real-world event TOPIC (not a ticker)."""

    def get_event_headlines(self, queries, per_query=6):
        """queries — search phrases (e.g. a strategy's tags). Returns a
        flat list of headline dicts, each carrying which query found it:
        {title, source, link, published, query}.

        One failed search is skipped — a single flaky query shouldn't
        sink the whole scan. If EVERY query fails, raises RuntimeError:
        an honest error beats silently reporting "nothing found" when the
        feed itself was actually unreachable.
        """
        headlines = []
        failures = 0
        for query in queries:
            try:
                response = requests.get(
                    FEED_URL.format(query=requests.utils.quote(query)),
                    timeout=10,
                    headers={"User-Agent": "Mozilla/5.0"},  # some feeds reject bare scripts
                )
                response.raise_for_status()
                for item in parse_rss(response.text, limit=per_query):
                    headlines.append({**item, "query": query})
            except Exception:
                failures += 1
        if queries and failures == len(queries):
            raise RuntimeError("Could not fetch any event headlines right now — "
                              "the news feed may be temporarily unreachable.")
        return headlines
