import memory.pending_followups as pf
from memory.pending_followups import classify_followup_deferral_with_llm
from services.gemini import MastroResponse

def test_classify_followup_deferral_with_llm_multimodal_list(monkeypatch):
    def mock_safe_gemini_call(prompt, *args, **kwargs):
        # We simulate the exact scenario of the bug where the LLM response content was a list
        return MastroResponse([{"type": "text", "text": '{"should_defer": true, "delay_minutes": 60, "target_window": "morning", "reason": "test", "confidence": 0.9}'}])

    import services.gemini as sg
    monkeypatch.setattr(sg, "safe_gemini_call", mock_safe_gemini_call)

    result = classify_followup_deferral_with_llm(
        topic="test",
        subject="test",
        source_user_text="test",
        current_user_text="test"
    )

    assert result["should_defer"] is True
    assert result["delay_minutes"] == 60
    assert result["reason"] == "test"
