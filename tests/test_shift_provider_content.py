"""Provider content shapes must not lose the semantic work-shift endpoint."""
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from tests.test_shift_family_availability import isolated_shift, _shift, ATHENS
from memory import routine_db
from services import context_extractor as extractor
from services.routine_context import resolve_current_shift

WEDNESDAY = datetime(2026, 10, 28, 11, 4, 10, tzinfo=ATHENS)
WEEKLY = "και βαρδια σου εχω πει αυτη την εβδομαδα ειμαι πρωινοσ ακομα δνε το εχεισ σημειωσει"


@pytest.mark.usefixtures("offline_behavioral_io")
@pytest.mark.parametrize("shape", ["string", "text_blocks", "split_blocks", "thinking_and_text"])
@pytest.mark.parametrize("scope", ["week", "day"])
def test_full_shift_extraction_preserves_provider_schedule(
    isolated_shift: tuple, monkeypatch: pytest.MonkeyPatch, shape: str, scope: str,
) -> None:
    """Exercise actual parsing, scoring, ordinary daily write and guarded repair."""
    model, history, path = isolated_shift
    text = WEEKLY if scope == "week" else "Σήμερα μόνο δουλεύω πρωινή βάρδια."
    until = "2026-10-30" if scope == "week" else "2026-10-28"
    routine_db.set_context_states_if_unchanged(
        {"current_shift": ("morning", "2026-10-27")}, {"current_shift": None},
        recorded_at=WEDNESDAY-timedelta(days=1))
    event = history.append_message(role="user", content=text, channel="web",
                                   timestamp=WEDNESDAY, db_path=path)
    envelope = {"flags": {"current_shift": "morning"}, "event_rowid": event["rowid"],
                "support_rowids": [event["rowid"]]}
    monkeypatch.setattr(extractor, "_recent_user_context_hint", lambda channel: "")
    monkeypatch.setattr(extractor, "safe_gemini_call",
                        lambda prompt: SimpleNamespace(text=json.dumps(envelope)))
    payload = json.dumps([_shift(until)])
    raw = payload
    if shape == "text_blocks":
        raw = [{"type": "text", "text": payload, "extras": {"signature": "opaque-provider-metadata"}}]
    elif shape == "split_blocks":
        raw = [{"type": "text", "text": "["}, {"type": "text", "text": payload[1:]}]
    elif shape == "thinking_and_text":
        raw = [{"type": "thinking", "thinking": json.dumps([_shift("2026-10-28", "night")])},
               {"type": "text", "text": payload}]
    calls = []

    def reply(messages: list) -> SimpleNamespace:
        """Inspect source identity and return a provider-shaped schedule response."""
        assert text in messages[0].content
        assert "source_at" in messages[0].content
        calls.append(True)
        return SimpleNamespace(content=raw)

    model.invoke = reply
    extractor.extract_and_update_context_flags(text, channel="web", conversation_db_path=path,
                                              now=WEDNESDAY+timedelta(seconds=30))
    stored = routine_db.get_context_state("current_shift")
    assert calls == [True]
    assert stored["value"] == "morning" and stored["expires_at"] == until
    assert datetime.fromisoformat(stored["updated_at"]) == WEDNESDAY
    assert resolve_current_shift(datetime(2026, 10, 30, 23, 59, tzinfo=ATHENS)) == (
        "morning" if scope == "week" else None)
    # Existing weekend fallback is off; the weekly morning flag has expired.
    assert resolve_current_shift(datetime(2026, 10, 31, 0, 0, tzinfo=ATHENS)) == "off"
    assert resolve_current_shift(datetime(2026, 11, 2, 9, 0, tzinfo=ATHENS)) is None


@pytest.mark.usefixtures("offline_behavioral_io")
@pytest.mark.parametrize("content", [
    [], [{"type": "thinking", "thinking": "[]"}],
    [{"type": "tool_call", "name": "set_context_state", "args": {"current_shift": "night"}}],
    [{"type": "text", "text": "not JSON"}],
    [{"type": "text", "text": json.dumps([_shift("not-a-date", "night")])}],
])
def test_invalid_provider_content_cannot_replace_known_schedule(isolated_shift: tuple, content: object) -> None:
    """Non-answer metadata, malformed output and invalid dates confer no write."""
    model, history, path = isolated_shift
    routine_db.set_context_states_if_unchanged(
        {"current_shift": ("morning", "2026-10-30")}, {"current_shift": None},
        recorded_at=WEDNESDAY-timedelta(hours=1))
    before = routine_db.get_context_state("current_shift")
    saved = history.append_message(role="user", content="Δεν έχω επιβεβαιώσει αλλαγή.", channel="matrix",
                                   timestamp=WEDNESDAY, db_path=path)
    model.invoke = lambda messages: SimpleNamespace(content=content)
    extractor.reconcile_context_message(saved["content"], saved["rowid"], path,
                                        WEDNESDAY+timedelta(seconds=30))
    assert routine_db.get_context_state("current_shift") == before
