"""Native-store regressions for PR263 review findings and queued identities."""

import json
from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace
from typing import Iterator
from pathlib import Path

import pytest

from tests.test_shift_family_availability import isolated_shift, _shift, TUESDAY
from memory import routine_db
from services import context_extractor as extractor

pytestmark = pytest.mark.usefixtures("offline_behavioral_io")


def test_custom_history_path_reaches_live_schedule(
    isolated_shift: tuple, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The extractor's explicit path must reach reconciliation and its guard."""
    import config

    model, history, path = isolated_shift
    other_path = str(tmp_path / "other-history.db")
    history.init_db(other_path)
    monkeypatch.setattr(config, "CONVERSATION_DB_FILE", other_path)
    text = "Από εβδομάδα είμαι πρωινός στη δουλειά."
    history.append_message(role="user", channel="matrix", content=text,
                           timestamp=TUESDAY, db_path=path)
    monkeypatch.setattr(extractor, "_recent_user_context_hint", lambda channel: "")
    monkeypatch.setattr(extractor, "safe_gemini_call", lambda prompt: SimpleNamespace(
        text='{"flags": {}, "event_rowid": null, "support_rowids": []}'))
    model.invoke = lambda messages: SimpleNamespace(content=json.dumps([_shift()]))
    extractor.extract_and_update_context_flags(text, channel="matrix",
        conversation_db_path=path, now=TUESDAY+timedelta(seconds=30))
    assert routine_db.get_context_state("current_shift")["value"] == "morning"
    assert history.load_messages(db_path=other_path) == []


@pytest.mark.parametrize("superseded", [False, True])
def test_queued_source_considers_later_reports_without_borrowing_identity(
    isolated_shift: tuple, superseded: bool,
) -> None:
    """An unrelated later message must not lose the source; a correction wins."""
    model, history, path = isolated_shift
    text = "Αυτή την εβδομάδα δουλεύω πρωινή βάρδια."
    event = history.append_message(role="user", channel="matrix", content=text,
                                   timestamp=TUESDAY, db_path=path)
    later = "Διόρθωση, τελικά είμαι νυχτερινός." if superseded else "Ευχαριστώ φίλε."
    history.append_message(role="user", channel="web", content=later,
                           timestamp=TUESDAY+timedelta(seconds=2), db_path=path)
    invoked = []

    def reply(messages: list) -> SimpleNamespace:
        """Use the bounded semantic reference, keeping actual persistence real."""
        prompt = str(messages[0].content)
        assert text in prompt and later in prompt
        assert "later_owner_reports" in prompt and "source_rowid" in prompt
        invoked.append(True)
        return SimpleNamespace(content=json.dumps([] if superseded else [_shift()]))

    model.invoke = reply
    extractor.reconcile_context_message(text, event["rowid"], path, TUESDAY+timedelta(seconds=30))
    assert invoked == [True]
    stored = routine_db.get_context_state("current_shift")
    if superseded:
        assert stored is None  # No lexical fallback may resurrect the superseded report.
    else:
        assert stored["value"] == "morning"
        assert stored["updated_at"] == TUESDAY.isoformat()


@pytest.mark.parametrize("change_history", [False, True])
def test_non_shift_requests_keep_functionality_under_final_history_guard(
    isolated_shift: tuple, monkeypatch: pytest.MonkeyPatch, change_history: bool,
) -> None:
    """Preserve explicit durable requests without applying stale rule results."""
    model, history, path = isolated_shift
    text = "Το σχολείο δεν θα λειτουργήσει αυτή την εβδομάδα."
    event = history.append_message(role="user", channel="matrix", content=text,
                                   timestamp=TUESDAY, db_path=path)
    directive = {"kind": "context_state_set", "key": "school_open", "value": False,
                 "until_date": "2026-10-30", "reason": "school_break"}
    monkeypatch.setattr(extractor, "infer_routine_reconciliation_directives",
                        lambda *a, **k: [directive])
    native_guard = history.guard_owner_history_version

    @contextmanager
    def guard(marker: int, *, db_path: str) -> Iterator[bool]:
        """Inject a new message after inference, at the final commit boundary."""
        if change_history:
            history.append_message(role="user", channel="matrix", content="Άλλαξε τελικά αυτό.",
                                   timestamp=TUESDAY+timedelta(seconds=3), db_path=path)
        with native_guard(marker, db_path=db_path) as valid:
            yield valid

    monkeypatch.setattr(history, "guard_owner_history_version", guard)
    extractor.reconcile_context_message(text, event["rowid"], path, TUESDAY+timedelta(seconds=30))
    stored = routine_db.get_context_state("school_open")
    assert stored is None if change_history else stored["value"] == "false"


def test_queued_identity_cannot_point_to_another_report(isolated_shift: tuple) -> None:
    """Exact row identity must agree with both the text and trusted provenance."""
    model, history, path = isolated_shift
    event = history.append_message(role="user", channel="matrix", content="Άλλο μήνυμα.",
                                   timestamp=TUESDAY, db_path=path)

    def forbidden(messages: list) -> SimpleNamespace:
        pytest.fail("A mismatched queued identity reached the model")

    model.invoke = forbidden
    extractor.reconcile_context_message("Πρωινός αυτή την εβδομάδα.", event["rowid"], path,
                                        TUESDAY+timedelta(seconds=30))
    assert routine_db.get_context_state("current_shift") is None
