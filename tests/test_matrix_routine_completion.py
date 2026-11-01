"""Offline regression coverage for inbound Matrix routine confirmations."""

from __future__ import annotations

from langchain_core.messages import SystemMessage

from services.routine_completion_helper import RoutineSelection


def test_matrix_pending_completion_updates_routine_before_returning_context(
    monkeypatch,
) -> None:
    """A Matrix completion consumes the pending reminder and records success."""
    import memory.event_log as event_log
    import memory.routine_db as routine_db
    import clients.telegram_bot as telegram_bot
    import core.messenger_draft as messenger_draft
    import services.routine_completion_selector as completion_selector
    from services.matrix_routine_completion import process_pending_routine_confirmation

    calls: list[tuple[str, int]] = []
    monkeypatch.setattr(messenger_draft, "active_draft_status", lambda: (True, "active", {}))
    monkeypatch.setattr(
        routine_db,
        "load_pending_confirmations",
        lambda: {7: {"event": "Ύπνος Αλέξανδρου", "draft_offer": False}},
    )
    monkeypatch.setattr(routine_db, "confirm_routine", lambda rid: calls.append(("confirm", rid)))
    monkeypatch.setattr(
        routine_db,
        "mark_routine_responded",
        lambda rid: calls.append(("responded", rid)),
    )
    monkeypatch.setattr(
        routine_db,
        "mark_routine_triggered_today",
        lambda rid: calls.append(("triggered", rid)),
    )
    monkeypatch.setattr(
        routine_db,
        "remove_pending_confirmation",
        lambda rid: calls.append(("removed", rid)),
    )
    monkeypatch.setattr(event_log, "log_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        telegram_bot, "pending_routine_confirmations",
        {7: {"event": "Ύπνος Αλέξανδρου"}},
    )
    monkeypatch.setattr(
        completion_selector,
        "select_routine",
        lambda user_text, candidates, pool: RoutineSelection("complete", 7),
    )

    result = process_pending_routine_confirmation("Το έκανα", channel="matrix")

    assert isinstance(result, SystemMessage)
    assert calls == [
        ("confirm", 7),
        ("responded", 7),
        ("triggered", 7),
        ("removed", 7),
    ]
    assert telegram_bot.pending_routine_confirmations == {}


def test_matrix_non_confirmation_passes_through_without_mutation(monkeypatch) -> None:
    """Unrelated Matrix chat remains a normal graph turn."""
    import memory.routine_db as routine_db
    import services.routine_completion_selector as completion_selector
    from services.matrix_routine_completion import process_pending_routine_confirmation

    monkeypatch.setattr(
        routine_db,
        "load_pending_confirmations",
        lambda: {7: {"event": "Ύπνος Αλέξανδρου", "draft_offer": False}},
    )
    monkeypatch.setattr(routine_db, "get_eligible_preemptive_routines_for_day", lambda _day: [])
    monkeypatch.setattr(routine_db, "get_active_routine_catalog", lambda: [])
    monkeypatch.setattr(
        completion_selector,
        "select_routine",
        lambda user_text, candidates, pool: RoutineSelection("none", None),
    )
    monkeypatch.setattr(
        routine_db,
        "confirm_routine",
        lambda rid: (_ for _ in ()).throw(AssertionError("unexpected routine mutation")),
    )

    assert process_pending_routine_confirmation("Τι καιρό κάνει;", channel="matrix") is None


def test_matrix_draft_offer_returns_deferred_authorization(monkeypatch) -> None:
    """A selected draft offer is authorized but not consumed before tool success."""
    from datetime import datetime

    import memory.routine_db as routine_db
    import services.routine_completion_selector as completion_selector
    from services.matrix_routine_completion import (
        MatrixRoutineDraftOffer,
        process_pending_routine_confirmation,
    )

    sent_at = datetime(2026, 9, 17, 8, 0)
    monkeypatch.setattr(
        routine_db,
        "load_pending_confirmations",
        lambda: {5: {"event": "Message Sofia", "draft_offer": True, "sent_at": sent_at}},
    )
    monkeypatch.setattr(
        completion_selector,
        "select_routine",
        lambda user_text, candidates, pool: RoutineSelection("draft", 5),
    )
    acknowledged: list[tuple[int, datetime]] = []
    monkeypatch.setattr(
        routine_db,
        "acknowledge_pending_draft_offer",
        lambda routine_id, offered_at: acknowledged.append((routine_id, offered_at)) or True,
    )

    result = process_pending_routine_confirmation("Ετοίμασέ το", channel="matrix")

    assert isinstance(result, MatrixRoutineDraftOffer)
    assert result.routine_id == 5
    assert result.sent_at == sent_at
    assert acknowledged == []


def test_matrix_routine_offer_cannot_replace_an_active_messenger_draft(
    monkeypatch,
) -> None:
    """An existing reviewed draft excludes new routine-draft authorization."""
    from datetime import datetime

    import core.messenger_draft as messenger_draft
    import memory.routine_db as routine_db
    import services.routine_completion_selector as completion_selector
    from services.matrix_routine_completion import process_pending_routine_confirmation

    monkeypatch.setattr(
        messenger_draft,
        "active_draft_status",
        lambda: (True, "active", {"target_name": "Σοφία", "message": "Παλιό draft"}),
    )
    monkeypatch.setattr(
        routine_db,
        "load_pending_confirmations",
        lambda: {5: {
            "event": "Message Sofia",
            "draft_offer": True,
            "sent_at": datetime(2026, 9, 17, 8, 0),
        }},
    )
    monkeypatch.setattr(routine_db, "get_eligible_preemptive_routines_for_day", lambda _day: [])
    monkeypatch.setattr(routine_db, "get_active_routine_catalog", lambda: [])
    seen_candidates: list[dict[int, str]] = []

    def select_offer(_text: str, candidates: dict[int, str], _pool: str) -> RoutineSelection:
        seen_candidates.append(candidates)
        return RoutineSelection("draft", 5)

    monkeypatch.setattr(completion_selector, "select_routine", select_offer)

    result = process_pending_routine_confirmation("Ετοίμασέ το", channel="matrix")

    assert result is None
    assert seen_candidates
    assert "[MESSENGER_DRAFT_OFFER]" not in seen_candidates[0][5]


def test_matrix_draft_offer_reaches_the_real_selector_boundary(monkeypatch) -> None:
    """The production selector sees the canonical persisted draft marker."""
    from datetime import datetime

    import memory.routine_db as routine_db
    import services.routine_completion_selector as completion_selector
    from services.matrix_routine_completion import MatrixRoutineDraftOffer
    from services.matrix_routine_completion import process_pending_routine_confirmation

    monkeypatch.setattr(
        routine_db,
        "load_pending_confirmations",
        lambda: {
            5: {
                "event": "Message Sofia",
                "draft_offer": True,
                "sent_at": datetime(2026, 9, 17, 8, 0),
            }
        },
    )

    def select_from_prompt(prompt: str):
        assert "[MESSENGER_DRAFT_OFFER]" in prompt
        return type(
            "Response",
            (),
            {"text": '{"action":"draft","routine_id":5}'},
        )()

    monkeypatch.setattr(completion_selector, "safe_gemini_call", select_from_prompt)

    result = process_pending_routine_confirmation("Ετοίμασέ το", channel="matrix")

    assert isinstance(result, MatrixRoutineDraftOffer)


def test_matrix_completion_before_reminder_marks_today_without_pending_prompt(
    monkeypatch,
) -> None:
    import memory.event_log as event_log
    import memory.routine_db as routine_db
    import services.routine_completion_selector as selector
    from services.matrix_routine_completion import process_pending_routine_confirmation

    monkeypatch.setattr(routine_db, "load_pending_confirmations", lambda: {})
    monkeypatch.setattr(
        routine_db,
        "get_eligible_preemptive_routines_for_day",
        lambda _day: [{"id": 8, "event": "Προπόνηση Αλέξανδρου"}],
    )
    monkeypatch.setattr(
        selector, "select_routine",
        lambda _text, _candidates, pool: RoutineSelection("complete", 8)
        if pool == "today" else RoutineSelection("none", None),
    )
    triggered: list[int] = []
    monkeypatch.setattr(
        routine_db, "mark_routine_triggered_today", triggered.append
    )
    monkeypatch.setattr(event_log, "log_event", lambda *_args, **_kwargs: None)

    result = process_pending_routine_confirmation(
        "Πήγαμε ήδη στην προπόνηση", channel="matrix"
    )

    assert isinstance(result, SystemMessage)
    assert triggered == [8]


def test_matrix_unrelated_message_does_not_change_today_or_catalog(
    monkeypatch,
) -> None:
    import memory.routine_db as routine_db
    import services.routine_completion_selector as selector
    from services.matrix_routine_completion import process_pending_routine_confirmation

    monkeypatch.setattr(routine_db, "load_pending_confirmations", lambda: {})
    monkeypatch.setattr(
        routine_db, "get_eligible_preemptive_routines_for_day",
        lambda _day: [{"id": 8, "event": "Προπόνηση Αλέξανδρου"}],
    )
    monkeypatch.setattr(
        routine_db, "get_active_routine_catalog",
        lambda: [{"id": 8, "event": "Προπόνηση Αλέξανδρου"}],
    )
    monkeypatch.setattr(
        selector, "select_routine",
        lambda *_args: RoutineSelection("none", None),
    )
    monkeypatch.setattr(
        routine_db,
        "mark_routine_triggered_today",
        lambda _id: (_ for _ in ()).throw(AssertionError("unexpected mutation")),
    )
    assert process_pending_routine_confirmation("Τι καιρό κάνει;", channel="matrix") is None


def test_matrix_preemptive_skip_prevents_later_routine_prompt(monkeypatch) -> None:
    import memory.event_log as event_log
    import memory.routine_db as routine_db
    import services.routine_completion_selector as selector
    from services.matrix_routine_completion import process_pending_routine_confirmation

    monkeypatch.setattr(routine_db, "load_pending_confirmations", lambda: {})
    monkeypatch.setattr(
        routine_db, "get_eligible_preemptive_routines_for_day",
        lambda _day: [{"id": 8, "event": "Προπόνηση Αλέξανδρου"}],
    )
    monkeypatch.setattr(
        selector, "select_routine",
        lambda _text, _candidates, pool: RoutineSelection("skip_today", 8)
        if pool == "today" else RoutineSelection("none", None),
    )
    skipped: list[int] = []
    monkeypatch.setattr(
        routine_db, "record_routine_skip_today",
        lambda rid: skipped.append(rid) or {"skip_streak": 1},
    )
    monkeypatch.setattr(event_log, "log_event", lambda *_args, **_kwargs: None)

    assert isinstance(
        process_pending_routine_confirmation("Σήμερα δεν θα πάμε προπόνηση"),
        SystemMessage,
    )
    assert skipped == [8]


def test_matrix_can_pause_catalog_routine_without_pending_prompt(monkeypatch) -> None:
    import memory.event_log as event_log
    import memory.routine_db as routine_db
    import services.routine_completion_selector as selector
    from services.matrix_routine_completion import process_pending_routine_confirmation

    monkeypatch.setattr(routine_db, "load_pending_confirmations", lambda: {})
    monkeypatch.setattr(routine_db, "get_eligible_preemptive_routines_for_day", lambda _day: [])
    monkeypatch.setattr(
        routine_db, "get_active_routine_catalog",
        lambda: [{"id": 8, "event": "Προπόνηση Αλέξανδρου"}],
    )
    monkeypatch.setattr(
        selector, "select_routine",
        lambda _text, _candidates, pool: RoutineSelection("pause", 8)
        if pool == "catalog" else RoutineSelection("none", None),
    )
    paused: list[int] = []
    monkeypatch.setattr(routine_db, "pause_routine_indefinitely", paused.append)
    monkeypatch.setattr(event_log, "log_event", lambda *_args, **_kwargs: None)

    result = process_pending_routine_confirmation(
        "Σταμάτα την Προπόνηση Αλέξανδρου", channel="matrix"
    )

    assert isinstance(result, SystemMessage)
    assert paused == [8]
