"""
migrate_to_neon.py — one-off script: copies every saved document from the
local dashboard/data/*.json files into the shared Postgres database (Neon),
so the Mac and the cloud viewer read/write the same live data instead of
the cloud copy resetting on every restart.

Run ONCE, after DATABASE_URL is set in .env:
    ./venv/bin/python migrate_to_neon.py

Safe to re-run: each document is simply overwritten, always in the
direction files → database, never the other way — the Mac's files are
the permanent record; the database is catching up to match them.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

from dashboard.storage import DATA_DIR, FileDoc, PostgresDoc


def migrate(data_dir, url):
    """Copy every `data_dir`/*.json document into the Postgres database at
    `url`. Returns the list of document names copied. A plain function
    (not tied to os.environ/.env) so it's testable without a real database
    — see tests/test_migrate_to_neon.py."""
    names = []
    for path in sorted(data_dir.glob("*.json")):
        name = path.stem  # "portfolio.json" -> "portfolio"
        data = FileDoc(path).load()
        PostgresDoc(name, url).save(data)
        names.append(name)
    return names


def main():
    load_dotenv()
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        print("DATABASE_URL is not set in .env — nothing to migrate to. "
              "Set it first (see HANDOVER.md's Neon section), then run "
              "this again.")
        return

    if not DATA_DIR.exists() or not any(DATA_DIR.glob("*.json")):
        print(f"{DATA_DIR} has no saved documents yet — nothing to migrate.")
        return

    names = migrate(DATA_DIR, url)
    print(f"Migrated {len(names)} document(s) to the shared database:")
    for name in names:
        print(f"  ✓ {name}")
    print("\ndashboard/data/*.json files are left untouched — they're now "
          "a stale local backup; the database is the live copy from here.")


if __name__ == "__main__":
    main()
