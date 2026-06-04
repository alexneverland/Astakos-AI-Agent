def test_recent_activity_guard_skips_and_logs(monkeypatch):
    import clients.telegram_bot as bot

    events = []
    monkeypatch.setattr(bot, "_seconds_since_user_activity", lambda: 120)
    monkeypatch.setattr(bot, "log_event", lambda *args, **kwargs: events.append((args, kwargs)))

    assert bot.should_skip_proactive_for_recent_activity(max_age_seconds=900) is True
    assert events[0][0] == ("proactive", "skipped")
    assert events[0][1]["reason"] == "recent_activity"


def test_old_activity_guard_allows_proactive(monkeypatch):
    import clients.telegram_bot as bot

    events = []
    monkeypatch.setattr(bot, "_seconds_since_user_activity", lambda: 1200)
    monkeypatch.setattr(bot, "log_event", lambda *args, **kwargs: events.append((args, kwargs)))

    assert bot.should_skip_proactive_for_recent_activity(max_age_seconds=900) is False
    assert events == []
