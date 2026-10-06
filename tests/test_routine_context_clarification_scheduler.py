"""Scheduler/context integration without live providers or user databases."""
from datetime import datetime, timedelta
from types import SimpleNamespace

from memory.routine_context_clarification import ATHENS, ClarificationStore
from services.routine_context_clarification import RoutineCandidate
from services.routine_context_evidence import ContextEvidence

NOW = datetime(2026, 10, 6, 10, tzinfo=ATHENS)


def test_scoped_projection_keeps_unscoped_work_and_unknowns():
    from services.routine_context import project_routine_context
    original = {"user_out_of_home": True, "partner_with_user": True, "current_shift": "afternoon"}
    result = project_routine_context(original, {"user_out_of_home": ContextEvidence()})
    assert result["user_out_of_home"] is None and result["partner_with_user"] is None
    assert result["current_shift"] == "afternoon" and original["user_out_of_home"] is True


def test_semantic_dependencies_cached_and_checked_against_whitelist(tmp_path):
    from services.routine_context_clarification_scheduler import resolve_dependencies
    store = ClarificationStore(tmp_path / "state.json")
    routine = RoutineCandidate("1", "Activity", NOW + timedelta(minutes=12), ())
    calls = []
    classify = lambda packet: calls.append(packet) or {"flags": ["user_out_of_home"]}
    assert resolve_dependencies(routine, {}, store, NOW, classify) == ("user_out_of_home",)
    assert resolve_dependencies(routine, {}, store, NOW, classify) == ("user_out_of_home",)
    assert len(calls) == 1
    other = RoutineCandidate("2", "Other", routine.slot_at, ())
    assert resolve_dependencies(other, {}, store, NOW, lambda _: {"flags": ["private_new_flag"]}) is None


def test_dependency_failure_is_not_retried_every_poll(tmp_path):
    from services.routine_context_clarification_scheduler import resolve_dependencies
    store = ClarificationStore(tmp_path / "state.json")
    routine = RoutineCandidate("1", "Activity", NOW + timedelta(minutes=12), ())
    calls = []
    def failed(_):
        calls.append(True)
        raise TimeoutError("provider unavailable")
    assert resolve_dependencies(routine, {}, store, NOW, failed) is None
    assert resolve_dependencies(routine, {}, store, NOW, failed) is None
    assert calls == [True]


def test_no_context_dependency_does_not_block_ordinary_routine(tmp_path):
    from services.routine_context_clarification_scheduler import routine_context_block
    store = ClarificationStore(tmp_path / "state.json")
    routine = RoutineCandidate("1", "Activity", NOW + timedelta(minutes=12), ())
    from services.routine_context_clarification_scheduler import resolve_dependencies
    assert resolve_dependencies(routine, {}, store, NOW, lambda _: {"flags": []}) == ()
    assert routine_context_block(routine, {}, {}, store, NOW) is False


def test_structured_unknown_blocks_null_suppression_without_model(tmp_path):
    from services.routine_context_clarification_scheduler import routine_context_block
    cond = {"condition_type": "context_flag", "condition_mode": "suppress_when_true",
            "condition_payload": {"flag": "partner_with_user", "equals": True}}
    routine = RoutineCandidate("1", "Activity", NOW + timedelta(minutes=12), (cond,))
    assert routine_context_block(routine, {}, {}, ClarificationStore(tmp_path / "state.json"), NOW)


def test_independent_block_does_not_require_dependency_classification(tmp_path):
    from services.routine_context_clarification_scheduler import routine_context_block
    cond = {"condition_type": "context_flag", "condition_mode": "allow_when_true",
            "condition_payload": {"flag": "school_open", "equals": True}}
    routine = RoutineCandidate("1", "School", NOW + timedelta(minutes=12), (cond,))
    assert not routine_context_block(routine, {"school_open": False}, {},
                                     ClarificationStore(tmp_path / "state.json"), NOW)


def test_pending_question_blocks_competing_completion_and_expired_slot(tmp_path):
    from memory.routine_context_clarification import QuestionRequest
    from services.routine_context_clarification_scheduler import question_blocks_dispatch
    store = ClarificationStore(tmp_path / "state.json")
    slot = NOW + timedelta(minutes=12)
    question = QuestionRequest("q", "topic", ("1",), ("user_out_of_home",),
                               slot, "Home?", "matrix")
    assert store.reserve(question, now=NOW)
    assert store.begin_send("q", now=NOW)
    assert store.mark_sent("q", external_id="$q", now=NOW)
    other = RoutineCandidate("2", "Other", slot, ())
    assert question_blocks_dispatch(store, NOW, other)
    assert store.close("q", outcome="resolved", now=NOW + timedelta(minutes=1))
    assert not question_blocks_dispatch(store, NOW + timedelta(minutes=1), other)
    original = RoutineCandidate("1", "Home activity", slot, ())
    assert question_blocks_dispatch(store, slot, original)
    assert not question_blocks_dispatch(store, slot + timedelta(days=1),
                                       RoutineCandidate("1", "Home activity", slot + timedelta(days=1), ()))


def test_queue_coalesces_ticks_and_releases_after_worker_error(monkeypatch, tmp_path):
    import services.routine_context_clarification_scheduler as worker
    import config
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(worker, "_queued", False)
    monkeypatch.setattr(worker, "clarification_unavailable", lambda: False)
    def failed(*args, **kwargs):
        raise RuntimeError("fixture")
    monkeypatch.setattr(worker, "load_poll_snapshot", failed)
    calls = []
    worker.schedule_context_clarification(calls.append)
    worker.schedule_context_clarification(calls.append)
    assert len(calls) == 1
    calls[0]()
    worker.schedule_context_clarification(calls.append)
    assert len(calls) == 2
