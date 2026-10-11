"""Fixed-clock integration tests; only model and transport are synthetic."""
from datetime import datetime, timedelta
import pytest

pytestmark = pytest.mark.usefixtures("offline_behavioral_io")

from memory.behavioral_conversation_preferences import PreferenceStore
from memory.behavioral_initiative_state import InitiativeStore
from memory.conversation_history import append_message, load_messages
from services.behavioral_conversation_evidence import build_behavioral_evidence
from services.external_delivery import DeliveryReceipt
from services.behavioral_conversation_initiative import run_initiative


NOW = datetime(2026, 10, 2, 12)


def setup(tmp_path, channel="matrix"):
    """Use real temporary storage with qualifying cross-channel observations."""
    db = str(tmp_path / "history.db")
    append_message(role="user", content="Καλημέρα", channel="web", db_path=db,
                   timestamp=NOW - timedelta(minutes=20))
    events = [dict(event_type="drink", category="food", subject="user", item="beer",
                   action_kind="consume", status="consumed", record_state="confirmed",
                   event_date=f"2026-09-{day}", confidence=.95, negated=0, hypothetical=0,
                   reported_by_user=1, source_message_id=str(day), source_rowid=day,
                   source_channel=source) for day, source in [(24, "web"), (25, "matrix"), (26, "telegram")]]
    sent = []
    def send(target, text, identity):
        sent.append((target, text, identity))
        return DeliveryReceipt(target, "$confirmed")
    kwargs = dict(store=InitiativeStore(tmp_path / "state.json"),
                  preferences=PreferenceStore(tmp_path / "prefs.json"),
                  history_loader=lambda: load_messages(db_path=db),
                  evidence_loader=lambda **kw: build_behavioral_evidence(events, **kw),
                  classify=lambda payload: dict(selected_index=0, blocked=False,
                                                recently_discussed=False, message="Πώς σου φαίνεται να το χαλαρώσεις λίγο;"),
                  sender=send, record=lambda **kw: append_message(db_path=db, **kw),
                  clock=lambda: NOW, selected_channel=lambda: channel,
                  unavailable=lambda: False, budget=lambda: True,
                  current_context=lambda: {})
    return kwargs, sent, db


@pytest.mark.parametrize("channel", ["matrix", "telegram"])
def test_one_opener_once_across_restart_and_visible_in_shared_history(tmp_path, channel):
    kw, sent, db = setup(tmp_path, channel)
    assert run_initiative(**kw) == "delivered"
    kw["store"] = InitiativeStore(kw["store"].path)
    assert run_initiative(**kw) == "skip"
    assert len(sent) == 1
    rows = load_messages(db_path=db)
    assert len(rows) == 2
    assert rows[-1]["agent"] == "Behavioral_Agent"
    assert rows[-1]["channel"] == channel
    assert kw["store"].load()["pending"] is None


@pytest.mark.parametrize("role", ["user", "assistant"])
def test_recent_conversation_or_reminder_blocks_before_model(tmp_path, role):
    kw, sent, db = setup(tmp_path)
    append_message(role=role, content="Recent message", channel="telegram", db_path=db,
                   timestamp=NOW - timedelta(minutes=14))
    kw["classify"] = lambda _: pytest.fail("Model must not run while busy")
    assert run_initiative(**kw) == "skip"
    assert not sent


@pytest.mark.parametrize("change", ["history", "preferences", "quiet", "channel"])
def test_changed_context_during_model_cancels_send(tmp_path, change):
    kw, sent, db = setup(tmp_path)
    original = kw["classify"]
    def classify(payload):
        if change == "history":
            append_message(role="user", content="Τώρα μιλάω", channel="web", db_path=db, timestamp=NOW)
        elif change == "preferences":
            kw["preferences"].update([], suppress="No habit comments", allow_ids=[])
        elif change == "quiet":
            kw["unavailable"] = lambda: True
        else:
            kw["selected_channel"] = lambda: "telegram"
        return original(payload)
    # Mutating functions in kw cannot change already bound call arguments.
    flag = {"blocked": False, "channel": "matrix"}
    kw["unavailable"] = lambda: flag["blocked"]
    kw["selected_channel"] = lambda: flag["channel"]
    def decision(payload):
        result = classify(payload)
        flag["blocked"] = change == "quiet"
        flag["channel"] = "telegram" if change == "channel" else "matrix"
        return result
    kw["classify"] = decision
    assert run_initiative(**kw) == "skip"
    assert not sent


def test_same_topic_seven_days_and_daily_cap(tmp_path):
    kw, sent, db = setup(tmp_path)
    assert run_initiative(**kw) == "delivered"
    kw["clock"] = lambda: NOW + timedelta(days=6)
    assert run_initiative(**kw) == "skip"
    kw["clock"] = lambda: NOW + timedelta(days=7)
    assert run_initiative(**kw) == "delivered"
    assert len(sent) == 2


@pytest.mark.parametrize("channel", ["matrix", "telegram"])
def test_ambiguous_delivery_uses_matrix_identity_but_never_retries_telegram(tmp_path, channel):
    kw, sent, db = setup(tmp_path, channel)
    successful = kw["sender"]
    attempts = []
    def failed(target, text, identity):
        attempts.append(identity)
        raise OSError("Transport lost acknowledgement")
    kw["sender"] = failed
    assert run_initiative(**kw) == "held"
    assert kw["store"].load()["delivered"] == []
    kw["sender"] = successful
    result = run_initiative(**kw)
    assert result == ("delivered" if channel == "matrix" else "held")
    if channel == "matrix":
        assert sent[0][2] == attempts[0]
    else:
        assert not sent


def test_history_failure_retries_only_local_record_once(tmp_path):
    kw, sent, db = setup(tmp_path)
    original = kw["record"]
    def crash_after_record(**fields):
        original(**fields)
        raise OSError("Crash after history commit")
    kw["record"] = crash_after_record
    assert run_initiative(**kw) == "held"
    kw["record"] = original
    assert run_initiative(**kw) == "delivered"
    assert len(sent) == 1
    assert len(load_messages(db_path=db)) == 2


def test_opt_out_and_invalid_model_do_not_send(tmp_path):
    kw, sent, _ = setup(tmp_path)
    kw["preferences"].update([], suppress="No beer commentary", allow_ids=[])
    def decision(payload):
        assert payload["preferences"][0]["scope"] == "No beer commentary"
        return dict(selected_index=0, blocked=True, recently_discussed=False, message="skip")
    kw["classify"] = decision
    assert run_initiative(**kw) == "skip"
    kw["classify"] = lambda _: {"selected_index": True}
    assert run_initiative(**kw) == "skip"
    assert not sent


def test_unchanged_skipped_context_does_not_spend_model_calls_each_poll(tmp_path):
    kw, sent, _ = setup(tmp_path)
    calls = []
    def skip(payload):
        calls.append(payload)
        return dict(selected_index=None, blocked=False, recently_discussed=False, message="")
    kw["classify"] = skip
    assert run_initiative(**kw) == "skip"
    assert run_initiative(**kw) == "skip"
    assert len(calls) == 1
    assert not sent


def test_completed_background_intake_reopens_skipped_evaluation(tmp_path):
    """A new qualifying packet matters even if the shared history is unchanged."""
    kw, sent, db = setup(tmp_path)
    load = kw["evidence_loader"]
    packets = load(today=NOW.date(), window_days=30)
    kw["evidence_loader"] = lambda **options: packets
    calls = []
    def decide(payload):
        calls.append(payload)
        return dict(selected_index=0 if len(calls) > 1 else None, blocked=False,
                    recently_discussed=False, message="Χαίρομαι που βρίσκεις χρόνο για αυτά.")
    kw["classify"] = decide
    assert run_initiative(**kw) == "skip"
    packets[0] = dict(packets[0], occurrence_count=4, distinct_date_count=4,
                      event_dates=packets[0]["event_dates"] + ["2026-10-01"])
    kw["store"] = InitiativeStore(kw["store"].path)
    assert run_initiative(**kw) == "delivered"
    assert len(calls) == 2 and len(sent) == 1
    assert load_messages(db_path=db)[-1]["agent"] == "Behavioral_Agent"


def test_lower_ranked_qualifying_topic_can_open_a_conversation(tmp_path):
    """Strong generic repetitions must not hide every lower-ranked topic."""
    from tests.test_behavioral_conversation_evidence import event
    from memory.behavioral_event_state import record_event
    from services.behavioral_conversation_evidence import load_behavioral_evidence
    kw, sent, db = setup(tmp_path)
    rows = [event(day, item=f"entity {i}", source_message_id=f"{i}:{day}")
            for i in range(6) for day in range(20, 27-i//2)]
    observations = str(tmp_path / "observations.db")
    for row in rows:
        record_event(dict(row, negated=False, hypothetical=False, reported_by_user=True), db_path=observations)
    kw["evidence_loader"] = lambda **options: load_behavioral_evidence(db_path=observations, **options)
    def choose(payload):
        evidence = payload["evidence"]
        selected = next((i for i, p in enumerate(evidence) if p["item"] == "entity 5"), None)
        return dict(selected_index=selected, blocked=False, recently_discussed=False,
                    message="Πώς πάει αυτή η ασχολία σου;" if selected is not None else "")
    kw["classify"] = choose
    assert run_initiative(**kw) == "delivered"
    assert len(sent) == 1
    assert load_messages(db_path=db)[-1]["agent"] == "Behavioral_Agent"


def test_pending_retry_does_not_ignore_changed_family_context(tmp_path):
    kw, sent, _ = setup(tmp_path)
    kw["sender"] = lambda *args: (_ for _ in ()).throw(OSError())
    assert run_initiative(**kw) == "held"
    kw["current_context"] = lambda: {"quiet_hours": True}
    kw["sender"] = lambda *args: pytest.fail("Stale pending context must not send")
    assert run_initiative(**kw) == "held"
    assert not sent


@pytest.mark.parametrize("condition", ["quiet", "budget", "provider", "missing_history", "corrupt_preferences"])
def test_unavailable_conditions_never_send(tmp_path, condition):
    kw, sent, _ = setup(tmp_path)
    if condition == "quiet":
        kw["unavailable"] = lambda: True
    elif condition == "budget":
        kw["budget"] = lambda: False
    elif condition == "provider":
        kw["classify"] = lambda _: (_ for _ in ()).throw(RuntimeError("Provider unavailable"))
    elif condition == "missing_history":
        kw["history_loader"] = lambda: []
    else:
        kw["preferences"].path.write_text("broken")
    assert run_initiative(**kw) in {"skip", "held"}
    assert not sent
    assert kw["store"].load()["pending"] is None


def test_lost_receipt_persistence_retries_same_matrix_transaction(tmp_path, monkeypatch):
    kw, sent, _ = setup(tmp_path)
    original = kw["store"].save
    def fail_after_delivery(state):
        if state["pending"] and state["pending"]["external_id"]:
            raise OSError("Cannot persist acknowledgement")
        original(state)
    monkeypatch.setattr(kw["store"], "save", fail_after_delivery)
    assert run_initiative(**kw) == "held"
    assert kw["store"].load()["pending"]["external_id"] is None
    monkeypatch.setattr(kw["store"], "save", original)
    assert run_initiative(**kw) == "delivered"
    # A real Matrix homeserver treats the repeated transaction as the same event.
    assert sent[0][2] == sent[1][2]


def test_different_topic_cannot_bypass_daily_cap(tmp_path):
    kw, sent, _ = setup(tmp_path)
    assert run_initiative(**kw) == "delivered"
    kw["clock"] = lambda: NOW + timedelta(minutes=16)
    kw["evidence_loader"] = lambda **kw: pytest.fail("Daily cap must precede selecting another topic")
    assert run_initiative(**kw) == "skip"
    assert len(sent) == 1


def test_cross_process_lock_excludes_second_sender(tmp_path):
    from filelock import FileLock
    kw, sent, _ = setup(tmp_path)
    with FileLock(str(kw["store"].path) + ".lock"):
        assert run_initiative(**kw) == "held"
    assert not sent


def test_diagnostics_preserve_model_decline_across_cached_polls(tmp_path):
    kw, sent, _ = setup(tmp_path)
    kw["classify"] = lambda _: dict(selected_index=None, blocked=False,
                                   recently_discussed=False, message="")
    assert run_initiative(**kw) == "skip"
    assert run_initiative(**kw) == "skip"
    diagnostic = kw["store"].load_diagnostics()
    assert diagnostic["last_check"]["reason"] == "already_evaluated"
    assert diagnostic["last_decision"]["reason"] == "model_no_topic"
    assert diagnostic["last_decision"]["candidate_count"] == 1
    assert not sent


@pytest.mark.parametrize("condition,reason", [
    ("quiet", "quiet_hours"), ("model", "model_error"),
    ("transport", "delivery_error"), ("invalid", "invalid_model_decision"),
])
def test_diagnostic_reason_is_safe_and_does_not_change_delivery(tmp_path, condition, reason):
    kw, sent, _ = setup(tmp_path)
    if condition == "quiet":
        kw["unavailable"] = lambda: "quiet_hours"
    elif condition == "model":
        kw["classify"] = lambda _: (_ for _ in ()).throw(RuntimeError("SECRET_PRIVATE_TEXT"))
    elif condition == "transport":
        kw["sender"] = lambda *args: (_ for _ in ()).throw(OSError("SECRET_PRIVATE_TEXT"))
    else:
        kw["classify"] = lambda _: {"message": "SECRET_PRIVATE_TEXT"}
    assert run_initiative(**kw) in {"skip", "held"}
    diagnostic = kw["store"].load_diagnostics()
    assert diagnostic["last_check"]["reason"] == reason
    assert "SECRET_PRIVATE_TEXT" not in str(diagnostic)
    assert not sent


def test_diagnostics_failure_cannot_prevent_or_repeat_delivery(tmp_path, monkeypatch):
    kw, sent, _ = setup(tmp_path)
    monkeypatch.setattr(kw["store"], "record_diagnostic", lambda _: (_ for _ in ()).throw(OSError()))
    assert run_initiative(**kw) == "delivered"
    assert run_initiative(**kw) == "skip"
    assert len(sent) == 1


@pytest.mark.parametrize("minutes,result", [(20, "delivered"), (14, "skip"), (-1, "skip")])
@pytest.mark.parametrize("offset_hours", [0, 3])
def test_offset_history_is_compared_to_legacy_local_clock(tmp_path, minutes, result, offset_hours):
    """A context question with an offset must not disable initiative gates."""
    from datetime import timezone
    kw, sent, db = setup(tmp_path)
    append_message(role="assistant", content="Home?", channel="matrix", db_path=db,
                   agent="Routine_Context",
                   timestamp=(NOW - timedelta(minutes=minutes)).astimezone(
                       timezone(timedelta(hours=offset_hours))))
    if result == "skip":
        kw["classify"] = lambda _: pytest.fail("Recent/future history must block the model")
    assert run_initiative(**kw) == result
    assert len(sent) == (result == "delivered")
    assert kw["store"].load_diagnostics()["last_check"].get("error_type") is None


def test_offset_delivery_receipt_preserves_daily_and_topic_limits(tmp_path):
    """Persisted offset receipts retain the existing daily/seven-day policy."""
    from datetime import timezone
    kw, sent, _ = setup(tmp_path)
    assert run_initiative(**kw) == "delivered"
    state = kw["store"].load()
    state["delivered"][0]["delivered_at"] = NOW.astimezone(timezone.utc).isoformat()
    kw["store"].save(state)
    kw["clock"] = lambda: NOW + timedelta(minutes=20)
    assert run_initiative(**kw) == "skip"
    kw["clock"] = lambda: NOW + timedelta(days=6)
    assert run_initiative(**kw) == "skip"
    kw["clock"] = lambda: NOW + timedelta(days=7)
    assert run_initiative(**kw) == "delivered"
    assert len(sent) == 2
