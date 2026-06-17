from datetime import datetime
import services.routine_context as rc


def test_build_runtime_routine_context_returns_expected_keys(monkeypatch):
    monkeypatch.setattr(rc, "resolve_alexandros_camp_state", lambda now=None: True)
    monkeypatch.setattr(rc, "resolve_football_season", lambda now=None: False)
    monkeypatch.setattr(rc, "resolve_school_open", lambda now=None: False)
    monkeypatch.setattr(rc, "resolve_current_shift", lambda now=None: "afternoon")

    result = rc.build_runtime_routine_context(datetime(2026, 6, 17))

    assert result["alexandros_at_camp"] is True
    assert result["football_season"] is False
    assert result["school_open"] is False
    assert result["current_shift"] == "afternoon"

def test_resolve_current_shift_not_found(monkeypatch):
    monkeypatch.setattr("memory.routine_db.get_context_state", lambda k: None)
    assert rc.resolve_current_shift() is None

def test_resolve_current_shift_expired(monkeypatch):
    monkeypatch.setattr("memory.routine_db.get_context_state", lambda k: {"value": "afternoon", "expires_at": "2026-06-16"})
    now = datetime(2026, 6, 17)
    assert rc.resolve_current_shift(now) is None

def test_resolve_current_shift_valid(monkeypatch):
    monkeypatch.setattr("memory.routine_db.get_context_state", lambda k: {"value": "afternoon", "expires_at": "2026-06-20"})
    now = datetime(2026, 6, 17)
    assert rc.resolve_current_shift(now) == "afternoon"
