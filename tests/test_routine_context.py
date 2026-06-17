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
