from memory.working_memory import _looks_like_user_fact_not_capability


def test_user_family_fact_is_not_capability():
    assert _looks_like_user_fact_not_capability("Μπορεί να πηγαίνει τον γιο του στο σχολείο") is True
    assert _looks_like_user_fact_not_capability("Ο Αλέξανδρος ξεκινάει δημοτικό") is True
    assert _looks_like_user_fact_not_capability("Η Σοφία είναι σπίτι") is True


def test_astakos_tool_capability_is_allowed():
    assert _looks_like_user_fact_not_capability("Ο Αστακός μπορεί να στέλνει μήνυμα Messenger μετά από approval") is False
    assert _looks_like_user_fact_not_capability("Δυνατότητα αναζήτησης shared SQLite history και Chroma memories") is False


def test_empty_capability_is_rejected():
    assert _looks_like_user_fact_not_capability("") is True
