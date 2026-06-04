from datetime import datetime


def test_append_message_stores_channel_timestamp_and_session(tmp_path):
    from memory.conversation_history import append_message, load_messages

    db_path = str(tmp_path / "conversation.db")
    ts = datetime(2026, 6, 4, 18, 42, 10)

    saved = append_message(
        role="user",
        content="γειά",
        channel="telegram",
        agent="Chat_Agent",
        metadata={"source": "test"},
        timestamp=ts,
        db_path=db_path,
    )

    messages = load_messages(db_path=db_path)
    assert len(messages) == 1
    assert messages[0]["id"] == saved["id"]
    assert messages[0]["channel"] == "telegram"
    assert messages[0]["role"] == "user"
    assert messages[0]["date"] == "2026-06-04"
    assert messages[0]["time"] == "18:42"
    assert messages[0]["session_id"] == "2026-06-04"
    assert messages[0]["agent"] == "Chat_Agent"
    assert messages[0]["metadata"] == {"source": "test"}


def test_load_messages_can_filter_by_channel_and_session(tmp_path):
    from memory.conversation_history import append_message, load_messages

    db_path = str(tmp_path / "conversation.db")
    append_message(
        role="user",
        content="web first",
        channel="web",
        session_id="s1",
        timestamp=datetime(2026, 6, 4, 10, 0),
        db_path=db_path,
    )
    append_message(
        role="assistant",
        content="telegram second",
        channel="telegram",
        session_id="s1",
        timestamp=datetime(2026, 6, 4, 10, 1),
        db_path=db_path,
    )
    append_message(
        role="user",
        content="web other session",
        channel="web",
        session_id="s2",
        timestamp=datetime(2026, 6, 4, 10, 2),
        db_path=db_path,
    )

    web_messages = load_messages(channel="web", db_path=db_path)
    assert [m["content"] for m in web_messages] == ["web first", "web other session"]

    s1_messages = load_messages(session_id="s1", db_path=db_path)
    assert [m["content"] for m in s1_messages] == ["web first", "telegram second"]


def test_load_messages_returns_recent_entries_in_chronological_order(tmp_path):
    from memory.conversation_history import append_message, load_messages

    db_path = str(tmp_path / "conversation.db")
    for minute in range(5):
        append_message(
            role="user",
            content=f"m{minute}",
            channel="web",
            timestamp=datetime(2026, 6, 4, 10, minute),
            db_path=db_path,
        )

    messages = load_messages(limit=3, db_path=db_path)
    assert [m["content"] for m in messages] == ["m2", "m3", "m4"]
