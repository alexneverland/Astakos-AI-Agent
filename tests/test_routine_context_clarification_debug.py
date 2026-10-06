"""Bounded diagnostics and authenticated route contract."""
from datetime import datetime, timedelta
from pathlib import Path

from memory.routine_context_clarification import ATHENS, ClarificationStore, QuestionRequest
from services.routine_context_evidence import ContextEvidence


def test_diagnostics_never_return_private_question_or_coordinates(tmp_path):
    from services.routine_context_clarification_debug import clarification_diagnostics
    now = datetime(2026, 10, 6, 10, tzinfo=ATHENS)
    store = ClarificationStore(tmp_path / "state.json")
    store.reserve(QuestionRequest("q", "topic", ("1",), ("user_out_of_home",),
                  now + timedelta(minutes=12), "private wording", "matrix"), now=now)
    result = clarification_diagnostics(store.path, now, {"user_out_of_home": ContextEvidence(reason="stale")})
    assert result["pending"]["status"] == "reserved"
    assert result["evidence"]["user_out_of_home"]["reason"] == "stale"
    assert "private wording" not in str(result) and "question" not in result["pending"]


def test_missing_ledger_debug_has_no_write_side_effect(tmp_path):
    from services.routine_context_clarification_debug import clarification_diagnostics
    path = tmp_path / "missing.json"
    assert clarification_diagnostics(path, datetime.now(ATHENS), {})["pending"] is None
    assert list(tmp_path.iterdir()) == []


def test_latest_check_reports_recorded_skip_not_private_payload():
    from services.routine_context_clarification_debug import latest_clarification_check
    events = [{"action": "context_clarification_poll", "timestamp": "2026-10-06T10:00:00",
               "outcome": "recent_activity", "question": "private"},
              {"action": "routine_triggered", "timestamp": "2026-10-06T10:01:00"}]
    assert latest_clarification_check(events) == {"at": "2026-10-06T10:00:00", "outcome": "recent_activity"}
    assert latest_clarification_check([]) is None


def test_debug_runtime_retains_authentication_and_renders_clarification():
    import ast
    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root / "api/server.py").read_text(encoding="utf-8"))
    node = next(row for row in tree.body if isinstance(row, ast.AsyncFunctionDef) and row.name == "debug_runtime")
    assert "Depends(require_token)" in ast.unparse(node)
    assert '"context_clarification"' in ast.unparse(node) or "'context_clarification'" in ast.unparse(node)
    assert "Context clarification" in (root / "api/debug_dashboard.html").read_text(encoding="utf-8")
