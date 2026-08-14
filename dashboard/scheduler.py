"""
scheduler.py — two optional background helpers that run inside the Mac
app's own process, on one shared 60-second-tick thread:

  1. The FILL scheduler — settles pending paper-trade orders once a day
     even if Leon never opens the dashboard. No AI call, no fresh
     analysis — just process_fills() and snapshot(), both of which the
     dashboard already runs on every page view; this just guarantees they
     also happen once a day on their own.

  2. The OVERNIGHT ANALYSIS scheduler — runs up to three fresh analyses a
     night while the US market is open and Leon is asleep (Sydney time),
     spending HIS Claude subscription's own usage window rather than
     dollars. Only fires when his Claude account is the active provider
     — an unattended loop must never silently spend an API key he didn't
     choose to spend while asleep.

Runs ONLY inside the Mac app's own long-lived process (started from
app.py's `if __name__ == "__main__":` block) — if the app isn't running
(or the Mac is asleep), nothing fires, and nothing is owed; the next
dashboard open catches up (fills settle on their own; a missed overnight
slot is skipped, not queued). Render/gunicorn never starts this thread at
all: the cloud copy resets on every restart anyway, and running a
background thread per gunicorn worker would mean it could fire twice.
Both helpers are off by default; Leon switches them on from the dashboard.
"""

import re
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from .config_loader import load_rules
from .storage import get_doc

SYDNEY_TZ = ZoneInfo("Australia/Sydney")
# The overnight schedule is set in market time, not Sydney time — it's
# what keeps the three run times correct year-round without Leon having
# to think about daylight saving on either side of the Pacific.
ET_TZ = ZoneInfo("America/New_York")

# Used only if rules.yaml's scheduler.analysis_times_et is ever missing.
DEFAULT_ANALYSIS_TIMES_ET = ["09:35", "12:30", "15:30"]


def load_settings():
    """{"enabled": bool, "last_run_date": "YYYY-MM-DD" or None}."""
    return get_doc("scheduler").load() or {"enabled": False, "last_run_date": None}


def save_settings(settings):
    get_doc("scheduler").save(settings)


# ── The overnight analysis scheduler ──────────────────────────────────────

def load_overnight_settings():
    """{"enabled": bool, "times_et": [3 "HH:MM" strings] or None,
    "last_runs": {"HH:MM": "YYYY-MM-DD run for that slot"},
    "last_error": str or None}.

    times_et: None means "use rules.yaml's scheduler.analysis_times_et
    defaults" — set only once Leon has edited the times in the dashboard.
    """
    return get_doc("overnight").load() or {
        "enabled": False, "times_et": None, "last_runs": {}, "last_error": None,
    }


def save_overnight_settings(settings):
    get_doc("overnight").save(settings)


def effective_analysis_times(settings, rules=None):
    """The three ET times actually in effect right now: Leon's saved
    times if he's customised them, else rules.yaml's defaults. Always
    returns real numbers, whether or not he's ever touched the setting."""
    if settings.get("times_et"):
        return settings["times_et"]
    rules = rules or load_rules()
    return rules.get("scheduler", {}).get(
        "analysis_times_et", DEFAULT_ANALYSIS_TIMES_ET)


_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def validate_analysis_times(times):
    """Check three candidate overnight-run times before saving. Raises
    ValueError with a friendly, specific message on the first problem
    found — exactly three, each a real HH:MM, each inside the US trading
    session (09:30-16:00 ET), and all three different from each other
    (three runs must mean three different moments in the night)."""
    if not isinstance(times, list) or len(times) != 3:
        raise ValueError("Give exactly three times.")
    for t in times:
        if not isinstance(t, str) or not _TIME_RE.match(t):
            raise ValueError(f"'{t}' isn't a valid 24-hour HH:MM time.")
        if not ("09:30" <= t <= "16:00"):
            raise ValueError(
                f"{t} ET is outside the US trading session (09:30-16:00).")
    if len(set(times)) != 3:
        raise ValueError("The three times must be different from each other.")


def _slots_due(settings, now_et, slots):
    """Every slot time that's due right now — weekday only (the market
    lives Mon-Fri; US holidays are NOT checked, so a holiday tick just
    wastes one run on a stale close, which is harmless) and not already
    run for today's ET date. Internal helper shared by due_analysis_slot
    (which reports just the one to fire) and run_overnight_once (which
    must mark ALL of them caught up, not just the one it fires)."""
    if now_et.weekday() >= 5:  # Monday=0 … Saturday=5, Sunday=6
        return []
    today = now_et.date().isoformat()
    last_runs = settings.get("last_runs") or {}
    now_hhmm = now_et.strftime("%H:%M")
    return [s for s in slots if now_hhmm >= s and last_runs.get(s) != today]


def due_analysis_slot(settings, now_et, slots):
    """The single slot that should trigger an overnight analysis run
    right now, or None. If MORE than one slot is currently due (the Mac
    was asleep through an earlier one and just woke up), returns the
    LATEST — one catch-up run on the freshest data beats several stale
    ones. This also gives a nice morning behaviour for free: Mac asleep
    all night, dashboard opened after the close → one run on final
    closing prices, using whatever slot time is closest to now."""
    due = _slots_due(settings, now_et, slots)
    return due[-1] if due else None


def should_run_overnight_analysis(settings, now_et, slots, provider_name):
    """Should an overnight run fire right now, and for which slot?
    Combines due_analysis_slot with the toggle and the PROVIDER GATE: an
    unattended loop must never silently spend an API key Leon toggled
    away from — only his own Claude account (his subscription's usage
    window, not dollars) is allowed to fire on its own while he's asleep.
    """
    if not settings.get("enabled"):
        return None
    if provider_name != "claude_code":
        return None
    return due_analysis_slot(settings, now_et, slots)


def run_overnight_once(settings, now_et, slots, provider_name, run_analysis_fn):
    """Fire one overnight analysis run if one is due right now.

    run_analysis_fn — a one-argument callable, run_analysis_fn(slot),
    supplied by app.py (which owns the watchlists/provider/portfolio and
    the analysis lock) — this module stays unaware of any of that, the
    same separation the fill scheduler already has from PaperPortfolio.

    Marks EVERY currently-due slot done for today's ET date BEFORE
    calling run_analysis_fn — same reasoning as the fill scheduler: if
    the run itself fails partway through, the next slot (or tomorrow's
    session) is a perfectly fine retry, not an endless loop against the
    same slot. Any error the run raises is caught here and recorded in
    last_error for the dashboard to show — a rate-limit hit or a provider
    hiccup must not kill this thread for the rest of the app's life.

    Returns True if a run was attempted (successfully or not), False if
    nothing was due."""
    slot = should_run_overnight_analysis(settings, now_et, slots, provider_name)
    if slot is None:
        return False

    today = now_et.date().isoformat()
    last_runs = dict(settings.get("last_runs") or {})
    for s in _slots_due(settings, now_et, slots):
        last_runs[s] = today
    settings["last_runs"] = last_runs
    settings["last_error"] = None  # clear any earlier error — we're trying again
    save_overnight_settings(settings)

    try:
        run_analysis_fn(slot)
    except Exception as e:
        settings = load_overnight_settings()  # re-read: the run may have
                                              # touched other fields too
        settings["last_error"] = str(e)
        save_overnight_settings(settings)
    return True


# ── The order-fill scheduler ────────────────────────────────────────────

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


def start_scheduler_thread(portfolio, fill_hour=8, poll_seconds=60,
                           run_overnight_analysis=None):
    """Start the ONE background loop that drives both schedulers. Call
    this once, from app.py's `__main__` block only — never at import
    time, and never under gunicorn (see the module docstring for why).

    run_overnight_analysis — optional one-argument callable, supplied by
    app.py, that actually runs one overnight analysis for a given slot
    (get_provider() + searcher.run_analysis() + place_orders() — see
    app.py's _run_overnight_analysis()). Pass None to disable the
    overnight scheduler entirely (still used by tests that only care
    about the fill scheduler)."""

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

            if run_overnight_analysis is not None:
                try:
                    # Imported here, not at module level: this file must
                    # stay importable (and testable) without pulling in
                    # the whole llm package.
                    from .llm.provider import current_provider_name
                    now_et = datetime.now(ET_TZ)
                    overnight_settings = load_overnight_settings()
                    slots = effective_analysis_times(overnight_settings)
                    run_overnight_once(overnight_settings, now_et, slots,
                                       current_provider_name(),
                                       run_overnight_analysis)
                except Exception:
                    # Same reasoning as the fill scheduler above — a
                    # flaky tick must not end the thread's life. (Errors
                    # from inside a run itself are already caught and
                    # recorded by run_overnight_once — this is a second,
                    # outer net for the tick's own plumbing.)
                    pass

            time.sleep(poll_seconds)

    threading.Thread(target=_loop, daemon=True).start()
