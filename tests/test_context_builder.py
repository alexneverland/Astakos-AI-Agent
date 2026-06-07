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


def test_empty_memory_context_renders_empty():
    assert MemoryContext([], [], []).render() == ""
