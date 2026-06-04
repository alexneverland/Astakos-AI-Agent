def test_analytics_loader_prefers_shared_history(monkeypatch):
    from services import analytics_engine

    shared = [{"role": "user", "content": "shared", "date": "2026-06-04", "time": "10:00"}]
    legacy = [{"role": "user", "content": "legacy", "date": "2026-06-04", "time": "10:00"}]

    monkeypatch.setattr(analytics_engine, "_load_shared_user_messages", lambda cutoff: shared)
    monkeypatch.setattr(analytics_engine, "_load_legacy_history", lambda: legacy)

    messages, source = analytics_engine._load_user_messages_for_analytics("2026-06-01")

    assert messages == shared
    assert source == "shared_sqlite"


def test_analytics_loader_falls_back_to_legacy_history(monkeypatch):
    from services import analytics_engine

    legacy = [
        {"role": "assistant", "content": "ignored", "date": "2026-06-04", "time": "10:00"},
        {"role": "user", "content": "too old", "date": "2026-05-01", "time": "10:00"},
        {"role": "human", "content": "legacy user", "date": "2026-06-04", "time": "10:01"},
    ]

    monkeypatch.setattr(analytics_engine, "_load_shared_user_messages", lambda cutoff: [])
    monkeypatch.setattr(analytics_engine, "_load_legacy_history", lambda: legacy)

    messages, source = analytics_engine._load_user_messages_for_analytics("2026-06-01")

    assert [m["content"] for m in messages] == ["legacy user"]
    assert source == "legacy_json"
