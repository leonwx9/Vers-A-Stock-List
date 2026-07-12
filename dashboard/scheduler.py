"""
scheduler.py — an optional, once-a-day helper that settles pending paper-
trade orders even if Leon never opens the dashboard that day.

This is deliberately the ONLY thing it does: no AI call, no Strategy Lab
scan, no fresh analysis — just process_fills() (settle anything the market
has already made due) and snapshot() (record today's portfolio-graph
point). Both are already free, no-AI operations the dashboard already runs
on every page view; this just makes sure they also happen once a day even
if nobody's watching.

Runs ONLY inside the Mac app's own long-lived process (started from
app.py's `if __name__ == "__main__":` block) — if the app isn't running,
this can't fire, and nothing is owed. Render/gunicorn never starts this
thread at all: the cloud copy resets on every restart anyway, and running
a background thread per gunicorn worker would mean it could fire twice.
Off by default; Leon switches it on from the Paper Portfolio panel.
"""

import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from .storage import get_doc

SYDNEY_TZ = ZoneInfo("Australia/Sydney")


def load_settings():
    """{"enabled": bool, "last_run_date": "YYYY-MM-DD" or None}."""
    return get_doc("scheduler").load() or {"enabled": False, "last_run_date": None}


def save_settings(settings):
    get_doc("scheduler").save(settings)


def should_run(settings, now_sydney, fill_hour):
    """Should today's automatic fill-run happen right now?

    now_sydney — a timezone-aware datetime already converted to Sydney
                 time (passed in, not computed here, so tests can hand in
                 any moment without faking the clock).
    fill_hour  — the Sydney HOUR (0-23) after which the run becomes due;
                 "at or past" that hour (not "exactly"), so starting the
                 app later in the day still catches up today's run.
    """
    if not settings.get("enabled"):
        return False
    if now_sydney.hour < fill_hour:
        return False
    today = now_sydney.date().isoformat()
    return settings.get("last_run_date") != today


def run_once(portfolio, settings, now_sydney):
    """Settle due orders and record today's graph point. Marks today's
    date done BEFORE the work, same reasoning as the Lab's daily scan: if
    something goes wrong partway through, the next tick (or the next time
    Leon opens the dashboard, which settles fills on its own anyway) is a
    perfectly fine fallback — no need to retry within the same day.

    `now_sydney` is also handed to process_fills(): it's timezone-aware,
    so the engine's own NY-time conversion works correctly, and it keeps
    this whole call using ONE consistent instant instead of quietly
    re-reading the real clock partway through."""
    settings["last_run_date"] = now_sydney.date().isoformat()
    save_settings(settings)
    portfolio.process_fills(now=now_sydney)
    portfolio.snapshot()


def start_scheduler_thread(portfolio, fill_hour=8, poll_seconds=60):
    """Start the background loop. Call this once, from app.py's
    `__main__` block only — never at import time, and never under
    gunicorn (see the module docstring for why)."""

    def _loop():
        while True:
            try:
                now_sydney = datetime.now(SYDNEY_TZ)
                settings = load_settings()
                if should_run(settings, now_sydney, fill_hour):
                    run_once(portfolio, settings, now_sydney)
            except Exception:
                # A flaky price fetch at 8am must not kill this thread for
                # the rest of the app's life — just try again next minute.
                pass
            time.sleep(poll_seconds)

    threading.Thread(target=_loop, daemon=True).start()
