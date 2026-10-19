"""Multimodal provider responses retain the strict shared batch contract."""
from services.gemini import MastroResponse
from services.followup_update_selector import select_followup_updates


def test_followup_batch_adapter_multimodal_list(monkeypatch):
    def model(prompt, *args, **kwargs):
        return MastroResponse([{"type": "text", "text": '{"updates":[{"id":1,"action":"defer","delay_minutes":60,"target_window":"explicit_timer","reason":"test","confidence":0.9}]}'}])
    monkeypatch.setattr("services.gemini.safe_gemini_call", model)
    result = select_followup_updates(user_text="Later", candidates=[{
        "id": 1, "status": "pending", "topic": "test", "subject": "Test", "source_user_text": "Plan"}])
    assert result[0]["action"] == "defer" and result[0]["delay_minutes"] == 60
