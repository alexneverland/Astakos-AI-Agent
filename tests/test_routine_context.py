from datetime import datetime
import services.routine_context as rc


def test_build_runtime_routine_context_returns_expected_keys(monkeypatch):
    monkeypatch.setattr(rc, "resolve_alexandros_away_state", lambda now=None: True)
    monkeypatch.setattr(rc, "resolve_alexandros_away_reason", lambda now=None: "camp")
    monkeypatch.setattr(rc, "resolve_football_season", lambda now=None: False)
    monkeypatch.setattr(rc, "resolve_school_open", lambda now=None: False)
    monkeypatch.setattr(rc, "resolve_current_shift", lambda now=None: "afternoon")
    monkeypatch.setattr(rc, "resolve_sofia_work_mode", lambda now=None: "home")
    monkeypatch.setattr(rc, "resolve_user_at_work", lambda now=None: True)
    monkeypatch.setattr(rc, "resolve_quiet_hours", lambda now=None: False)

    result = rc.build_runtime_routine_context(datetime(2026, 6, 17))

    assert result["alexandros_away_from_home"] is True
    assert result["alexandros_away_reason"] == "camp"
    assert result["football_season"] is False
    assert result["school_open"] is False
    assert result["current_shift"] == "afternoon"
    assert result["sofia_work_mode"] == "home"
    assert result["user_at_work"] is True
    assert result["quiet_hours"] is False

def test_current_shift_returns_value_when_valid_context_state(monkeypatch):
    monkeypatch.setattr("memory.routine_db.get_context_state", lambda k: {"value": "afternoon", "expires_at": "2026-12-31"})
    assert rc.resolve_current_shift(datetime(2026, 6, 17)) == "afternoon"

def test_current_shift_returns_none_when_no_record(monkeypatch):
    monkeypatch.setattr("memory.routine_db.get_context_state", lambda k: None)
    assert rc.resolve_current_shift(datetime(2026, 6, 17)) is None

def test_current_shift_returns_none_when_expires_at_is_old(monkeypatch):
    monkeypatch.setattr("memory.routine_db.get_context_state", lambda k: {"value": "morning", "expires_at": "2026-06-16"})
    assert rc.resolve_current_shift(datetime(2026, 6, 17)) is None

def test_current_shift_ignores_invalid_value(monkeypatch):
    monkeypatch.setattr("memory.routine_db.get_context_state", lambda k: {"value": "evening", "expires_at": "2026-12-31"})
    assert rc.resolve_current_shift(datetime(2026, 6, 17)) is None

def test_current_shift_e2e_pipeline(tmp_path, monkeypatch):
    import memory.routine_db as routine_db
    from services.routine_reconciler import apply_routine_reconciliation_directives
    
    # 1. Setup a fresh temporary DB
    temp_db = tmp_path / "test_routines.db"
    monkeypatch.setattr(routine_db, "DB_PATH", str(temp_db))
    routine_db.setup_db()
    

    
    now = datetime(2026, 6, 17, 12, 0, 0)
    
    # 3. Fact triggers shift change
    from services.routine_reconciler import infer_routine_reconciliation_candidates
    fact = "[USER_FACT]: Αυτή την εβδομάδα έχω δουλειά απόγευμα."
    directives = infer_routine_reconciliation_candidates(
        fact, 
        category="family", 
        reason="user_stated", 
        now=now
    )
    
    # 4. Apply directives -> This should write to context_state
    apply_routine_reconciliation_directives(directives)
    
    # 5. Verify the full build reads it correctly
    monkeypatch.setattr(rc, "resolve_quiet_hours", lambda now=None: False)
    ctx = rc.build_runtime_routine_context(now)
    assert ctx["current_shift"] == "afternoon"

def test_current_shift_returns_weekday_override(monkeypatch):
    monkeypatch.setattr(
        "memory.routine_db.get_context_state",
        lambda k: {"value": "afternoon", "expires_at": "2026-12-31"} if k == "current_shift" else None
    )
    assert rc.resolve_current_shift(datetime(2026, 6, 17)) == "afternoon"  # Wednesday

def test_current_shift_returns_off_on_weekend_even_if_weekday_shift_exists(monkeypatch):
    monkeypatch.setattr(
        "memory.routine_db.get_context_state",
        lambda k: {"value": "afternoon", "expires_at": "2026-12-31"} if k == "current_shift" else None
    )
    assert rc.resolve_current_shift(datetime(2026, 6, 20)) == "off"  # Saturday

def test_current_shift_weekend_override_wins(monkeypatch):
    def fake_get_context_state(key):
        if key == "weekend_work_override":
            return {"value": "morning", "expires_at": "2026-12-31"}
        if key == "current_shift":
            return {"value": "afternoon", "expires_at": "2026-12-31"}
        return None

    monkeypatch.setattr("memory.routine_db.get_context_state", fake_get_context_state)
    assert rc.resolve_current_shift(datetime(2026, 6, 20)) == "morning"
