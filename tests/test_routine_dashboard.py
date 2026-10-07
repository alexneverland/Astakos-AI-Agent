from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import subprocess
import shutil

import pytest

from api.server import (
    _latest_routine_outcome,
    _routine_outcome_fields,
    _routine_outcome_label,
)
from core.i18n import t


def test_dashboard_label_mapper() -> None:
    """Renders readable labels for scheduler and manual routine outcomes."""
    assert _routine_outcome_label("routine_condition_blocked") == "Blocked by condition"
    assert _routine_outcome_label("routine_cooldown_skip") == "Skipped: cooldown"
    assert _routine_outcome_label("routine_triggered") == "Sent"
    assert _routine_outcome_label("preemptive_completed") == "Completed today"
    assert _routine_outcome_label("confirmed") == "Confirmed"
    assert _routine_outcome_label("routine_acknowledged") == t("api.server.routine_outcome_acknowledged")
    assert _routine_outcome_label("routine_skipped_today") == t("api.server.routine_outcome_skipped_today")
    assert _routine_outcome_label("routine_paused") == t("api.server.routine_outcome_paused")
    assert _routine_outcome_label("routine_response_window_expired") == t("api.server.routine_outcome_response_window_expired")
    assert _routine_outcome_label("routine_unanswered_decay") == t("api.server.routine_outcome_unanswered_decay")
    assert _routine_outcome_label("unknown_action") == "Recorded: Unknown action"


def test_missing_event_has_no_dashboard_outcome() -> None:
    """Keeps the dashboard's no-event state distinct from lifecycle outcomes."""
    assert _latest_routine_outcome([], 123) is None
    assert _routine_outcome_fields([], 123)["last_outcome_label"] == "Not evaluated"


def test_latest_event_is_picked_including_manual_completion() -> None:
    """Includes manual completion events that do not use the routine_ prefix."""
    today_events = [
        {"routine_id": 123, "action": "routine_condition_allowed", "timestamp": "2026-06-26T10:00:00"},
        {"routine_id": 123, "action": "preemptive_completed", "timestamp": "2026-06-26T10:05:00"},
        {"routine_id": 999, "action": "routine_triggered", "timestamp": "2026-06-26T10:10:00"},
    ]

    latest = _latest_routine_outcome(today_events, 123)

    assert latest is not None
    assert latest["action"] == "preemptive_completed"
    assert _routine_outcome_label(latest["action"]) == "Completed today"


def test_non_active_routine_receives_pause_outcome_fields() -> None:
    """Keeps a paused routine's lifecycle result visible after its state changes."""
    fields = _routine_outcome_fields(
        [{"routine_id": 42, "action": "routine_paused", "timestamp": "2026-07-30T09:30:00"}],
        42,
    )

    assert fields == {
        "last_outcome_action": "routine_paused",
        "last_outcome_label": t("api.server.routine_outcome_paused"),
        "last_outcome_ts": "2026-07-30T09:30:00",
        "last_outcome_reason": None,
    }


def test_dashboard_indefinite_pause_contract_is_rendered() -> None:
    """The runtime payload and dashboard UI both preserve the indefinite-pause state."""
    project_root = Path(__file__).resolve().parent.parent
    server_source = (project_root / "api" / "server.py").read_text(encoding="utf-8")
    dashboard_source = (project_root / "api" / "debug_dashboard.html").read_text(encoding="utf-8")

    assert '"paused_indefinitely": bool(paused_indefinitely)' in server_source
    assert "r.paused_indefinitely" in dashboard_source
    assert "PAUSED INDEFINITELY" in dashboard_source


def test_condition_pass_does_not_replace_a_dispatch_block() -> None:
    """A later diagnostic check is not evidence that a reminder was delivered."""
    events = [
        {"routine_id": 11, "action": "routine_cooldown_skip", "timestamp": "2026-10-07T09:00:00", "reason": "cooldown"},
        {"routine_id": 11, "action": "routine_condition_allowed", "timestamp": "2026-10-07T09:01:00"},
    ]
    fields = _routine_outcome_fields(events, 11)
    assert fields["last_outcome_action"] == "routine_cooldown_skip"
    assert fields["last_outcome_ts"] == "2026-10-07T09:00:00"
    assert fields["last_condition_check_action"] == "routine_condition_allowed"
    assert fields["last_condition_check_ts"] == "2026-10-07T09:01:00"


def test_condition_only_is_not_a_final_outcome() -> None:
    """Unknown delivery stays unknown even when all conditions passed."""
    fields = _routine_outcome_fields([{"routine_id": 11, "action": "routine_condition_allowed"}], 11)
    assert fields["last_outcome_action"] is None
    assert fields["last_condition_check_action"] == "routine_condition_allowed"


def test_new_confirmed_send_replaces_previous_block() -> None:
    """Preserving a block must not hide an actual later transport success."""
    events = [
        {"routine_id": 11, "action": "routine_cooldown_skip"},
        {"routine_id": 11, "action": "routine_triggered"},
        {"routine_id": 11, "action": "routine_condition_allowed"},
    ]
    assert _latest_routine_outcome(events, 11)["action"] == "routine_triggered"


def test_debug_cooldown_preserves_zero_and_distinguishes_legacy_effective_value() -> None:
    """Debug reports storage faithfully without pretending staged policy is active."""
    from services.routine_feedback_debug import cooldown_diagnostics
    now = datetime(2026, 10, 7, 10, tzinfo=ZoneInfo("Europe/Athens"))
    result = cooldown_diagnostics(0, "2026-10-07T09:00:00", effective_hours=4, now=now)
    assert result["cooldown_hours"] == 0
    assert result["effective_cooldown_hours"] == 4
    assert result["cooldown_remaining_h"] == 3
    assert result["cooldown_read_error"] is False


def test_debug_cooldown_handles_offset_timestamp_and_corruption() -> None:
    """UTC receipts are measured as instants, and invalid state is not shown as zero."""
    from services.routine_feedback_debug import cooldown_diagnostics
    now = datetime(2026, 10, 7, 10, tzinfo=ZoneInfo("Europe/Athens"))
    valid = cooldown_diagnostics(20, "2026-10-07T06:00:00+00:00", effective_hours=20, now=now)
    assert valid["cooldown_remaining_h"] == 19
    broken = cooldown_diagnostics(20, "invalid", effective_hours=20, now=now)
    assert broken["cooldown_remaining_h"] is None
    assert broken["cooldown_read_error"] is True


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for dashboard JavaScript")
def test_dashboard_renders_separate_decision_and_staged_feedback() -> None:
    """Execute the actual JS renderers offline, including escaping and zero values."""
    source = Path(__file__).resolve().parent.parent / "api" / "debug_dashboard.html"
    script = r"""
      const fs = require('fs'), assert = require('assert');
      const html = fs.readFileSync(process.argv[1], 'utf8');
      for (const block of html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)) new Function(block[1]);
      const part = html.slice(html.indexOf('  function renderOutcome(r)'), html.indexOf('  const evts ='));
      const esc = x => String(x).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
      const render = new Function('esc','r', part + '\nreturn renderOutcome(r) + renderRoutineFeedback(r) + renderRoutineCooldown(r);');
      const output = render(esc, {last_outcome_label:'Skipped: cooldown',
        last_outcome_reason:'<unsafe>', last_condition_check_action:'routine_condition_allowed',
        cooldown_hours:0,effective_cooldown_hours:4,cooldown_remaining_h:3,
        feedback_diagnostics:{status:'uninitialized'}});
      assert(output.includes('Skipped: cooldown'));
      assert(output.includes('Latest condition check: passed'));
      assert(output.includes('&lt;unsafe&gt;'));
      assert(!output.includes('<unsafe>'));
      assert(output.includes('Stored: 0h'));
      assert(output.includes('Scheduler: 4h'));
      assert(output.includes('Dated feedback: not activated'));
      const recorded = render(esc, {feedback_diagnostics:{status:'recorded',
        derived_cooldown_hours:20,unanswered_streak:2,refusal_streak:0,
        today:{date:'2026-10-07',feedback:'acknowledge',delivered_at:null},
        backoff_until:'2026-10-08T12:00:00+03:00'}});
      assert(recorded.includes('Staged policy preview'));
      assert(recorded.includes('Unanswered days: 2 / 3'));
      assert(recorded.includes('acknowledge'));
      const active = render(esc, {feedback_diagnostics:{status:'recorded', active:true,
        derived_cooldown_hours:0, unanswered_streak:0, refusal_streak:0}});
      assert(active.includes('Active dated feedback policy'));
      assert(!active.includes('Staged policy preview'));
    """
    result = subprocess.run(["node", "-e", script, str(source)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
