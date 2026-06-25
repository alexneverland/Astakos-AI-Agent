from services.messenger_intent import classify_messenger_intent


def test_create_draft_intent():
    result = classify_messenger_intent("Γράψε ένα μήνυμα", has_active_draft=False)
    assert result.intent == "create_draft"


def test_clarify_draft_intent():
    result = classify_messenger_intent("Ποιο μήνυμα;", has_active_draft=True)
    assert result.intent == "clarify_draft"


def test_clear_draft_intent():
    result = classify_messenger_intent("Αυτό το έχουμε στείλει, κλείστο", has_active_draft=True)
    assert result.intent == "clear_draft"


def test_confirm_send_requires_active_draft():
    result = classify_messenger_intent("Στείλε", has_active_draft=True)
    assert result.intent == "confirm_send"


def test_send_without_active_draft_is_not_confirm():
    result = classify_messenger_intent("Στείλε", has_active_draft=False)
    assert result.intent != "confirm_send"
