from datetime import datetime

def build_runtime_routine_context(now: datetime | None = None) -> dict:
    current = now or datetime.now()

    return {
        "today": current.strftime("%Y-%m-%d"),
        "alexandros_at_camp": resolve_alexandros_camp_state(current),
        "football_season": resolve_football_season(current),
        "school_open": resolve_school_open(current),
        "current_shift": resolve_current_shift(current),
        "sofia_work_mode": resolve_sofia_work_mode(current),
        "user_at_work": resolve_user_at_work(current),
        "quiet_hours": resolve_quiet_hours(current),
    }

def resolve_alexandros_camp_state(now: datetime | None = None) -> bool | None:
    current = now or datetime.now()
    today = current.strftime("%Y-%m-%d")
    from memory.routine_db import get_context_state
    state_data = get_context_state("alexandros_at_camp")
    if not state_data:
        return False
    expires_at = state_data.get("expires_at")
    if expires_at and expires_at < today:
        return None
    return str(state_data.get("value")).lower() == "true"

def resolve_sofia_work_mode(now: datetime | None = None) -> str | None:
    current = now or datetime.now()
    today = current.strftime("%Y-%m-%d")
    from memory.routine_db import get_context_state
    state_data = get_context_state("sofia_work_mode")
    if not state_data:
        return "office"  # Default
    expires_at = state_data.get("expires_at")
    if expires_at and expires_at < today:
        return "office"
    return str(state_data.get("value")).lower()

def resolve_football_season(now: datetime | None = None) -> bool | None:
    current = now or datetime.now()
    today = current.strftime("%Y-%m-%d")
    from memory.routine_db import get_context_state
    state_data = get_context_state("football_season")
    if state_data:
        expires_at = state_data.get("expires_at")
        if not expires_at or expires_at >= today:
            return str(state_data.get("value")).lower() == "true"
    return True

def resolve_school_open(now: datetime | None = None) -> bool | None:
    current = now or datetime.now()
    today = current.strftime("%Y-%m-%d")
    from memory.routine_db import get_context_state
    state_data = get_context_state("school_open")
    if state_data:
        expires_at = state_data.get("expires_at")
        if not expires_at or expires_at >= today:
            return str(state_data.get("value")).lower() == "true"
    return True

def resolve_current_shift(now: datetime | None = None) -> str | None:
    from memory.runtime_state import get_current_shift
    return get_current_shift()

def resolve_user_at_work(now: datetime | None = None) -> bool:
    current = now or datetime.now()
    today = current.strftime("%Y-%m-%d")
    from memory.routine_db import get_context_state
    state_data = get_context_state("user_at_work")
    if state_data:
        expires_at = state_data.get("expires_at")
        if not expires_at or expires_at >= today:
            return str(state_data.get("value")).lower() == "true"
    return False

def resolve_quiet_hours(now: datetime | None = None) -> bool:
    current = now or datetime.now()
    today = current.strftime("%Y-%m-%d")
    from memory.routine_db import get_context_state
    state_data = get_context_state("quiet_hours")
    if state_data:
        expires_at = state_data.get("expires_at")
        if not expires_at or expires_at >= today:
            return str(state_data.get("value")).lower() == "true"
            
    # Fallback to defaults
    from clients.telegram_bot import QUIET_HOURS
    h = current.hour
    start, end = QUIET_HOURS
    return h >= start or h < end
