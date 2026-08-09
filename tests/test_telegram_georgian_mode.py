import json
from types import SimpleNamespace


def test_vacation_routine_pause_keeps_reminders_and_followups_active(monkeypatch):
    import clients.telegram_bot as bot

    monkeypatch.setattr(bot._time, "time", lambda: 1000.0)
    monkeypatch.setattr(
        bot,
        "_override_state",
        {
            "pause_reminders": False,
            "mute_proactive": False,
            "sleep_until": None,
            "routine_pause_until": 2000.0,
        },
    )

    assert bot.is_routines_paused() is True
    assert bot.is_reminders_paused() is False
    assert bot.is_proactive_muted() is False


def test_scheduler_status_shows_active_vacation_routine_pause(monkeypatch):
    import clients.telegram_bot as bot

    monkeypatch.setattr(bot.time, "time", lambda: 1000.0)
    monkeypatch.setattr(bot._time, "time", lambda: 1000.0)
    monkeypatch.setattr(bot, "is_quiet_hours", lambda: False)
    monkeypatch.setattr(
        bot,
        "_override_state",
        {
            "pause_reminders": False,
            "mute_proactive": False,
            "sleep_until": None,
            "routine_pause_until": 1000.0 + 2 * 86400,
        },
    )

    status = bot.AstakosScheduler().status()

    assert "Vacation routines paused" in status
    assert "2 day(s) remaining" in status


def test_runtime_snapshot_includes_active_vacation_routine_pause(tmp_path, monkeypatch):
    import clients.telegram_bot as bot
    import config

    monkeypatch.setattr(bot.time, "time", lambda: 1000.0)
    monkeypatch.setattr(bot._time, "time", lambda: 1000.0)
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(
        bot,
        "_override_state",
        {
            "pause_reminders": False,
            "mute_proactive": False,
            "sleep_until": None,
            "routine_pause_until": 1000.0 + 2 * 86400,
        },
    )

    bot.AstakosScheduler()._write_snapshot()

    snapshot = json.loads((tmp_path / "runtime_snapshot.json").read_text(encoding="utf-8"))
    assert snapshot["routines_paused"] is True
    assert snapshot["routine_pause_remaining_days"] == 2


def test_routine_scheduler_skips_during_vacation_pause(monkeypatch):
    import clients.telegram_bot as bot

    def routine_db_must_not_be_queried(_path):
        raise AssertionError("routine DB must not be queried")

    monkeypatch.setattr(bot, "is_routines_paused", lambda: True)
    monkeypatch.setattr(bot, "pending_routine_confirmations", {})
    with monkeypatch.context() as context:
        context.setattr(bot.os.path, "exists", routine_db_must_not_be_queried)
        bot.job_check_routines()


def test_vacation_pause_reactivates_and_clears_pending_routine_confirmations(monkeypatch):
    import clients.telegram_bot as bot
    import memory.routine_db as routine_db

    expired = []
    removed = []
    monkeypatch.setattr(
        bot,
        "pending_routine_confirmations",
        {42: {"event": "Morning routine"}},
    )
    monkeypatch.setattr(
        routine_db,
        "expire_routine_confirmation",
        lambda routine_id: expired.append(routine_id),
    )
    monkeypatch.setattr(
        routine_db,
        "remove_pending_confirmation",
        lambda routine_id: removed.append(routine_id),
    )

    bot._clear_pending_routine_confirmations_for_vacation()

    assert bot.pending_routine_confirmations == {}
    assert expired == [42]
    assert removed == [42]


def test_startup_missed_routines_skip_during_vacation_pause(monkeypatch):
    import clients.telegram_bot as bot

    def routine_db_must_not_be_queried(_path):
        raise AssertionError("routine DB must not be queried")

    monkeypatch.setattr(bot, "is_routines_paused", lambda: True)
    with monkeypatch.context() as context:
        context.setattr(bot.os.path, "exists", routine_db_must_not_be_queried)
        bot.startup_check_missed_routines()


def test_georgian_quick_phrases_menu_alias_is_recognized():
    import clients.telegram_bot as bot

    assert "/g_phrases" in bot.GEORGIAN_COMMAND_ALIASES
    assert "/g_phrases" in bot.GEORGIAN_QUICK_PHRASES_ALIASES


def test_pending_georgian_mode_consumes_once(monkeypatch):
    import clients.telegram_bot as bot

    now = [1000.0]
    monkeypatch.setattr(bot.time, "time", lambda: now[0])

    bot._clear_pending_georgian()
    bot._arm_pending_georgian()

    assert bot._consume_pending_georgian() is True
    assert bot._consume_pending_georgian() is False


def test_pending_georgian_mode_expires(monkeypatch):
    import clients.telegram_bot as bot

    now = [1000.0]
    monkeypatch.setattr(bot.time, "time", lambda: now[0])

    bot._clear_pending_georgian()
    bot._arm_pending_georgian()
    now[0] += bot.PENDING_GEORGIAN_TTL_SECONDS + 1

    assert bot._consume_pending_georgian() is False


def test_send_georgian_translation_sends_text_and_audio(monkeypatch):
    import clients.telegram_bot as bot
    from tools import georgian

    sent = []
    posted = []

    monkeypatch.setattr(
        georgian,
        "translate",
        lambda text, src="auto": {"translated": "გამარჯობა", "phonetic": "gamarjoba", "src": "el", "tgt": "ka"},
    )
    monkeypatch.setattr(georgian, "tts_audio", lambda text, lang="ka": b"audio-bytes")
    monkeypatch.setattr(bot, "send_telegram_msg", lambda msg: sent.append(msg) or 123)
    monkeypatch.setattr(
        bot.requests,
        "post",
        lambda url, data=None, files=None, timeout=None: posted.append(
            SimpleNamespace(url=url, data=data, files=files, timeout=timeout)
        ),
    )

    bot._send_georgian_translation("καλημέρα")

    assert sent == ["🇬🇪 <code>გამარჯობა</code>\n📢 <i>gamarjoba</i>"]
    assert posted[0].url.endswith("/sendAudio")
    assert posted[0].files["audio"][0] == "georgian.mp3"
