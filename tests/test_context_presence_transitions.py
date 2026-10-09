"""Source-grounded presence transitions use isolated stores and no live providers."""

from datetime import datetime, timedelta
import json
import socket
from types import SimpleNamespace

import pytest

from services.routine_feedback import ATHENS

EVENT_AT = datetime(2026, 10, 9, 10, 4, 25, tzinfo=ATHENS)
SHARED_TEXT = "γυρισα η σοφια δεν δουλευει σημερα καθομαστε και ταχτοποιουμε τα παιχνιδια να πεταξουμε και να δωσουμε μερικα"
DEPARTURE = "Έφυγα, φίλε, πάω να πάρω το λεωφορείο. Μια συννεφιά την έχει λίγο σήμερα, ε?"
CONDITION = {"condition_type": "context_flag", "condition_mode": "suppress_when_true",
             "condition_payload": {"flag": "partner_with_user", "equals": True}}


@pytest.fixture
def transition_store(tmp_path, monkeypatch) -> tuple:
    """Persist the reported shared activity, then isolate all external boundaries."""
    from memory import conversation_history as history, routine_db as db
    from services import context_extractor as extractor

    def deny_network(*args, **kwargs) -> None:
        pytest.fail("Presence regression attempted an outbound connection")

    monkeypatch.setattr(socket.socket, "connect", deny_network)
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "routines.db"))
    db.setup_db()
    path = str(tmp_path / "history.db")
    shared_at = EVENT_AT.replace(hour=8, minute=59, second=41)
    shared = history.append_message(role="user", channel="web", content=SHARED_TEXT,
                                    timestamp=shared_at, db_path=path)
    db.set_context_states_if_unchanged(
        {"partner_with_user": ("true", "2026-10-09"),
         "user_out_of_home": ("false", "2026-10-09"),
         "user_at_work": ("false", "2026-10-09")},
        {"partner_with_user": None, "user_out_of_home": None, "user_at_work": None},
        recorded_at=shared_at,
    )
    history.append_message(role="user", channel="web", content="ναι φιλε σιγα σιγα ετοιμαζομαι",
                           timestamp=EVENT_AT.replace(hour=9, minute=31, second=40), db_path=path)
    monkeypatch.setattr(extractor, "reconcile_context_message", lambda _: None)
    monkeypatch.setattr(extractor, "load_recent_state_messages",
                        lambda **_: history.load_daily_state_messages(now=EVENT_AT, db_path=path))
    return history, db, extractor, path, shared


@pytest.mark.parametrize("channel", ["web", "matrix", "telegram"])
@pytest.mark.parametrize("together", [False, True])
def test_completed_departure_updates_persisted_presence_and_routine_condition(
    transition_store, monkeypatch, channel, together,
) -> None:
    """Verified model decisions must reach the final stored routine gate."""
    from services.routine_conditions import evaluate_routine_conditions
    history, db, extractor, path, shared = transition_store
    text = "Φύγαμε με τη Σοφία, πάμε να πάρουμε το λεωφορείο." if together else DEPARTURE
    event = history.append_message(role="user", channel=channel, content=text,
                                   timestamp=EVENT_AT, db_path=path)

    def model(prompt: str) -> SimpleNamespace:
        assert SHARED_TEXT in prompt and text in prompt
        assert "2026-10-09T08:59:41" in prompt
        return SimpleNamespace(text=json.dumps({
            "flags": {"user_out_of_home": True, "partner_with_user": together,
                      "user_at_work": False},
            "event_rowid": event["rowid"], "support_rowids": [shared["rowid"], event["rowid"]],
        }))

    monkeypatch.setattr(extractor, "safe_gemini_call", model)
    extractor.extract_and_update_context_flags(text, channel=channel,
        now=EVENT_AT + timedelta(seconds=30), conversation_db_path=path)

    presence = db.get_context_state("partner_with_user")
    assert presence["value"] == str(together).lower()
    assert presence["updated_at"] == EVENT_AT.isoformat()
    assert db.get_context_state("user_out_of_home")["value"] == "true"
    assert db.get_context_state("user_at_work")["value"] == "false"
    assert db.get_context_state("partner_work_mode") is None
    assert evaluate_routine_conditions([CONDITION], {"partner_with_user": presence["value"]},
                                       EVENT_AT.replace(hour=10, minute=45))["allowed"] is (not together)


@pytest.mark.parametrize("scenario", ["future", "ambiguous", "bad_source", "older_event",
    "external", "bad_type", "bad_enum", "unknown_flag", "new_history", "new_state", "provider_failure"])
def test_unsupported_transition_cannot_clear_stored_copresence(
    transition_store, monkeypatch, scenario,
) -> None:
    """Incomplete meaning and invalid provenance cannot authorize presence writes."""
    history, db, extractor, path, shared = transition_store
    text = "Σε λίγο θα πάρω το λεωφορείο." if scenario == "future" else DEPARTURE
    event = history.append_message(role="user", channel="matrix", content=text,
        timestamp=EVENT_AT, db_path=path,
        metadata={"untrusted_external_tool_names": ["user_provided_asset"]} if scenario == "external" else {})
    previous = db.get_context_state("partner_with_user")

    def model(prompt: str) -> SimpleNamespace:
        if scenario == "provider_failure":
            raise RuntimeError("injected offline provider failure")
        if scenario == "new_history":
            history.append_message(role="user", channel="web", content="Τελικά πήγαμε μαζί.",
                                   timestamp=EVENT_AT + timedelta(seconds=1), db_path=path)
        if scenario == "new_state":
            db.set_context_states_if_unchanged({"partner_with_user": ("true", "2026-10-09")},
                {"partner_with_user": previous}, recorded_at=EVENT_AT + timedelta(seconds=1))
        flags = {} if scenario in {"future", "ambiguous"} else {
            "partner_with_user": "false" if scenario == "bad_type" else False}
        if scenario == "bad_enum":
            flags["current_shift"] = "late"
        if scenario == "unknown_flag":
            flags["invented_permission"] = True
        return SimpleNamespace(text=json.dumps({
            "flags": flags,
            "event_rowid": 999 if scenario == "bad_source" else
                shared["rowid"] if scenario == "older_event" else event["rowid"],
            "support_rowids": [shared["rowid"], event["rowid"]],
        }))

    monkeypatch.setattr(extractor, "safe_gemini_call", model)
    extractor.extract_and_update_context_flags(text, channel="matrix",
        now=EVENT_AT + timedelta(seconds=30), conversation_db_path=path)
    assert db.get_context_state("partner_with_user")["value"] == "true"
    if scenario != "new_state":
        assert db.get_context_state("partner_with_user") == previous


@pytest.mark.parametrize("text,flags", [
    ("Έφυγα για το λεωφορείο, εκείνοι συνεχίζουν το παιχνίδι στο σπίτι.",
     {"user_out_of_home": True, "family_at_home": False,
      "partner_with_user": False, "kid1_with_user": False, "kid1_with_partner": True}),
    ("Τους συνάντησα στο πάρκο, τώρα παίζουμε όλοι μαζί.",
     {"user_out_of_home": True, "partner_with_user": True, "kid1_with_user": True}),
    ("Τελείωσα τη βάρδια, τώρα είμαστε όλοι σπίτι.",
     {"user_at_work": False, "family_at_home": True, "quiet_hours": False}),
    ("Στη δουλειά είμαι τώρα, έχουν έρθει και οι δυο εδώ μαζί μου.",
     {"user_at_work": True, "partner_with_user": True, "kid1_with_user": True}),
    ("Η Σοφία δουλεύει στο γραφείο της, είμαστε εγώ κι ο μικρός εκεί μαζί της.",
     {"partner_at_work": True, "partner_work_mode": "office",
      "partner_with_user": True, "kid1_with_user": True, "kid1_with_partner": True}),
])
def test_general_transition_persists_all_grounded_related_flags(
    transition_store, monkeypatch, text, flags,
) -> None:
    """Child, household and work consequences share the same schema-driven path."""
    history, db, extractor, path, shared = transition_store
    prior = history.append_message(role="user", channel="web", content="Η Σοφία κι ο Αλέξανδρος είναι σπίτι.",
        timestamp=EVENT_AT - timedelta(minutes=10), db_path=path)
    event = history.append_message(role="user", channel="matrix", content=text,
                                   timestamp=EVENT_AT, db_path=path)
    monkeypatch.setattr(extractor, "safe_gemini_call", lambda _: SimpleNamespace(text=json.dumps({
        "flags": flags, "event_rowid": event["rowid"],
        "support_rowids": [shared["rowid"], prior["rowid"], event["rowid"]],
    })))
    extractor.extract_and_update_context_flags(text, channel="matrix", now=EVENT_AT,
                                               conversation_db_path=path)
    for key, value in flags.items():
        state = db.get_context_state(key)
        assert state["value"] == str(value).lower()
        assert state["updated_at"] == EVENT_AT.isoformat()


@pytest.mark.parametrize("kind,value", [("boolean", False), ("enum", "separate")])
def test_registered_future_flag_uses_same_schema_and_conditional_writer(
    transition_store, monkeypatch, kind, value,
) -> None:
    """A new typed schema entry needs no new interpretation branch or phrase list."""
    history, db, extractor, path, shared = transition_store
    key = "test_additional_relation"
    if kind == "boolean":
        monkeypatch.setattr(extractor, "_CONTEXT_BOOLEAN_FLAGS", extractor._CONTEXT_BOOLEAN_FLAGS | {key})
    else:
        monkeypatch.setattr(extractor, "_CONTEXT_ENUM_VALUES",
                            {**extractor._CONTEXT_ENUM_VALUES, key: {"together", "separate"}})
    text = "Η παρέα χωρίστηκε, ο καθένας συνέχισε τη δική του διαδρομή."
    event = history.append_message(role="user", channel="matrix", content=text,
                                   timestamp=EVENT_AT, db_path=path)

    def model(prompt: str) -> SimpleNamespace:
        assert key in prompt and "state_schema" in prompt
        return SimpleNamespace(text=json.dumps({"flags": {key: value},
            "event_rowid": event["rowid"], "support_rowids": [shared["rowid"], event["rowid"]]}))

    monkeypatch.setattr(extractor, "safe_gemini_call", model)
    extractor.extract_and_update_context_flags(text, channel="matrix", now=EVENT_AT,
                                               conversation_db_path=path)
    assert db.get_context_state(key)["value"] == str(value).lower()


def test_no_state_change_preserves_existing_routine_request_handling(
    transition_store, monkeypatch,
) -> None:
    """The new empty envelope must not consume unrelated durable routine work."""
    history, db, extractor, path, _ = transition_store
    text = "Αύριο άλλαξε την ώρα της ρουτίνας μου."
    history.append_message(role="user", channel="matrix", content=text,
                           timestamp=EVENT_AT, db_path=path)
    previous = db.get_context_state("partner_with_user")
    requests = []
    monkeypatch.setattr(extractor, "reconcile_context_message", requests.append)
    monkeypatch.setattr(extractor, "safe_gemini_call", lambda _: SimpleNamespace(
        text='{"flags": {}, "event_rowid": null, "support_rowids": []}'))
    extractor.extract_and_update_context_flags(text, channel="matrix", now=EVENT_AT,
                                               conversation_db_path=path)
    assert requests == [text]
    assert db.get_context_state("partner_with_user") == previous
