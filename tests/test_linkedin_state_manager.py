import json
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _reload_module(monkeypatch, draft_file):
    import config
    import importlib
    import astakos_skills.linkedin_state_manager as manager

    monkeypatch.setattr(config, "LINKEDIN_DRAFT_FILE", str(draft_file))
    return importlib.reload(manager)


def test_update_pending_linkedin_post_uses_configured_draft_file(monkeypatch, tmp_path):
    draft_file = tmp_path / "linkedin_draft.json"
    manager = _reload_module(monkeypatch, draft_file)

    result = manager.update_pending_linkedin_post.func(
        draft_text="hello linkedin",
        photo_path="outputs/photo.png",
    )

    data = json.loads(draft_file.read_text(encoding="utf-8"))
    assert result.startswith("SUCCESS_JSON:")
    payload = json.loads(result[len("SUCCESS_JSON:"):])
    assert payload["kind"] == "linkedin_draft_saved"
    assert payload["draft_text"] == "hello linkedin"
    assert payload["photo_path"] == "outputs/photo.png"
    assert data["text"] == "hello linkedin"
    assert data["content"] == "hello linkedin"
    assert data["image_path"] == "outputs/photo.png"
    assert data["pending_linkedin_post"]["text"] == "hello linkedin"


def test_process_linkedin_post_keeps_draft_when_publish_returns_error(monkeypatch, tmp_path):
    draft_file = tmp_path / "linkedin_draft.json"
    manager = _reload_module(monkeypatch, draft_file)
    draft_file.write_text(
        json.dumps(
            {
                "text": "hello",
                "content": "hello",
                "image_path": "",
                "pending_linkedin_post": {"text": "hello", "photo_path": ""},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    fake_tools = types.ModuleType("tools.system")
    fake_tools.post_to_linkedin = types.SimpleNamespace(
        invoke=lambda _args: "❌ Αποτυχία: mocked"
    )
    monkeypatch.setitem(sys.modules, "tools.system", fake_tools)

    result = manager.process_and_clear_linkedin_post.func()

    data = json.loads(draft_file.read_text(encoding="utf-8"))
    assert result.startswith("❌")
    assert "pending_linkedin_post" in data


def test_process_linkedin_post_clears_draft_after_success(monkeypatch, tmp_path):
    draft_file = tmp_path / "linkedin_draft.json"
    manager = _reload_module(monkeypatch, draft_file)
    draft_file.write_text(
        json.dumps(
            {
                "text": "hello",
                "content": "hello",
                "image_path": "",
                "pending_linkedin_post": {"text": "hello", "photo_path": ""},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    fake_tools = types.ModuleType("tools.system")
    fake_tools.post_to_linkedin = types.SimpleNamespace(
        invoke=lambda _args: "✅ Το LinkedIn post ανέβηκε"
    )
    monkeypatch.setitem(sys.modules, "tools.system", fake_tools)

    result = manager.process_and_clear_linkedin_post.func()

    data = json.loads(draft_file.read_text(encoding="utf-8"))
    assert "δημοσιεύτηκε" in result
    assert data == {}
