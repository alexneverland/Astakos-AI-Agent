# ================================================================
# Tests: is_routine_temporarily_inactive_meta() — pure logic
# (no DB, purely state-machine cases A-E + backward-compat)
# ================================================================
from datetime import datetime

import pytest

from memory.routine_db import is_routine_temporarily_inactive_meta


_NOW = datetime(2026, 6, 17, 12, 0, 0)  # "today" in tests = 2026-06-17


def _meta(**kw):
    defaults = {
        "active_from": None, "active_until": None, "paused_until": None,
        "resume_rule": None, "pause_reason": None,
    }
    defaults.update(kw)
    return defaults


# ── A: paused_until in the future ⇒ inactive ──────────────────────

def test_paused_until_future_is_inactive():
    meta = _meta(paused_until="2026-09-01")
    inactive, reason = is_routine_temporarily_inactive_meta(meta, now=_NOW)
    assert inactive is True
    assert reason == "paused_until"


def test_paused_until_today_is_still_inactive():
    """paused_until == today ⇒ still paused (inclusive boundary)."""
    meta = _meta(paused_until="2026-06-17")
    inactive, reason = is_routine_temporarily_inactive_meta(meta, now=_NOW)
    assert inactive is True
    assert reason == "paused_until"


# ── B: paused_until in the past ⇒ active ──────────────────────

def test_paused_until_past_is_active():
    meta = _meta(paused_until="2026-01-01")
    inactive, reason = is_routine_temporarily_inactive_meta(meta, now=_NOW)
    assert inactive is False
    assert reason is None


# ── C: before active_from ⇒ inactive ─────────────────────────

def test_before_active_from_is_inactive():
    meta = _meta(active_from="2026-07-01")
    inactive, reason = is_routine_temporarily_inactive_meta(meta, now=_NOW)
    assert inactive is True
    assert reason == "before_active_from"


def test_active_from_today_is_active():
    """active_from == today ⇒ already started (inclusive boundary)."""
    meta = _meta(active_from="2026-06-17")
    inactive, reason = is_routine_temporarily_inactive_meta(meta, now=_NOW)
    assert inactive is False
    assert reason is None


# ── D: after active_until ⇒ inactive ─────────────────────────

def test_after_active_until_is_inactive():
    meta = _meta(active_until="2026-05-01")
    inactive, reason = is_routine_temporarily_inactive_meta(meta, now=_NOW)
    assert inactive is True
    assert reason == "after_active_until"


def test_active_until_today_is_active():
    """active_until == today ⇒ still valid today (inclusive boundary)."""
    meta = _meta(active_until="2026-06-17")
    inactive, reason = is_routine_temporarily_inactive_meta(meta, now=_NOW)
    assert inactive is False
    assert reason is None


# ── E: inside active window ⇒ active ─────────────────────────

def test_inside_active_window_is_active():
    meta = _meta(active_from="2026-01-01", active_until="2026-12-31")
    inactive, reason = is_routine_temporarily_inactive_meta(meta, now=_NOW)
    assert inactive is False
    assert reason is None


# ── Backward compatibility: no columns defined ───────────────

def test_all_fields_none_is_active_backward_compat():
    """Old routines without the new schedule fields must remain active."""
    meta = _meta()
    inactive, reason = is_routine_temporarily_inactive_meta(meta, now=_NOW)
    assert inactive is False
    assert reason is None


def test_missing_keys_in_dict_defaults_to_active():
    """A dict without any schedule keys at all should not crash."""
    inactive, reason = is_routine_temporarily_inactive_meta({}, now=_NOW)
    assert inactive is False
    assert reason is None


# ── Priority: paused_until overrides the active window check ──

def test_paused_until_takes_priority_over_active_window():
    """If it is BOTH paused AND inside the active window, pause wins."""
    meta = _meta(active_from="2026-01-01", active_until="2026-12-31",
                 paused_until="2026-09-01")
    inactive, reason = is_routine_temporarily_inactive_meta(meta, now=_NOW)
    assert inactive is True
    assert reason == "paused_until"


# ── now defaults to datetime.now() when omitted ────────────────

def test_now_defaults_to_current_time_when_omitted():
    """Without now=, the function must work with datetime.now() without raising an exception."""
    meta = _meta()
    inactive, reason = is_routine_temporarily_inactive_meta(meta)
    assert inactive is False
    assert reason is None


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {fn.__name__}: {e}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
