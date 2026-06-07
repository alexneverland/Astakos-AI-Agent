from memory.context_builder import (
    MemoryContext,
    build_memory_context,
    format_recent_messages,
    semantic_facts_for_query,
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


def test_empty_memory_context_renders_empty():
    assert MemoryContext([], []).render() == ""
