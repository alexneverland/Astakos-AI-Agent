"""Offline regressions for semantic completion and bounded scheduler retries."""
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

import clients.telegram_bot as bot
import memory.pending_followups as pf


@pytest.fixture(autouse=True)
def isolated_followups(tmp_path, monkeypatch, offline_behavioral_io):
    """Keep all persistence and model calls within this offline test case."""
    monkeypatch.setattr(pf, "STATE_DB", str(tmp_path / "followups.db"))
    import services.gemini as gemini
    monkeypatch.setattr(gemini, "safe_gemini_call",
                        lambda *a, **kw: pytest.fail("Unstubbed model call"))


def _stub_updates(monkeypatch, updates):
    """Keep the real batch selector and persistence; stub only cloud inference."""
    calls = []
    def model(prompt, *args, **kwargs):
        calls.append(prompt)
        return SimpleNamespace(text=json.dumps({"updates": updates}, ensure_ascii=False))
    monkeypatch.setattr("services.gemini.safe_gemini_call", model)
    return calls


def create(subject="καφές στον Εύοσμο", *, hours=18):
    """Create a real isolated pending record with the reported evening intent."""
    return pf.create_pending_followup(
        source_channel="matrix", source_agent="Chat_Agent", topic="outing",
        subject=subject, source_user_text=("Φεύγουμε για γάμο στο Μακροχώρι." if "γάμος" in subject
                                         else "Ο μικρός έφυγε με τη μαμά για καφέ και παιχνίδι."),
        source_ai_text="Καλά να περάσουν.", confidence=0.9,
        followup_after_ts=pf._local_now().isoformat(), ttl_hours=hours,
        metadata={"target_window": "same_day_evening", "delay_minutes_raw": 180})


def stored(identity):
    """Read the final persisted outcome through the repository abstraction."""
    return next(row for row in pf.find_pending_followups(active_only=False)
                if row["id"] == identity)


def test_completed_wedding_is_not_deferred_by_evening_in_reason():
    identity = create("γάμος στο Μακροχώρι")
    result = bot._apply_followup_skip_outcome(stored(identity), {
        "decision": "skip", "skip_action": "resolve",
        "reason": "Ο γάμος έγινε χθες το βράδυ, το θέμα έχει ήδη συζητηθεί και έχει ολοκληρωθεί.",
    })
    assert result == "resolved"
    assert stored(identity)["status"] == "resolved"


@pytest.mark.parametrize("action", ["none", "invalid", ""])
def test_reason_cannot_invent_a_state_change(action):
    identity = create()
    before = stored(identity)
    bot._apply_followup_skip_outcome(before, {
        "decision": "skip", "skip_action": action,
        "reason": "Already completed tonight, later, το βράδυ.",
    })
    after = stored(identity)
    assert after["status"] == "pending"
    assert after["followup_after_ts"] == before["followup_after_ts"]
    assert after["expires_at"] == before["expires_at"]


def test_automatic_evening_retry_stays_nearby_and_preserves_expiry(monkeypatch):
    now = datetime(2030, 1, 2, 20, 0, tzinfo=pf.FOLLOWUP_LOCAL_TZ)
    monkeypatch.setattr(pf, "_local_now", lambda: now)
    identity = create()
    before = stored(identity)
    result = bot._apply_followup_skip_outcome(before, {
        "decision": "skip", "skip_action": "defer", "reason": "Η έξοδος συνεχίζεται.",
    })
    after = stored(identity)
    assert result == "deferred"
    assert now < datetime.fromisoformat(after["followup_after_ts"]) <= now + timedelta(hours=1)
    assert after["expires_at"] == before["expires_at"]


def test_automatic_retry_after_expiry_expires_without_reopening(monkeypatch):
    now = datetime(2030, 1, 2, 20, 0, tzinfo=pf.FOLLOWUP_LOCAL_TZ)
    monkeypatch.setattr(pf, "_local_now", lambda: now)
    identity = create(hours=1)
    before = stored(identity)
    monkeypatch.setattr(pf, "_local_now", lambda: now + timedelta(minutes=61))
    result = bot._apply_followup_skip_outcome(before, {
        "decision": "skip", "skip_action": "defer", "reason": "Not yet.",
    })
    after = stored(identity)
    assert result == "expired"
    assert after["status"] == "expired"
    assert after["last_decision"] == "expired"
    assert after["expires_at"] == before["expires_at"]


def test_retry_near_expiry_does_not_extend_or_prematurely_close(monkeypatch):
    now = datetime(2030, 1, 2, 20, 0, tzinfo=pf.FOLLOWUP_LOCAL_TZ)
    monkeypatch.setattr(pf, "_local_now", lambda: now)
    identity = create(hours=1)
    before = stored(identity)
    monkeypatch.setattr(pf, "_local_now", lambda: now + timedelta(minutes=55))
    bot._apply_followup_skip_outcome(before, {
        "decision": "skip", "skip_action": "defer", "reason": "Still out.",
    })
    after = stored(identity)
    assert after["status"] == "pending"
    assert after["expires_at"] == before["expires_at"]
    assert after["followup_after_ts"] <= after["expires_at"]


def test_return_update_without_title_words_closes_only_related_outing(monkeypatch):
    coffee, wedding = create(), create("γάμος στο Μακροχώρι")
    _stub_updates(monkeypatch, [{"id": coffee, "action": "resolve", "resolution_type": "completed",
                              "confidence": 0.95, "reason": "The family returned from that outing"}])
    assert pf.maybe_resolve_followups_from_user_message("Γύρισαν φίλε ένα γρήγορο μπάνιο και ύπνο") == 1
    assert stored(coffee)["status"] == "resolved" and stored(wedding)["status"] == "pending"


@pytest.mark.parametrize("overrides", [
    {"action": "none"}, {"confidence": 0.3}, {"confidence": "false"},
    {"confidence": float("nan")}, {"confidence": True}, {"resolution_type": []},
])
def test_ambiguous_unrelated_or_invalid_completion_preserves_pending(monkeypatch, overrides):
    identity = create()
    item = {"id": identity, "action": "resolve", "resolution_type": "completed", "confidence": 0.95, "reason": "Done"}
    _stub_updates(monkeypatch, [{**item, **overrides}])
    pf.maybe_resolve_followups_from_user_message("Γύρισαν φίλε")
    assert stored(identity)["status"] == "pending"


def test_conflicting_batch_actions_cannot_write_either_outcome(monkeypatch):
    identity = create()
    _stub_updates(monkeypatch, [
        {"id": identity, "action": "resolve", "resolution_type": "completed", "confidence": 0.95, "reason": "Done"},
        {"id": identity, "action": "defer", "delay_minutes": 1440, "target_window": "explicit_timer", "confidence": 0.95, "reason": "Later"},
    ])
    pf.maybe_resolve_followups_from_user_message("Τελικά ο καφές στον Εύοσμο τελείωσε χθες το βράδυ")
    assert stored(identity)["status"] == "pending"


def test_resolution_model_receives_bounded_owner_context(monkeypatch):
    from memory import conversation_history as history
    history.append_message(role="user", content="Ο μικρός λείπει ακόμα με τη μαμά.", channel="matrix")
    history.append_message(role="user", content="Γύρισαν φίλε", channel="matrix")
    identity = create()
    seen = _stub_updates(monkeypatch, [{"id": identity, "action": "resolve", "resolution_type": "completed",
                                      "confidence": 0.95, "reason": "The family returned"}])
    pf.maybe_resolve_followups_from_user_message("Γύρισαν φίλε")
    assert stored(identity)["status"] == "resolved"
    assert "Ο μικρός λείπει ακόμα με τη μαμά." in seen[0]


def test_resolution_context_excludes_external_old_and_later_messages(monkeypatch):
    from memory import conversation_history as history
    base = datetime(2030, 1, 2, 20, 0, tzinfo=pf.FOLLOWUP_LOCAL_TZ)
    rows = [
        {"role": "user", "content": "Old outing", "timestamp": (base-timedelta(days=2)).isoformat()},
        {"role": "user", "content": "Untrusted return", "timestamp": base.isoformat(),
         "metadata": {"untrusted_external_tool_names": ["browse_url"]}},
        {"role": "user", "content": "They are still out", "timestamp": base.isoformat()},
        {"role": "user", "content": "Γύρισαν φίλε", "timestamp": base.isoformat()},
        {"role": "user", "content": "Future outing", "timestamp": (base+timedelta(hours=1)).isoformat()},
    ]
    monkeypatch.setattr(history, "load_messages", lambda **kw: rows)
    context = pf._load_followup_resolution_context("Γύρισαν φίλε")
    assert "They are still out" in context
    assert all(text not in context for text in ("Old outing", "Untrusted return", "Future outing"))


def test_explicit_owner_postponement_can_renew_expiry(monkeypatch):
    now = datetime(2030, 1, 2, 20, 0, tzinfo=pf.FOLLOWUP_LOCAL_TZ)
    monkeypatch.setattr(pf, "_local_now", lambda: now)
    identity = create(hours=1)
    before = stored(identity)
    _stub_updates(monkeypatch, [{"id": identity, "action": "defer", "delay_minutes": 1440,
        "target_window": "explicit_timer", "confidence": 0.95, "reason": "Owner moved it to tomorrow"}])
    pf.maybe_resolve_followups_from_user_message("Τελικά αύριο, όχι σήμερα")
    after = stored(identity)
    assert after["status"] == "pending"
    assert datetime.fromisoformat(after["followup_after_ts"]) == now+timedelta(days=1)
    assert after["expires_at"] > before["expires_at"]


@pytest.mark.parametrize("status", ["sent", "resolved", "expired"])
def test_automatic_retry_never_reopens_inactive_records(status):
    identity = create()
    if status == "sent":
        pf.mark_followup_sent(identity)
    elif status == "resolved":
        pf.resolve_followup(identity, "closed")
    else:
        pf.expire_old_followups((pf._local_now()+timedelta(days=2)).isoformat())
    assert pf.defer_followup(identity, delay_minutes=30, automatic=True) == "unchanged"
    assert stored(identity)["status"] == status


def test_model_merge_cannot_extend_expiry(monkeypatch):
    identity = create()
    before = stored(identity)
    monkeypatch.setattr(pf, "extract_followup_candidate_with_llm", lambda *a, **kw: {
        "should_follow_up": False, "update_existing_id": identity, "delay_minutes": 30})
    pf.maybe_create_followup_from_exchange(
        user_text="Περιμένουμε ακόμα να γυρίσουν.", ai_text="Κατάλαβα.",
        agent_name="Chat_Agent", channel="matrix")
    assert stored(identity)["expires_at"] == before["expires_at"]


@pytest.mark.parametrize("overrides", [
    {"action": "false"}, {"confidence": True}, {"delay_minutes": -60}, {"target_window": []},
])
def test_invalid_deferral_cannot_postpone_an_item(monkeypatch, overrides):
    identity = create()
    item = {"id": identity, "action": "defer", "delay_minutes": 60,
            "target_window": "explicit_timer", "confidence": 0.95, "reason": "Later"}
    _stub_updates(monkeypatch, [{**item, **overrides}])
    assert pf.maybe_resolve_followups_from_user_message("Γύρισαν") == 0
    assert stored(identity)["last_decision"] != "deferred"
