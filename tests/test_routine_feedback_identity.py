"""Offline identity evidence regressions with real temporary ledger writes."""
import json
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from tests.test_routine_feedback_store import store


@pytest.mark.parametrize("channel", ["web", "matrix", "telegram"])
@pytest.mark.parametrize("scenario", ["departure", "preparation", "explicit_other", "ambiguous", "race", "new_candidate"])
def test_shift_departure_identity_uses_recorded_engagement(store, tmp_path, monkeypatch, scenario, channel):
    """Inspect the real model input and verify both final dated outcomes."""
    from memory.conversation_history import append_message
    from services.routine_completion_selector import select_dated_routine
    from services.routine_feedback_turn import process_catalog_feedback_turn

    tz = ZoneInfo("Europe/Athens")
    now = datetime(2026, 10, 9, 10, 4, 25, tzinfo=tz)
    delivered = now.replace(hour=9, minute=31, second=6)
    acknowledged = delivered.replace(second=40)
    with store.connection_factory() as connection:
        connection.execute("UPDATE routines SET event_name=? WHERE id=11",
                           ("Αναχώρηση για δουλειά (Απογευματινή Βάρδια)",))
        connection.execute("INSERT INTO routines(id,event_name) VALUES(6,?)",
                           ("Αναχώρηση για δουλειά (Πρωινή Βάρδια)",))
        connection.execute("ALTER TABLE routines ADD COLUMN conditions_json TEXT")
        connection.execute("UPDATE routines SET conditions_json=? WHERE id=11",
                           ('[{"type":"current_shift","value":"afternoon"}]',))
    store.record_delivery(11, now.date(), at=delivered, receipt_id="afternoon-reminder",
                          channel="matrix", question="Ώρα για αναχώρηση για τη βάρδια!")
    store.record_feedback(11, now.date(), "acknowledge", at=acknowledged)
    texts = {
        "departure": "Έφυγα, φίλε, πάω να πάρω το λεωφορείο. Μια συννεφιά την έχει λίγο σήμερα, ε?",
        "preparation": "ναι φιλε σιγα σιγα ετοιμαζομαι",
        "explicit_other": "Σήμερα έφυγα και για την πρωινή βάρδια, εκείνη εννοώ",
        "ambiguous": "Το έκανα τελικά",
        "race": "Έφυγα, φίλε, πάω να πάρω το λεωφορείο",
        "new_candidate": "Έφυγα, φίλε, πάω να πάρω το λεωφορείο",
    }
    path = str(tmp_path / "history.db")
    saved = append_message(role="user", content=texts[scenario], channel=channel,
                           timestamp=now, db_path=path)

    def provider(prompt):
        """Return scenario output only after checking authoritative evidence delivery."""
        assert "A recorded acknowledgement can connect" in prompt
        assert "If competing\nidentities remain plausible, clarify" in prompt
        payload = json.loads(prompt.split("INPUT:\n", 1)[1].split("\n\nChoose", 1)[0])
        candidates = {item["routine_id"]: item for item in payload["candidates"]}
        evidence = candidates[11]["identity_evidence"]
        assert evidence["routine"]["conditions_json"] == '[{"type":"current_shift","value":"afternoon"}]'
        occurrence = evidence["occurrences"][0]
        assert occurrence["delivered_at"] == delivered.isoformat()
        assert occurrence["feedback"] == "acknowledge"
        assert occurrence["feedback_at"] == acknowledged.isoformat()
        assert occurrence["question_text"] == "Ώρα για αναχώρηση για τη βάρδια!"
        assert candidates[6]["identity_evidence"]["occurrences"] == []
        assert payload["pending_question"] is None  # Expired, but still identity evidence.
        engaged = [rid for rid, candidate in candidates.items()
                   if any(row["occurrence_date"] == now.date().isoformat()
                          and row["delivered_at"] is not None
                          and row["feedback"] == "acknowledge"
                          for row in candidate["identity_evidence"]["occurrences"])]
        assert len(engaged) == 1
        if scenario == "race":
            store.record_feedback(6, now.date(), "acknowledge", at=now)
        if scenario == "new_candidate":
            with store.connection_factory() as connection:
                connection.execute("INSERT INTO routines(id,event_name) VALUES(12,?)",
                                   ("Αναχώρηση για άλλη δουλειά",))
        action = "clarify" if scenario == "ambiguous" else (
            "acknowledge" if scenario == "preparation" else "complete")
        rid = (None if scenario == "ambiguous" else
               next(rid for rid in candidates if rid not in engaged)
               if scenario == "explicit_other" else engaged[0])
        return SimpleNamespace(text=json.dumps({"action": action, "routine_id": rid,
            "occurrence_date": None if action == "clarify" else now.date().isoformat()}))

    monkeypatch.setattr("services.routine_completion_selector.safe_gemini_call", provider)
    monkeypatch.setattr("socket.socket.connect", lambda *a, **k: pytest.fail("outbound call"))
    result = process_catalog_feedback_turn(texts[scenario], store=store,
        selector=select_dated_routine, now=now, clock=lambda: now, trusted=True,
        user_rowid=saved["rowid"], conversation_db_path=path)
    assert result.status == ("stale" if scenario in ("race", "new_candidate") else
                             "clarify" if scenario == "ambiguous" else "applied")
    afternoon = store.occurrences(11)[0]
    assert afternoon.delivered_at == delivered
    assert afternoon.feedback == ("complete" if scenario == "departure" else "acknowledge")
    morning = store.occurrences(6)
    if scenario in ("explicit_other", "race"):
        assert morning[0].feedback == ("complete" if scenario == "explicit_other" else "acknowledge")
        assert morning[0].delivered_at is None
    else:
        assert morning == []


def test_previous_selector_keyword_contract_remains_supported(store, tmp_path) -> None:
    """A fixed-signature offline consumer can still commit canonical feedback."""
    from memory.conversation_history import append_message
    from services.routine_completion_helper import DatedRoutineSelection
    from services.routine_feedback_turn import process_catalog_feedback_turn
    now = datetime(2026, 10, 9, 10, tzinfo=ZoneInfo("Europe/Athens"))
    path = str(tmp_path / "history.db")
    text = "Το ολοκλήρωσα σήμερα"
    saved = append_message(role="user", channel="web", content=text, timestamp=now, db_path=path)

    def selector(user_text, candidates, dates, *, now, trusted, pending_question):
        """Use the supported pre-evidence signature without accepting extra keywords."""
        return DatedRoutineSelection("complete", 11, now.date())

    result = process_catalog_feedback_turn(text, store=store, selector=selector,
        now=now, clock=lambda: now, trusted=True, user_rowid=saved["rowid"],
        conversation_db_path=path)
    assert result.status == "applied"
    assert store.occurrences(11)[0].feedback == "complete"
