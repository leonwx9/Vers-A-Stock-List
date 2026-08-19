"""Tests for the storage layer (file mode; database mode needs a real DB)."""

import os

from dashboard.storage import FileDoc, PostgresDoc, get_doc


def test_database_url_is_never_visible_during_tests():
    # Regression guard for the 2026-08-19 incident: the autouse fixture in
    # conftest.py must neutralise DATABASE_URL before every test, even
    # though it's genuinely set in Leon's real .env — otherwise get_doc()
    # below would silently return a PostgresDoc instead of a FileDoc, and
    # any test monkeypatching DATA_DIR would actually hit the real
    # database. Empty-but-present (not deleted) on purpose — see
    # conftest.py's docstring for why deleting it isn't enough.
    assert os.environ.get("DATABASE_URL") == ""
    assert isinstance(get_doc("anything"), FileDoc)


def test_load_dotenv_cannot_undo_the_test_safety_net():
    # The exact bug that slipped through once: a function under test calls
    # load_dotenv() again mid-test (get_provider() does). With override=
    # False (dotenv's default), that must NOT resurrect the real
    # DATABASE_URL from disk once conftest.py has neutralised it.
    from dotenv import load_dotenv
    load_dotenv()
    assert os.environ.get("DATABASE_URL") == ""
    assert isinstance(get_doc("anything"), FileDoc)


def test_filedoc_roundtrip(tmp_path):
    doc = FileDoc(tmp_path / "thing.json")
    assert doc.load() is None                 # nothing saved yet
    doc.save({"hello": [1, 2, 3]})
    assert doc.load() == {"hello": [1, 2, 3]}
    doc.delete()
    assert doc.load() is None
    doc.delete()                              # deleting twice is fine


def test_filedoc_save_leaves_no_scratch_file_behind(tmp_path):
    # Saves go via a scratch file that's atomically swapped into place —
    # after a save, only the real document should exist.
    doc = FileDoc(tmp_path / "thing.json")
    doc.save({"a": 1})
    doc.save({"a": 2})                        # overwrite the same way
    assert doc.load() == {"a": 2}
    assert [p.name for p in tmp_path.iterdir()] == ["thing.json"]


def test_get_doc_uses_files_without_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert isinstance(get_doc("anything"), FileDoc)


def test_get_doc_uses_postgres_with_database_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@example.com/db")
    doc = get_doc("anything")
    assert isinstance(doc, PostgresDoc)       # constructed, never connected
    assert doc.name == "anything"
