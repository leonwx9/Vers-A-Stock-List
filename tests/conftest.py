"""Test-wide safety net: the test suite must NEVER touch the real cloud
database, no matter what's in .env.

Several test modules import dashboard.app (to test its Flask routes), and
app.py calls load_dotenv() at import time — which pulls Leon's real
DATABASE_URL into os.environ for the rest of the pytest process the
moment any such module is collected. Without this fixture, any OTHER
test that monkeypatches storage.DATA_DIR (expecting to write into a temp
folder) would silently ignore that and read/write Leon's REAL production
Neon database instead — which is exactly what happened once already
(2026-08-19, caught because 17 tests failed against unexpectedly-real
data; fixed by re-running migrate_to_neon.py to restore it).

Set to an EMPTY STRING, not deleted — several functions under test
(get_provider(), current_provider_name()) call load_dotenv() again
partway through their own execution. dotenv's default override=False
only skips a key that's already PRESENT in os.environ, regardless of its
value — so delenv() leaves the door open for a later load_dotenv() call
inside the test to silently re-import the real DATABASE_URL from disk
(confirmed happening: get_provider() built a real ClaudeCodeProvider off
Leon's actual toggle choice in Neon instead of the test's own env/temp
storage). An empty string is "already present" as far as dotenv is
concerned, so it can never be re-populated once this fixture runs.

autouse + function-scoped so it's set immediately before EVERY test body
runs, regardless of when or how many times load_dotenv() already
populated it during collection.
"""

import pytest


@pytest.fixture(autouse=True)
def no_real_database(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
