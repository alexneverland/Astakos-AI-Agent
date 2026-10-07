"""Dated dispatch contracts with temporary storage and injected transport only."""
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from memory.routine_feedback import RoutineFeedbackStore
from services.external_delivery import DeliveryReceipt


@pytest.fixture
def store(tmp_path):
    """Use a minimal temporary canonical routine row, never owner storage."""
    path = tmp_path / "routines.db"
    def connect():
        return sqlite3.connect(path, timeout=5)
    with connect() as connection:
        connection.execute("""CREATE TABLE routines (id INTEGER PRIMARY KEY,
            notify_cooldown_hours REAL, explicit_skip_streak INTEGER,
            unanswered_reminder_streak INTEGER, confidence REAL)""")
        connection.execute("INSERT INTO routines VALUES (11, 0, 0, 0, 1)")
    ledger = RoutineFeedbackStore(connect)
    ledger.initialize()
    return ledger


NOW = datetime(2026, 10, 7, 9, tzinfo=ZoneInfo("Europe/Athens"))


@pytest.mark.parametrize("channel", ["matrix", "telegram"])
@pytest.mark.parametrize("failure", [None, "transport", "projection"])
def test_batch_coordinator_sends_once_and_retains_each_member(store, channel, failure):
    """One actual send, all-member reservation, durable recovery and no resend."""
    from services.routine_feedback_dispatch import DatedRoutineSender, repair_staged_deliveries
    with store.connection_factory() as connection:
        connection.execute("INSERT INTO routines VALUES (12, 0, 0, 0, 1)")
        if failure == "projection":
            connection.execute("""CREATE TRIGGER reject_member BEFORE UPDATE OF receipt_id
                ON routine_occurrences WHEN NEW.routine_id=12
                BEGIN SELECT RAISE(ABORT, 'offline projection'); END""")
    calls = []
    def deliver(text):
        calls.append(text)
        if failure == "transport":
            raise TimeoutError("unknown outcome")
        return DeliveryReceipt(channel, "shared-event")
    sender = DatedRoutineSender(store, lambda: NOW, deliver)
    revisions = {rid: sender.revision(rid) for rid in (11, 12)}
    result = sender.send_batch(occurrence_date=NOW.date(), text="Both routines?",
                              expected_revisions=revisions, eligible=lambda: True)
    assert result.status == {None: "sent", "transport": "uncertain", "projection": "recording_pending"}[failure]
    reopened = RoutineFeedbackStore(store.connection_factory)
    assert DatedRoutineSender(reopened, lambda: NOW, deliver).send_batch(
        occurrence_date=NOW.date(), text="Both routines?",
        expected_revisions={rid: reopened.revision(rid) for rid in (11, 12)},
        eligible=lambda: True).status == "blocked"
    if failure == "projection":
        assert len(reopened.pending_delivery_proofs()) == 1
        with reopened.connection_factory() as connection:
            connection.execute("DROP TRIGGER reject_member")
        assert repair_staged_deliveries(store=reopened, now=NOW) == 1
    if failure != "transport":
        assert all(reopened.occurrences(rid)[0].delivered_at == NOW for rid in (11, 12))
        pending = reopened.pending_question(now=NOW)
        assert pending.routine_ids == (11, 12) and pending.event_id == "shared-event"
    else:
        assert all(reopened.occurrences(rid)[0].delivered_at is None for rid in (11, 12))
    assert calls == ["Both routines?"]


def reserved_pair(store, *, channel="matrix"):
    """Two actual reservations sharing one immutable transport receipt."""
    from memory.routine_feedback import PendingDeliveryProof
    with store.connection_factory() as connection:
        connection.execute("INSERT INTO routines VALUES (12, 0, 0, 0, 1)")
    assert store.claim_batch_dispatch({rid: store.revision(rid) for rid in (11, 12)},
        NOW.date(), at=NOW, is_eligible=lambda: True)
    return tuple(PendingDeliveryProof(rid, NOW.date(), NOW, "$group", channel, None)
                 for rid in (11, 12))


@pytest.mark.parametrize("channel", ["matrix", "telegram"])
@pytest.mark.parametrize("projection_failure", [False, True])
def test_group_receipt_survives_reopen_with_one_history_row(store, tmp_path, channel, projection_failure):
    """Recovery writes both dated receipts, but the common message only once."""
    from memory.conversation_history import append_message, load_messages
    from services.routine_feedback_dispatch import maintain_dated_feedback
    proofs = reserved_pair(store, channel=channel)
    assert store.stage_deliveries(proofs, history_content="One group reminder")
    assert store.stage_deliveries(proofs, history_content="One group reminder")
    assert store.pending_delivery_proofs() == proofs
    if projection_failure:
        with store.connection_factory() as connection:
            connection.execute("""CREATE TRIGGER reject_second_projection BEFORE UPDATE OF receipt_id
                ON routine_occurrences WHEN NEW.routine_id=12
                BEGIN SELECT RAISE(ABORT, 'offline projection failure'); END""")
    reopened = RoutineFeedbackStore(store.connection_factory)
    history_path = str(tmp_path / "group-history.db")
    record = lambda **kwargs: append_message(db_path=history_path, **kwargs)
    assert maintain_dated_feedback(store=reopened, now=NOW, record=record) == (not projection_failure)
    if projection_failure:
        assert reopened.pending_delivery_proofs() == (proofs[1],)
        assert len(load_messages(db_path=history_path)) == 1
        with store.connection_factory() as connection:
            connection.execute("DROP TRIGGER reject_second_projection")
        reopened = RoutineFeedbackStore(store.connection_factory)
    assert maintain_dated_feedback(store=reopened, now=NOW, record=record)
    assert len(load_messages(db_path=history_path)) == 1
    assert not reopened.pending_delivery_proofs() and not reopened.pending_history_repairs()
    assert all(reopened.occurrences(rid)[0].delivered_at == NOW for rid in (11, 12))


@pytest.mark.parametrize("conflict", ["unreserved", "other_receipt"])
def test_group_staging_member_conflict_leaves_siblings_unchanged(store, conflict):
    """No partial proof when a later member is missing or belongs to another send."""
    from dataclasses import replace
    proofs = reserved_pair(store)
    if conflict == "unreserved":
        with store.connection_factory() as connection:
            connection.execute("DELETE FROM routine_occurrences WHERE routine_id=12")
    else:
        assert store.stage_delivery(replace(proofs[1], receipt_id="$previous"))
    before = store.pending_delivery_proofs()
    assert not store.stage_deliveries(proofs, history_content="One group reminder")
    assert store.pending_delivery_proofs() == before
    assert not store.pending_history_repairs()


def test_group_staging_second_member_sqlite_failure_is_atomic(store):
    """Actual SQLite abort preserves held claims but no partial receipt/history."""
    proofs = reserved_pair(store)
    with store.connection_factory() as connection:
        connection.execute("""CREATE TRIGGER reject_group_proof BEFORE UPDATE OF staged_receipt_id
            ON routine_occurrences WHEN NEW.routine_id=12
            BEGIN SELECT RAISE(ABORT, 'offline staging failure'); END""")
    with pytest.raises(sqlite3.IntegrityError):
        store.stage_deliveries(proofs, history_content="One group reminder")
    assert not store.pending_delivery_proofs() and not store.pending_history_repairs()
    assert not store.claim_dispatch(11, NOW.date(), at=NOW,
        expected_revision=store.revision(11), is_eligible=lambda: True)
    with store.connection_factory() as connection:
        connection.execute("DROP TRIGGER reject_group_proof")
    assert store.stage_deliveries(proofs, history_content="One group reminder")
    assert store.pending_delivery_proofs() == proofs


@pytest.mark.parametrize("mismatch", ["receipt", "channel", "instant", "duplicate", "empty"])
def test_group_staging_rejects_nonshared_or_invalid_proof(store, mismatch):
    """Group membership must describe one send, never unrelated transport evidence."""
    from dataclasses import replace
    proofs = reserved_pair(store)
    if mismatch == "receipt": proofs = (proofs[0], replace(proofs[1], receipt_id="$other"))
    if mismatch == "channel": proofs = (proofs[0], replace(proofs[1], channel="telegram"))
    if mismatch == "instant": proofs = (proofs[0], replace(proofs[1], delivered_at=NOW + timedelta(seconds=1)))
    if mismatch == "duplicate": proofs = (proofs[0], proofs[0])
    if mismatch == "empty": proofs = ()
    with pytest.raises(ValueError):
        store.stage_deliveries(proofs, history_content="One group reminder")
    assert not store.pending_delivery_proofs() and not store.pending_history_repairs()


@pytest.mark.parametrize("block", [None, "stale", "reserved", "complete", "gate", "backoff"])
def test_batch_reservation_is_all_or_none(store, block):
    """A rejected member must not strand reservations or pressure on its siblings."""
    with store.connection_factory() as connection:
        connection.execute("INSERT INTO routines VALUES (12, 0, 0, 0, 1)")
    if block == "reserved":
        assert store.claim_dispatch(12, NOW.date(), at=NOW,
            expected_revision=store.revision(12), is_eligible=lambda: True)
    elif block == "complete":
        store.record_feedback(12, NOW.date(), "complete", at=NOW)
    elif block == "backoff":
        for offset in (3, 2, 1):
            at = NOW - timedelta(days=offset)
            store.record_delivery(12, at.date(), at=at, receipt_id=f"$past-{offset}")
    revisions = {rid: store.revision(rid) for rid in (11, 12)}
    if block == "stale":
        revisions[12] = "outdated revision"
    before = {rid: store.revision(rid) for rid in (11, 12)}
    assert store.claim_batch_dispatch(revisions, NOW.date(), at=NOW,
        is_eligible=lambda: block != "gate") == (block is None)
    if block is not None:
        assert {rid: store.revision(rid) for rid in (11, 12)} == before
    else:
        # A competing single send or restarted batch cannot take either member.
        reopened = RoutineFeedbackStore(store.connection_factory)
        assert not reopened.claim_batch_dispatch(
            {rid: reopened.revision(rid) for rid in (11, 12)}, NOW.date(),
            at=NOW, is_eligible=lambda: True)
        assert not reopened.claim_dispatch(11, NOW.date(), at=NOW,
            expected_revision=reopened.revision(11), is_eligible=lambda: True)
        assert all(row.delivered_at is None for rid in (11, 12) for row in reopened.occurrences(rid))


def test_overlapping_concurrent_batches_reserve_only_one_complete_group(store):
    """Independent connections serialize intersecting batch claims across processes."""
    with store.connection_factory() as connection:
        connection.executemany("INSERT INTO routines VALUES (?, 0, 0, 0, 1)", [(12,), (13,)])
    revisions = {rid: store.revision(rid) for rid in (11, 12, 13)}
    def claim(ids):
        ledger = RoutineFeedbackStore(store.connection_factory)
        return ledger.claim_batch_dispatch({rid: revisions[rid] for rid in ids},
            NOW.date(), at=NOW, is_eligible=lambda: True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(claim, [(11, 12), (12, 13)]))
    assert sorted(outcomes) == [False, True]
    expected = {11, 12} if outcomes[0] else {12, 13}
    assert {rid for rid in (11, 12, 13) if store.occurrences(rid)} == expected


@pytest.mark.parametrize("days", [-1, 1])
def test_batch_reservation_rejects_noncurrent_dates_without_mutation(store, days):
    """Batches cannot revive yesterday or pre-send a future occurrence."""
    before = store.revision(11)
    if days > 0:
        with pytest.raises(ValueError):
            store.claim_batch_dispatch({11: before}, (NOW + timedelta(days=days)).date(),
                at=NOW, is_eligible=lambda: True)
    else:
        assert not store.claim_batch_dispatch({11: before}, (NOW + timedelta(days=days)).date(),
            at=NOW, is_eligible=lambda: True)
    assert store.revision(11) == before


def test_batch_database_failure_rolls_back_already_reserved_member(store):
    """An actual second-member SQLite failure cannot leave a partial reservation."""
    with store.connection_factory() as connection:
        connection.execute("INSERT INTO routines VALUES (12, 0, 0, 0, 1)")
        connection.execute("""CREATE TRIGGER reject_second_claim BEFORE INSERT
            ON routine_occurrences WHEN NEW.routine_id=12
            BEGIN SELECT RAISE(ABORT, 'offline group failure'); END""")
    before = {rid: store.revision(rid) for rid in (11, 12)}
    with pytest.raises(sqlite3.IntegrityError):
        store.claim_batch_dispatch(before, NOW.date(), at=NOW, is_eligible=lambda: True)
    assert {rid: store.revision(rid) for rid in (11, 12)} == before
    assert not store.occurrences(11) and not store.occurrences(12)


@pytest.mark.parametrize("revisions", [{}, {False: "revision"}, {11: None}, {11: ""}])
def test_batch_invalid_structured_input_never_mutates_storage(store, revisions):
    """Validate identifiers and revisions, never interpret user wording here."""
    before = store.revision(11)
    with pytest.raises(ValueError):
        store.claim_batch_dispatch(revisions, NOW.date(), at=NOW, is_eligible=lambda: True)
    assert store.revision(11) == before


def test_tick_counts_only_closed_delivered_days_and_preserves_confidence(store):
    """Repeated scheduler ticks cannot count today's open response window."""
    from services.routine_feedback_dispatch import maintain_dated_feedback
    for offset in (2, 1, 0):
        at = NOW - timedelta(days=offset)
        store.record_delivery(11, at.date(), at=at, receipt_id=f"${offset}")
    assert maintain_dated_feedback(store=store, now=NOW + timedelta(hours=8),
        record=lambda **kwargs: pytest.fail("no history work"))
    assert store.debug_snapshot([11], now=NOW)[11]["derived_cooldown_hours"] == 0
    tomorrow = NOW + timedelta(days=1)
    assert maintain_dated_feedback(store=store, now=tomorrow,
        record=lambda **kwargs: pytest.fail("no history work"))
    assert maintain_dated_feedback(store=RoutineFeedbackStore(store.connection_factory), now=tomorrow,
        record=lambda **kwargs: pytest.fail("no history work"))
    snapshot = store.debug_snapshot([11], now=tomorrow)[11]
    assert snapshot["derived_cooldown_hours"] == 20
    with store.connection_factory() as connection:
        assert connection.execute("SELECT notify_cooldown_hours, confidence FROM routines").fetchone() == (20, 1)


def test_tick_recovers_history_even_when_receipt_projection_still_fails(store, tmp_path):
    """Independent history repair progresses; failed receipt projection blocks dispatch."""
    from memory.conversation_history import append_message, load_messages
    from services.external_assistant_delivery import AssistantHistoryError
    from services.routine_feedback_dispatch import maintain_dated_feedback
    with store.connection_factory() as connection:
        connection.execute("""CREATE TRIGGER reject_receipt BEFORE UPDATE OF receipt_id
            ON routine_occurrences BEGIN SELECT RAISE(ABORT, 'blocked write'); END""")
    def deliver(text):
        raise AssistantHistoryError(DeliveryReceipt("matrix", "$tick"), lambda: None)
    assert dispatch(store, deliver).status == "recording_pending"
    reopened = RoutineFeedbackStore(store.connection_factory)
    history = str(tmp_path / "tick-history.db")
    record = lambda **kwargs: append_message(db_path=history, **kwargs)
    assert maintain_dated_feedback(store=reopened, now=NOW, record=record) is False
    assert len(load_messages(db_path=history)) == 1
    assert reopened.pending_history_repairs() == ()
    assert len(reopened.pending_delivery_proofs()) == 1
    with reopened.connection_factory() as connection:
        connection.execute("DROP TRIGGER reject_receipt")
    assert maintain_dated_feedback(store=reopened, now=NOW, record=record)
    assert len(load_messages(db_path=history)) == 1
    assert reopened.pending_delivery_proofs() == ()


def test_tick_does_not_guess_unconfirmed_claim_or_initialize_storage(store):
    """Held timeouts stay held and missing migrations fail closed without DDL."""
    from services.routine_feedback_dispatch import maintain_dated_feedback
    def timeout(text):
        raise TimeoutError("unconfirmed")
    assert dispatch(store, timeout).status == "uncertain"
    assert maintain_dated_feedback(store=store, now=NOW + timedelta(days=4),
        record=lambda **kwargs: pytest.fail("unknown send is not history"))
    assert store.occurrences(11)[0].delivered_at is None
    with store.connection_factory() as connection:
        connection.execute("DROP TABLE routine_occurrences")
    assert maintain_dated_feedback(store=store, now=NOW,
        record=lambda **kwargs: pytest.fail("no migration")) is False
    with store.connection_factory() as connection:
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='routine_occurrences'").fetchone() is None


@pytest.mark.parametrize("channel", ["matrix", "telegram"])
def test_actual_scheduler_tick_projects_midnight_without_sending(store, monkeypatch, tmp_path, channel):
    """The shared runtime entry point invokes the real dated maintenance boundary."""
    from clients import telegram_bot as bot
    from memory.conversation_history import append_message
    from services.routine_feedback_dispatch import maintain_dated_feedback
    for offset in (2, 1, 0):
        at = NOW - timedelta(days=offset)
        store.record_delivery(11, at.date(), at=at, receipt_id=f"{channel}-{offset}")
    clock = [NOW.replace(hour=23, minute=59)]
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0].astimezone(tz) if tz is not None else clock[0].replace(tzinfo=None)
    monkeypatch.setattr(bot, "datetime", Clock)
    monkeypatch.setattr(bot, "_external_background_runtime_channel", channel)
    monkeypatch.setattr(bot, "pending_routine_confirmations", {})
    monkeypatch.setattr(bot, "is_proactive_muted", lambda: True)
    monkeypatch.setattr(bot, "_send_and_record_assistant", lambda *args, **kwargs: pytest.fail("maintenance must not send"))
    history = str(tmp_path / "scheduler-history.db")
    monkeypatch.setattr(bot, "_dated_routine_feedback_tick", lambda at: maintain_dated_feedback(
        store=store, now=at, record=lambda **kwargs: append_message(db_path=history, **kwargs)))
    bot.job_check_routines()
    with store.connection_factory() as connection:
        assert connection.execute("SELECT notify_cooldown_hours FROM routines").fetchone() == (0,)
    clock[0] = (NOW + timedelta(days=1)).replace(hour=0, minute=0)
    bot.job_check_routines()
    bot.job_check_routines()
    with store.connection_factory() as connection:
        assert connection.execute("SELECT notify_cooldown_hours, confidence FROM routines").fetchone() == (20, 1)


def test_history_repair_survives_restart_and_uncertain_history_commit(store, tmp_path):
    """Replay only history, including a write that committed before raising."""
    from memory.conversation_history import append_message, load_messages
    from services.external_assistant_delivery import AssistantHistoryError
    from services.routine_feedback_dispatch import repair_pending_history
    sends = []
    def deliver(text):
        sends.append(text)
        raise AssistantHistoryError(DeliveryReceipt("matrix", "$history"),
                                    lambda: None)
    assert dispatch(store, deliver).status == "sent"
    reopened = RoutineFeedbackStore(store.connection_factory)
    history_path = str(tmp_path / "history.db")
    def record_then_fail(**kwargs):
        append_message(db_path=history_path, **kwargs)
        raise OSError("commit acknowledgement lost")
    with pytest.raises(OSError):
        repair_pending_history(store=reopened, record=record_then_fail)
    assert len(reopened.pending_history_repairs()) == 1
    assert repair_pending_history(store=reopened,
        record=lambda **kwargs: append_message(db_path=history_path, **kwargs)) == 1
    assert repair_pending_history(store=reopened,
        record=lambda **kwargs: pytest.fail("already repaired")) == 0
    rows = load_messages(db_path=history_path)
    assert len(rows) == 1
    assert rows[0]["content"] == "Reminder"
    assert rows[0]["channel"] == "matrix"
    assert rows[0]["timestamp"] == NOW.isoformat(timespec="seconds")
    assert dispatch(reopened, deliver).status == "blocked"
    assert sends == ["Reminder"]


def test_uncertain_send_never_creates_history_repair(store):
    """No receipt means no fabricated history work after restart."""
    from services.routine_feedback_dispatch import repair_pending_history
    def timeout(text):
        raise TimeoutError("unknown")
    assert dispatch(store, timeout).status == "uncertain"
    assert repair_pending_history(store=store,
        record=lambda **kwargs: pytest.fail("no confirmed send")) == 0


def dispatch(store, deliver, **overrides):
    """Exercise the inactive coordinator with a real ledger and synthetic send."""
    from services.routine_feedback_dispatch import send_dated_reminder
    kwargs = dict(store=store, routine_id=11, occurrence_date=NOW.date(),
                  text="Reminder", question="Completed?", now=lambda: NOW,
                  expected_revision=store.revision(11), eligible=lambda: True,
                  deliver=deliver)
    kwargs.update(overrides)
    return send_dated_reminder(**kwargs)


def test_confirmed_delivery_deduplicates_across_reopen_and_channel_change(store):
    """Zero cooldown and a second channel cannot resend an occurrence."""
    sends = []
    def deliver(text):
        sends.append(text)
        return DeliveryReceipt("matrix", "$receipt")
    assert dispatch(store, deliver).status == "sent"
    reopened = RoutineFeedbackStore(store.connection_factory)
    assert dispatch(reopened, deliver).status == "blocked"
    assert sends == ["Reminder"]
    assert reopened.pending_question(now=NOW).event_id == "$receipt"


def test_history_failure_preserves_delivery_and_only_repairs_history(store):
    """A confirmed receipt counts even when recording chat history fails."""
    from services.external_assistant_delivery import deliver_external_assistant_text
    from services.external_delivery import ExternalDeliveryRouter
    sends, repairs = [], []
    class Transport:
        def send_text(self, text, *, silent=False):
            sends.append(text)
            return "$receipt"
    router = ExternalDeliveryRouter(channel_selector=lambda: "matrix")
    router.register("matrix", Transport())
    def record(*args):
        if not sends or not repairs:
            repairs.append("failed")
            raise OSError("history temporarily unavailable")
        repairs.append("history")
    def deliver(text):
        return deliver_external_assistant_text(text, agent="Routine_Agent",
                                               router=router, record_message=record)
    result = dispatch(store, deliver)
    assert result.status == "sent"
    assert store.occurrences(11)[0].delivered_at == NOW
    result.history_repair()
    assert store.pending_history_repairs() == ()
    assert dispatch(store, deliver).status == "blocked"
    assert sends == ["Reminder"] and repairs == ["failed", "history"]


def test_receipt_and_history_failures_recover_independently_after_restart(store, tmp_path):
    """Canonical ledger repair must not erase pending conversation repair."""
    from memory.conversation_history import append_message, load_messages
    from services.external_assistant_delivery import AssistantHistoryError
    from services.routine_feedback_dispatch import repair_pending_history, repair_staged_deliveries
    with store.connection_factory() as connection:
        connection.execute("""CREATE TRIGGER reject_receipt BEFORE UPDATE OF receipt_id
            ON routine_occurrences BEGIN SELECT RAISE(ABORT, 'blocked write'); END""")
    sends = []
    def deliver(text):
        sends.append(text)
        raise AssistantHistoryError(DeliveryReceipt("telegram", "123"), lambda: None)
    assert dispatch(store, deliver).status == "recording_pending"
    reopened = RoutineFeedbackStore(store.connection_factory)
    with reopened.connection_factory() as connection:
        connection.execute("DROP TRIGGER reject_receipt")
    assert repair_staged_deliveries(store=reopened, now=NOW + timedelta(days=1)) == 1
    assert reopened.pending_delivery_proofs() == ()
    assert len(reopened.pending_history_repairs()) == 1
    history_path = str(tmp_path / "repaired-history.db")
    assert repair_pending_history(store=reopened,
        record=lambda **kwargs: append_message(db_path=history_path, **kwargs)) == 1
    assert load_messages(db_path=history_path)[0]["channel"] == "telegram"
    assert sends == ["Reminder"]


def test_oversized_history_payload_is_rejected_before_transport(store):
    """Every accepted reminder can be durably recovered before reserving a send."""
    with pytest.raises(ValueError):
        dispatch(store, lambda text: pytest.fail("invalid payload sent"), text="x" * 20001)
    assert store.occurrences(11) == []


def test_uncertain_transport_is_held_after_restart_without_counting_silence(store):
    """A timeout may hide a delivery: never resend or fabricate a receipt."""
    sends = []
    def deliver(text):
        sends.append(text)
        raise TimeoutError("unknown transport outcome")
    assert dispatch(store, deliver).status == "uncertain"
    reopened = RoutineFeedbackStore(store.connection_factory)
    assert dispatch(reopened, deliver).status == "blocked"
    assert reopened.occurrences(11)[0].delivered_at is None
    pressure = reopened.reconcile(11, now=NOW + timedelta(days=1))
    assert pressure.unanswered_streak == 0 and pressure.cooldown_hours == 0
    assert sends == ["Reminder"]


@pytest.mark.parametrize("feedback", ["complete", "skip_today", "defer"])
def test_current_feedback_suppresses_delivery(store, feedback):
    """No transport call is allowed after an occurrence becomes ineligible."""
    store.record_feedback(11, NOW.date(), feedback, at=NOW)
    def forbidden(text):
        raise AssertionError("must not send")
    assert dispatch(store, forbidden).status == "blocked"


def test_stale_revision_or_eligibility_never_calls_transport(store):
    """Generation cannot authorize a reminder after feedback/config changes."""
    revision = store.revision(11)
    store.record_feedback(11, NOW.date(), "acknowledge", at=NOW)
    def forbidden(text):
        raise AssertionError("must not send")
    assert dispatch(store, forbidden, expected_revision=revision).status == "blocked"
    assert dispatch(store, forbidden, eligible=lambda: False).status == "blocked"


def test_parallel_workers_and_reentrant_send_do_not_duplicate(store):
    """Independent store handles share the durable claim, not a process lock."""
    sends = []
    def deliver(text):
        sends.append(text)
        assert dispatch(RoutineFeedbackStore(store.connection_factory), deliver).status == "blocked"
        return DeliveryReceipt("telegram", "42")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: dispatch(
            RoutineFeedbackStore(store.connection_factory), deliver), range(2)))
    assert sorted(result.status for result in results) == ["blocked", "sent"]
    assert sends == ["Reminder"]


def test_closed_day_backoff_expires_without_confidence_penalty(store):
    """Three unanswered delivered days block before the deadline, not forever."""
    for day in (4, 5, 6):
        at = NOW.replace(day=day)
        store.record_delivery(11, at.date(), at=at, receipt_id=str(day))
    sends = []
    def deliver(text):
        sends.append(text)
        return DeliveryReceipt("matrix", "$receipt")
    assert dispatch(store, deliver).status == "blocked"
    later = NOW + timedelta(days=1)
    assert dispatch(store, deliver, now=lambda: later,
                    occurrence_date=later.date()).status == "sent"
    with store.connection_factory() as connection:
        assert connection.execute("SELECT confidence FROM routines WHERE id=11").fetchone() == (1.0,)
    assert sends == ["Reminder"]


def test_acknowledgement_clears_pressure_but_cannot_resend_today(store):
    """Engagement changes pressure, never the occurrence's receipt deduplication."""
    def deliver(text):
        return DeliveryReceipt("matrix", "$receipt")
    assert dispatch(store, deliver).status == "sent"
    store.record_feedback(11, NOW.date(), "acknowledge", at=NOW + timedelta(minutes=1))
    assert dispatch(store, deliver, now=lambda: NOW + timedelta(minutes=2)).status == "blocked"


def test_failed_ledger_write_retains_receipt_for_later_repair_without_resend(store):
    """An actual SQLite abort must not lose confirmed proof or retry transport."""
    with store.connection_factory() as connection:
        connection.execute("""CREATE TRIGGER reject_receipt BEFORE UPDATE OF receipt_id
            ON routine_occurrences WHEN NEW.receipt_id IS NOT NULL
            BEGIN SELECT RAISE(ABORT, 'temporary write failure'); END""")
    clock, sends = [NOW], []
    def deliver(text):
        sends.append(text)
        return DeliveryReceipt("matrix", "$receipt")
    result = dispatch(store, deliver, now=lambda: clock[0])
    assert result.status == "recording_pending"
    assert result.receipt == DeliveryReceipt("matrix", "$receipt")
    assert store.occurrences(11)[0].delivered_at is None
    assert dispatch(store, deliver).status == "blocked"
    with pytest.raises(sqlite3.IntegrityError, match="temporary write failure"):
        result.delivery_repair()
    with store.connection_factory() as connection:
        connection.execute("DROP TRIGGER reject_receipt")
    clock[0] = NOW + timedelta(days=1)
    # Newer evidence must not make an older confirmed receipt impossible to repair.
    store.record_feedback(11, NOW.date(), "complete", at=clock[0])
    result.delivery_repair()
    result.delivery_repair()
    row = store.occurrences(11)[0]
    assert row.delivered_at == NOW and row.feedback == "complete"
    assert sends == ["Reminder"]
    assert store.reconcile(11, now=clock[0]).unanswered_streak == 0


def test_restart_repairs_durable_proof_even_after_completion_and_channel_change(store):
    """Discard all callbacks; reopen storage and recover proof without transport."""
    from services.routine_feedback_dispatch import repair_staged_deliveries
    with store.connection_factory() as connection:
        connection.execute("""CREATE TRIGGER reject_receipt BEFORE UPDATE OF receipt_id
            ON routine_occurrences WHEN NEW.receipt_id IS NOT NULL
            BEGIN SELECT RAISE(ABORT, 'temporary write failure'); END""")
    sends = []
    def deliver(text):
        sends.append(text)
        return DeliveryReceipt("matrix", "$receipt")
    assert dispatch(store, deliver).status == "recording_pending"
    reopened = RoutineFeedbackStore(store.connection_factory)
    with reopened.connection_factory() as connection:
        connection.execute("DROP TRIGGER reject_receipt")
    later = NOW + timedelta(days=1)
    reopened.record_feedback(11, NOW.date(), "complete", at=later)
    assert repair_staged_deliveries(store=reopened, now=later) == 1
    assert repair_staged_deliveries(store=reopened, now=later) == 0
    occurrence = reopened.occurrences(11)[0]
    assert occurrence.delivered_at == NOW and occurrence.feedback == "complete"
    assert sends == ["Reminder"]
    assert reopened.pending_delivery_proofs() == ()
    assert dispatch(reopened, lambda _: DeliveryReceipt("telegram", "99"),
                    now=lambda: later).status == "blocked"


def test_durable_proof_requires_claim_and_cannot_replace_first_receipt(store):
    """Staged work cannot invent a send or overwrite the reserved transport proof."""
    from memory.routine_feedback import PendingDeliveryProof
    proof = PendingDeliveryProof(11, NOW.date(), NOW, "$receipt", "matrix", "Completed?")
    assert store.stage_delivery(proof) is False
    assert store.pending_delivery_proofs() == ()
    assert store.claim_dispatch(11, NOW.date(), at=NOW,
        expected_revision=store.revision(11), is_eligible=lambda: True)
    assert store.stage_delivery(proof) is True
    assert store.stage_delivery(proof) is True
    other = PendingDeliveryProof(11, NOW.date(), NOW, "99", "telegram", "Completed?")
    assert store.stage_delivery(other) is False
    assert store.pending_delivery_proofs() == (proof,)


def test_repair_failure_preserves_durable_proof_for_next_restart(store):
    """A second database failure must not remove the already committed proof."""
    from services.routine_feedback_dispatch import repair_staged_deliveries
    with store.connection_factory() as connection:
        connection.execute("""CREATE TRIGGER reject_receipt BEFORE UPDATE OF receipt_id
            ON routine_occurrences WHEN NEW.receipt_id IS NOT NULL
            BEGIN SELECT RAISE(ABORT, 'temporary write failure'); END""")
    result = dispatch(store, lambda _: DeliveryReceipt("matrix", "$receipt"))
    assert result.status == "recording_pending"
    reopened = RoutineFeedbackStore(store.connection_factory)
    with pytest.raises(sqlite3.IntegrityError, match="temporary write failure"):
        repair_staged_deliveries(store=reopened, now=NOW)
    assert reopened.pending_delivery_proofs()[0].receipt_id == "$receipt"
    assert reopened.occurrences(11)[0].delivered_at is None
    with reopened.connection_factory() as connection:
        connection.execute("DROP TRIGGER reject_receipt")
    assert repair_staged_deliveries(store=reopened, now=NOW) == 1


def test_uncertain_send_has_no_durable_proof_to_repair(store):
    """Recovery cannot manufacture evidence from a claim or a timeout."""
    from services.routine_feedback_dispatch import repair_staged_deliveries
    def timeout(text):
        raise TimeoutError("unknown outcome")
    assert dispatch(store, timeout).status == "uncertain"
    assert repair_staged_deliveries(store=store, now=NOW + timedelta(days=1)) == 0
    assert store.occurrences(11)[0].delivered_at is None


def test_delayed_receipt_repair_rejects_future_evidence_without_mutation(store):
    """Separate reconciliation time cannot legitimize a future delivery instant."""
    with pytest.raises(ValueError, match="future"):
        store.record_delivery(11, NOW.date(), at=NOW + timedelta(hours=1),
                              receipt_id="$receipt", reconciled_at=NOW)
    assert store.occurrences(11) == []


@pytest.mark.parametrize("receipt", [DeliveryReceipt("matrix", ""),
    DeliveryReceipt("matrix", True), DeliveryReceipt("web", "$receipt"),
    DeliveryReceipt("matrix", "x" * 513)])
def test_invalid_transport_proof_is_held_not_offered_as_recording_repair(store, receipt):
    """Malformed identifiers cannot masquerade as confirmed external delivery."""
    result = dispatch(store, lambda text: receipt)
    assert result.status == "uncertain" and result.receipt is None
    assert result.delivery_repair is None
    assert store.occurrences(11)[0].delivered_at is None


@pytest.mark.parametrize("days", [-1, 1])
def test_dispatch_never_replays_past_or_future_slots(store, days):
    """Recovery may reconcile old evidence, not send obsolete reminders."""
    def forbidden(text):
        raise AssertionError("must not send")
    day = (NOW + timedelta(days=days)).date()
    if days < 0:
        assert dispatch(store, forbidden, occurrence_date=day).status == "blocked"
    else:
        with pytest.raises(ValueError, match="future"):
            dispatch(store, forbidden, occurrence_date=day)
    assert store.occurrences(11) == []
