"""Regression coverage for the nightly routine-discovery job."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any


def test_nightly_analytics_runs_without_reflection_or_behavioral_intake(monkeypatch: Any) -> None:
    """Keeps routine discovery active without rescanning behavioral events."""
    import clients.telegram_bot as bot

    analytics_calls: list[bool] = []
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
        "services.reflection_engine",
        SimpleNamespace(run_reflection=lambda: reflection_calls.append(True) or {"pending_items": []}),
    )

    bot.job_analytics_engine()

    assert analytics_calls == [True]
    assert reflection_calls == []


def test_nightly_routine_analytics_notification_is_unchanged(monkeypatch: Any) -> None:
    """Removing behavioral intake does not alter routine analytics notifications."""
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
    bot.job_analytics_engine()

    assert len(notifications) == 1


def test_nightly_routine_analytics_failure_is_contained(monkeypatch: Any) -> None:
    """Routine analytics failures remain contained after intake is decoupled."""
    import clients.telegram_bot as bot

    class ThreeAm:
        @classmethod
        def now(cls) -> SimpleNamespace:
            return SimpleNamespace(hour=3)

    monkeypatch.setattr(bot, "datetime", ThreeAm)
    monkeypatch.setitem(
        sys.modules,
        "services.analytics_engine",
        SimpleNamespace(run_analytics=lambda: (_ for _ in ()).throw(RuntimeError("unavailable"))),
    )
    bot.job_analytics_engine()
