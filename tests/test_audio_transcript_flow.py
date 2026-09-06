def test_audio_transcript_flow():
    """Telegram voice metadata stays trusted and out of the user transcript."""
    from clients.telegram_bot import _prepare_telegram_message
    from memory.pending_assets import looks_like_asset_confirmation_prompt

    clean_user_text, is_voice_mode, voice_context = _prepare_telegram_message(
        "Καλημέρα",
        voice_input=True,
    )

    assert clean_user_text == "Καλημέρα"
    assert is_voice_mode is False
    assert voice_context is not None
    assert "voice message" not in clean_user_text.casefold()
    assert looks_like_asset_confirmation_prompt(clean_user_text) is False


def test_legacy_voice_transport_markers_are_removed() -> None:
    """Old queued Telegram voice messages remain compatible without prompt leakage."""
    from clients.telegram_bot import _prepare_telegram_message

    clean_user_text, is_voice_mode, voice_context = _prepare_telegram_message(
        "[VOICE]: [VOICE_INPUT] Καλημέρα",
    )

    assert clean_user_text == "Καλημέρα"
    assert is_voice_mode is False
    assert voice_context is not None


def test_voice_reply_requires_enabled_telegram_voice_mode(monkeypatch) -> None:
    """Voice input alone stays text; the /voice toggle enables spoken replies."""
    import clients.telegram_bot as bot

    monkeypatch.setattr(bot, "voice_mode_enabled", True)
    clean_user_text, is_voice_mode, voice_context = bot._prepare_telegram_message(
        "Καλημέρα",
        voice_input=True,
    )

    assert clean_user_text == "Καλημέρα"
    assert is_voice_mode is True
    assert voice_context is not None


def test_telegram_tts_uses_the_configured_locale(monkeypatch) -> None:
    """Telegram voice delivery must synthesize and send audio without stale i18n names."""
    import asyncio
    from types import SimpleNamespace

    import config
    import core.i18n as i18n
    import tools.telegram as telegram

    synthesis_calls = []
    sent = []
    monkeypatch.setattr(telegram, "_suppress_test_delivery", lambda reason: False)
    monkeypatch.setattr(config, "TELEGRAM_TOKEN", "test-token")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "test-chat")
    monkeypatch.setattr(
        "core.text_to_speech.synthesize_speech",
        lambda text, locale: synthesis_calls.append((text, locale)) or b"voice-bytes",
    )
    monkeypatch.setattr(
        telegram.requests,
        "post",
        lambda *args, **kwargs: sent.append((args, kwargs))
        or SimpleNamespace(status_code=200, text="ok"),
    )

    asyncio.run(telegram.send_telegram_voice("Καλημέρα"))

    assert synthesis_calls == [("Καλημέρα", i18n.LANG)]
    assert len(sent) == 1


def test_telegram_tts_failure_falls_back_to_the_text_reply(monkeypatch) -> None:
    """A provider failure never makes the user's Telegram reply disappear."""
    import asyncio

    import config
    import tools.telegram as telegram

    text_replies: list[str] = []
    monkeypatch.setattr(telegram, "_suppress_test_delivery", lambda reason: False)
    monkeypatch.setattr(config, "TELEGRAM_TOKEN", "test-token")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "test-chat")
    monkeypatch.setattr(
        "core.text_to_speech.synthesize_speech",
        lambda text, locale: (_ for _ in ()).throw(RuntimeError("offline failure")),
    )
    monkeypatch.setattr(
        telegram,
        "send_telegram_msg",
        lambda text: text_replies.append(text),
    )

    asyncio.run(telegram.send_telegram_voice("Καλημέρα"))

    assert text_replies == ["Καλημέρα"]


def test_telegram_tts_setup_failure_warns_then_preserves_text(monkeypatch) -> None:
    """A voice setup failure is actionable and never exposes exception details."""
    import asyncio

    import config
    import tools.telegram as telegram
    from core.ai_provider import VoiceProviderSetupRequired
    from core.i18n import t

    delivered: list[str] = []
    monkeypatch.setattr(telegram, "_suppress_test_delivery", lambda reason: False)
    monkeypatch.setattr(config, "TELEGRAM_TOKEN", "test-token")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "test-chat")
    monkeypatch.setattr(
        "core.text_to_speech.synthesize_speech",
        lambda text, locale: (_ for _ in ()).throw(
            VoiceProviderSetupRequired(
                "setup failed with secret-value",
                provider="anthropic",
            )
        ),
    )
    monkeypatch.setattr(telegram, "send_telegram_msg", delivered.append)

    asyncio.run(telegram.send_telegram_voice("Καλημέρα"))

    assert delivered == [
        t("clients.telegram_bot.voice_output_setup_required"),
        "Καλημέρα",
    ]
    assert "secret-value" not in " ".join(delivered)
