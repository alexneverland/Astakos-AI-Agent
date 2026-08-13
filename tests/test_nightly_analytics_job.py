"""Regression coverage for the nightly routine-discovery job."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any


def test_nightly_analytics_runs_without_invoking_reflection(monkeypatch: Any) -> None:
    """Keeps passive routine discovery active while Reflection remains paused."""
    import clients.telegram_bot as bot

    analytics_calls: list[bool] = []
    behavioral_event_calls: list[bool] = []
    reflection_calls: list[bool] = []

    class ThreeAm:
        """Provides a deterministic 03:00 scheduler clock."""

        @classmethod
        def now(cls) -> SimpleNamespace:
            """Returns a clock value inside the nightly analytics window."""
            return SimpleNamespace(hour=3)

    monkeypatch.setattr(bot, "datetime", ThreeAm)
    monkeypatch.setattr(bot, "send_telegram_msg", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(bot, "pending_reflection_confirmations", {})
    monkeypatch.setitem(
        sys.modules,
        "services.analytics_engine",
        SimpleNamespace(run_analytics=lambda: analytics_calls.append(True) or {"created": 0, "merged": 0}),
    )
    monkeypatch.setitem(
        sys.modules,
        "services.behavioral_event_extractor",
        SimpleNamespace(run_behavioral_event_intake=lambda: behavioral_event_calls.append(True) or {}),
    )
    monkeypatch.setitem(
        sys.modules,
        "services.reflection_engine",
        SimpleNamespace(run_reflection=lambda: reflection_calls.append(True) or {"pending_items": []}),
    )

    bot.job_analytics_engine()

    assert analytics_calls == [True]
    assert behavioral_event_calls == [True]
    assert reflection_calls == []


def test_behavioral_intake_failure_does_not_block_routine_analytics_notification(monkeypatch: Any) -> None:
    """Behavioral recording is observational and cannot break routine analytics."""
    import clients.telegram_bot as bot

    class ThreeAm:
        @classmethod
        def now(cls) -> SimpleNamespace:
            return SimpleNamespace(hour=3)

    notifications: list[str] = []
    monkeypatch.setattr(bot, "datetime", ThreeAm)
    monkeypatch.setattr(bot, "send_telegram_msg", lambda message: notifications.append(message))
    monkeypatch.setitem(
        sys.modules,
        "services.analytics_engine",
        SimpleNamespace(run_analytics=lambda: {"created": 1, "merged": 0, "detected": 1}),
    )
    monkeypatch.setitem(
        sys.modules,
        "services.behavioral_event_extractor",
        SimpleNamespace(run_behavioral_event_intake=lambda: (_ for _ in ()).throw(RuntimeError("unavailable"))),
    )

    bot.job_analytics_engine()

    assert len(notifications) == 1
