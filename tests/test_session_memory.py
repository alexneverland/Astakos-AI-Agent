import json


def test_log_exchange_writes_memory_and_shared_exchange(monkeypatch):
    import memory.session_memory as session_memory

    session_memory.SESSION_LOGS.clear()
    calls = []
    monkeypatch.setattr(session_memory, "append_exchange", lambda **kwargs: calls.append(kwargs))

    session_memory.log_exchange("hello", "hi", "Chat_Agent", channel="telegram")

    assert session_memory.SESSION_LOGS == [{
        "time": session_memory.SESSION_LOGS[0]["time"],
        "agent": "Chat_Agent",
        "channel": "telegram",
        "user": "hello",
        "ai": "hi",
    }]
    assert calls[0]["user_text"] == "hello"
    assert calls[0]["ai_text"] == "hi"
    assert calls[0]["agent"] == "Chat_Agent"
    assert calls[0]["channel"] == "telegram"


def test_run_session_summary_uses_persistent_unsummarized_exchanges(monkeypatch):
    import memory.session_memory as session_memory

    class Response:
        text = json.dumps({
            "date": "2026-06-04 18:42",
            "channel": "mixed",
            "summary": "Συζητήθηκαν web και Telegram.",
            "completed": [],
            "pending": ["να συνεχιστεί το session store"],
            "next_session_hint": "Συνέχισε από το shared session store.",
            "mood": "productive",
        }, ensure_ascii=False)

    exchanges = [
        {
            "id": "ex-web",
            "time": "18:40",
            "channel": "web",
            "agent": "Chat_Agent",
            "user": "web question",
            "ai": "web answer",
        },
        {
            "id": "ex-telegram",
            "time": "18:41",
            "channel": "telegram",
            "agent": "Chat_Agent",
            "user": "telegram question",
            "ai": "telegram answer",
        },
    ]
    marked = []
    saved = []
    emitted = []

    session_memory.SESSION_LOGS[:] = [{"time": "18:39", "agent": "Old", "channel": "web", "user": "old", "ai": "old"}]
    session_memory.is_summarizing = False

    monkeypatch.setattr(session_memory, "load_unsummarized_exchanges", lambda limit=200: exchanges)
    monkeypatch.setattr(session_memory, "mark_exchanges_summarized", lambda ids: marked.extend(ids))
    monkeypatch.setattr(session_memory, "safe_gemini_call", lambda prompt: Response())
    monkeypatch.setattr(session_memory.memory, "save", lambda **kwargs: saved.append(kwargs))
    monkeypatch.setattr(session_memory.bus, "emit", lambda *args, **kwargs: emitted.append((args, kwargs)))

    session_memory._run_session_summary(channel="telegram")

    assert marked == ["ex-web", "ex-telegram"]
    assert saved[0]["memory_type"] == "session"
    assert saved[0]["summary"]["channel"] == "mixed"
    assert session_memory.SESSION_LOGS == []
    assert emitted[0][1]["channel"] == "mixed"
    session_memory.is_summarizing = False
