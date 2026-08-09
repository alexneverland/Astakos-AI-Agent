from types import SimpleNamespace


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
