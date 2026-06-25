from datetime import datetime

def build_runtime_routine_context(now: datetime | None = None) -> dict:
    current = now or datetime.now()
    today = current.strftime("%Y-%m-%d")
    away_state = resolve_alexandros_away_state(current)

    ctx = {}
    try:
        from memory.routine_db import get_connection
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT key, value, expires_at FROM context_state")
        for row in c.fetchall():
            k, v, exp = row[0], row[1], row[2]
            if exp and exp < today:
                continue
            if str(v).lower() == "true":
                ctx[k] = True
            elif str(v).lower() == "false":
                ctx[k] = False
            else:
                ctx[k] = v
        conn.close()
    except Exception as e:
        print(f"Error loading dynamic context flags: {e}")

    ctx.update({
        "today": today,
        "alexandros_away_from_home": away_state,
        "alexandros_away_reason": resolve_alexandros_away_reason(current),
        "football_season": resolve_football_season(current),
        "school_open": resolve_school_open(current),
        "current_shift": resolve_current_shift(current),
        "sofia_work_mode": resolve_sofia_work_mode(current),
        "user_at_work": resolve_user_at_work(current),
        "user_out_of_home": resolve_user_out_of_home(current),
        "quiet_hours": resolve_quiet_hours(current),
    })
    ctx["alexandros_present"] = not bool(away_state)
    return ctx

def resolve_alexandros_away_state(now: datetime | None = None) -> bool | None:
    current = now or datetime.now()
    today = current.strftime("%Y-%m-%d")
    from memory.routine_db import get_context_state
    state_data = get_context_state("alexandros_away_from_home")
    if not state_data:
        return False
    expires_at = state_data.get("expires_at")
    if expires_at and expires_at < today:
        return False
    return str(state_data.get("value")).lower() == "true"

def resolve_alexandros_away_reason(now: datetime | None = None) -> str | None:
    current = now or datetime.now()
    today = current.strftime("%Y-%m-%d")
    from memory.routine_db import get_context_state
    state_data = get_context_state("alexandros_away_reason")
    if not state_data:
        return None
    expires_at = state_data.get("expires_at")
    if expires_at and expires_at < today:
        return None
    return str(state_data.get("value"))

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
    current = now or datetime.now()
    today = current.strftime("%Y-%m-%d")
    from memory.routine_db import get_context_state

    # 1. explicit weekend override (optional future-safe hook)
    weekend_override = get_context_state("weekend_work_override")
    if current.weekday() >= 5:
        if weekend_override:
            expires_at = weekend_override.get("expires_at")
            if not (expires_at and expires_at < today):
                val = str(weekend_override.get("value")).lower()
                if val in ("morning", "afternoon", "night"):
                    return val
        return "off"

    # 2. weekday shift override
    state_data = get_context_state("current_shift")
    if state_data:
        expires_at = state_data.get("expires_at")
        if not (expires_at and expires_at < today):
            val = str(state_data.get("value")).lower()
            if val in ("morning", "afternoon", "night"):
                return val

    return None

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

def resolve_user_out_of_home(now: datetime | None = None) -> bool:
    current = now or datetime.now()
    today = current.strftime("%Y-%m-%d")
    from memory.routine_db import get_context_state
    state_data = get_context_state("user_out_of_home")
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

    from clients.telegram_bot import QUIET_HOURS
    h = current.hour
    start, end = QUIET_HOURS

    if start == end:
        return False
    if start < end:
        return start <= h < end
    return h >= start or h < end
