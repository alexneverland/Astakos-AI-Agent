"""Offline real adapter and scheduler integration for initiative delivery."""
import pytest
from clients.matrix_delivery import MatrixExternalTransport
from services.external_delivery import ExternalDeliveryRouter, ExternalDeliveryError


def test_matrix_generic_transaction_send_preserves_identity_and_selection():
    attempts = []
    adapter = MatrixExternalTransport(send_text=lambda _: pytest.fail("No non-idempotent send"),
        send_transaction_text=lambda text, tx: attempts.append((text, tx)) or "$one",
        approval_reaction_hint="reply")
    router = ExternalDeliveryRouter(channel_selector=lambda: "matrix")
    router.register("matrix", adapter)
    for _ in range(2):
        assert router.send_idempotent_matrix_text("Hello", transaction_id="stable").external_id == "$one"
    assert attempts == [("Hello", "stable")] * 2
    other = ExternalDeliveryRouter(channel_selector=lambda: "telegram")
    other.register("telegram", adapter)
    with pytest.raises(ExternalDeliveryError):
        other.send_idempotent_matrix_text("Hello", transaction_id="stable")
    assert len(attempts) == 2


def test_scheduler_only_enqueues_one_slow_worker(monkeypatch):
    import clients.telegram_bot as bot
    import services.behavioral_initiative_scheduler as service
    class Scheduler:
        def __init__(self):
            self.jobs = {}
        def register(self, func, interval_seconds, name, verbose):
            self.jobs[name] = (func, interval_seconds)
    monkeypatch.setattr(bot, "AstakosScheduler", Scheduler)
    monkeypatch.setattr(bot, "_external_background_runtime_channel", "matrix")
    monkeypatch.setattr(bot.shutdown_event, "is_set", lambda: False)
    queued = []
    monkeypatch.setattr(bot, "enqueue_slow_task", lambda func, *args: queued.append((func, args)))
    service._reset_for_tests()
    try:
        scheduler = bot._build_external_scheduler()
        job, interval = scheduler.jobs["behavioral_initiative"]
        assert interval == 600
        job()
        job()
        assert len(queued) == 1
        assert queued[0][0].__name__ == "run_behavioral_initiative_job"
    finally:
        service._reset_for_tests()


def test_real_worker_delivers_and_records_via_shared_boundaries(tmp_path, monkeypatch):
    """Run the production worker with real temp stores and real Matrix adapter."""
    from datetime import datetime, timedelta
    import config
    import clients.telegram_bot as bot
    import services.behavioral_initiative_scheduler as worker
    import services.behavioral_conversation_evidence as evidence
    import services.routine_context as context
    import memory.conversation_history as history
    from services.behavioral_conversation_evidence import build_behavioral_evidence

    db = str(tmp_path / "history.db")
    now = datetime.now()
    original_load, original_append = history.load_messages, history.append_message
    original_append(role="user", content="Καλημέρα φίλε", channel="web", db_path=db,
                    timestamp=now - timedelta(minutes=20))
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(bot, "_external_background_runtime_channel", "matrix")
    monkeypatch.setattr(bot.shutdown_event, "is_set", lambda: False)
    monkeypatch.setattr(bot, "is_quiet_hours", lambda: False)
    monkeypatch.setattr(bot, "is_proactive_muted", lambda: False)
    monkeypatch.setattr(bot, "can_send_proactive", lambda: True)
    monkeypatch.setattr("core.messaging_channel.resolve_external_channel", lambda: "matrix")
    monkeypatch.setattr(history, "load_messages", lambda **kw: original_load(db_path=db, **kw))
    monkeypatch.setattr(history, "append_message", lambda **kw: original_append(db_path=db, **kw))
    monkeypatch.setattr(context, "build_runtime_routine_context", lambda: {})
    events = [dict(event_type="activity", category="exercise", subject="user", item="walking",
                   action_kind="participate", status="completed", record_state="confirmed",
                   event_date=(now - timedelta(days=day)).date().isoformat(), confidence=.95,
                   negated=0, hypothetical=0, reported_by_user=1, source_message_id=str(day),
                   source_rowid=day, source_channel="web") for day in (1, 2, 3)]
    monkeypatch.setattr(evidence, "load_behavioral_evidence", lambda **kw: build_behavioral_evidence(events, **kw))
    monkeypatch.setattr(worker, "_classify", lambda _: dict(selected_index=0, blocked=False,
                                                          recently_discussed=False, message="Πώς πάνε οι βόλτες σου;"))
    delivered = []
    transport = MatrixExternalTransport(send_text=lambda _: pytest.fail("Wrong sender"),
        send_transaction_text=lambda text, tx: delivered.append((text, tx)) or "$opener",
        approval_reaction_hint="reply")
    router = ExternalDeliveryRouter(channel_selector=lambda: "matrix")
    router.register("matrix", transport)
    monkeypatch.setattr("services.external_delivery.external_delivery_router", router)
    worker.run_behavioral_initiative_job()
    worker.run_behavioral_initiative_job()
    assert len(delivered) == 1
    assert delivered[0][1].startswith("astakos-behavioral-")
    assert original_load(db_path=db)[-1]["content"] == "Πώς πάνε οι βόλτες σου;"
    assert (tmp_path / "behavioral_initiative_state.json").exists()
