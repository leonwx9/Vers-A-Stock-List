"""Tests for the one-off Neon migration script. No real database — the
Postgres side is faked, only the file-enumeration logic is exercised."""

import json

import migrate_to_neon


class FakePostgresDoc:
    saved = {}

    def __init__(self, name, url):
        self.name = name
        self.url = url

    def save(self, data):
        FakePostgresDoc.saved[self.name] = (self.url, data)


def test_migrate_copies_every_saved_document(tmp_path, monkeypatch):
    (tmp_path / "portfolio.json").write_text(json.dumps({"cash": 10000}))
    (tmp_path / "watchlists.json").write_text(json.dumps({"lists": []}))
    FakePostgresDoc.saved = {}
    monkeypatch.setattr(migrate_to_neon, "PostgresDoc", FakePostgresDoc)

    names = migrate_to_neon.migrate(tmp_path, "postgresql://fake")

    assert set(names) == {"portfolio", "watchlists"}
    assert FakePostgresDoc.saved["portfolio"] == ("postgresql://fake", {"cash": 10000})
    assert FakePostgresDoc.saved["watchlists"] == ("postgresql://fake", {"lists": []})


def test_migrate_ignores_leftover_tmp_files(tmp_path, monkeypatch):
    # FileDoc.save() writes name.json.tmp before the atomic rename — a
    # crash mid-write could leave one behind; it must never be migrated
    # as if it were a real document.
    (tmp_path / "portfolio.json").write_text(json.dumps({"cash": 1}))
    (tmp_path / "portfolio.json.tmp").write_text(json.dumps({"cash": 999}))
    FakePostgresDoc.saved = {}
    monkeypatch.setattr(migrate_to_neon, "PostgresDoc", FakePostgresDoc)

    names = migrate_to_neon.migrate(tmp_path, "postgresql://fake")
    assert names == ["portfolio"]


def test_migrate_returns_empty_list_for_an_empty_directory(tmp_path, monkeypatch):
    FakePostgresDoc.saved = {}
    monkeypatch.setattr(migrate_to_neon, "PostgresDoc", FakePostgresDoc)
    assert migrate_to_neon.migrate(tmp_path, "postgresql://fake") == []
