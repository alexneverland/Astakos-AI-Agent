import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_read_local_file_allows_exact_messenger_draft(monkeypatch, tmp_path):
    import config
    from tools.system import read_local_file

    photos_dir = tmp_path / "photos"
    photos_dir.mkdir()
    draft = tmp_path / "messenger_draft.json"
    draft.write_text('{"message":"hello draft"}', encoding="utf-8")

    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(config, "PHOTOS_DIR", str(photos_dir))

    result = read_local_file.func(str(draft))

    assert "hello draft" in result


def test_read_local_file_blocks_unapproved_root_file(monkeypatch, tmp_path):
    import config
    from tools.system import read_local_file

    photos_dir = tmp_path / "photos"
    photos_dir.mkdir()
    secret = tmp_path / "secret.json"
    secret.write_text('{"secret": true}', encoding="utf-8")

    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(config, "PHOTOS_DIR", str(photos_dir))

    result = read_local_file.func(str(secret))

    assert "path" in result
    assert "secret" in result
