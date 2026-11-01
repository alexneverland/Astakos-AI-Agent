"""Shared-history freshness checks using real isolated conversation storage."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from memory.conversation_history import append_message

NOW = datetime(2026, 10, 7, 23, 59, tzinfo=ZoneInfo("Europe/Athens"))


def save(path, channel="web", *, role="user", content="done", metadata=None):
    """Persist a uniquely identified temporary message through the normal API."""
    from uuid import uuid4
    return append_message(role=role, content=content, channel=channel,
                          metadata=metadata, timestamp=NOW, message_id=str(uuid4()),
                          db_path=str(path))


def guard(path, rowid, *, clock=lambda: NOW, correlation=lambda: True):
    """Build the inactive adapter guard with explicit correlation ownership."""
    from services.routine_feedback_turn import make_feedback_freshness
    return make_feedback_freshness(user_rowid=rowid, db_path=str(path), now=NOW,
                                  clock=clock, correlation_is_current=correlation)


@pytest.mark.parametrize("channel", ["web", "telegram", "matrix"])
def test_new_owner_message_from_any_channel_invalidates_turn(tmp_path, channel):
    path = tmp_path / "conversation.db"
    first = save(path)
    fresh = guard(path, first["rowid"])
    assert fresh()
    for index in range(60):
        save(path, role="assistant", content=f"notification {index}")
    assert fresh()
    save(path, channel, content="actually skip it")
    assert not fresh()


def test_external_rows_are_not_trusted_owner_feedback(tmp_path):
    path = tmp_path / "conversation.db"
    first = save(path)
    fresh = guard(path, first["rowid"])
    for index in range(60):
        save(path, "matrix", content=f"upload {index}",
             metadata={"untrusted_external_tool_names": ["user_provided_asset"]})
    assert fresh()
    assert not guard(path, save(path, "matrix", content="external",
                     metadata={"untrusted_external_tool_names": ["user_provided_asset"]})["rowid"])()


def test_insertion_order_not_client_clock_decides_freshness(tmp_path):
    path = tmp_path / "conversation.db"
    first = save(path)
    fresh = guard(path, first["rowid"])
    append_message(role="user", content="new but clock is behind", channel="telegram",
                   timestamp=NOW - timedelta(days=1), db_path=str(path))
    assert not fresh()


def test_day_rollover_and_changed_question_reject_old_answer(tmp_path):
    path = tmp_path / "conversation.db"
    first = save(path)
    assert not guard(path, first["rowid"], clock=lambda: NOW + timedelta(minutes=2))()
    current = [True]
    fresh = guard(path, first["rowid"], correlation=lambda: current[0])
    assert fresh()
    current[0] = False
    assert not fresh()


@pytest.mark.parametrize("rowid", [0, -1, True, "1", None])
def test_missing_persisted_owner_identity_fails_closed(tmp_path, rowid):
    assert not guard(tmp_path / "conversation.db", rowid)()


def test_storage_error_fails_closed(tmp_path, monkeypatch):
    import memory.conversation_history as history
    path = tmp_path / "conversation.db"
    first = save(path)
    fresh = guard(path, first["rowid"])
    def fail(**kwargs):
        raise OSError("unavailable")
    monkeypatch.setattr(history, "get_latest_trusted_user_rowid", fail)
    assert not fresh()
