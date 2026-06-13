import json
import os
from datetime import datetime

from tools.system import (
    _count_memory_audit_ops,
    _doctor_summarize_logs,
    _format_memory_ops_summary,
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
