"""Offline regressions for delivery-confirmed completion and connection lifetime."""
import sqlite3

import pytest

from tests.test_reminders_sql import _make_reminders_db, _row_status, PAST_TIME


@pytest.mark.parametrize("channel", ["matrix", "telegram"])
def test_timed_reminder_retries_failed_send_and_completes_only_once(tmp_path, monkeypatch, channel):
    """Exercise the actual worker and assistant wrapper across both transports."""
    import config
    from clients import telegram_bot as bot
    from memory import conversation_history
    from services.external_delivery import external_delivery_router, DeliveryReceipt

    db = str(tmp_path / "state.db")
    _make_reminders_db(db, [{"task": "fixture reminder", "time": PAST_TIME}])
    monkeypatch.setattr(config, "STATE_DB", db)
    monkeypatch.setattr(bot, "is_reminders_paused", lambda: False)
    monkeypatch.setattr(bot, "is_duplicate_notification", lambda *a, **k: False)
    events, history, sends = [], [], []
    monkeypatch.setattr(bot, "log_event", lambda *a, **k: events.append(a))
    monkeypatch.setattr(bot, "_append_to_analytics_log", lambda *a, **k: history.append(a))
    monkeypatch.setattr(conversation_history, "append_message", lambda **k: history.append(k))
    def failed(*a, **k):
        raise RuntimeError("offline transport failure")
    monkeypatch.setattr(external_delivery_router, "send_text", failed)
    monkeypatch.setattr(external_delivery_router, "send_text_to", failed)
    bot.job_check_reminders()
    assert _row_status(db, "fixture reminder") == "pending"
    assert events == [] and history == []
    def confirmed(text, **kwargs):
        sends.append(text)
        return DeliveryReceipt(channel, "fixture-event")
    monkeypatch.setattr(external_delivery_router, "send_text", confirmed)
    bot.job_check_reminders()
    bot.job_check_reminders()
    assert _row_status(db, "fixture reminder") == "done"
    assert len(sends) == len(events) == len(history) == 1


def test_location_reminder_does_not_complete_when_assistant_wrapper_returns_no_receipt(tmp_path, monkeypatch):
    """The Telegram entry point must preserve failure at its callback boundary."""
    import config
    from clients import telegram_bot as bot
    db = str(tmp_path / "state.db")
    _make_reminders_db(db, [{"task": "fixture location", "time": "loc:home"}])
    monkeypatch.setattr(config, "STATE_DB", db)
    monkeypatch.setattr(config, "GPS_STORAGE_FILE", str(tmp_path / "gps.json"))
    monkeypatch.setattr(config, "HOME_COORDS", (0.0, 0.0))
    monkeypatch.setattr(config, "HOME_RADIUS_M", 150)
    monkeypatch.setattr(bot, "_send_and_record_assistant", lambda *a, **k: None)
    point = {"chat": {"id": 1}, "location": {"latitude": 0.0, "longitude": 0.0}}
    bot.handle_location(point, live_update=True)
    assert _row_status(db, "fixture location") == "pending"
    monkeypatch.setattr(bot, "_send_and_record_assistant", lambda *a, **k: "fixture-event")
    bot.handle_location(point, live_update=True)
    assert _row_status(db, "fixture location") == "done"


@pytest.mark.parametrize("fails", [False, True])
def test_location_memory_closes_connections_even_on_error(tmp_path, monkeypatch, fails):
    """Keep references alive so GC cannot conceal a missing explicit close."""
    from memory import location_reminders as memory
    db = str(tmp_path / "state.db")
    _make_reminders_db(db, [{"task": "fixture", "time": "loc:home"}])
    connections = []
    original = sqlite3.connect
    class TrackedConnection(sqlite3.Connection):
        closed = False
        def close(self):
            self.closed = True
            super().close()
    def connect(*args, **kwargs):
        conn = original(*args, **kwargs, factory=TrackedConnection)
        connections.append(conn)
        return conn
    monkeypatch.setattr(memory.sqlite3, "connect", connect)
    def distance(*args):
        if fails:
            raise RuntimeError("distance failure")
        return 0
    kwargs = dict(db_path=db, lat=0, lon=0, home_coords=(0, 0), home_radius_m=150,
                  distance_meters=distance)
    if fails:
        with pytest.raises(RuntimeError):
            memory.find_triggered_location_reminders(**kwargs)
    else:
        assert memory.find_triggered_location_reminders(**kwargs) == [(1, "fixture", "home")]
        memory.finish_location_reminder(db_path=db, reminder_id=1)
        assert _row_status(db, "fixture") == "done"
    assert connections and all(conn.closed for conn in connections)
