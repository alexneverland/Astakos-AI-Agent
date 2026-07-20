from services.messenger_intent import (
    classify_messenger_intent,
    is_create_draft_intent,
)


def test_create_draft_intent():
    result = classify_messenger_intent("Γράψε ένα μήνυμα", has_active_draft=False)
    assert result.intent == "create_draft"


def test_clarify_draft_intent():
    result = classify_messenger_intent("Ποιο μήνυμα;", has_active_draft=True)
    assert result.intent == "clarify_draft"



def test_confirm_send_requires_active_draft():
    result = classify_messenger_intent("Στείλε", has_active_draft=True)
    assert result.intent == "confirm_send"


def test_send_without_active_draft_is_not_confirm():
    result = classify_messenger_intent("Στείλε", has_active_draft=False)
    assert result.intent != "confirm_send"


def test_long_create_message_with_active_draft_stays_create_draft():
    result = classify_messenger_intent(
        "Φτιάξε ένα ωραίο messenger μήνυμα για τη Partner να της δώσουμε δύναμη στη δουλειά",
        has_active_draft=True,
    )
    assert result.intent == "create_draft"

def test_general_close_topic_is_not_clear_draft():
    result = classify_messenger_intent("Όχι κλείσε το θέμα δοκιμές κάναμε", has_active_draft=True)
    assert result.intent == "general_chat"

def test_explicit_clear_draft_still_works():
    result = classify_messenger_intent("κλείσε το draft", has_active_draft=True)
    assert result.intent == "clear_draft"

def test_is_create_draft_intent_rejects_unrelated_messages():
    assert is_create_draft_intent("Γράψε ένα μήνυμα")
    assert not is_create_draft_intent("Έχει δουλειά σήμερα δεύτερα φίλε")
