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


def test_doctor_command_invokes_structured_tool(monkeypatch):
    import clients.telegram_bot as bot
    import tools.system as system

    calls = []
    monkeypatch.setattr(
        system,
        "system_doctor",
        SimpleNamespace(invoke=lambda payload: calls.append(payload) or "doctor report"),
    )

    assert bot._run_system_doctor_command() == "doctor report"
    assert calls == [{"days": 1}]


def test_vacation_pause_skip_is_logged_once_per_pause(monkeypatch):
    import clients.telegram_bot as bot

    printed = []
    monkeypatch.setattr(bot, "_vacation_pause_logged_until", None, raising=False)
    monkeypatch.setattr(bot, "print", lambda message: printed.append(message), raising=False)

    bot._log_vacation_routine_skip(2000.0)
    bot._log_vacation_routine_skip(2000.0)

    assert printed == ["[job_check_routines]: Vacation routine pause active — skipped"]


def test_vacation_pause_log_reset_allows_the_next_pause_to_log(monkeypatch):
    import clients.telegram_bot as bot

    printed = []
    monkeypatch.setattr(bot, "_vacation_pause_logged_until", 2000.0, raising=False)
    monkeypatch.setattr(bot, "print", lambda message: printed.append(message), raising=False)

    bot._reset_vacation_pause_skip_log()
    bot._log_vacation_routine_skip(2000.0)

    assert printed == ["[job_check_routines]: Vacation routine pause active — skipped"]


def test_doctor_command_sends_long_reports_with_chunking(monkeypatch):
    import clients.telegram_bot as bot

    sent = []
    monkeypatch.setattr(bot, "_run_system_doctor_command", lambda: "doctor report")
    monkeypatch.setattr(bot, "send_telegram_msg_full", lambda text: sent.append(text))

    bot._send_system_doctor_report()

    assert sent == ["doctor report"]


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


def test_transcribed_voice_uses_pending_georgian_translation(monkeypatch):
    import clients.telegram_bot as bot

    translations = []
    monkeypatch.setattr(bot, "_consume_pending_georgian", lambda: True)
    monkeypatch.setattr(bot, "_consume_pending_partner", lambda: False)
    monkeypatch.setattr(
        bot,
        "_send_georgian_translation",
        lambda text, force_src="auto": translations.append((text, force_src)),
    )

    assert bot._handle_transcribed_voice("καλημέρα") is True
    assert translations == [("καλημέρα", "auto")]


def test_transcribed_voice_uses_pending_partner_translation(monkeypatch):
    import clients.telegram_bot as bot

    translations = []
    monkeypatch.setattr(bot, "_consume_pending_georgian", lambda: False)
    monkeypatch.setattr(bot, "_consume_pending_partner", lambda: True)
    monkeypatch.setattr(
        bot,
        "_send_georgian_translation",
        lambda text, force_src="auto": translations.append((text, force_src)),
    )

    assert bot._handle_transcribed_voice("გამარჯობა") is True
    assert translations == [("გამარჯობა", "ka")]


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
    assert posted[0].url.endswith("/sendVoice")
    assert posted[0].files["voice"][0] == "georgian.mp3"
