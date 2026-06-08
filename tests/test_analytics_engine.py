def test_analytics_loader_uses_shared_history(monkeypatch):
    from services import analytics_engine

    shared = [{"role": "user", "content": "shared", "date": "2026-06-04", "time": "10:00"}]

    calls = []
    monkeypatch.setattr(
        analytics_engine,
        "_load_shared_user_messages",
        lambda cutoff: (calls.append(cutoff) or shared),
    )

    messages, source = analytics_engine._load_user_messages_for_analytics("2026-06-01")

    assert messages == shared
    assert source == "shared_sqlite"
    assert calls == ["2026-06-01"]


def test_analytics_loader_has_no_legacy_json_fallback(monkeypatch):
    from services import analytics_engine

    monkeypatch.setattr(analytics_engine, "_load_shared_user_messages", lambda cutoff: [])

    messages, source = analytics_engine._load_user_messages_for_analytics("2026-06-01")

    assert messages == []
    assert source == "shared_sqlite"
    assert not hasattr(analytics_engine, "_load_legacy_history")
    assert not hasattr(analytics_engine, "_filter_recent_user_messages")
