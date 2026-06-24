def test_asset_context_keeps_conversation_and_skips_uploaded_body(monkeypatch):
    import memory.conversation_history as history

    monkeypatch.setattr(history, "load_recent_context", lambda **kwargs: [
        {"role": "user", "content": "Μιλάμε για τον διαγωνισμό Kaggle"},
        {"role": "assistant", "content": "Ναι, τον AI Agent Security"},
        {"role": "user", "content": "[USER_UPLOADED_FILE]: message.txt"},
    ])

    result = history.build_asset_context_text("telegram")

    assert "διαγωνισμό Kaggle" in result
    assert "AI Agent Security" in result
    assert "USER_UPLOADED_FILE" not in result
