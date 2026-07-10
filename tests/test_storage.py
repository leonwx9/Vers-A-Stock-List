"""Tests for the storage layer (file mode; database mode needs a real DB)."""

from dashboard.storage import FileDoc, PostgresDoc, get_doc


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
