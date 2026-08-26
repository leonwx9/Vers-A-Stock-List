"""Test-wide safety net: the test suite must NEVER touch the real cloud
database, no matter what's in .env.

THE MODULE-LEVEL LINE BELOW (not the fixture) is the actual fix. dashboard/
app.py builds its `watchlists` and `portfolio` objects exactly ONCE, the
moment it's first imported — e.g. `watchlists = WatchlistStore()`, which
calls storage.get_doc() once and keeps that connection forever. Several
test files import dashboard.app to test its Flask routes; pytest imports
every test module during COLLECTION, before running any fixture (even an
autouse one) — so by the time any fixture could clear DATABASE_URL, those
singletons had already locked onto Leon's real Neon database. A fixture
alone was tried and failed (2026-08-19): it protects code that calls
get_doc() fresh inside a test, but not objects already built at import.
Confirmed damage from that gap: every full test-suite run silently
created a real "From the phone" watchlist in production (test_viewer_mode
exercises a real, allowed-even-in-viewer-mode watchlist-create route) —
5 copies before this was caught and cleaned up.

Setting os.environ here, as plain module-level code, runs when pytest
loads THIS conftest.py — which always happens before it imports any test
module in this directory, so dashboard.app's load_dotenv() finds
DATABASE_URL already present (as "") and — per dotenv's override=False
default, which only skips a key already PRESENT, regardless of its value
— never overwrites it. That's what keeps the get_doc() calls inside
WatchlistStore()/PaperPortfolio() honest at import time.

The fixture below is a second, narrower layer: it re-applies the same
empty value before every individual test body, because a few functions
under test (get_provider(), current_provider_name()) call load_dotenv()
again mid-execution, and monkeypatch's teardown between tests would
otherwise let a later real load_dotenv() call have something to (not)
override. Belt and braces — the module-level line is what matters most.
"""

import os

import pytest

os.environ["DATABASE_URL"] = ""


@pytest.fixture(autouse=True)
def no_real_database(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
