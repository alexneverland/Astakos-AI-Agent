from unittest.mock import MagicMock

import memory.context_builder as cb
from memory.context_builder import build_memory_context


def test_initial_news_opening_skips_semantic(monkeypatch):
    debug_calls = []
    monkeypatch.setattr(cb, "temporal_history_for_query", MagicMock(return_value=[]))
    monkeypatch.setattr(
        cb,
        "_record_memory_context_debug",
        lambda **kwargs: debug_calls.append(kwargs),
    )

    build_memory_context(
        "Διάβασα μια είδηση ότι πειράζουν τους μετρητές της ΔΕΔΔΗΕ",
        semantic_k=8,
        recent_loader=MagicMock(return_value=[]),
        semantic_search=MagicMock(side_effect=AssertionError("semantic_search should not run")),
    )

    assert len(debug_calls) == 1
    assert debug_calls[0]["semantic_k_used"] == 0
    assert debug_calls[0]["semantic_adjust_reason"] == "news_or_web_fact_skip"


def test_followup_web_discussion_keeps_semantic(monkeypatch):
    debug_calls = []
    monkeypatch.setattr(cb, "temporal_history_for_query", MagicMock(return_value=[]))
    monkeypatch.setattr(cb, "semantic_facts_for_query", MagicMock(return_value=[]))
    monkeypatch.setattr(
        cb,
        "_record_memory_context_debug",
        lambda **kwargs: debug_calls.append(kwargs),
    )

    build_memory_context(
        "Άρα αυτό πόσο σοβαρό είναι τελικά;",
        semantic_k=8,
        recent_loader=MagicMock(return_value=[]),
    )

    assert len(debug_calls) == 1
    assert debug_calls[0]["semantic_k_used"] == 8
    assert debug_calls[0]["semantic_adjust_reason"] is None


def test_tool_result_query_skips_semantic(monkeypatch):
    debug_calls = []
    monkeypatch.setattr(cb, "temporal_history_for_query", MagicMock(return_value=[]))
    monkeypatch.setattr(cb, "semantic_facts_for_query", MagicMock(return_value=[]))
    monkeypatch.setattr(
        cb,
        "_record_memory_context_debug",
        lambda **kwargs: debug_calls.append(kwargs),
    )

    build_memory_context(
        "Τίτλος: Κάποιο άρθρο URL: https://example.com Περίληψη: κάτι εδώ",
        semantic_k=8,
        recent_loader=MagicMock(return_value=[]),
    )

    assert len(debug_calls) == 1
    assert debug_calls[0]["semantic_k_used"] == 0
    assert debug_calls[0]["semantic_adjust_reason"] == "tool_result_query"


def test_personal_query_keeps_default_semantic_k(monkeypatch):
    debug_calls = []
    monkeypatch.setattr(cb, "temporal_history_for_query", MagicMock(return_value=[]))
    monkeypatch.setattr(cb, "semantic_facts_for_query", MagicMock(return_value=[]))
    monkeypatch.setattr(
        cb,
        "_record_memory_context_debug",
        lambda **kwargs: debug_calls.append(kwargs),
    )

    build_memory_context(
        "Θυμάσαι τι λέγαμε για τον Αλέξανδρο και την κατασκήνωση;",
        semantic_k=8,
        recent_loader=MagicMock(return_value=[]),
    )

    assert len(debug_calls) == 1
    assert debug_calls[0]["semantic_k_used"] == 8
    assert debug_calls[0]["semantic_adjust_reason"] is None


def test_followup_with_recent_web_results_downshifts_semantic(monkeypatch):
    debug_calls = []

    def fake_recent_loader(**kwargs):
        return [
            {
                "channel": "web",
                "time": "11:21",
                "role": "assistant",
                "content": "Τίτλος: Το παρασκήνιο πίσω από το κύκλωμα με τους έξυπνους μετρητές URL: https://example.com Περίληψη: Κάτι σχετικό εδώ.",
            }
        ]

    monkeypatch.setattr(cb, "temporal_history_for_query", MagicMock(return_value=[]))
    monkeypatch.setattr(cb, "semantic_facts_for_query", MagicMock(return_value=[]))
    monkeypatch.setattr(
        cb,
        "_record_memory_context_debug",
        lambda **kwargs: debug_calls.append(kwargs),
    )

    build_memory_context(
        "Πώς μπορούσαν εξωτερικά και πείραζαν το software;",
        channel="web",
        semantic_k=8,
        recent_loader=fake_recent_loader,
    )

    assert len(debug_calls) == 1
    assert debug_calls[0]["semantic_k_used"] == 2
    assert debug_calls[0]["semantic_adjust_reason"] == "recent_web_context_downshift"


def test_followup_without_recent_web_results_keeps_semantic(monkeypatch):
    debug_calls = []

    def fake_recent_loader(**kwargs):
        return [
            {
                "channel": "web",
                "time": "11:21",
                "role": "assistant",
                "content": "Μια απλή άσχετη απάντηση χωρίς web result.",
            }
        ]

    monkeypatch.setattr(cb, "temporal_history_for_query", MagicMock(return_value=[]))
    monkeypatch.setattr(cb, "semantic_facts_for_query", MagicMock(return_value=[]))
    monkeypatch.setattr(
        cb,
        "_record_memory_context_debug",
        lambda **kwargs: debug_calls.append(kwargs),
    )

    build_memory_context(
        "Πώς μπορούσαν εξωτερικά και πείραζαν το software;",
        channel="web",
        semantic_k=8,
        recent_loader=fake_recent_loader,
    )

    assert len(debug_calls) == 1
    assert debug_calls[0]["semantic_k_used"] == 8
    assert debug_calls[0]["semantic_adjust_reason"] is None


def test_recent_context_followup_downshifts_semantic(monkeypatch):
    debug_calls = []

    def fake_recent_loader(**kwargs):
        return [
            {
                "channel": "web",
                "time": "14:43",
                "role": "user",
                "content": "το κουνελι το φωναζουμε Κουθαθα ετσι το ονομασε ο Αλεξανδρος",
            },
            {
                "channel": "web",
                "time": "14:43",
                "role": "assistant",
                "content": "Κουθάθα λοιπόν ο μάγκας! Το κράτησα, ωραίο όνομα διάλεξε ο μικρός.",
            },
        ]

    monkeypatch.setattr(cb, "temporal_history_for_query", MagicMock(return_value=[]))
    monkeypatch.setattr(cb, "semantic_facts_for_query", MagicMock(return_value=[]))
    monkeypatch.setattr(
        cb,
        "_record_memory_context_debug",
        lambda **kwargs: debug_calls.append(kwargs),
    )

    build_memory_context(
        "ο αλεξανδρος το αγαπαει πολυ",
        channel="web",
        semantic_k=8,
        recent_loader=fake_recent_loader,
    )

    assert len(debug_calls) == 1
    assert debug_calls[0]["semantic_k_used"] == 3
    assert debug_calls[0]["semantic_adjust_reason"] == "recent_context_overlap_downshift"


def test_recall_query_with_overlap_keeps_full_semantic(monkeypatch):
    debug_calls = []

    def fake_recent_loader(**kwargs):
        return [
            {
                "channel": "telegram",
                "time": "14:43",
                "role": "user",
                "content": "το κουνελι το φωναζουμε Κουθαθα ετσι το ονομασε ο Αλεξανδρος",
            }
        ]

    monkeypatch.setattr(cb, "temporal_history_for_query", MagicMock(return_value=[]))
    monkeypatch.setattr(cb, "semantic_facts_for_query", MagicMock(return_value=[]))
    monkeypatch.setattr(
        cb,
        "_record_memory_context_debug",
        lambda **kwargs: debug_calls.append(kwargs),
    )

    build_memory_context(
        "θυμάσαι πώς το ονόμασε ο Kid1 τελικά;",
        channel="telegram",
        semantic_k=8,
        recent_loader=fake_recent_loader,
    )

    assert len(debug_calls) == 1
    assert debug_calls[0]["semantic_k_used"] == 8
    assert debug_calls[0]["semantic_adjust_reason"] is None


def test_direct_web_research_skips_semantic_but_keeps_recent_context(monkeypatch):
    debug_calls = []
    recent_loader = MagicMock(
        return_value=[
            {
                "channel": "web",
                "time": "11:21",
                "role": "assistant",
                "content": "Recent conversation context.",
            }
        ]
    )

    monkeypatch.setattr(cb, "temporal_history_for_query", MagicMock(return_value=[]))
    monkeypatch.setattr(
        cb,
        "_record_memory_context_debug",
        lambda **kwargs: debug_calls.append(kwargs),
    )

    context = build_memory_context(
        "Ψάξε στο web για τις πολιτικές επιστροφών των Amazon και eBay.",
        channel="web",
        semantic_k=8,
        recent_loader=recent_loader,
        semantic_search=MagicMock(
            side_effect=AssertionError("semantic search should not run")
        ),
    )

    assert context.recent_lines
    assert len(debug_calls) == 1
    assert debug_calls[0]["semantic_k_used"] == 0
    assert debug_calls[0]["semantic_adjust_reason"] == "direct_web_research_skip"


def test_direct_web_url_comparison_is_classified_for_semantic_skip():
    assert cb.classify_memory_query_intent(
        "Άνοιξε και σύγκρινε μόνο αυτές τις επίσημες σελίδες."
    ) == "direct_web_research"
