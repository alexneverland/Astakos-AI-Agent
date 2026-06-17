from datetime import datetime

from memory.routine_db import get_connection


def build_runtime_routine_context(now: datetime | None = None) -> dict:
    current = now or datetime.now()

    return {
        "today": current.strftime("%Y-%m-%d"),
        "alexandros_at_camp": resolve_alexandros_camp_state(current),
        "football_season": resolve_football_season(current),
        "school_open": resolve_school_open(current),
        "current_shift": resolve_current_shift(current),
    }


def resolve_alexandros_camp_state(now: datetime | None = None) -> bool | None:
    current = now or datetime.now()
    today = current.strftime("%Y-%m-%d")

    conn = get_connection()
    cursor = conn.cursor()

    rows = cursor.execute(
        """
        SELECT event_name, muted_until
        FROM routines
        WHERE state IN ('active', 'learned')
        """
    ).fetchall()

    conn.close()

    for event_name, muted_until in rows:
        text = (event_name or "").lower()
        if "αλέξανδρ" in text or "αλεξανδρ" in text:
            if muted_until and muted_until >= today:
                return True

    return False


def resolve_football_season(now: datetime | None = None) -> bool | None:
    current = now or datetime.now()
    today = current.strftime("%Y-%m-%d")

    conn = get_connection()
    cursor = conn.cursor()

    rows = cursor.execute(
        """
        SELECT event_name, paused_until, resume_rule
        FROM routines
        WHERE state IN ('active', 'learned')
        """
    ).fetchall()

    conn.close()

    for event_name, paused_until, resume_rule in rows:
        text = (event_name or "").lower()
        if "ποδόσφαιρ" in text or "ποδοσφαιρ" in text:
            if paused_until and paused_until >= today and resume_rule == "every_september":
                return False

    return True


def resolve_school_open(now: datetime | None = None) -> bool | None:
    current = now or datetime.now()
    today = current.strftime("%Y-%m-%d")

    conn = get_connection()
    cursor = conn.cursor()

    rows = cursor.execute(
        """
        SELECT event_name, paused_until, pause_reason
        FROM routines
        WHERE state IN ('active', 'learned')
        """
    ).fetchall()

    conn.close()

    for event_name, paused_until, pause_reason in rows:
        text = (event_name or "").lower()
        if "σχολ" in text:
            if paused_until and paused_until >= today and pause_reason == "school_break":
                return False

    return True


def resolve_current_shift(now: datetime | None = None) -> str | None:
    # MVP: δεν έχουμε ακόμα structured source of truth
    # άρα άστο None στην αρχή μέχρι να δέσεις reliable source.
    return None
