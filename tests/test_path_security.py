from api.path_security import resolve_allowed_file


def test_resolve_allowed_file_accepts_file_inside_allowed_directory(tmp_path):
    uploads_dir = tmp_path / "uploads"
    uploads_dir.mkdir()
    uploaded_file = uploads_dir / "photo.png"
    uploaded_file.write_text("test", encoding="utf-8")

    assert resolve_allowed_file(uploaded_file, (uploads_dir,)) == str(
        uploaded_file.resolve()
    )


def test_resolve_allowed_file_rejects_file_outside_allowed_directory(tmp_path):
    uploads_dir = tmp_path / "uploads"
    uploads_dir.mkdir()
    secret_file = tmp_path / "secret.txt"
    secret_file.write_text("secret", encoding="utf-8")

    assert resolve_allowed_file(secret_file, (uploads_dir,)) is None


def test_resolve_allowed_file_rejects_directory_and_missing_file(tmp_path):
    uploads_dir = tmp_path / "uploads"
    uploads_dir.mkdir()

    assert resolve_allowed_file(uploads_dir, (uploads_dir,)) is None
    assert resolve_allowed_file(uploads_dir / "missing.txt", (uploads_dir,)) is None
