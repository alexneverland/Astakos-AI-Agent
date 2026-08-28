import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_save_draft_writes_active_metadata(monkeypatch, tmp_path):
    import config
    from core.messenger_draft import active_draft_status, save_draft

    draft_file = tmp_path / "messenger_draft.json"
    monkeypatch.setattr(config, "MESSENGER_DRAFT_FILE", str(draft_file))
    monkeypatch.setattr(config, "MESSENGER_DRAFT_TTL_SECONDS", 1800)

    save_draft("Sofia", "hello")

    data = json.loads(draft_file.read_text(encoding="utf-8"))
    assert data["target_name"] == "Sofia"
    assert data["message"] == "hello"
    assert data["status"] == "pending"
    assert data["created_at"]
    assert data["expires_at"]
    assert active_draft_status()[0] is True


def test_expired_draft_is_not_active(monkeypatch, tmp_path):
    import config
    from core.messenger_draft import active_draft_status

    draft_file = tmp_path / "messenger_draft.json"
    monkeypatch.setattr(config, "MESSENGER_DRAFT_FILE", str(draft_file))
    draft_file.write_text(
        json.dumps(
            {
                "target_name": "Sofia",
                "message": "hello",
                "status": "pending",
                "created_at": (datetime.now() - timedelta(hours=2)).isoformat(timespec="seconds"),
                "expires_at": (datetime.now() - timedelta(hours=1)).isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    is_active, reason, _ = active_draft_status()

    assert is_active is False
    assert reason == "expired"


def test_execute_local_pipeline_refuses_missing_draft(monkeypatch, tmp_path):
    import config
    from tools.web import execute_local_pipeline

    monkeypatch.setattr(config, "MESSENGER_DRAFT_FILE", str(tmp_path / "missing.json"))

    result = execute_local_pipeline.func()

    assert "Δεν βρέθηκε προσχέδιο" in result


def test_debug_draft_state_exposes_metadata_not_message(monkeypatch, tmp_path):
    import config
    from core.messenger_draft import debug_draft_state, save_draft

    draft_file = tmp_path / "messenger_draft.json"
    monkeypatch.setattr(config, "MESSENGER_DRAFT_FILE", str(draft_file))

    save_draft("Sofia", "private message text")
    state = debug_draft_state()

    assert state["exists"] is True
    assert state["active"] is True
    assert state["target_name"] == "Sofia"
    assert state["message_chars"] == len("private message text")
    assert "message" not in state
    assert "private message text" not in json.dumps(state, ensure_ascii=False)


def test_relay_local_payload_rejects_ambiguous_friend_target(monkeypatch, tmp_path):
    import config
    from tools.web import relay_local_payload

    draft_file = tmp_path / "messenger_draft.json"
    monkeypatch.setattr(config, "MESSENGER_DRAFT_FILE", str(draft_file))

    result = relay_local_payload.func("friend", "hello")

    assert "Δεν αποθήκευσα Messenger draft" in result
    assert "ambiguous target" in result
    assert not draft_file.exists()


def test_relay_local_payload_accepts_known_contact(monkeypatch, tmp_path):
    import config
    from tools.web import relay_local_payload

    draft_file = tmp_path / "messenger_draft.json"
    monkeypatch.setattr(config, "MESSENGER_DRAFT_FILE", str(draft_file))
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))
    profile_db = tmp_path / "astakos_profile.db"
    monkeypatch.setattr(config, "PROFILE_DB", str(profile_db))
    import sqlite3
    conn = sqlite3.connect(str(profile_db))
    try:
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS profile_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                fact TEXT NOT NULL,
                photo_path TEXT,
                date TEXT,
                metadata_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        c.execute("INSERT INTO profile_facts (category, fact) VALUES ('contacts', 'sofia: 123')")
        conn.commit()
    finally:
        conn.close()

    result = relay_local_payload.func("Sofia", "hello")

    assert "DRAFT" in result
    import json
    data = json.loads(draft_file.read_text(encoding="utf-8"))
    assert data["target_name"] == "Sofia"
    assert data["message"] == "hello"


def test_relay_local_payload_overwrites_draft_with_conversational_text(monkeypatch, tmp_path):
    """Draft payload remains message content and overwrites the active draft."""
    import config
    from core.messenger_draft import save_draft
    from tools.web import relay_local_payload

    draft_file = tmp_path / "messenger_draft.json"
    monkeypatch.setattr(config, "MESSENGER_DRAFT_FILE", str(draft_file))
    monkeypatch.setattr("tools.web._messenger_target_status", lambda target: (True, ""))
    save_draft("Sofia", "Παλιό μήνυμα")

    result = relay_local_payload.func("Sofia", "Ποιο draft λες; Θα το δω μετά.")

    assert "DRAFT" in result
    data = json.loads(draft_file.read_text(encoding="utf-8"))
    assert data["message"] == "Ποιο draft λες; Θα το δω μετά."
