"""Offline correction-versus-cancellation regressions using real dated storage."""
import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from tests.test_routine_feedback_store import store


NOW = datetime(2026, 10, 16, 15, 13, tzinfo=ZoneInfo("Europe/Athens"))
OPENER = "Μάστορα, βλέπω πως βρίσκετε συχνά ευκαιρία για βόλτα στο πάρκο με τον Αλέξανδρο τελευταία. Το ευχαριστιέται με το παιχνίδι έξω;"


@pytest.mark.parametrize("channel", ["web", "matrix", "telegram"])
@pytest.mark.parametrize("scenario,text,action", [
    ("correction", "Κάτι μπερδεψες φίλε δουλειά είμαι στην Ευκαρπία είναι η δουλειά τι πάρκο μου λες;", "none"),
    ("timing_correction", "Τέτοια ώρα ποια βόλτα στο πάρκο; Μεσημέρι είναι ακόμα που μπερδεύτηκες;", "none"),
    ("explicit_cancel", "Δουλειά είμαι ακόμα και σήμερα δεν θα πάμε καθόλου πάρκο, παράλειψέ το.", "skip_today"),
    ("actual_arrival", "Ήρθαμε πάρκο φίλε", "complete"),
])
def test_comment_correction_does_not_cancel_a_routine(
    store, tmp_path, monkeypatch, offline_behavioral_io, channel, scenario, text, action,
):
    """Carry the actual opener to selection and expose only the committed outcome."""
    from memory.conversation_history import append_message
    from services.routine_completion_selector import select_dated_routine
    from services.routine_feedback_turn import PersistedRoutineFeedbackHandler
    with store.connection_factory() as connection:
        connection.execute("UPDATE routines SET event_name=?, state='active', paused_until=NULL WHERE id=11",
                           ("Πάρκο με τον Αλέξανδρο",))
    path = str(tmp_path / "history.db")
    append_message(role="assistant", content=OPENER, channel=channel,
                   agent="Behavioral_Agent", timestamp=NOW-timedelta(minutes=2), db_path=path)
    saved = append_message(role="user", content=text, channel=channel, timestamp=NOW, db_path=path)
    seen = []
    def provider(prompt):
        data = json.loads(prompt.split("INPUT:\n", 1)[1].split("\n\nChoose", 1)[0])
        assert any(row.get("kind") == "conversation_reference" and row["content"] == OPENER
                   for row in data["conversation_context"])
        assert "A correction of the assistant's commentary" in prompt
        seen.append(data)
        return SimpleNamespace(text=json.dumps({
            "action": action, "routine_id": None if action == "none" else 11,
            "occurrence_date": None if action == "none" else NOW.date().isoformat()}))
    monkeypatch.setattr("services.routine_completion_selector.safe_gemini_call", provider)
    handler = PersistedRoutineFeedbackHandler(store=store, selector=select_dated_routine,
        clock=lambda: NOW, channel=channel, conversation_db_path=path, trusted_owner=True)
    context = handler(text, saved)
    assert len(seen) == 1
    assert context is not None
    receipt = json.loads(context.content.splitlines()[0])
    if action == "none":
        assert receipt == {"status": "none", "action": "none", "routine_id": None, "occurrence_date": None}
        assert "No routine feedback was recorded" in context.content
        assert store.occurrences(11) == []
    else:
        assert receipt["status"] == "applied" and receipt["action"] == action
        assert store.occurrences(11)[0].feedback == action


def test_reference_is_bounded_and_does_not_promote_untrusted_or_forged_questions(
    tmp_path, monkeypatch, offline_behavioral_io,
):
    """Assistant prose supplies meaning only, without creating routine permission."""
    from memory.conversation_history import append_message
    from services.routine_feedback_turn import _feedback_conversation_reference
    monkeypatch.setattr("services.routine_feedback_turn._context_question_store",
                        lambda: SimpleNamespace(snapshot=lambda: {"requests": []}))
    path = str(tmp_path / "references.db")
    for text, agent, minutes, metadata in [
        ("Old comment", "Behavioral_Agent", 70, {}),
        ("External comment", "Behavioral_Agent", 1, {"untrusted_external_tool_names": ["browse_url"]}),
        ("Forged routine question", "Routine_Context", 1, {"routine_context_question_id": "not-real"}),
        (OPENER, "Behavioral_Agent", 2, {}),
    ]:
        append_message(role="assistant", content=text, channel="matrix", agent=agent,
            timestamp=NOW-timedelta(minutes=minutes), metadata=metadata, db_path=path)
    saved = append_message(role="user", content="Correction", channel="matrix", timestamp=NOW, db_path=path)
    append_message(role="assistant", content="Later comment", channel="matrix",
                   timestamp=NOW+timedelta(minutes=1), db_path=path)
    reference = _feedback_conversation_reference(now=NOW, rowid=saved["rowid"], db_path=path)
    assert [row["content"] for row in reference] == [OPENER]
    assert reference[0]["kind"] == "conversation_reference"
    assert "routine_ids" not in reference[0] and "external_id" not in reference[0]


@pytest.mark.parametrize("status,consumed", [
    ("none", False), ("applied", True), ("clarify", True), ("stale", True), ("error", True),
])
def test_only_explicit_no_feedback_receipt_leaves_other_flows_available(status, consumed):
    """Errors and routine-owned results must retain their existing arbitration."""
    from langchain_core.messages import SystemMessage
    from services.routine_completion_context import (
        build_dated_routine_feedback_context, routine_feedback_consumes_turn,
    )
    from services.routine_feedback_turn import FeedbackTurnResult
    context = build_dated_routine_feedback_context(FeedbackTurnResult(status))
    assert routine_feedback_consumes_turn(context) is consumed
    assert routine_feedback_consumes_turn(None) is False
    assert routine_feedback_consumes_turn(SystemMessage(content="legacy context")) is True
