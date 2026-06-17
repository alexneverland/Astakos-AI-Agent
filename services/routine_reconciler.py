import re
from datetime import datetime, timedelta


# ── Subject tokens ───────────────────────────────────────────────────────────
_ALEXANDROS_TOKENS      = ["αλεξανδρ"]
_SOFIA_TOKENS           = ["σοφια"]

# ── Activity / event tokens ──────────────────────────────────────────────────
_FOOTBALL_TOKENS        = ["ποδοσφαιρ", "προπονησ"]
_BASKETBALL_TOKENS      = ["μπασκετ", "μπασκεμπολ"]
_CHILD_ACTIVITY_TOKENS  = _FOOTBALL_TOKENS + _BASKETBALL_TOKENS + ["δραστηριοτητ", "τμημα", "μαθημα"]
_SUMMER_BREAK_TOKENS    = ["καλοκαιρ", "σταματ", "ξαναρχ", "σεπτεμβρ"]
_CAMP_TOKENS            = ["κατασκην", "camp"]
_SCHOOL_TOKENS          = ["σχολει", "σχολικ"]
_SCHOOL_BREAK_TOKENS    = ["δεν εχει σχολει", "τελειωσε το σχολει", "διακοπ", "καλοκαιρ"]
_MORNING_TOKENS         = ["πρωι", "πρωιν", "ξυπνημ", "ετοιμασι"]

# ── State / action tokens ────────────────────────────────────────────────────
_ABSENCE_TOKENS         = ["λειπ", "μακρια", "απουσιαζ", "δεν θα ειναι", "δεν ειναι σπιτι"]
_RETURN_TOKENS          = ["επιστρεφ", "γυρισ", "επεστρεψ", "ηρθε πισω", "ξαναγυρ"]
_STOP_TOKENS            = ["σταματ", "δεν εχει", "δεν παει", "δεν θα παει", "τελειωσ"]
_SHIFT_PM_TOKENS        = ["απογευμα", "βραδυ", "βραδιν"]
_SHIFT_AM_TOKENS        = ["πρωι", "πρωιν"]
_WORK_TOKENS            = ["δουλει", "δουλευ", "βαρδι", "σεφτ"]
_WEEK_TOKENS            = ["εβδομαδ", "αυτη την εβδομαδ", "αυτη εβδομαδ"]

# ── Exclude tokens ───────────────────────────────────────────────────────────
_ROUTINE_EXCLUDE_TOKENS = ["messenger", "μηνυμα"]
_MESSENGER_EXCLUDE      = ["σχολει", "ποδοσφαιρ", "μπασκετ", "κατασκην"]

# ── Work-routine conflict targets ────────────────────────────────────────────
_WORK_DEPARTURE_TOKENS  = ["αναχωρησ", "φευγ", "δουλεια", "δουλειαν"]
_SLEEP_TOKENS           = ["υπνο", "κοιμ", "νυχτ"]
_LUNCH_TOKENS           = ["μεσημερ", "φαγητ", "γευμ"]


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

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


def _infer_week_until(now: datetime) -> str:
    """Επιστρέφει την Κυριακή της τρέχουσας εβδομάδας (end-of-week scope)."""
    days_to_sunday = 6 - now.weekday()  # Mon=0, Sun=6
    return (now + timedelta(days=days_to_sunday)).strftime("%Y-%m-%d")


def _infer_september_resume(normalized_fact: str, *, now: datetime, explicit_dates: list[str]) -> str | None:
    for date_str in explicit_dates:
        if date_str[5:7] == "09":
            return date_str
    if "σεπτεμβρ" not in normalized_fact:
        return None
    year = now.year if now.strftime("%m-%d") <= "09-01" else now.year + 1
    return f"{year}-09-01"


def _build_directive(
    kind: str,
    subject_tokens: list[str],
    include_tokens: list[str],
    exclude_tokens: list[str],
    *,
    until_date: str | None = None,
    reason: str | None = None,
    resume_rule: str | None = None,
) -> dict:
    """
    Κατασκευάζει directive dict με σταθερή δομή.
    - schedule_pause / notifications_unmute: απαιτεί subject_tokens.
    - notifications_mute: επιτρέπει κενό subject (match μόνο by include_tokens).
    - Για mute/pause: απαιτεί until_date.
    """
    if kind in ("schedule_pause", "notifications_unmute") and not subject_tokens:
        return {}
    if kind in ("schedule_pause", "notifications_mute") and not until_date:
        return {}
    d: dict = {
        "kind": kind,
        "subject_tokens": subject_tokens,
        "include_tokens": include_tokens,
        "exclude_tokens": exclude_tokens,
        "reason": reason,
    }
    if until_date:
        d["until_date"] = until_date
    if resume_rule:
        d["resume_rule"] = resume_rule
    return d



# ─────────────────────────────────────────────────────────────────────────────
# Rule groups
# ─────────────────────────────────────────────────────────────────────────────

def _rule_seasonal_football(normalized: str, dates: list[str], now: datetime) -> list[dict]:
    """Ποδόσφαιρο Αλέξανδρου σταμάτησε καλοκαίρι → schedule_pause μέχρι Σεπτέμβριο."""
    if not (
        _contains_any(normalized, _ALEXANDROS_TOKENS)
        and _contains_any(normalized, _FOOTBALL_TOKENS)
        and _contains_any(normalized, _SUMMER_BREAK_TOKENS)
    ):
        return []
    until = _infer_september_resume(normalized, now=now, explicit_dates=dates)
    if not until:
        return []
    d = _build_directive(
        "schedule_pause",
        subject_tokens=_ALEXANDROS_TOKENS,
        include_tokens=_FOOTBALL_TOKENS,
        exclude_tokens=_ROUTINE_EXCLUDE_TOKENS,
        until_date=until,
        reason="summer_break",
        resume_rule="every_september",
    )
    return [d] if d else []


def _rule_camp_absence(normalized: str, dates: list[str], now: datetime) -> list[dict]:
    """Αλέξανδρος λείπει / κατασκήνωση → notifications_mute."""
    if not _contains_any(normalized, _ALEXANDROS_TOKENS):
        return []
    if not (_contains_any(normalized, _CAMP_TOKENS) or _contains_any(normalized, _ABSENCE_TOKENS)):
        return []
    until = max(dates) if dates else _infer_relative_until(normalized, now=now)
    if not until:
        return []
    reason = "camp_absence" if _contains_any(normalized, _CAMP_TOKENS) else "temporary_absence"
    d = _build_directive(
        "notifications_mute",
        subject_tokens=_ALEXANDROS_TOKENS,
        include_tokens=[],
        exclude_tokens=_ROUTINE_EXCLUDE_TOKENS,
        until_date=until,
        reason=reason,
    )
    return [d] if d else []


def _rule_return_home(normalized: str) -> list[dict]:
    """Αλέξανδρος γύρισε → notifications_unmute."""
    if not (
        _contains_any(normalized, _ALEXANDROS_TOKENS)
        and _contains_any(normalized, _RETURN_TOKENS)
        and (_contains_any(normalized, _CAMP_TOKENS) or "σπιτι" in normalized)
    ):
        return []
    d = _build_directive(
        "notifications_unmute",
        subject_tokens=_ALEXANDROS_TOKENS,
        include_tokens=[],
        exclude_tokens=_ROUTINE_EXCLUDE_TOKENS,
        reason="returned_home",
    )
    return [d] if d else []


def _rule_school_break(normalized: str, dates: list[str], now: datetime) -> list[dict]:
    """
    Phase 3A — school_break:
    Facts: "δεν έχει σχολείο", "τελείωσε το σχολείο", "από αύριο διακοπές"
    Target: σχολικές + πρωινές ρουτίνες Αλέξανδρου
    Action: schedule_pause — απαιτεί σαφές scope.
    """
    has_school_break = _contains_any(normalized, _SCHOOL_BREAK_TOKENS)
    has_school_ref   = _contains_any(normalized, _SCHOOL_TOKENS)
    if not (has_school_break or has_school_ref):
        return []
    until = None
    if dates:
        until = max(dates)
    else:
        until = _infer_september_resume(normalized, now=now, explicit_dates=dates)
        if not until:
            until = _infer_relative_until(normalized, now=now)
    if not until:
        return []
    d = _build_directive(
        "schedule_pause",
        subject_tokens=_ALEXANDROS_TOKENS,
        include_tokens=_SCHOOL_TOKENS + _MORNING_TOKENS,
        exclude_tokens=_ROUTINE_EXCLUDE_TOKENS,
        until_date=until,
        reason="school_break",
        resume_rule="every_september",
    )
    return [d] if d else []


def _rule_shift_week(normalized: str, now: datetime) -> list[dict]:
    """
    Phase 3A — shift_week:
    Facts: "αυτή την εβδομάδα έχω απόγευμα", "δουλεύω πρωί αυτή την εβδομάδα"
    Target: conflicting departure / lunch / sleep routines
    Action: notifications_mute μέχρι Κυριακή — ΟΧΙ full reschedule.

    Guard: work + week + shift — και τα τρία πρέπει να υπάρχουν.
    """
    has_work  = _contains_any(normalized, _WORK_TOKENS)
    has_week  = _contains_any(normalized, _WEEK_TOKENS)
    has_shift = _contains_any(normalized, _SHIFT_PM_TOKENS) or _contains_any(normalized, _SHIFT_AM_TOKENS)
    if not (has_work and has_week and has_shift):
        return []
    until = _infer_week_until(now)
    if _contains_any(normalized, _SHIFT_PM_TOKENS):
        include = _WORK_DEPARTURE_TOKENS + _LUNCH_TOKENS
        reason  = "shift_afternoon_week"
    else:
        include = _SLEEP_TOKENS
        reason  = "shift_morning_week"
    # subject_tokens=[] → match μόνο by include_tokens (ο χρήστης ο ίδιος)
    d = _build_directive(
        "notifications_mute",
        subject_tokens=[],
        include_tokens=include,
        exclude_tokens=_ALEXANDROS_TOKENS + _SOFIA_TOKENS,
        until_date=until,
        reason=reason,
    )
    return [d] if d else []


def _rule_temporary_absence_other_person(normalized: str, dates: list[str], now: datetime) -> list[dict]:
    """
    Phase 3A — temporary_absence_other_person:
    Facts: "η Σοφία δουλεύει πρωί όλη την εβδομάδα", "η Σοφία λείπει"
    Target: Messenger/Sofia proactive ρουτίνες
    Action: soft notifications_mute — όχι βαριές αλλαγές.

    Guard: Σοφία + absence/work + scope.
    """
    has_sofia   = _contains_any(normalized, _SOFIA_TOKENS)
    has_absence = _contains_any(normalized, _ABSENCE_TOKENS) or _contains_any(normalized, _WORK_TOKENS)
    if not (has_sofia and has_absence):
        return []
    until = None
    if dates:
        until = max(dates)
    elif _contains_any(normalized, _WEEK_TOKENS):
        until = _infer_week_until(now)
    else:
        until = _infer_relative_until(normalized, now=now)
    if not until:
        return []
    d = _build_directive(
        "notifications_mute",
        subject_tokens=_SOFIA_TOKENS,
        include_tokens=["σοφια", "messenger", "μηνυμα"],
        exclude_tokens=_MESSENGER_EXCLUDE,
        until_date=until,
        reason="sofia_absent_or_shifted",
    )
    return [d] if d else []


def _rule_child_activity_pause(normalized: str, dates: list[str], now: datetime) -> list[dict]:
    """
    Phase 3A — child_activity_pause:
    Facts: "σταμάτησε το μπάσκετ", "δεν έχει ποδόσφαιρο αυτή την εβδομάδα"
    Target: παιδικές δραστηριότητες
    Action: schedule_pause μέχρι explicit date ή end-of-week.

    Guard: stop + activity + child subject — και τα τρία.
    """
    has_child    = (
        _contains_any(normalized, _ALEXANDROS_TOKENS)
        or "παιδι" in normalized
        or "μικρ" in normalized
    )
    has_activity = _contains_any(normalized, _CHILD_ACTIVITY_TOKENS)
    has_stop     = _contains_any(normalized, _STOP_TOKENS)
    if not (has_child and has_activity and has_stop):
        return []
    until = None
    if dates:
        until = max(dates)
    elif _contains_any(normalized, _WEEK_TOKENS):
        until = _infer_week_until(now)
    else:
        until = _infer_september_resume(normalized, now=now, explicit_dates=dates)
        if not until:
            until = _infer_relative_until(normalized, now=now)
    if not until:
        return []
    if _contains_any(normalized, _BASKETBALL_TOKENS):
        include = _BASKETBALL_TOKENS
        reason  = "child_basketball_pause"
    elif _contains_any(normalized, _FOOTBALL_TOKENS):
        include = _FOOTBALL_TOKENS
        reason  = "child_football_pause"
    else:
        include = _CHILD_ACTIVITY_TOKENS
        reason  = "child_activity_pause"
    d = _build_directive(
        "schedule_pause",
        subject_tokens=_ALEXANDROS_TOKENS,
        include_tokens=include,
        exclude_tokens=_ROUTINE_EXCLUDE_TOKENS,
        until_date=until,
        reason=reason,
    )
    return [d] if d else []


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def infer_routine_reconciliation_directives(
    fact: str,
    *,
    category: str,
    reason: str,
    now: datetime | None = None,
) -> list[dict]:
    """
    Μετατρέπει saved memory fact σε conservative routine-control directives.

    Κάθε rule group είναι ανεξάρτητο και deterministic.
    Directive παράγεται μόνο αν: σαφές subject + σαφές time scope.

    Rule groups:
    1. seasonal_football              — ποδόσφαιρο Αλέξανδρου καλοκαίρι
    2. camp_absence                   — κατασκήνωση / απουσία Αλέξανδρου
    3. return_home                    — επιστροφή Αλέξανδρου
    4. school_break                   — σχολικές διακοπές          [Phase 3A]
    5. child_activity_pause           — παιδική δραστηριότητα pause [Phase 3A]
    6. temporary_absence_other_person — Σοφία λείπει/δουλεύει       [Phase 3A]
    7. shift_week                     — εβδομαδιαία αλλαγή βάρδιας  [Phase 3A]
    """
    current         = now or datetime.now()
    normalized_fact = _normalize(fact)
    dates           = _extract_iso_dates(str(fact))
    directives: list[dict] = []

    if "[user_fact]" not in normalized_fact and reason not in {"user_stated", "agent_inferred"}:
        return directives

    rules = [
        (_rule_seasonal_football,              (normalized_fact, dates, current)),
        (_rule_camp_absence,                   (normalized_fact, dates, current)),
        (_rule_school_break,                   (normalized_fact, dates, current)),
        (_rule_child_activity_pause,           (normalized_fact, dates, current)),
        (_rule_temporary_absence_other_person, (normalized_fact, dates, current)),
        (_rule_shift_week,                     (normalized_fact, current)),
        (_rule_return_home,                    (normalized_fact,)),
    ]
    for rule_fn, args in rules:
        directives.extend(rule_fn(*args))

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
            r_id  = routine["id"]
            label = routine["event"]
            kind  = directive["kind"]

            if kind == "schedule_pause":
                meta      = get_routine_schedule_meta(r_id)
                new_until = directive["until_date"]
                if meta.get("paused_until") and meta["paused_until"] >= new_until:
                    stats["skipped"] += 1
                    continue
                set_routine_paused_until(r_id, new_until, reason=directive.get("reason"))
                if directive.get("resume_rule"):
                    set_routine_resume_rule(r_id, directive["resume_rule"])
                stats["schedule_paused"] += 1
                log_event(
                    "routines", "auto_schedule_pause",
                    routine_id=r_id, event=label,
                    until_date=new_until,
                    reason=directive.get("reason"),
                    resume_rule=directive.get("resume_rule"),
                )
                continue

            if kind == "notifications_mute":
                new_until      = directive["until_date"]
                existing_until = get_routine_muted_until(r_id)
                if existing_until and existing_until >= new_until:
                    stats["skipped"] += 1
                    continue
                set_routine_muted_until(r_id, new_until)
                stats["notifications_muted"] += 1
                log_event(
                    "routines", "auto_notifications_mute",
                    routine_id=r_id, event=label,
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
                    "routines", "auto_notifications_unmute",
                    routine_id=r_id, event=label,
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
        stats[key] > 0
        for key in ("schedule_paused", "notifications_muted", "notifications_unmuted")
    )
    return stats
