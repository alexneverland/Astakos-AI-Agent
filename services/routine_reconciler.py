import re
from datetime import datetime, timedelta


_ALEXANDROS_TOKENS = ["αλεξανδρ"]
_FOOTBALL_TOKENS = ["ποδοσφαιρ", "προπονησ"]
_SUMMER_BREAK_TOKENS = ["καλοκαιρ", "σταματ", "ξαναρχ", "σεπτεμβρ"]
_CAMP_TOKENS = ["κατασκην", "camp"]
_ABSENCE_TOKENS = ["λειπ", "μακρια", "απουσιαζ", "δεν θα ειναι", "δεν ειναι σπιτι"]
_RETURN_TOKENS = ["επιστρεφ", "γυρισ", "επεστρεψ", "ηρθε πισω", "ξαναγυρ"]
_ROUTINE_EXCLUDE_TOKENS = ["σοφια", "messenger", "μηνυμα", "δουλεια"]


def _normalize(text: str) -> str:
    import unicodedata

    raw = str(text or "").strip().lower()
    normalized = unicodedata.normalize("NFD", raw)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _contains_any(text: str, tokens: list[str]) -> bool:
    return any(tok in text for tok in tokens)


def _extract_iso_dates(text: str) -> list[str]:
    out = []

    for match in re.findall(r"\b(20\d{2}-\d{2}-\d{2})\b", text):
        out.append(match)

    for day, month, year in re.findall(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", text):
        try:
            out.append(datetime(int(year), int(month), int(day)).strftime("%Y-%m-%d"))
        except ValueError:
            continue

    unique = []
    for item in out:
        if item not in unique:
            unique.append(item)
    return unique


def _infer_relative_until(normalized_fact: str, *, now: datetime) -> str | None:
    match = re.search(r"(?:σε|για)\s+(\d{1,2})\s*(?:μερες|μερα|ημερες|ημερα)", normalized_fact)
    if not match:
        return None
    try:
        days = int(match.group(1))
    except ValueError:
        return None
    if days <= 0:
        return None
    return (now + timedelta(days=days)).strftime("%Y-%m-%d")


def _infer_september_resume(normalized_fact: str, *, now: datetime, explicit_dates: list[str]) -> str | None:
    for date_str in explicit_dates:
        if date_str[5:7] == "09":
            return date_str
    if "σεπτεμβρ" not in normalized_fact:
        return None
    year = now.year if now.strftime("%m-%d") <= "09-01" else now.year + 1
    return f"{year}-09-01"


def infer_routine_reconciliation_directives(
    fact: str,
    *,
    category: str,
    reason: str,
    now: datetime | None = None,
) -> list[dict]:
    """
    Μετατρέπει saved memory fact σε conservative routine-control directives.

    Design:
    - summer/school-season facts -> schedule pause
    - temporary absence/camp facts -> notification mute
    - return facts -> clear notification mute

    Δεν κάνει broad NLP. Πιάνει μόνο καθαρά patterns ώστε να μην πειράζει άσχετες
    ρουτίνες από απλές καθημερινές κουβέντες.
    """
    current = now or datetime.now()
    normalized_fact = _normalize(fact)
    dates = _extract_iso_dates(str(fact))
    directives: list[dict] = []

    if "[user_fact]" not in normalized_fact and reason not in {"user_stated", "agent_inferred"}:
        return directives

    # 1) Seasonal activity pause — π.χ. ποδόσφαιρο που σταμάτησε μέχρι Σεπτέμβριο
    if (
        _contains_any(normalized_fact, _ALEXANDROS_TOKENS)
        and _contains_any(normalized_fact, _FOOTBALL_TOKENS)
        and _contains_any(normalized_fact, _SUMMER_BREAK_TOKENS)
    ):
        until_date = _infer_september_resume(normalized_fact, now=current, explicit_dates=dates)
        if until_date:
            directives.append({
                "kind": "schedule_pause",
                "subject_tokens": _ALEXANDROS_TOKENS,
                "include_tokens": _FOOTBALL_TOKENS,
                "exclude_tokens": _ROUTINE_EXCLUDE_TOKENS,
                "until_date": until_date,
                "reason": "summer_break",
                "resume_rule": "every_september",
            })

    # 2) Temporary absence / camp — mute routine notifications until return
    absence_until = None
    if _contains_any(normalized_fact, _ALEXANDROS_TOKENS):
        if _contains_any(normalized_fact, _CAMP_TOKENS) or _contains_any(normalized_fact, _ABSENCE_TOKENS):
            if dates:
                absence_until = max(dates)
            else:
                absence_until = _infer_relative_until(normalized_fact, now=current)
        if absence_until:
            directives.append({
                "kind": "notifications_mute",
                "subject_tokens": _ALEXANDROS_TOKENS,
                "include_tokens": [],
                "exclude_tokens": _ROUTINE_EXCLUDE_TOKENS,
                "until_date": absence_until,
                "reason": "camp_absence" if _contains_any(normalized_fact, _CAMP_TOKENS) else "temporary_absence",
            })

    # 3) Return / back home — clear temporary notification mute
    if (
        _contains_any(normalized_fact, _ALEXANDROS_TOKENS)
        and _contains_any(normalized_fact, _RETURN_TOKENS)
        and (_contains_any(normalized_fact, _CAMP_TOKENS) or "σπιτι" in normalized_fact)
    ):
        directives.append({
            "kind": "notifications_unmute",
            "subject_tokens": _ALEXANDROS_TOKENS,
            "include_tokens": [],
            "exclude_tokens": _ROUTINE_EXCLUDE_TOKENS,
            "reason": "returned_home",
        })

    return directives


def apply_routine_reconciliation_directives(directives: list[dict]) -> dict:
    from memory.routine_db import (
        find_routines_for_reconciliation,
        get_routine_muted_until,
        get_routine_schedule_meta,
        set_routine_muted_until,
        clear_routine_muted_until,
        set_routine_paused_until,
        set_routine_resume_rule,
    )
    from memory.event_log import log_event

    stats = {
        "directives": len(directives),
        "matched_routines": 0,
        "schedule_paused": 0,
        "notifications_muted": 0,
        "notifications_unmuted": 0,
        "skipped": 0,
    }

    for directive in directives:
        routines = find_routines_for_reconciliation(
            subject_tokens=directive.get("subject_tokens") or [],
            include_tokens=directive.get("include_tokens") or [],
            exclude_tokens=directive.get("exclude_tokens") or [],
        )
        stats["matched_routines"] += len(routines)

        for routine in routines:
            r_id = routine["id"]
            label = routine["event"]
            kind = directive["kind"]

            if kind == "schedule_pause":
                meta = get_routine_schedule_meta(r_id)
                new_until = directive["until_date"]
                if meta.get("paused_until") and meta["paused_until"] >= new_until:
                    stats["skipped"] += 1
                    continue
                set_routine_paused_until(r_id, new_until, reason=directive.get("reason"))
                if directive.get("resume_rule"):
                    set_routine_resume_rule(r_id, directive["resume_rule"])
                stats["schedule_paused"] += 1
                log_event(
                    "routines",
                    "auto_schedule_pause",
                    routine_id=r_id,
                    event=label,
                    until_date=new_until,
                    reason=directive.get("reason"),
                    resume_rule=directive.get("resume_rule"),
                )
                continue

            if kind == "notifications_mute":
                new_until = directive["until_date"]
                existing_until = get_routine_muted_until(r_id)
                if existing_until and existing_until >= new_until:
                    stats["skipped"] += 1
                    continue
                set_routine_muted_until(r_id, new_until)
                stats["notifications_muted"] += 1
                log_event(
                    "routines",
                    "auto_notifications_mute",
                    routine_id=r_id,
                    event=label,
                    until_date=new_until,
                    reason=directive.get("reason"),
                )
                continue

            if kind == "notifications_unmute":
                existing_until = get_routine_muted_until(r_id)
                if not existing_until:
                    stats["skipped"] += 1
                    continue
                clear_routine_muted_until(r_id)
                stats["notifications_unmuted"] += 1
                log_event(
                    "routines",
                    "auto_notifications_unmute",
                    routine_id=r_id,
                    event=label,
                    reason=directive.get("reason"),
                )

    return stats


def reconcile_fact_to_routines(
    fact: str,
    *,
    category: str,
    reason: str,
    now: datetime | None = None,
) -> dict:
    directives = infer_routine_reconciliation_directives(
        fact,
        category=category,
        reason=reason,
        now=now,
    )
    if not directives:
        return {"applied": False, "directives": 0, "matched_routines": 0}

    stats = apply_routine_reconciliation_directives(directives)
    stats["applied"] = any(
        stats[key] > 0 for key in ("schedule_paused", "notifications_muted", "notifications_unmuted")
    )
    return stats
