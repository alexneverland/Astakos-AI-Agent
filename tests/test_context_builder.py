from memory.context_builder import (
    MemoryContext,
    build_memory_context,
    format_recent_messages,
    looks_like_tool_output,
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
    """Bug πραγματικού περιστατικού: ο Αστακός είδε ένα χθεσινοβραδινό μήνυμα για
    μπριζόλες δίπλα σε ένα σημερινό για φακές, και τα μπέρδεψε -- επειδή και τα
    δύο εμφανίζονταν σαν γυμνό '[telegram 20:Χ]' χωρίς ένδειξη μέρας. Η γραμμή
    του 'σήμερα' πρέπει να μένει ΑΚΡΙΒΩΣ όπως πριν (καμία αλλαγή για την
    συντριπτική πλειοψηφία), ενώ η χθεσινή πρέπει να σημαδεύεται καθαρά.
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

    assert "[ΠΡΟΣΦΑΤΟ ΙΣΤΟΡΙΚΟ WEB+TELEGRAM]" in rendered
    assert "[ΣΧΕΤΙΚΕΣ ΜΝΗΜΕΣ CHROMA]" in rendered
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
    """Η αποθηκευμένη φράση χρησιμοποιεί 'γενέθλια'/'Αλέξανδρου' (ονομαστική/γενική),
    η ερώτηση χρησιμοποιεί 'γενεθλιών' (γενική πληθυντικού) — φυσιολογική διατύπωση
    που πριν το stemming θα έχανε το scoring boost λόγω ακριβούς substring match."""
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
