"""Tests for the Fix bulletin — a small persistent note Leon edits himself.
Nothing here is read by any other part of the app; it's a sticky note."""

from dashboard import bulletin


def test_first_load_seeds_the_known_housekeeping_items(tmp_path, monkeypatch):
    import dashboard.storage as storage
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)

    loaded = bulletin.load()
    assert "scan-history" in loaded["text"]
    assert (tmp_path / "bulletin.json").exists()


def test_second_load_does_not_re_seed_over_leons_own_edit(tmp_path, monkeypatch):
    import dashboard.storage as storage
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)

    bulletin.load()  # seeds it, like a real first visit would
    bulletin.save("- my own note")
    assert bulletin.load()["text"] == "- my own note"


def test_save_and_reload_round_trip(tmp_path, monkeypatch):
    import dashboard.storage as storage
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)

    bulletin.save("- remember to check the scheduler")
    assert bulletin.load()["text"] == "- remember to check the scheduler"


def test_save_caps_an_extremely_long_paste(tmp_path, monkeypatch):
    import dashboard.storage as storage
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)

    saved = bulletin.save("x" * 50000)
    assert len(saved) == bulletin.MAX_LENGTH
