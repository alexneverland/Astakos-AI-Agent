import json
import os
from datetime import datetime

from tools.system import (
    _count_memory_audit_ops,
    _doctor_summarize_logs,
    _doctor_status_label,
    _filter_memory_audit_entries,
    _format_memory_ops_summary,
    _format_pending_routines,
    memory_review,
    system_doctor,
)


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_doctor_summarize_logs_counts_events_and_trace_issues(tmp_path):
    today = datetime.now().date().isoformat()
    _write_json(
        tmp_path / "logs" / "events" / f"{today}.json",
        [
            {"job": "proactive", "action": "complete"},
            {"job": "fit_briefing", "action": "error", "error": "boom"},
        ],
    )
    _write_json(
        tmp_path / "logs" / "traces" / f"{today}.json",
        [
            {
                "timestamp": f"{today}T10:00:00",
                "agent": "Chat_Agent",
                "user_message": "ok",
                "duration_ms": 1000,
                "tool_calls": [],
            },
            {
                "timestamp": f"{today}T10:01:00",
                "agent": "tool_loop_block",
                "user_message": "loop",
                "duration_ms": 50000,
                "loop_guard": True,
                "tool_calls": [{"tool": "x", "error": False}],
            },
            {
                "timestamp": f"{today}T10:02:00",
                "agent": "Home_Agent",
                "user_message": "tool error",
                "duration_ms": 1200,
                "tool_calls": [{"tool": "x", "error": True}],
            },
        ],
    )

    result = _doctor_summarize_logs(days=1, root=str(tmp_path), slow_ms=45000)

    assert result["events"] == 2
    assert result["event_errors"] == 1
    assert result["traces"] == 3
    assert result["trace_issues"] == 2
    assert result["loop_guards"] == 1
    assert result["slow_traces"] == 1
    assert len(result["last_issues"]) == 2


def test_system_doctor_tool_returns_readable_report():
    result = system_doctor.invoke({"days": 1})

    assert isinstance(result, str)
    assert "Astakos Doctor" in result
    assert "Logs" in result
    assert "Pending approvals" in result
    assert "Memory ops" in result


def test_memory_audit_ops_summary_counts_main_operations():
    counts = _count_memory_audit_ops([
        {"op": "add"},
        {"op": "overwrite"},
        {"op": "skip_duplicate"},
        {"op": "skip_keep_old"},
        {"op": "reflection_saved"},
        {"op": "reflection_applied"},
    ])

    assert counts["total"] == 6
    assert counts["add"] == 1
    assert counts["overwrite"] == 1
    assert counts["skip_duplicate"] == 1
    assert counts["skip_keep_old"] == 1
    assert counts["reflection"] == 2
    assert _format_memory_ops_summary(counts) == "6 ops (add 1, overwrite 1, skipped 2, reflections 2)"


def test_memory_review_tool_returns_readable_report():
    result = memory_review.invoke({"days": 1})

    assert isinstance(result, str)
    assert "Memory Review" in result


def test_doctor_status_label_escalates_by_severity():
    assert _doctor_status_label(warnings=[], pending_actions=[], logs={"event_errors": 0, "trace_issues": 0, "loop_guards": 0}) == "OK"
    assert _doctor_status_label(warnings=[], pending_actions=[{"tool_name": "x"}], logs={"event_errors": 0, "trace_issues": 0, "loop_guards": 0}) == "Προσοχή"
    assert _doctor_status_label(warnings=[], pending_actions=[], logs={"event_errors": 0, "trace_issues": 1, "loop_guards": 0}) == "Προσοχή"
    assert _doctor_status_label(warnings=[], pending_actions=[], logs={"event_errors": 1, "trace_issues": 0, "loop_guards": 0}) == "Άμεσος έλεγχος"


def test_format_pending_routines_includes_event_names():
    result = _format_pending_routines({
        12: {"event": "Σύνταξη μηνύματος στη Σοφία", "sent_at": object()},
        13: {"event": "Πάρκο με Αλέξανδρο", "sent_at": object()},
    })

    assert result.startswith("2 — ")
    assert "Σύνταξη μηνύματος στη Σοφία" in result
    assert "Πάρκο με Αλέξανδρο" in result


def test_filter_memory_audit_entries_by_op_and_category():
    entries = [
        {"op": "add", "category": "family", "fact": "a"},
        {"op": "overwrite", "category": "family", "fact": "b"},
        {"op": "skip_duplicate", "category": "projects", "fact": "c"},
        {"op": "reflection_saved", "category": "", "fact": "d"},
    ]

    assert [e["fact"] for e in _filter_memory_audit_entries(entries, op="add")] == ["a"]
    assert [e["fact"] for e in _filter_memory_audit_entries(entries, op="skip")] == ["c"]
    assert [e["fact"] for e in _filter_memory_audit_entries(entries, op="reflection")] == ["d"]
    assert [e["fact"] for e in _filter_memory_audit_entries(entries, category="family")] == ["a", "b"]
    assert [e["fact"] for e in _filter_memory_audit_entries(entries, op="overwrite", category="family")] == ["b"]
