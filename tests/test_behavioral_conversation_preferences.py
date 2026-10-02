"""Temporary-state contracts for shared semantic commentary preferences."""
import pytest

from memory.behavioral_conversation_preferences import PreferenceStore


def test_missing_store_does_not_create_data(tmp_path):
    path = tmp_path / "prefs.json"
    assert PreferenceStore(path).load() == []
    assert not path.exists()


def test_persist_opt_out_reload_and_explicit_revoke(tmp_path):
    store = PreferenceStore(tmp_path / "prefs.json")
    saved = store.update([], suppress="Comments on drinking", allow_ids=[])
    assert saved and saved[0]["scope"] == "Comments on drinking"
    restarted = PreferenceStore(store.path)
    assert restarted.load() == saved
    assert restarted.update(saved, suppress=None, allow_ids=[saved[0]["id"]]) == []
    assert restarted.load() == []


def test_stale_writer_cannot_erase_newer_preference(tmp_path):
    store = PreferenceStore(tmp_path / "prefs.json")
    saved = store.update([], suppress="Drinking", allow_ids=[])
    assert store.update([], suppress="Work", allow_ids=[]) is None
    assert store.load() == saved


def test_corruption_is_not_overwritten(tmp_path):
    path = tmp_path / "prefs.json"
    path.write_text('{bad', encoding="utf-8")
    with pytest.raises(ValueError):
        PreferenceStore(path).update([], suppress="Work", allow_ids=[])
    assert path.read_text(encoding="utf-8") == '{bad'


def test_failed_replace_preserves_data_and_removes_staging(tmp_path, monkeypatch):
    import memory.behavioral_conversation_preferences as module
    store = PreferenceStore(tmp_path / "prefs.json")
    saved = store.update([], suppress="Work", allow_ids=[])
    monkeypatch.setattr(module.os, "replace", lambda *_: (_ for _ in ()).throw(OSError("blocked")))
    with pytest.raises(OSError):
        store.update(saved, suppress="Drinking", allow_ids=[])
    assert store.load() == saved
    assert not list(tmp_path.glob(".behavioral-prefs-*.tmp"))
