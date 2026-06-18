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


def test_log_exchange_auto_summarizes_when_threshold_reached(monkeypatch):
    import memory.session_memory as session_memory

    triggered = []

    class ImmediateThread:
        def __init__(self, target, daemon=False):
            self.target = target
            self.daemon = daemon

        def start(self):
            self.target()

    session_memory.SESSION_LOGS.clear()
    session_memory.is_summarizing = False
    monkeypatch.setattr(session_memory, "AUTO_SESSION_SUMMARY_EXCHANGE_THRESHOLD", 2)
    monkeypatch.setattr(session_memory, "append_exchange", lambda **kwargs: {"id": "ex-new"})
    monkeypatch.setattr(
        session_memory,
        "load_unsummarized_exchanges",
        lambda limit=200: [{"id": "ex-1"}, {"id": "ex-2"}],
    )
    monkeypatch.setattr(session_memory, "_run_session_summary", lambda channel="web": triggered.append(channel))
    monkeypatch.setattr(session_memory.threading, "Thread", ImmediateThread)

    session_memory.log_exchange("hello", "hi", "Chat_Agent", channel="web")

    assert triggered == ["web"]


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


def test_event_memory_candidate_captures_family_day_event():
    import datetime
    import memory.session_memory as session_memory

    candidate = session_memory._extract_event_memory_candidate(
        "Τέλος το ποδόσφαιρο ωραία ήταν πήρε και μετάλλιο τώρα γυρνάμε",
        "Μπράβο στον μικρό για το μετάλλιο!",
        agent_name="Chat_Agent",
        channel="telegram",
        now=datetime.datetime(2026, 6, 6, 12, 38),
    )

    assert candidate["memory_type"] == "fact"
    assert candidate["category"] == "family"
    assert candidate["source"] == "telegram"
    assert candidate["reason"] == "user_stated"
    assert "2026-06-06" in candidate["fact"]
    assert "μετάλλιο" in candidate["fact"]


def test_event_memory_candidate_ignores_plain_question():
    import memory.session_memory as session_memory

    candidate = session_memory._extract_event_memory_candidate(
        "Ο Αλέξανδρος τι έκανε χτες το πρωί;",
        "Δεν ξέρω ακόμα.",
        agent_name="Chat_Agent",
        channel="web",
    )

    assert candidate is None


def test_event_memory_candidate_captures_personal_day_event():
    import datetime
    import memory.session_memory as session_memory

    candidate = session_memory._extract_event_memory_candidate(
        "Σήμερα είχα συνέντευξη για δουλειά και πήγε καλά",
        "Μπράβο, σημαντικό νέο για τη δουλειά σου.",
        agent_name="Chat_Agent",
        channel="web",
        now=datetime.datetime(2026, 6, 7, 16, 0),
    )

    assert candidate["memory_type"] == "fact"
    assert candidate["category"] == "lazaros"
    assert candidate["source"] == "web"
    assert "2026-06-07" in candidate["fact"]
    assert "συνέντευξη" in candidate["fact"]


def test_temporary_family_memory_candidate_captures_absence_window():
    import datetime
    import memory.session_memory as session_memory

    candidate = session_memory._extract_temporary_family_memory_candidate(
        "Ο Αλέξανδρος είναι κατασκήνωση και θα γυρίσει την άλλη εβδομάδα",
        "Οκ, το κρατάω υπόψη μου.",
        agent_name="Chat_Agent",
        channel="telegram",
        now=datetime.datetime(2026, 6, 16, 18, 30),
    )

    assert candidate["memory_type"] == "fact"
    assert candidate["category"] == "family"
    assert candidate["source"] == "telegram"
    assert candidate["confidence"] == 0.9
    assert "2026-06-16" in candidate["fact"]
    assert "κατασκήνωση" in candidate["fact"]
    assert "γυρίσει" in candidate["fact"]


def test_temporary_family_memory_candidate_ignores_question():
    import memory.session_memory as session_memory

    candidate = session_memory._extract_temporary_family_memory_candidate(
        "Ο Αλέξανδρος είναι ακόμα κατασκήνωση ή γύρισε;",
        "Δεν ξέρω ακόμα.",
        agent_name="Chat_Agent",
        channel="web",
    )

    assert candidate is None


def test_memory_sifter_saves_temporary_family_memory_even_if_llm_returns_empty(monkeypatch):
    import memory.session_memory as session_memory

    saved = []

    class EmptyResponse:
        text = "ΚΕΝΟ"

    monkeypatch.setattr(session_memory.memory, "save", lambda **kwargs: saved.append(kwargs))
    monkeypatch.setattr(session_memory, "safe_gemini_call", lambda prompt: EmptyResponse())
    session_memory.SESSION_LOGS.clear()

    session_memory.run_memory_sifter_fast(
        "Ο Αλέξανδρος είναι κατασκήνωση μέχρι την Κυριακή και μετά γυρνάει σπίτι",
        "Το κρατάω στο νου μου.",
        agent_name="Chat_Agent",
        channel="telegram",
    )

    assert any(
        entry.get("category") == "family" and "κατασκήνωση" in entry.get("fact", "")
        for entry in saved
    )


def test_confirmed_memory_candidate_captures_family_watch():
    import datetime
    import memory.session_memory as session_memory

    candidate = session_memory._extract_confirmed_memory_candidate(
        "Ναι κράτα το για δώρο στη Σοφία",
        "Αποθηκεύτηκε στη μνήμη στα μελλοντικά δώρα για τη Σοφία (Rosefield Bangle S - White Gold).",
        agent_name="Chat_Agent",
        channel="telegram",
        now=datetime.datetime(2026, 6, 5, 19, 30),
    )

    assert candidate["memory_type"] == "fact"
    assert candidate["category"] == "family"
    assert candidate["source"] == "telegram"
    assert candidate["confidence"] == 0.9
    assert "2026-06-05" in candidate["fact"]
    assert "Rosefield Bangle S - White Gold" in candidate["fact"]
    assert "Σοφία" in candidate["fact"]


def test_confirmed_memory_candidate_infers_project_category():
    import datetime
    import memory.session_memory as session_memory

    candidate = session_memory._extract_confirmed_memory_candidate(
        "Κράτα στη μνήμη ότι στο Mastroapp θέλουμε το API να γυρνάει μόνο JSON",
        "Το αποθήκευσα στη μνήμη.",
        agent_name="Dev_Agent",
        channel="web",
        now=datetime.datetime(2026, 6, 7, 18, 10),
    )

    assert candidate["category"] == "projects"
    assert "Mastroapp" in candidate["fact"]


def test_confirmed_memory_candidate_ignores_message_drafts():
    import memory.session_memory as session_memory

    candidate = session_memory._extract_confirmed_memory_candidate(
        "Στείλε ένα μήνυμα στη Σοφία",
        "Το προσχέδιο αποθηκεύτηκε. Θέλεις αλλαγές ή να το στείλω;",
        agent_name="Chat_Agent",
        channel="telegram",
    )

    assert candidate is None


def test_memory_sifter_includes_recent_session_context_in_prompt(monkeypatch):
    import memory.session_memory as session_memory

    captured = {}

    class EmptyResponse:
        text = "ΚΕΝΟ"

    session_memory.SESSION_LOGS[:] = [
        {"time": "10:00", "agent": "Chat_Agent", "channel": "web",
         "user": "Πάμε για ΛΕΓΚΟ;", "ai": "Ναι, ωραία ιδέα!"},
        {"time": "10:05", "agent": "Chat_Agent", "channel": "web",
         "user": "Τι θα φτιάξουμε;", "ai": "Ένα διαστημόπλοιο."},
    ]
    monkeypatch.setattr(session_memory, "_extract_event_memory_candidate", lambda *a, **k: None)
    monkeypatch.setattr(session_memory, "_extract_confirmed_memory_candidate", lambda *a, **k: None)

    def fake_gemini(prompt):
        captured["prompt"] = prompt
        return EmptyResponse()

    monkeypatch.setattr(session_memory, "safe_gemini_call", fake_gemini)

    session_memory.run_memory_sifter_slow(
        "Ωραία τα φτιάξαμε", "Ναι, τέλειο αποτέλεσμα!",
        agent_name="Chat_Agent", channel="web",
    )

    prompt = captured["prompt"]
    assert "ΠΡΟΗΓΟΥΜΕΝΟ ΠΛΑΙΣΙΟ" in prompt
    assert "ΜΗΝ εξάγεις facts από αυτό το τμήμα" in prompt
    assert "Πάμε για ΛΕΓΚΟ;" in prompt
    assert "Τι θα φτιάξουμε;" in prompt
    assert "ΤΡΕΧΟΥΣΑ ΑΝΤΑΛΛΑΓΗ" in prompt
    assert "Ωραία τα φτιάξαμε" in prompt
    # Σειρά: παλιό πλαίσιο -> δείκτης τρέχουσας -> τρέχουσα ανταλλαγή
    assert (
        prompt.index("ΠΡΟΗΓΟΥΜΕΝΟ ΠΛΑΙΣΙΟ")
        < prompt.index("ΤΡΕΧΟΥΣΑ ΑΝΤΑΛΛΑΓΗ")
        < prompt.index("Ωραία τα φτιάξαμε")
    )
    session_memory.SESSION_LOGS.clear()


def test_memory_sifter_omits_context_block_when_session_logs_empty(monkeypatch):
    import memory.session_memory as session_memory

    captured = {}

    class EmptyResponse:
        text = "ΚΕΝΟ"

    session_memory.SESSION_LOGS.clear()
    monkeypatch.setattr(session_memory, "_extract_event_memory_candidate", lambda *a, **k: None)
    monkeypatch.setattr(session_memory, "_extract_confirmed_memory_candidate", lambda *a, **k: None)

    def fake_gemini(prompt):
        captured["prompt"] = prompt
        return EmptyResponse()

    monkeypatch.setattr(session_memory, "safe_gemini_call", fake_gemini)

    session_memory.run_memory_sifter_slow(
        "Γεια σου", "Γεια!", agent_name="Chat_Agent", channel="web",
    )

    prompt = captured["prompt"]
    assert "ΠΡΟΗΓΟΥΜΕΝΟ ΠΛΑΙΣΙΟ" not in prompt
    assert "ΤΡΕΧΟΥΣΑ ΑΝΤΑΛΛΑΓΗ" in prompt
