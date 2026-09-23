"""Offline contracts for the Telegram external-delivery adapter."""

from __future__ import annotations

from clients.telegram_delivery import TelegramExternalTransport


def test_long_telegram_delivery_fails_when_an_earlier_chunk_fails(monkeypatch) -> None:
    from tools import telegram

    sent = iter([None, 22])
    monkeypatch.setattr(
        telegram, "send_telegram_msg",
        lambda text, disable_notification=False: next(sent),
    )
    transport = TelegramExternalTransport()

    assert transport.send_text("x" * 3501) is None


def test_telegram_transport_preserves_short_and_long_text_delivery() -> None:
    short_calls: list[tuple[str, bool]] = []
    long_calls: list[tuple[str, bool]] = []
    transport = TelegramExternalTransport(
        send_message=lambda text, silent: short_calls.append((text, silent)) or 11,
        send_full_message=lambda text, silent: long_calls.append((text, silent)) or 12,
    )

    short_id = transport.send_text("σύντομο", silent=True)
    long_text = "x" * 3501
    long_id = transport.send_text(long_text)

    assert short_id == 11
    assert long_id == 12
    assert short_calls == [("σύντομο", True)]
    assert long_calls == [(long_text, False)]
