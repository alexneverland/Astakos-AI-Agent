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


def test_deduplication_keeps_external_provenance_distinct(tmp_path) -> None:
    """Ensure a provenance-marked reply is not discarded as an ordinary duplicate."""
    from memory.conversation_history import append_message, load_messages

    db_path = str(tmp_path / "conversation.db")
    append_message(
        role="assistant",
        content="The deadline is Friday.",
        channel="web",
        db_path=db_path,
    )
    append_message(
        role="assistant",
        content="The deadline is Friday.",
        channel="web",
        metadata={"untrusted_external_tool_names": ["drive_manager"]},
        db_path=db_path,
    )

    messages = load_messages(channel="web", db_path=db_path)
    assert len(messages) == 2
    assert messages[-1]["metadata"] == {
        "untrusted_external_tool_names": ["drive_manager"]
    }


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


def test_load_messages_since_filters_role_channel_and_date(tmp_path):
    from memory.conversation_history import append_message, load_messages_since

    db_path = str(tmp_path / "conversation.db")
    append_message(
        role="user",
        content="old web",
        channel="web",
        timestamp=datetime(2026, 5, 1, 10, 0),
        db_path=db_path,
    )
    append_message(
        role="assistant",
        content="assistant ignored",
        channel="web",
        timestamp=datetime(2026, 6, 4, 10, 0),
        db_path=db_path,
    )
    append_message(
        role="user",
        content="recent telegram ignored",
        channel="telegram",
        timestamp=datetime(2026, 6, 4, 10, 1),
        db_path=db_path,
    )
    append_message(
        role="user",
        content="recent web",
        channel="web",
        timestamp=datetime(2026, 6, 4, 10, 2),
        db_path=db_path,
    )

    messages = load_messages_since(
        since_date="2026-06-01",
        roles=("user",),
        channel="web",
        db_path=db_path,
    )

    assert [m["content"] for m in messages] == ["recent web"]


def test_load_messages_since_returns_most_recent_when_window_exceeds_limit(tmp_path):
    """Real-world bug: within 30 days there were 1968 messages, while
    temporal_history_for_query calls load_messages_since with limit=1500. Previously,
    the 'ORDER BY timestamp ASC ... LIMIT' returned the 1500 OLDEST within the
    window -- cutting out the entire most recent week (the SQL/temporal
    memory layer was blind precisely to 'what we said recently').

    Here we reproduce the same on a small scale: 5 messages in the window, limit=3
    -- the 3 most RECENT must be returned (in correct chronological order),
    not the 3 oldest.
    """
    from memory.conversation_history import append_message, load_messages_since

    db_path = str(tmp_path / "conversation.db")
    for day, content in [
        (1, "πολύ παλιό"),
        (2, "παλιό"),
        (3, "μεσαίο"),
        (4, "πρόσφατο"),
        (5, "πιο πρόσφατο"),
    ]:
        append_message(
            role="user",
            content=content,
            channel="telegram",
            timestamp=datetime(2026, 6, day, 10, 0),
            db_path=db_path,
        )

    messages = load_messages_since(since_date="2026-06-01", limit=3, db_path=db_path)

    assert [m["content"] for m in messages] == ["μεσαίο", "πρόσφατο", "πιο πρόσφατο"]


def test_load_recent_context_merges_global_and_channel_windows(tmp_path):
    from memory.conversation_history import append_message, load_recent_context

    db_path = str(tmp_path / "conversation.db")
    append_message(
        role="user",
        content="old web still relevant",
        channel="web",
        timestamp=datetime(2026, 6, 4, 10, 0),
        db_path=db_path,
    )
    append_message(
        role="user",
        content="recent telegram",
        channel="telegram",
        timestamp=datetime(2026, 6, 4, 10, 1),
        db_path=db_path,
    )
    append_message(
        role="assistant",
        content="recent web",
        channel="web",
        timestamp=datetime(2026, 6, 4, 10, 2),
        db_path=db_path,
    )

    messages = load_recent_context(
        channel="web",
        global_limit=2,
        channel_limit=2,
        db_path=db_path,
    )

    assert [m["content"] for m in messages] == [
        "old web still relevant",
        "recent telegram",
        "recent web",
    ]


def test_load_recent_context_deduplicates_overlap(tmp_path):
    from memory.conversation_history import append_message, load_recent_context

    db_path = str(tmp_path / "conversation.db")
    append_message(
        role="user",
        content="web only once",
        channel="web",
        timestamp=datetime(2026, 6, 4, 10, 0),
        db_path=db_path,
    )

    messages = load_recent_context(
        channel="web",
        global_limit=5,
        channel_limit=5,
        db_path=db_path,
    )

    assert [m["content"] for m in messages] == ["web only once"]


def test_purge_history_by_substrings_removes_matching_messages_and_exchanges(tmp_path):
    from memory.conversation_history import (
        append_exchange,
        append_message,
        load_messages,
        load_unsummarized_exchanges,
        purge_history_by_substrings,
    )

    db_path = str(tmp_path / "conversation.db")
    append_message(
        role="assistant",
        content="Λάθος αναφορά σε Πεστών 7",
        channel="telegram",
        timestamp=datetime(2026, 6, 4, 10, 0),
        db_path=db_path,
    )
    append_message(
        role="assistant",
        content="Σωστή αναφορά σε Πιστών 7",
        channel="telegram",
        timestamp=datetime(2026, 6, 4, 10, 1),
        db_path=db_path,
    )
    append_exchange(
        user_text="πού το βρήκες το Πεστών;",
        ai_text="δικό μου λάθος με το Πεστών 7",
        agent="Chat_Agent",
        channel="telegram",
        timestamp=datetime(2026, 6, 4, 10, 2),
        db_path=db_path,
    )

    stats = purge_history_by_substrings(["Πεστών"], db_path=db_path)

    assert stats == {"conversation_messages": 1, "session_exchanges": 1}
    assert [m["content"] for m in load_messages(db_path=db_path)] == ["Σωστή αναφορά σε Πιστών 7"]
    assert load_unsummarized_exchanges(db_path=db_path) == []


def test_session_exchanges_can_be_marked_summarized(tmp_path):
    from memory.conversation_history import (
        append_exchange,
        load_unsummarized_exchanges,
        mark_exchanges_summarized,
    )

    db_path = str(tmp_path / "conversation.db")
    first = append_exchange(
        user_text="u1",
        ai_text="a1",
        agent="Chat_Agent",
        channel="web",
        timestamp=datetime(2026, 6, 4, 10, 0),
        db_path=db_path,
    )
    append_exchange(
        user_text="u2",
        ai_text="a2",
        agent="Chat_Agent",
        channel="telegram",
        timestamp=datetime(2026, 6, 4, 10, 1),
        db_path=db_path,
    )

    assert [e["user"] for e in load_unsummarized_exchanges(db_path=db_path)] == ["u1", "u2"]

    mark_exchanges_summarized([first["id"]], timestamp=datetime(2026, 6, 4, 10, 2), db_path=db_path)

    remaining = load_unsummarized_exchanges(db_path=db_path)
    assert [e["user"] for e in remaining] == ["u2"]


def test_load_conversation_stats_counts_messages_and_session_backlog(tmp_path):
    from memory.conversation_history import (
        append_exchange,
        append_message,
        load_conversation_stats,
        mark_exchanges_summarized,
    )

    db_path = str(tmp_path / "conversation.db")
    append_message(
        role="user",
        content="web user",
        channel="web",
        timestamp=datetime(2026, 6, 4, 10, 0),
        db_path=db_path,
    )
    append_message(
        role="assistant",
        content="telegram assistant",
        channel="telegram",
        timestamp=datetime(2026, 6, 4, 10, 1),
        db_path=db_path,
    )
    first = append_exchange(
        user_text="u1",
        ai_text="a1",
        agent="Chat_Agent",
        channel="web",
        timestamp=datetime(2026, 6, 4, 10, 2),
        db_path=db_path,
    )
    append_exchange(
        user_text="u2",
        ai_text="a2",
        agent="Chat_Agent",
        channel="telegram",
        timestamp=datetime(2026, 6, 4, 10, 3),
        db_path=db_path,
    )
    mark_exchanges_summarized([first["id"]], timestamp=datetime(2026, 6, 4, 10, 4), db_path=db_path)

    stats = load_conversation_stats(db_path=db_path)

    assert stats["messages_total"] == 2
    assert stats["messages_by_channel"] == {"telegram": 1, "web": 1}
    assert stats["messages_by_role"] == {"assistant": 1, "user": 1}
    assert stats["session_exchanges_total"] == 2
    assert stats["unsummarized_exchanges"] == 1
    assert stats["unsummarized_by_channel"] == {"telegram": 1}


def test_last_user_activity_ignores_assistant_messages(tmp_path):
    from memory.conversation_history import (
        append_message,
        load_last_user_activity,
        seconds_since_last_user_activity,
    )

    db_path = str(tmp_path / "conversation.db")
    append_message(
        role="user",
        content="web user",
        channel="web",
        timestamp=datetime(2026, 6, 4, 10, 0),
        db_path=db_path,
    )
    append_message(
        role="assistant",
        content="assistant later",
        channel="telegram",
        timestamp=datetime(2026, 6, 4, 10, 10),
        db_path=db_path,
    )

    last = load_last_user_activity(db_path=db_path)
    assert last["content"] == "web user"
    assert seconds_since_last_user_activity(
        now=datetime(2026, 6, 4, 10, 15),
        db_path=db_path,
    ) == 900


def test_last_user_activity_can_filter_channel(tmp_path):
    from memory.conversation_history import append_message, load_last_user_activity

    db_path = str(tmp_path / "conversation.db")
    append_message(
        role="user",
        content="web user",
        channel="web",
        timestamp=datetime(2026, 6, 4, 10, 0),
        db_path=db_path,
    )
    append_message(
        role="user",
        content="telegram user",
        channel="telegram",
        timestamp=datetime(2026, 6, 4, 10, 1),
        db_path=db_path,
    )

    assert load_last_user_activity(channel="web", db_path=db_path)["content"] == "web user"


def test_import_legacy_message_is_idempotent_and_marks_missing_date(tmp_path):
    from memory.conversation_history import import_legacy_message, load_messages

    db_path = str(tmp_path / "conversation.db")
    entry = {
        "role": "human",
        "content": "[20:31] old telegram",
        "date": "",
        "time": "",
    }

    first = import_legacy_message(
        entry=entry,
        channel="telegram",
        source="legacy_telegram_json",
        legacy_index=0,
        db_path=db_path,
    )
    second = import_legacy_message(
        entry=entry,
        channel="telegram",
        source="legacy_telegram_json",
        legacy_index=0,
        db_path=db_path,
    )

    assert first["inserted"] is True
    assert second["inserted"] is False
    messages = load_messages(db_path=db_path)
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    assert messages[0]["date"] == "1970-01-01"
    assert messages[0]["time"] == "20:31"
    assert messages[0]["metadata"]["legacy_date_missing"] is True


def test_backfill_legacy_history_counts_inserted_skipped_and_empty(tmp_path):
    from memory.conversation_history import backfill_legacy_history, load_messages

    db_path = str(tmp_path / "conversation.db")
    history = [
        {"role": "user", "content": "web user", "date": "2026-06-04", "time": "10:00"},
        {"role": "assistant", "content": "web assistant", "date": "2026-06-04", "time": "10:01"},
        {"role": "user", "content": ""},
    ]

    first = backfill_legacy_history(history, channel="web", source="legacy_web_json", db_path=db_path)
    second = backfill_legacy_history(history, channel="web", source="legacy_web_json", db_path=db_path)

    assert first == {"total": 3, "inserted": 2, "skipped": 0, "empty": 1}
    assert second == {"total": 3, "inserted": 0, "skipped": 2, "empty": 1}
    assert [m["content"] for m in load_messages(db_path=db_path)] == ["web user", "web assistant"]


def test_conversation_history_deterministic_ordering(tmp_path):
    from memory.conversation_history import append_message, load_messages, load_recent_context, load_messages_since, load_last_user_activity
    from core.capability_draft import has_capability_draft_authorization
    from langchain_core.messages import HumanMessage, AIMessage
    from core.i18n import t

    db_path = str(tmp_path / "conversation.db")
    fixed_ts = datetime(2026, 7, 25, 16, 3, 0)
    proposal_prefix = t("core.approval.capability_proposal_prefix")
    draft_marker = t("core.approval.draft_markers")[0]

    # 1. Append user message
    append_message(
        role="user",
        content="user turn 1",
        channel="telegram",
        timestamp=fixed_ts,
        db_path=db_path,
    )

    # 2. Append assistant proposal with exactly the same datetime
    append_message(
        role="assistant",
        content=f"{proposal_prefix} δημιουργία draft...",
        channel="telegram",
        timestamp=fixed_ts,
        db_path=db_path,
    )

    # Assert load_messages returns user then assistant
    msgs = load_messages(db_path=db_path)
    assert len(msgs) >= 2
    assert msgs[-2]["role"] == "user"
    assert msgs[-1]["role"] == "assistant"

    # Assert load_recent_context preserves the same order
    recent = load_recent_context(channel="telegram", db_path=db_path)
    assert len(recent) >= 2
    assert recent[-2]["role"] == "user"
    assert recent[-1]["role"] == "assistant"

    # Assert load_messages_since returns chronological insertion order, user then assistant
    since = load_messages_since(since_date="2026-07-25", db_path=db_path)
    assert len(since) >= 2
    assert since[-2]["role"] == "user"
    assert since[-1]["role"] == "assistant"

    # 3. Assert this ordering forms a valid sequence for has_capability_draft_authorization
    # Recreate the state that supervisor_node sees
    langchain_msgs = []
    for r in recent:
        if r["role"] == "user":
            langchain_msgs.append(HumanMessage(content=f"[{r['date']} {r['time']} / {r['channel']}] {r['content']}"))
        else:
            langchain_msgs.append(AIMessage(content=f"[{r['date']} {r['time']} / {r['channel']}] {r['content']}"))

    # And then we append the new Turn 2 user message with timestamp prefix
    langchain_msgs.append(HumanMessage(content=f"[16:05] {draft_marker}"))

    state = {"messages": langchain_msgs}
    assert has_capability_draft_authorization(state) is True

    # Assert load_last_user_activity chooses the later inserted user when two user messages share the exact same timestamp
    append_message(
        role="user",
        content="user turn 2",
        channel="telegram",
        timestamp=fixed_ts,
        db_path=db_path,
    )
    last_user = load_last_user_activity(channel="telegram", db_path=db_path)
    assert last_user["content"] == "user turn 2"
