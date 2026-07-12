from memory.context_builder import (
    MemoryContext,
    build_memory_context,
    format_recent_messages,
    looks_like_tool_output,
    looks_like_tool_result_query,
    semantic_facts_for_query,
    temporal_history_for_query,
)


class _Doc:
    def __init__(self, content):
        self.page_content = content


def test_format_recent_messages_keeps_order_and_speaker_labels():
    lines = format_recent_messages(
        [
            {"channel": "web", "time": "10:00", "role": "user", "content": "Καλημέρα"},
            {"channel": "telegram", "time": "10:01", "role": "assistant", "content": "Καλημέρα φίλε"},
        ]
    )

    assert lines == [
        "- [web 10:00] Λάζαρος: Καλημέρα",
        "- [telegram 10:01] Αστακός: Καλημέρα φίλε",
    ]


def test_format_recent_messages_marks_yesterday_so_it_is_not_confused_with_today():
    """Real-world bug: Astakos saw a message from last night about
    steaks next to one from today about lentils, and got them mixed up -- because both
    appeared as a bare '[telegram 20:X]' without any day indication. The line
    for 'today' must remain EXACTLY as before (no change for the
    vast majority), while yesterday's must be clearly marked.
    """
    import datetime as dt

    lines = format_recent_messages(
        [
            {
                "channel": "telegram",
                "date": "2026-06-06",
                "time": "20:48",
                "role": "user",
                "content": "Έφτιαξα μπριζόλες απόψε.",
            },
            {
                "channel": "telegram",
                "date": "2026-06-07",
                "time": "20:53",
                "role": "user",
                "content": "Σήμερα έκανα φακές.",
            },
            {
                "channel": "web",
                "time": "10:00",
                "role": "user",
                "content": "Μήνυμα χωρίς date -- πρέπει να μείνει όπως πριν.",
            },
        ],
        now=dt.datetime(2026, 6, 7, 21, 0),
    )

    assert lines[0] == "- [telegram χθες 20:48] Λάζαρος: Έφτιαξα μπριζόλες απόψε."
    assert lines[1] == "- [telegram 20:53] Λάζαρος: Σήμερα έκανα φακές."
    assert lines[2] == "- [web 10:00] Λάζαρος: Μήνυμα χωρίς date -- πρέπει να μείνει όπως πριν."


def test_semantic_facts_dedupes_and_strips_tags():
    def fake_search(query, k):
        return [
            _Doc("[USER_FACT] Ο Αλέξανδρος αγαπά LEGO. [Tags: family]"),
            _Doc("[USER_FACT] Ο Αλέξανδρος αγαπά LEGO. [Tags: duplicate]"),
            _Doc("[USER_FACT] Η Σοφία δουλεύει σήμερα."),
        ]

    facts = semantic_facts_for_query("Αλέξανδρος δραστηριότητα", search_fn=fake_search)

    assert facts == [
        "[USER_FACT] Ο Αλέξανδρος αγαπά LEGO.",
        "[USER_FACT] Η Σοφία δουλεύει σήμερα.",
    ]


def test_build_memory_context_combines_recent_and_semantic():
    def fake_recent_loader(**kwargs):
        return [
            {"channel": "telegram", "time": "12:30", "role": "user", "content": "Πάμε πάρκο"},
            {"channel": "telegram", "time": "12:31", "role": "assistant", "content": "Καλή βόλτα"},
        ]

    def fake_search(query, k):
        return [_Doc("[USER_FACT] Ο Αλέξανδρος θέλει πάρκο και παιχνίδι.")]

    context = build_memory_context(
        "τι να κάνω με τον Αλέξανδρο",
        recent_loader=fake_recent_loader,
        semantic_search=fake_search,
    )
    rendered = context.render()

    assert "[RECENT WEB+TELEGRAM HISTORY]" in rendered
    assert "[RELEVANT CHROMA MEMORIES]" in rendered
    assert "Πάμε πάρκο" in rendered
    assert "Ο Αλέξανδρος θέλει πάρκο" in rendered


def test_temporal_history_for_yesterday_morning_uses_sqlite_messages():
    def fake_history_loader(**kwargs):
        return [
            {
                "channel": "telegram",
                "date": "2026-06-06",
                "time": "09:15",
                "role": "user",
                "content": "Είμαστε όλοι μαζί στους αγώνες ποδοσφαίρου του Αλέξανδρου.",
            },
            {
                "channel": "telegram",
                "date": "2026-06-06",
                "time": "12:38",
                "role": "user",
                "content": "Τέλος το ποδόσφαιρο, πήρε και μετάλλιο.",
            },
            {
                "channel": "telegram",
                "date": "2026-06-06",
                "time": "18:00",
                "role": "user",
                "content": "Άσχετο απόγευμα.",
            },
        ]

    lines = temporal_history_for_query(
        "ο Αλέξανδρος τι έκανε χτες το πρωί που πήγαμε όλοι μαζί;",
        channel="telegram",
        history_loader=fake_history_loader,
        now=__import__("datetime").datetime(2026, 6, 7, 15, 0),
    )

    assert any("αγώνες ποδοσφαίρου" in line for line in lines)
    assert any("μετάλλιο" in line for line in lines)
    assert all("Άσχετο απόγευμα" not in line for line in lines)


def test_history_lookup_uses_sqlite_even_without_date_words():
    def fake_history_loader(**kwargs):
        assert kwargs["since_date"] == "2026-05-08"
        assert kwargs["limit"] == 1500
        return [
            {
                "channel": "web",
                "date": "2026-06-01",
                "time": "18:00",
                "role": "user",
                "content": "Μιλήσαμε για το πάρκο με τη Σοφία και τον Αλέξανδρο.",
            },
            {
                "channel": "telegram",
                "date": "2026-06-02",
                "time": "19:00",
                "role": "assistant",
                "content": "Άσχετο για μαγείρεμα.",
            },
        ]

    lines = temporal_history_for_query(
        "θυμάσαι τι λέγαμε για πάρκο Σοφία;",
        channel="web",
        history_loader=fake_history_loader,
        now=__import__("datetime").datetime(2026, 6, 7, 15, 0),
    )

    assert any("πάρκο με τη Σοφία" in line for line in lines)
    assert all("μαγείρεμα" not in line for line in lines)


def test_temporal_history_skips_memory_correction_chatter():
    def fake_history_loader(**kwargs):
        return [
            {
                "channel": "telegram",
                "date": "2026-06-05",
                "time": "18:00",
                "role": "assistant",
                "content": "Η παλιά εγγραφή Πεστών έχει διαγραφεί από τη μνήμη, ήταν δικό μου λάθος.",
            },
            {
                "channel": "telegram",
                "date": "2026-06-05",
                "time": "18:02",
                "role": "user",
                "content": "Θυμάσαι που μένω στην Πιστών 7;",
            },
        ]

    lines = temporal_history_for_query(
        "θυμάσαι που μένω;",
        channel="telegram",
        history_loader=fake_history_loader,
        now=__import__("datetime").datetime(2026, 6, 7, 12, 0),
    )

    assert any("Πιστών 7" in line for line in lines)
    assert all("διαγραφεί από τη μνήμη" not in line for line in lines)


def test_history_lookup_boosts_sofia_watch_gift_context():
    def fake_history_loader(**kwargs):
        return [
            {
                "channel": "telegram",
                "date": "2026-06-05",
                "time": "19:27",
                "role": "assistant",
                "content": "Πολύ κομψό κομμάτι, το Rosefield Bangle S, χρυσό με λευκό καντράν Mother of Pearl. Ψήνεις δωράκι για τη Σοφία;",
            },
            {
                "channel": "telegram",
                "date": "2026-06-05",
                "time": "19:30",
                "role": "assistant",
                "content": "Αποθηκεύτηκε στη μνήμη στα μελλοντικά δώρα για τη Σοφία (Rosefield Bangle S - White Gold).",
            },
            {
                "channel": "telegram",
                "date": "2026-06-07",
                "time": "17:01",
                "role": "assistant",
                "content": "Άσχετη συζήτηση για λινκ και αρχεία.",
            },
        ]

    lines = temporal_history_for_query(
        "Ένα ρολόι σου είχα ανεβάσει ένα λινκ",
        channel="telegram",
        history_loader=fake_history_loader,
        now=__import__("datetime").datetime(2026, 6, 7, 17, 55),
    )

    assert any("Rosefield Bangle S" in line for line in lines)
    assert any("μελλοντικά δώρα για τη Σοφία" in line for line in lines)


def test_tool_output_query_disables_memory_lookup():
    calls = {"recent": 0, "semantic": 0}

    def fake_recent_loader(**kwargs):
        calls["recent"] += 1
        return [{"channel": "web", "time": "10:00", "role": "user", "content": "recent"}]

    def fake_search(query, k):
        calls["semantic"] += 1
        return [_Doc("[USER_FACT] stale")]

    context = build_memory_context(
        "ΜΝΗΜΕΣ ΠΟΥ ΒΡΕΘΗΚΑΝ: [FAMILY] • Ο Αλέξανδρος έφαγε μπριζόλα",
        recent_loader=fake_recent_loader,
        semantic_search=fake_search,
    )

    assert looks_like_tool_output("ΜΝΗΜΕΣ ΠΟΥ ΒΡΕΘΗΚΑΝ: κάτι")
    assert context.render() == ""
    assert calls == {"recent": 0, "semantic": 0}


def test_meal_log_tool_output_disables_memory_lookup():
    calls = {"recent": 0, "semantic": 0}

    def fake_recent_loader(**kwargs):
        calls["recent"] += 1
        return [{"channel": "telegram", "time": "10:32", "role": "user", "content": "Στείλε μήνυμα στη Σοφία"}]

    def fake_search(query, k):
        calls["semantic"] += 1
        return [_Doc("[USER_FACT] Σοφία")]

    query = "✅ Το γεύμα 'φακές' καταγράφηκε επιτυχώς."
    context = build_memory_context(
        query,
        recent_loader=fake_recent_loader,
        semantic_search=fake_search,
    )

    assert looks_like_tool_output(query)
    assert context.render() == ""
    assert calls == {"recent": 0, "semantic": 0}


def test_routine_control_output_disables_memory_lookup():
    calls = {"recent": 0, "semantic": 0}

    def fake_recent_loader(**kwargs):
        calls["recent"] += 1
        return [{"channel": "telegram", "time": "21:04", "role": "assistant", "content": "tool output"}]

    def fake_search(query, k):
        calls["semantic"] += 1
        return [_Doc("[USER_FACT] noise")]

    query = "🔇 [Δευτέρα] Η ρουτίνα 'ποδόσφαιρο Αλέξανδρου' σιγάστηκε μέχρι 2026-06-25."
    context = build_memory_context(
        query,
        recent_loader=fake_recent_loader,
        semantic_search=fake_search,
    )

    assert looks_like_tool_output(query)
    assert context.render() == ""
    assert calls == {"recent": 0, "semantic": 0}


def test_empty_memory_context_renders_empty():
    assert MemoryContext([], [], []).render() == ""


def test_temporal_history_matches_inflected_query_against_stored_form():
    """The stored phrase uses 'γενέθλια'/'Αλέξανδρου' (nominative/genitive),
    the query uses 'γενεθλιών' (genitive plural) — a natural formulation
    which before stemming would lose the scoring boost due to exact substring match."""
    def fake_history_loader(**kwargs):
        return [
            {
                "channel": "telegram",
                "date": "2026-06-01",
                "time": "10:00",
                "role": "user",
                "content": "Τα γενέθλια του Αλέξανδρου είναι 25 Μαρτίου, θέλει LEGO διαστημόπλοιο.",
            },
            {
                "channel": "telegram",
                "date": "2026-06-02",
                "time": "11:00",
                "role": "assistant",
                "content": "Άσχετο, για συνταγή με φακές.",
            },
        ]

    lines = temporal_history_for_query(
        "τι να πάρουμε για τα γενεθλιών του Αλεξάνδρου;",
        channel="telegram",
        history_loader=fake_history_loader,
        now=__import__("datetime").datetime(2026, 6, 7, 12, 0),
    )

    assert any("LEGO διαστημόπλοιο" in line for line in lines)
    assert all("φακές" not in line for line in lines)

def test_semantic_skip_simple_ack_skipped():
    calls = {"recent": 0, "semantic": 0}

    def fake_recent_loader(**kwargs):
        calls["recent"] += 1
        return []

    def fake_search(query, k):
        calls["semantic"] += 1
        return [_Doc("[USER_FACT] stale")]

    # "yes" is a simple ack, should skip semantic search
    query = "[10:24] ναι"
    context = build_memory_context(
        query,
        recent_loader=fake_recent_loader,
        semantic_search=fake_search,
        semantic_k=5,
    )

    # _record_memory_context_debug checks the effective_semantic_k
    assert calls["semantic"] == 0  # The function is called, but with k=0
    assert len(context.semantic_facts) == 0


def test_tool_result_status_outputs_skip_semantic_but_keep_recent_context():
    calls = {"recent": 0, "semantic": 0}

    def fake_recent_loader(**kwargs):
        calls["recent"] += 1
        return [{"channel": "web", "time": "20:17", "role": "user", "content": "θα πάω σε καμιά ώρα"}]

    def fake_search(query, k):
        calls["semantic"] += 1
        return [_Doc("[USER_FACT] stale")] if k > 0 else []

    query = "✅ Δεν υπάρχουν ανοιχτά Google Tasks."
    context = build_memory_context(
        query,
        recent_loader=fake_recent_loader,
        semantic_search=fake_search,
        semantic_k=8,
    )

    assert looks_like_tool_result_query(query)
    assert calls == {"recent": 1, "semantic": 0}
    assert context.recent_lines
    assert context.semantic_facts == []


def test_tool_result_location_outputs_skip_semantic():
    calls = {"semantic": 0}

    def fake_search(query, k):
        calls["semantic"] += 1
        return [_Doc("[USER_FACT] location")] if k > 0 else []

    query = "📍 Συντεταγμένες: 40.648339, 22.935704 🚶 Είναι ΕΚΤΟΣ σπιτιού"
    context = build_memory_context(
        query,
        recent_loader=lambda **kwargs: [],
        semantic_search=fake_search,
        semantic_k=8,
    )

    assert looks_like_tool_result_query(query)
    assert calls["semantic"] == 0
    assert context.semantic_facts == []


def test_tool_result_routine_list_outputs_skip_semantic():
    calls = {"semantic": 0}

    def fake_search(query, k):
        calls["semantic"] += 1
        return [_Doc("[USER_FACT] routines")] if k > 0 else []

    query = "📅 Ρουτίνες για Thursday: • 05:30 — ξύπνημα Λάζαρου"
    context = build_memory_context(
        query,
        recent_loader=lambda **kwargs: [],
        semantic_search=fake_search,
        semantic_k=8,
    )

    assert looks_like_tool_result_query(query)
    assert calls["semantic"] == 0
    assert context.semantic_facts == []


def test_tool_result_background_save_confirmation_skips_semantic():
    calls = {"semantic": 0}

    def fake_search(query, k):
        calls["semantic"] += 1
        return [_Doc("[USER_FACT] background save")] if k > 0 else []

    query = "✅ Αποθηκεύεται σε background: [Ξηροκρήνη, Σοφία, Αλέξανδρος]"
    context = build_memory_context(
        query,
        recent_loader=lambda **kwargs: [],
        semantic_search=fake_search,
        semantic_k=8,
    )

    assert looks_like_tool_result_query(query)
    assert calls["semantic"] == 0
    assert context.semantic_facts == []


def test_tool_result_supermarket_price_list_skips_semantic():
    calls = {"semantic": 0}

    def fake_search(query, k):
        calls["semantic"] += 1
        return [_Doc("[USER_FACT] price list")] if k > 0 else []

    query = "📦 ΛΟΥΜΙΔΗΣ ΕΛΛΗΝΙΚΟΣ ΚΑΦΕΣ 30/96G ΑΒ Βασιλόπουλος: 2.54€ Μασούτης: 2.54€ My Market: 2.54€"
    context = build_memory_context(
        query,
        recent_loader=lambda **kwargs: [],
        semantic_search=fake_search,
        semantic_k=8,
    )

    assert looks_like_tool_result_query(query)
    assert calls["semantic"] == 0
    assert context.semantic_facts == []


def test_normal_location_user_message_keeps_semantic():
    calls = {"semantic": 0}

    def fake_search(query, k):
        calls["semantic"] += 1
        return [_Doc("[USER_FACT] family park")] if k > 0 else []

    query = "σχόλασα ήρθα σπίτι και θα πάω σε καμιά ώρα στην Ξηροκρήνη"
    context = build_memory_context(
        query,
        recent_loader=lambda **kwargs: [],
        semantic_search=fake_search,
        semantic_k=8,
    )

    assert not looks_like_tool_result_query(query)
    assert calls["semantic"] == 1
    assert context.semantic_facts


def test_semantic_skip_short_important_kept():
    calls = {"recent": 0, "semantic": 0}

    def fake_recent_loader(**kwargs):
        return []

    def fake_search(query, k):
        calls["semantic"] += 1
        return [_Doc("[USER_FACT] αλέξανδρος info")] if k > 0 else []

    # Short message, but mentions "Alexandros" -> kept
    query = "[10:24] ο Αλέξανδρος γύρισε"
    context = build_memory_context(
        query,
        recent_loader=fake_recent_loader,
        semantic_search=fake_search,
        semantic_k=5,
    )

    assert calls["semantic"] == 1
    assert len(context.semantic_facts) == 1

def test_semantic_skip_question_kept():
    calls = {"recent": 0, "semantic": 0}

    def fake_recent_loader(**kwargs):
        return []

    def fake_search(query, k):
        calls["semantic"] += 1
        return [_Doc("[USER_FACT] info")] if k > 0 else []

    # Short message, but has question mark -> kept
    query = "[10:24] τι έκανε;"
    context = build_memory_context(
        query,
        recent_loader=fake_recent_loader,
        semantic_search=fake_search,
        semantic_k=5,
    )

    assert calls["semantic"] == 1
    assert len(context.semantic_facts) == 1

def test_semantic_skip_work_message_kept():
    calls = {"recent": 0, "semantic": 0}

    def fake_recent_loader(**kwargs):
        return []

    def fake_search(query, k):
        calls["semantic"] += 1
        return [_Doc("[USER_FACT] work info")] if k > 0 else []

    # Short message, but mentions "work" -> kept
    query = "[10:24] είμαι στη δουλειά"
    context = build_memory_context(
        query,
        recent_loader=fake_recent_loader,
        semantic_search=fake_search,
        semantic_k=5,
    )

    assert calls["semantic"] == 1
    assert len(context.semantic_facts) == 1

def test_format_recent_messages_keeps_informative_part_and_drops_operational_tail():
    from memory.context_builder import format_recent_messages
    messages = [
        {
            "role": "assistant",
            "channel": "web",
            "time": "13:03",
            "date": "2026-06-24",
            "content": (
                "Το Kaggle page έχει Cloudflare protection, αλλά ξέρω το task.\n\n"
                "Γράψε απλά «Στείλε» και το εκτελώ αμέσως!"
            ),
        }
    ]

    lines = format_recent_messages(messages, limit=5)
    assert len(lines) == 1
    assert "Cloudflare protection" in lines[0]
    assert "Στείλε" not in lines[0]


def test_food_memory_query_detector_matches_recall_phrases():
    import memory.context_builder as cb

    assert cb.looks_like_food_memory_query("Τι πήρα σήμερα για φαγητό;") is True
    assert cb.looks_like_food_memory_query("Τι φαι φάγαμε σήμερα;") is True
    assert cb.looks_like_food_memory_query("Θυμάσαι τι ψάρια πήρα;") is True
    assert cb.looks_like_food_memory_query("Τι είχα πει ότι θα βάλω στο φούρνο;") is True


def test_food_memory_query_detector_does_not_match_generic_chat():
    import memory.context_builder as cb

    assert cb.looks_like_food_memory_query("Πάμε μετά μια βόλτα;") is False
    assert cb.looks_like_food_memory_query("Ναι ωραία") is False
    assert cb.looks_like_food_memory_query("Τι έγινε με τη δουλειά;") is False


def test_food_memory_query_boosts_semantic_k(monkeypatch):
    import memory.context_builder as cb

    captured = {}

    def fake_semantic_search(query, k=8):
        captured["query"] = query
        captured["k"] = k
        return []

    ctx = cb.build_memory_context(
        query="Τι πήρα σήμερα για φαγητό;",
        channel="telegram",
        recent_loader=lambda **kwargs: [],
        temporal_loader=lambda **kwargs: [],
        semantic_search=fake_semantic_search,
        semantic_k=8,
    )

    assert ctx is not None
    assert captured["k"] >= 6


def test_classify_memory_query_intent_food_recall():
    import memory.context_builder as cb

    result = cb.classify_memory_query_intent("Τι πήρα σήμερα για φαγητό;")
    assert result == "food_memory_recall"
    typo_result = cb.classify_memory_query_intent("Τι φαι φάγαμε σήμερα;")
    assert typo_result == "food_memory_recall"


def test_classify_memory_query_intent_tool_result():
    import memory.context_builder as cb

    result = cb.classify_memory_query_intent("Τίτλος: ΔΕΔΔΗΕ ... URL: https://example.com")
    assert result == "tool_result"


def test_classify_memory_query_intent_news_opening():
    import memory.context_builder as cb

    result = cb.classify_memory_query_intent("Διάβασα μια είδηση ότι πειράζουν τους μετρητές")
    assert result == "news_opening"


def test_classify_memory_query_intent_web_followup():
    import memory.context_builder as cb

    result = cb.classify_memory_query_intent(
        "Πώς μπορούσαν εξωτερικά να πειράζουν το software;",
        has_recent_web_results=True,
    )
    assert result == "web_followup"


def test_classify_memory_query_intent_low_complexity():
    import memory.context_builder as cb

    result = cb.classify_memory_query_intent("Ναι")
    assert result == "low_complexity"


def test_classify_memory_query_intent_generic():
    import memory.context_builder as cb

    result = cb.classify_memory_query_intent("Θυμάσαι τι είχαμε πει για τη βάρδια αύριο;")
    assert result == "generic"


def test_build_memory_context_records_query_intent_for_food_recall(monkeypatch):
    import memory.context_builder as cb

    captured = {}

    def fake_semantic_search(query, k=8):
        return []

    def fake_debug(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(cb, "_record_memory_context_debug", fake_debug)

    cb.build_memory_context(
        query="Τι πήρα σήμερα για φαγητό;",
        channel="telegram",
        recent_loader=lambda **kwargs: [],
        temporal_loader=lambda **kwargs: [],
        semantic_search=fake_semantic_search,
        semantic_k=8,
    )

    assert captured["query_intent"] == "food_memory_recall"


def test_build_memory_context_skips_debug_write_when_disabled(monkeypatch):
    import memory.context_builder as cb

    called = {"count": 0}

    def fake_debug(**kwargs):
        called["count"] += 1

    monkeypatch.setattr(cb, "_record_memory_context_debug", fake_debug)

    cb.build_memory_context(
        query="θυμάσαι τι φάγαμε;",
        channel="telegram",
        recent_loader=lambda **kwargs: [],
        temporal_loader=lambda **kwargs: [],
        semantic_search=lambda *args, **kwargs: [],
        semantic_k=4,
        write_debug=False,
    )

    assert called["count"] == 0


def test_reminder_request_skips_semantic():
    from memory.context_builder import classify_memory_query_intent

    result = classify_memory_query_intent(
        "[12:50] θυμησε μου στις 19:00 πριν φυγω απο την δουλεια να παρω τις μπριζολες λαιμου που πηρα"
    )

    assert result == "reminder_request"

def test_classify_memory_query_intent_action_command():
    import memory.context_builder as cb
    result = cb.classify_memory_query_intent('άνοιξε το φως')
    assert result == 'action_command'

def test_classify_memory_query_intent_weather():
    import memory.context_builder as cb
    result = cb.classify_memory_query_intent('τι καιρο θα κανει αυριο;')
    assert result == 'weather_or_utility'

def test_classify_memory_query_intent_nostalgia():
    import memory.context_builder as cb
    result = cb.classify_memory_query_intent('τι καναμε περυσι το καλοκαιρι;')
    assert result == 'nostalgia_query'

def test_classify_memory_query_intent_explicit_storage():
    import memory.context_builder as cb
    result = cb.classify_memory_query_intent('να θυμασαι οτι ο λαζαρος αλλαξε σχολειο')
    assert result == 'explicit_memory_storage'
