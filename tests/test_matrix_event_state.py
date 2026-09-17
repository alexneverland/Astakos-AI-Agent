"""Offline contracts for durable Matrix inbound/reply lifecycle state."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from memory.matrix_event_state import (
    MatrixEventStateError,
    get_matrix_event,
    list_pending_matrix_replies,
    list_stale_matrix_processing,
    mark_matrix_attachment_sent,
    mark_matrix_event_replied,
    mark_matrix_reply_text_sent,
    reserve_matrix_event,
    store_matrix_event_reply,
)


def _reserve(db_path: str, event_id: str = "$event-1") -> dict[str, object]:
    return reserve_matrix_event(
        event_id=event_id,
        room_id="!private-room:example.test",
        sender_id="@owner:example.test",
        db_path=db_path,
    )


def test_reserve_matrix_event_is_durable_and_unique(tmp_path) -> None:
    db_path = str(tmp_path / "state.db")

    first = _reserve(db_path)
    replay = _reserve(db_path)

    assert first["action"] == "reserved"
    assert first["status"] == "processing"
    assert replay == {
        "action": "already_reserved",
        "event_id": "$event-1",
        "status": "processing",
    }

    stored = get_matrix_event("$event-1", db_path=db_path)
    assert stored is not None
    assert stored["room_id"] == "!private-room:example.test"
    assert stored["sender_id"] == "@owner:example.test"
    assert stored["reply_text"] is None


def test_replayed_event_id_cannot_change_room_or_sender(tmp_path) -> None:
    db_path = str(tmp_path / "state.db")
    _reserve(db_path)

    with pytest.raises(MatrixEventStateError, match="identity mismatch"):
        reserve_matrix_event(
            event_id="$event-1",
            room_id="!other-room:example.test",
            sender_id="@owner:example.test",
            db_path=db_path,
        )

    with pytest.raises(MatrixEventStateError, match="identity mismatch"):
        reserve_matrix_event(
            event_id="$event-1",
            room_id="!private-room:example.test",
            sender_id="@other:example.test",
            db_path=db_path,
        )


def test_reply_is_persisted_before_delivery_and_recovered(tmp_path) -> None:
    db_path = str(tmp_path / "state.db")
    _reserve(db_path)

    saved = store_matrix_event_reply(
        "$event-1",
        "Αποθηκευμένη απάντηση",
        db_path=db_path,
    )

    assert saved["action"] == "reply_stored"
    assert saved["status"] == "reply_pending"
    assert list_pending_matrix_replies(db_path=db_path) == [
        {
            "event_id": "$event-1",
            "room_id": "!private-room:example.test",
            "sender_id": "@owner:example.test",
            "reply_text": "Αποθηκευμένη απάντηση",
            "reply_mode": "text",
            "attachment_paths": (),
            "text_sent": 0,
            "attachments_sent_count": 0,
            "status": "reply_pending",
        }
    ]

    replay = _reserve(db_path)
    assert replay["action"] == "already_reserved"
    assert replay["status"] == "reply_pending"


def test_mark_replied_is_idempotent_and_removes_pending_reply(tmp_path) -> None:
    db_path = str(tmp_path / "state.db")
    _reserve(db_path)
    store_matrix_event_reply("$event-1", "Έτοιμο", db_path=db_path)
    mark_matrix_reply_text_sent("$event-1", db_path=db_path)

    first = mark_matrix_event_replied("$event-1", db_path=db_path)
    replay = mark_matrix_event_replied("$event-1", db_path=db_path)

    assert first["action"] == "marked_replied"
    assert replay == {
        "action": "already_replied",
        "event_id": "$event-1",
        "status": "replied",
    }
    assert list_pending_matrix_replies(db_path=db_path) == []


def test_illegal_transitions_fail_closed(tmp_path) -> None:
    db_path = str(tmp_path / "state.db")
    _reserve(db_path)

    with pytest.raises(MatrixEventStateError, match="reply_pending"):
        mark_matrix_event_replied("$event-1", db_path=db_path)

    store_matrix_event_reply("$event-1", "Πρώτη", db_path=db_path)
    with pytest.raises(MatrixEventStateError, match="different reply"):
        store_matrix_event_reply("$event-1", "Δεύτερη", db_path=db_path)

    mark_matrix_reply_text_sent("$event-1", db_path=db_path)
    mark_matrix_event_replied("$event-1", db_path=db_path)
    with pytest.raises(MatrixEventStateError, match="replied"):
        store_matrix_event_reply("$event-1", "Πρώτη", db_path=db_path)


def test_stale_processing_is_reported_but_never_reclaimed(tmp_path) -> None:
    db_path = str(tmp_path / "state.db")
    started = datetime(2026, 9, 16, 10, 0, 0)
    _reserve_at = reserve_matrix_event(
        event_id="$stale",
        room_id="!private-room:example.test",
        sender_id="@owner:example.test",
        timestamp=started,
        db_path=db_path,
    )
    assert _reserve_at["action"] == "reserved"

    stale = list_stale_matrix_processing(
        older_than=started + timedelta(minutes=5),
        db_path=db_path,
    )

    assert [item["event_id"] for item in stale] == ["$stale"]
    assert _reserve(db_path, "$stale") == {
        "action": "already_reserved",
        "event_id": "$stale",
        "status": "processing",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("event_id", ""),
        ("room_id", "   "),
        ("sender_id", ""),
    ],
)
def test_reserve_rejects_missing_identifiers(tmp_path, field: str, value: str) -> None:
    values = {
        "event_id": "$event-1",
        "room_id": "!private-room:example.test",
        "sender_id": "@owner:example.test",
    }
    values[field] = value

    with pytest.raises(ValueError, match=field):
        reserve_matrix_event(**values, db_path=str(tmp_path / "state.db"))


def test_lifecycle_store_does_not_persist_user_message_or_secrets(tmp_path) -> None:
    db_path = str(tmp_path / "state.db")
    _reserve(db_path)
    store_matrix_event_reply("$event-1", "Απάντηση", db_path=db_path)

    row = get_matrix_event("$event-1", db_path=db_path)

    assert row is not None
    assert set(row) == {
        "event_id",
        "room_id",
        "sender_id",
        "status",
        "reply_text",
        "reply_mode",
        "attachment_paths_json",
        "text_sent",
        "attachments_sent_count",
        "failure_code",
        "created_at",
        "updated_at",
        "replied_at",
    }
    serialized = repr(row).lower()
    assert "access_token" not in serialized
    assert "user_text" not in serialized


def test_voice_reply_mode_is_persisted_for_retry(tmp_path) -> None:
    db_path = str(tmp_path / "state.db")
    _reserve(db_path)

    store_matrix_event_reply(
        "$event-1",
        "Φωνητική απάντηση",
        reply_mode="voice",
        db_path=db_path,
    )

    assert list_pending_matrix_replies(db_path=db_path)[0]["reply_mode"] == "voice"


def test_unknown_reply_mode_is_rejected(tmp_path) -> None:
    db_path = str(tmp_path / "state.db")
    _reserve(db_path)

    with pytest.raises(ValueError, match="reply_mode"):
        store_matrix_event_reply(
            "$event-1",
            "Απάντηση",
            reply_mode="video",
            db_path=db_path,
        )


def test_attachment_delivery_progress_is_durable_and_ordered(tmp_path) -> None:
    db_path = str(tmp_path / "state.db")
    _reserve(db_path)
    store_matrix_event_reply(
        "$event-1",
        "Έτοιμα",
        attachment_paths=("C:/outputs/one.pdf", "C:/outputs/two.png"),
        db_path=db_path,
    )

    mark_matrix_reply_text_sent("$event-1", db_path=db_path)
    mark_matrix_attachment_sent("$event-1", expected_index=0, db_path=db_path)

    pending = list_pending_matrix_replies(db_path=db_path)[0]
    assert pending["text_sent"] == 1
    assert pending["attachments_sent_count"] == 1
    assert pending["attachment_paths"] == (
        "C:/outputs/one.pdf",
        "C:/outputs/two.png",
    )
    with pytest.raises(MatrixEventStateError, match="order"):
        mark_matrix_attachment_sent("$event-1", expected_index=0, db_path=db_path)

    with pytest.raises(MatrixEventStateError, match="delivery stages"):
        mark_matrix_event_replied("$event-1", db_path=db_path)
