"""
storage.py — where saved app data (JSON documents) lives.

Every piece of runtime data — watchlists, the paper portfolio, the latest
analysis/scan, deep-dive caches — is one named JSON document. This module
answers a single question: where do those documents live?

  - Normally: as files in dashboard/data/ (exactly as before).
  - If DATABASE_URL is set in .env: in one table of a free cloud Postgres
    database (Neon/Supabase). That's what lets the cloud copy REMEMBER —
    Render's free disk is wiped on every restart, but the database isn't.

The rest of the app just calls get_doc("portfolio").load()/.save(data)
and never knows which one it got — same trick as the PriceSource swap.
"""

import json
import os
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"


class FileDoc:
    """One JSON document stored as a file (the default)."""

    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        """The document's contents, or None if it doesn't exist yet."""
        if not self.path.exists():
            return None
        with open(self.path) as f:
            return json.load(f)

    def save(self, data):
        self.path.parent.mkdir(exist_ok=True)
        # Write to a scratch file first, then swap it into place. os.replace
        # is atomic (all-or-nothing): if the app dies mid-write, the old
        # file survives intact instead of being left half-written — a
        # corrupted watchlists/portfolio file would stop the app booting.
        tmp_path = self.path.with_suffix(".json.tmp")
        with open(tmp_path, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, self.path)

    def delete(self):
        self.path.unlink(missing_ok=True)


class PostgresDoc:
    """One JSON document stored as a row in a cloud Postgres database.

    All documents share one two-column table (name → data). A connection
    is opened per operation — plenty for a one-user dashboard, and it
    can't leak connections.
    """

    _table_ready = False  # create the table once per process, not per call

    def __init__(self, name, url):
        self.name = name
        self.url = url

    def _run(self, query, params, fetch=False):
        import psycopg2  # imported here so file-mode never needs it installed

        conn = psycopg2.connect(self.url)
        try:
            with conn, conn.cursor() as cur:  # "with conn" commits on success
                if not PostgresDoc._table_ready:
                    cur.execute(
                        "CREATE TABLE IF NOT EXISTS app_docs ("
                        "  name TEXT PRIMARY KEY,"
                        "  data JSONB NOT NULL,"
                        "  updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"
                    )
                    PostgresDoc._table_ready = True
                cur.execute(query, params)
                return cur.fetchone() if fetch else None
        finally:
            conn.close()

    def load(self):
        row = self._run("SELECT data FROM app_docs WHERE name = %s",
                        (self.name,), fetch=True)
        return row[0] if row else None

    def save(self, data):
        self._run(
            "INSERT INTO app_docs (name, data, updated_at)"
            " VALUES (%s, %s, now())"
            " ON CONFLICT (name) DO UPDATE"
            "   SET data = EXCLUDED.data, updated_at = now()",
            (self.name, json.dumps(data)),
        )

    def delete(self):
        self._run("DELETE FROM app_docs WHERE name = %s", (self.name,))


def get_doc(name):
    """The document called `name`, from wherever documents live right now."""
    url = os.getenv("DATABASE_URL", "").strip()
    if url:
        return PostgresDoc(name, url)
    return FileDoc(DATA_DIR / f"{name}.json")
