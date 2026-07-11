import sys
from types import SimpleNamespace


def test_nutrition_result_is_sent_and_recorded(monkeypatch):
    import clients.telegram_bot as bot

    sent = []
    recorded = []

    monkeypatch.setattr(bot, "send_telegram_msg", lambda msg: sent.append(msg) or 123)
    monkeypatch.setattr(bot, "_append_to_analytics_log", lambda role, content, **kwargs: recorded.append((role, content)))
    monkeypatch.setitem(
        sys.modules,
        "astakos_skills.nutrition_analyzer",
        SimpleNamespace(analyze_nutrition=lambda image_path: f"nutrition:{image_path}"),
    )

    bot._run_nutrition("photo.jpg", "chat-1")

    assert sent == ["nutrition:photo.jpg"]
    assert recorded == [("ai", "nutrition:photo.jpg")]


def test_receipt_result_is_sent_and_recorded(monkeypatch):
    import clients.telegram_bot as bot

    sent = []
    recorded = []
    fake_receipt_tool = SimpleNamespace(invoke=lambda payload: f"receipt:{payload['image_path']}")

    monkeypatch.setattr(bot, "send_telegram_msg", lambda msg: sent.append(msg) or 123)
    monkeypatch.setattr(bot, "_append_to_analytics_log", lambda role, content, **kwargs: recorded.append((role, content)))
    monkeypatch.setitem(
        sys.modules,
        "astakos_skills.scan_receipt",
        SimpleNamespace(scan_receipt=fake_receipt_tool),
    )

    bot._run_receipt("receipt.jpg", "chat-2")

    assert sent == ["receipt:receipt.jpg"]
    assert recorded == [("ai", "receipt:receipt.jpg")]
