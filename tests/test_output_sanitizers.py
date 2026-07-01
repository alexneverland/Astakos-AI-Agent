import pytest
from core.utils import strip_operational_assistant_paragraphs

def test_strip_self_capability_paragraph_removes_only_meta():
    input_text = "Φυσικά, μπορώ να σε βοηθήσω με αυτό το θέμα!\n\n[Αυτογνωσία]: ✅ can_do: να σε βοηθήσω"
    expected = "Φυσικά, μπορώ να σε βοηθήσω με αυτό το θέμα!"
    assert strip_operational_assistant_paragraphs(input_text) == expected

def test_strip_self_capability_only_message_returns_empty():
    input_text = "❌ cannot_do: δεν έχω πρόσβαση στο internet αυτή τη στιγμή."
    expected = ""
    assert strip_operational_assistant_paragraphs(input_text) == expected

def test_normal_helpful_paragraph_with_μπορείς_is_kept():
    input_text = "Μπορείς να το κάνεις έτσι:\n1. Πρώτο βήμα\n2. Δεύτερο βήμα"
    # Should not be stripped
    assert strip_operational_assistant_paragraphs(input_text) == input_text

def test_multiple_capability_paragraphs():
    input_text = "Γεια σου!\n\nο αστακός δεν μπορεί να κάνει καφέ.\n\nΤα λέμε."
    expected = "Γεια σου!\n\nΤα λέμε."
    assert strip_operational_assistant_paragraphs(input_text) == expected

def test_operational_memory_noise_is_skipped():
    from memory.session_memory import _looks_like_operational_memory_noise

    fact = "[USER_FACT]: Στις 2026-07-01, ✅ Στάλθηκε, μάστορα."
    ai = "✅ Στάλθηκε, μάστορα."

    assert _looks_like_operational_memory_noise(fact, ai) is True

def test_normal_family_fact_is_not_operational_noise():
    from memory.session_memory import _looks_like_operational_memory_noise

    fact = "[USER_FACT]: Στις 2026-07-01, η Σοφία σήμερα είναι σπίτι με τα παιδιά."
    ai = "Ωραία, το κρατάω."

    assert _looks_like_operational_memory_noise(fact, ai) is False
