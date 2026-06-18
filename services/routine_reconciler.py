import re
from datetime import datetime, timedelta


# ── Subject tokens ───────────────────────────────────────────────────────────
_ALEXANDROS_TOKENS      = ["αλεξανδρ"]
_SOFIA_TOKENS           = ["σοφια"]

# ── Activity / event tokens ──────────────────────────────────────────────────
_FOOTBALL_TOKENS        = ["ποδοσφαιρο", "προπονηση", "μπαλα"]
_BASKETBALL_TOKENS      = ["μπασκετ", "μπασκεμπολ"]
_CHILD_ACTIVITY_TOKENS  = _FOOTBALL_TOKENS + _BASKETBALL_TOKENS + ["δραστηριοτητ", "τμημα", "μαθημα"]
_SUMMER_BREAK_TOKENS    = ["καλοκαιρ", "σταματ", "ξαναρχ", "σεπτεμβρ"]
_CAMP_TOKENS            = ["κατασκηνωση", "camp"]
_SCHOOL_TOKENS          = ["σχολει", "σχολικ"]
_SCHOOL_BREAK_TOKENS    = ["δεν εχει σχολει", "τελειωσε το σχολει", "διακοπ", "καλοκαιρ"]
_MORNING_TOKENS         = ["πρωι", "πρωιν", "ξυπνημ", "ετοιμασι"]
_GRANDMA_TOKENS         = ["γιαγια"]
_TRIP_TOKENS            = ["διακοπ", "ταξιδ", "εκδρομ"]

# ── State / action tokens ────────────────────────────────────────────────────
_ABSENCE_TOKENS         = ["λειπει", "εφυγε", "δεν ειναι εδω", "απουσιαζει"]
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

# ── Scoring thresholds [Phase 3B] ────────────────────────────────────────────
_AUTO_APPLY_THRESHOLD = 0.80   # score >= this → auto-apply
_DEBUG_ONLY_THRESHOLD = 0.55   # score in [this, AUTO_APPLY) → log, no apply
# score < _DEBUG_ONLY_THRESHOLD → silent reject


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


def _build_condition_directive(
    *,
    subject_tokens: list[str],
    include_tokens: list[str],
    exclude_tokens: list[str],
    condition_type: str,
    condition_payload: dict,
    condition_mode: str,
    reason: str | None = None,
) -> dict:
    if not condition_type or not condition_payload or not condition_mode:
        return {}

    return {
        "kind": "condition_add",
        "subject_tokens": subject_tokens,
        "include_tokens": include_tokens,
        "exclude_tokens": exclude_tokens,
        "condition_type": condition_type,
        "condition_payload": condition_payload,
        "condition_mode": condition_mode,
        "reason": reason,
    }

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


def _clamp_score(value: float) -> float:
    return max(0.0, min(1.0, round(value, 2)))


def _append_signal(signals: list[str], label: str) -> None:
    if label not in signals:
        signals.append(label)


def _append_flag(flags: list[str], label: str) -> None:
    if label not in flags:
        flags.append(label)


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
    
    d_state = {
        "kind": "context_state_set",
        "key": "football_season",
        "value": "false",
        "until_date": until,
        "reason": "summer_break",
        "subject_tokens": _ALEXANDROS_TOKENS,
        "include_tokens": _FOOTBALL_TOKENS,
        "exclude_tokens": _ROUTINE_EXCLUDE_TOKENS,
    }
    
    cond = _build_condition_directive(
        subject_tokens=_ALEXANDROS_TOKENS,
        include_tokens=_FOOTBALL_TOKENS,
        exclude_tokens=_ROUTINE_EXCLUDE_TOKENS,
        condition_type="context_flag",
        condition_payload={"flag": "football_season", "equals": True},
        condition_mode="allow_when_true",
        reason="seasonal_football_condition",
    )

    return [d_state] + ([cond] if cond else [])


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
    
    # 3C.2: Global state AND routine condition
    d_state_home = {
        "kind": "context_state_set",
        "key": "alexandros_away_from_home",
        "value": "true",
        "until_date": until,
        "reason": reason,
        "subject_tokens": _ALEXANDROS_TOKENS,
        "include_tokens": [],
        "exclude_tokens": [],
    }
    d_state_reason = {
        "kind": "context_state_set",
        "key": "alexandros_away_reason",
        "value": "camp",
        "until_date": until,
        "reason": reason,
        "subject_tokens": _ALEXANDROS_TOKENS,
        "include_tokens": [],
        "exclude_tokens": [],
    }
    cond = _build_condition_directive(
        subject_tokens=_ALEXANDROS_TOKENS,
        include_tokens=[],
        exclude_tokens=_ROUTINE_EXCLUDE_TOKENS,
        condition_type="context_flag",
        condition_payload={"flag": "alexandros_away_from_home", "equals": True},
        condition_mode="suppress_when_true",
        reason="camp_absence_condition",
    )
    
    return [d_state_home, d_state_reason] + ([cond] if cond else [])


def _rule_return_home(normalized: str) -> list[dict]:
    """Αλέξανδρος γύρισε → context_state_set (alexandros_at_camp = false)."""
    if not (
        _contains_any(normalized, _ALEXANDROS_TOKENS)
        and _contains_any(normalized, _RETURN_TOKENS)
        and (_contains_any(normalized, _CAMP_TOKENS) or "σπιτι" in normalized)
    ):
        return []
    
    d_state_home = {
        "kind": "context_state_set",
        "key": "alexandros_away_from_home",
        "value": "false",
        "until_date": None,
        "reason": "returned_home",
        "subject_tokens": _ALEXANDROS_TOKENS,
        "include_tokens": [],
        "exclude_tokens": [],
    }
    d_state_reason = {
        "kind": "context_state_set",
        "key": "alexandros_away_reason",
        "value": "",
        "until_date": None,
        "reason": "returned_home",
        "subject_tokens": _ALEXANDROS_TOKENS,
        "include_tokens": [],
        "exclude_tokens": [],
    }
    return [d_state_home, d_state_reason]

def _rule_alexandros_away_general(normalized: str, dates: list[str], now: datetime) -> list[dict]:
    """Γενικός κανόνας απουσίας Αλέξανδρου (π.χ. διακοπές, με τη γιαγιά)."""
    if not _contains_any(normalized, _ALEXANDROS_TOKENS):
        return []
        
    # Guard: if it's camp, _rule_camp_absence handles it.
    if _contains_any(normalized, _CAMP_TOKENS):
        return []
    
    has_absence = _contains_any(normalized, _ABSENCE_TOKENS)
    has_grandma = _contains_any(normalized, _GRANDMA_TOKENS)
    has_trip = _contains_any(normalized, _TRIP_TOKENS)
    
    if not (has_absence or has_grandma or has_trip):
        return []
        
    until = max(dates) if dates else _infer_relative_until(normalized, now=now)
    if not until:
        return []
        
    if has_grandma:
        away_reason = "grandmother"
    elif has_trip:
        away_reason = "trip"
    else:
        away_reason = "away"
        
    d_state_home = {
        "kind": "context_state_set",
        "key": "alexandros_away_from_home",
        "value": "true",
        "until_date": until,
        "reason": away_reason,
        "subject_tokens": _ALEXANDROS_TOKENS,
        "include_tokens": [],
        "exclude_tokens": [],
    }
    d_state_reason = {
        "kind": "context_state_set",
        "key": "alexandros_away_reason",
        "value": away_reason,
        "until_date": until,
        "reason": away_reason,
        "subject_tokens": _ALEXANDROS_TOKENS,
        "include_tokens": [],
        "exclude_tokens": [],
    }
    cond = _build_condition_directive(
        subject_tokens=_ALEXANDROS_TOKENS,
        include_tokens=[],
        exclude_tokens=_ROUTINE_EXCLUDE_TOKENS,
        condition_type="context_flag",
        condition_payload={"flag": "alexandros_away_from_home", "equals": True},
        condition_mode="suppress_when_true",
        reason="away_general_condition",
    )
    
    return [d_state_home, d_state_reason] + ([cond] if cond else [])


def _rule_school_break(normalized: str, dates: list[str], now: datetime) -> list[dict]:
    """
    Phase 3A — school_break:
    Facts: "δεν έχει σχολείο", "τελείωσε το σχολείο", "από αύριο διακοπές"
    Target: σχολικές + πρωινές ρουτίνες Αλέξανδρου
    Action: schedule_pause — απαιτεί σαφές scope.
    """
    has_school_break = _contains_any(normalized, _SCHOOL_BREAK_TOKENS)
    has_school_ref   = _contains_any(normalized, _SCHOOL_TOKENS)
    has_child_ref    = (
        _contains_any(normalized, _ALEXANDROS_TOKENS)
        or "παιδι" in normalized
        or "μικρ" in normalized
    )
    if not (has_school_ref and has_child_ref and has_school_break):
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
    
    d_state = {
        "kind": "context_state_set",
        "key": "school_open",
        "value": "false",
        "until_date": until,
        "reason": "school_break",
        "subject_tokens": _ALEXANDROS_TOKENS,
        "include_tokens": _SCHOOL_TOKENS + _MORNING_TOKENS,
        "exclude_tokens": _ROUTINE_EXCLUDE_TOKENS,
    }
    
    cond = _build_condition_directive(
        subject_tokens=_ALEXANDROS_TOKENS,
        include_tokens=_SCHOOL_TOKENS + _MORNING_TOKENS,
        exclude_tokens=_ROUTINE_EXCLUDE_TOKENS,
        condition_type="context_flag",
        condition_payload={"flag": "school_open", "equals": True},
        condition_mode="allow_when_true",
        reason="school_break_condition",
    )

    return [d_state] + ([cond] if cond else [])


def _rule_sofia_work_mode(normalized: str, dates: list[str], now: datetime) -> list[dict]:
    """
    Phase 3C.5 — sofia_work_mode:
    Facts: "Η Σοφία δουλεύει από το σπίτι αύριο", "Η Σοφία είναι τηλεργασία"
    """
    has_sofia = "σοφια" in normalized
    has_work = _contains_any(normalized, _WORK_TOKENS)
    has_remote = "σπιτι" in normalized or "τηλεργασια" in normalized or "remote" in normalized
    
    if not (has_sofia and has_work and has_remote):
        return []
        
    until = None
    if dates:
        until = max(dates)
    else:
        until = _infer_relative_until(normalized, now=now)
        if not until:
            until = now.strftime("%Y-%m-%d") # default today
            
    d_state = {
        "kind": "context_state_set",
        "key": "sofia_work_mode",
        "value": "remote",
        "until_date": until,
        "reason": "sofia_remote_work",
        "subject_tokens": ["σοφια"],
        "include_tokens": _WORK_TOKENS,
        "exclude_tokens": [],
    }
    return [d_state]


def _rule_football_season(normalized: str, dates: list[str], now: datetime) -> list[dict]:
    """
    Phase 3C.5 — football_season:
    Facts: "ξεκίνησε το ποδόσφαιρο", "άρχισαν οι προπονήσεις"
    """
    has_football = "ποδοσφαιρ" in normalized or "μπαλα" in normalized or "προπονηση" in normalized
    has_start = "ξεκινησ" in normalized or "αρχισ" in normalized
    has_end = "τελειωσ" in normalized or "σταματησ" in normalized or "εκλεισ" in normalized
    
    if not has_football:
        return []
        
    until = None
    if dates:
        until = max(dates)
    
    val = "true" if has_start else ("false" if has_end else None)
    if not val:
        return []
        
    d_state = {
        "kind": "context_state_set",
        "key": "football_season",
        "value": val,
        "until_date": until,
        "reason": "football_season_update",
        "subject_tokens": _ALEXANDROS_TOKENS,
        "include_tokens": ["ποδοσφαιρ", "μπαλα", "προπονηση"],
        "exclude_tokens": [],
    }
    return [d_state]


def _rule_shift_logic(normalized: str, now: datetime) -> list[dict]:
    """
    Phase 3A — shift_logic:
    Facts: "αυτή την εβδομάδα έχω απόγευμα", "δεν ισχύει το ξύπνημα 5:30 όταν είμαι απόγευμα"
    Target: conflicting departure / sleep routines
    Action: context_state_set for the week AND permanent condition_add directives.
    """
    has_work  = _contains_any(normalized, _WORK_TOKENS) or "αναχωρηση" in normalized or "δουλει" in normalized
    has_shift = _contains_any(normalized, _SHIFT_PM_TOKENS) or _contains_any(normalized, _SHIFT_AM_TOKENS)
    has_week  = _contains_any(normalized, _WEEK_TOKENS)

    if not has_shift:
        return []

    directives = []
    shift_val = "afternoon" if _contains_any(normalized, _SHIFT_PM_TOKENS) else "morning"

    # 1. State Update (μόνο αν αναφέρει συγκεκριμένη εβδομάδα)
    if has_week and has_work:
        until = _infer_week_until(now)
        d_state = {
            "kind": "context_state_set",
            "key": "current_shift",
            "value": shift_val,
            "until_date": until,
            "reason": f"shift_{shift_val}_week",
            "subject_tokens": [],
            "include_tokens": _WORK_TOKENS,
            "exclude_tokens": [],
        }
        directives.append(d_state)

    # 2. Permanent Condition for Morning Shift routines (e.g. sleep/wakeup)
    if _contains_any(normalized, _MORNING_TOKENS) or "ξυπνημα" in normalized or "πρωινο" in normalized:
        d_cond_morning = _build_directive(
            "condition_add",
            subject_tokens=[],
            include_tokens=["ξυπνημα", "πρωινο", "υπνος"] + _SLEEP_TOKENS,
            exclude_tokens=_ALEXANDROS_TOKENS + _SOFIA_TOKENS,
            reason="shift_morning_rule",
        )
        if d_cond_morning:
            d_cond_morning["condition_type"] = "shift_mode"
            d_cond_morning["condition_payload"] = {"flag": "current_shift", "equals": "afternoon"}
            # Αν λέει "δεν ισχύει", τότε suppress_when_true όταν είναι afternoon.
            # Αν λέει "ισχύει", τότε allow_when_true. Κάνουμε fallback σε suppress.
            if "δεν " in normalized or "οχι" in normalized:
                d_cond_morning["condition_mode"] = "suppress_when_true"
            else:
                d_cond_morning["condition_mode"] = "allow_when_true"
            directives.append(d_cond_morning)

    # 3. Permanent Condition for Afternoon Shift routines (e.g. departure)
    if "αναχωρηση" in normalized or "δουλει" in normalized or _contains_any(normalized, _WORK_DEPARTURE_TOKENS):
        d_cond_afternoon = _build_directive(
            "condition_add",
            subject_tokens=[],
            include_tokens=["αναχωρηση", "δουλει", "φευγω"] + _WORK_DEPARTURE_TOKENS,
            exclude_tokens=_ALEXANDROS_TOKENS + _SOFIA_TOKENS,
            reason="shift_afternoon_rule",
        )
        if d_cond_afternoon:
            d_cond_afternoon["condition_type"] = "shift_mode"
            # Αν λέει "ισχύει μόνο όταν είναι απόγευμα" -> allow_when_true (equals afternoon)
            d_cond_afternoon["condition_payload"] = {"flag": "current_shift", "equals": "afternoon"}
            if "μονο " in normalized or "ισχυει" in normalized and not ("δεν ισχυει" in normalized):
                d_cond_afternoon["condition_mode"] = "allow_when_true"
            else:
                d_cond_afternoon["condition_mode"] = "allow_when_true" # Default safe for departure
            directives.append(d_cond_afternoon)

    return directives


def _rule_temporary_absence_other_person(normalized: str, dates: list[str], now: datetime) -> list[dict]:
    """
    Phase 3A — temporary_absence_other_person:
    Facts: "η Σοφία δουλεύει πρωί όλη την εβδομάδα", "η Σοφία λείπει"
    Target: Messenger/Sofia proactive ρουτίνες
    Action: State + Condition (sofia_absent = true)
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
        
    d_state = {
        "kind": "context_state_set",
        "key": "sofia_absent",
        "value": "true",
        "until_date": until,
        "reason": "sofia_absent_or_shifted",
        "subject_tokens": _SOFIA_TOKENS,
        "include_tokens": ["σοφια", "messenger", "μηνυμα"],
        "exclude_tokens": _MESSENGER_EXCLUDE,
    }
    
    cond = _build_condition_directive(
        subject_tokens=_SOFIA_TOKENS,
        include_tokens=["σοφια", "messenger", "μηνυμα"],
        exclude_tokens=_MESSENGER_EXCLUDE,
        condition_type="context_flag",
        condition_payload={"flag": "sofia_absent", "equals": True},
        condition_mode="suppress_when_true",
        reason="sofia_absent_condition",
    )
    
    return [d_state] + ([cond] if cond else [])


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
    # Αν πρόκειται ήδη για καθαρό seasonal/summer break case, το αφήνουμε
    # στο ειδικότερο rule για να μη βγάζουμε duplicate directives.
    if _contains_any(normalized, _SUMMER_BREAK_TOKENS):
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
# Phase 3B — Scoring layer
# ─────────────────────────────────────────────────────────────────────────────

# Fixed signal weights (positive)
_W_SUBJECT  = 0.30
_W_ACTIVITY = 0.20
_W_STATE    = 0.20
_W_SCOPE    = 0.20
_W_SPECIAL  = 0.10

# Penalty weights (negative)
_P_NO_SUBJECT   = -0.35
_P_NO_SCOPE     = -0.25
_P_MULTI_MATCH  = -0.20
_P_MULTI_PERSON = -0.20
_P_GENERIC_TOK  = -0.15
_P_CONSERVATIVE = -0.25   # rules that are by-design conservative (shift_week)

# Rules that earn the +0.10 special bonus
_SPECIAL_RULES = {"seasonal_football", "camp_absence", "return_home"}
# Rules that get the conservative penalty
_CONSERVATIVE_RULES = {"shift_logic"}
# Rules where generic-token penalty applies if activity not found in fact
_ACTIVITY_REQUIRED_RULES = {"school_break"}


def score_candidate_directive(
    directive: dict,
    *,
    normalized_fact: str,
    matched_rule_name: str,
) -> dict:
    """
    Scores a candidate directive and returns an enriched copy.

    Returned dict has extra keys:
        rule_name, score, signals, ambiguity_flags, decision, auto_apply

    decision is one of: 'auto_apply' | 'debug_only' | 'rejected'
    """
    score: float = 0.0
    signals: list[str] = []
    ambiguity_flags: list[str] = []

    subject_tokens = directive.get("subject_tokens") or []
    include_tokens = directive.get("include_tokens") or []
    until_date     = directive.get("until_date")
    kind           = directive.get("kind", "")
    reason         = directive.get("reason") or ""

    # notifications_unmute does not need a scope — don't penalise for missing until_date
    scope_required = kind in {"schedule_pause", "notifications_mute"}

    # ── Positive signals ──────────────────────────────────────────────────────
    # has_subject: either explicit subject_tokens match OR (for shift_week) include_tokens match
    has_subject = (
        bool(subject_tokens) and any(tok in normalized_fact for tok in subject_tokens)
    ) or (
        not subject_tokens  # shift_week: no subject by design — treat include match as subject proxy
        and bool(include_tokens)
        and any(tok in normalized_fact for tok in include_tokens)
    )

    has_activity = bool(include_tokens) and any(tok in normalized_fact for tok in include_tokens)
    has_scope    = bool(until_date)
    # State = any word indicating a change of state / event in life
    has_state    = _contains_any(
        normalized_fact,
        _SUMMER_BREAK_TOKENS + _ABSENCE_TOKENS + _RETURN_TOKENS
        + _STOP_TOKENS + _CAMP_TOKENS + _WORK_TOKENS + _WEEK_TOKENS,
    )

    if has_subject:
        score += _W_SUBJECT
        if subject_tokens:
            _append_signal(signals, f"subject:{subject_tokens[0]}")
        else:
            _append_signal(signals, "subject:include_proxy")
    else:
        score += _P_NO_SUBJECT
        _append_flag(ambiguity_flags, "missing_subject")

    if has_activity:
        score += _W_ACTIVITY
        _append_signal(signals, f"activity:{include_tokens[0]}" if include_tokens else "activity")

    if has_state:
        score += _W_STATE
        _append_signal(signals, "state")

    if has_scope:
        score += _W_SCOPE
        # Signal: distinguish explicit ISO date vs inferred scope
        scope_label = "scope:explicit_date" if "20" in (until_date or "")[:4] else "scope:inferred"
        _append_signal(signals, scope_label)
    elif scope_required:
        score += _P_NO_SCOPE
        _append_flag(ambiguity_flags, "missing_scope")
    else:
        # notifications_unmute: η απουσία until_date είναι αναμενόμενη,
        # όχι αδυναμία του fact. Δίνουμε full scope-equivalent credit.
        score += _W_SCOPE
        _append_signal(signals, "scope:not_required")

    # ── Rule-level bonuses and penalties ─────────────────────────────────────
    if matched_rule_name in _SPECIAL_RULES:
        score += _W_SPECIAL
        _append_signal(signals, f"special_rule:{matched_rule_name}")

    if matched_rule_name in _CONSERVATIVE_RULES:
        score += _P_CONSERVATIVE
        _append_flag(ambiguity_flags, f"{matched_rule_name}_conservative")

    # Penalty: activity required by this rule but not found in fact
    if matched_rule_name in _ACTIVITY_REQUIRED_RULES and not has_activity:
        score += _P_GENERIC_TOK
        _append_flag(ambiguity_flags, "generic_school_reference")

    # Penalty: multiple persons in same fact → ambiguous
    has_alex  = _contains_any(normalized_fact, _ALEXANDROS_TOKENS)
    has_sofia = _contains_any(normalized_fact, _SOFIA_TOKENS)
    if has_alex and has_sofia:
        score += _P_MULTI_PERSON
        _append_flag(ambiguity_flags, "multiple_people")

    final_score = _clamp_score(score)

    if final_score >= _AUTO_APPLY_THRESHOLD:
        decision   = "auto_apply"
        auto_apply = True
    elif final_score >= _DEBUG_ONLY_THRESHOLD:
        decision   = "debug_only"
        auto_apply = False
    else:
        decision   = "rejected"
        auto_apply = False

    enriched = dict(directive)
    enriched["rule_name"]       = matched_rule_name
    enriched["score"]           = final_score
    enriched["signals"]         = signals
    enriched["ambiguity_flags"] = ambiguity_flags
    enriched["decision"]        = decision
    enriched["auto_apply"]      = auto_apply
    return enriched


def filter_directives_for_auto_apply(
    scored_directives: list[dict],
) -> tuple[list[dict], list[dict], list[dict]]:
    """
    Splits scored directives into three buckets.
    Returns: (auto_apply, debug_only, rejected)
    """
    auto_apply: list[dict] = []
    debug_only: list[dict] = []
    rejected:   list[dict] = []
    for d in scored_directives:
        decision = d.get("decision", "rejected")
        if decision == "auto_apply":
            auto_apply.append(d)
        elif decision == "debug_only":
            debug_only.append(d)
        else:
            rejected.append(d)
    return auto_apply, debug_only, rejected


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────


def _rule_user_at_work(normalized: str, dates: list[str], now) -> list[dict]:
    """
    User at work:
    Facts: "Έχω πάει γραφείο", "Δουλεύω στο γραφείο σήμερα", "Είμαι δουλειά"
    """
    has_work = _contains_any(normalized, _WORK_TOKENS) or "γραφειο" in normalized
    has_user = "ειμαι" in normalized or "εχω" in normalized or "δουλευω" in normalized
    
    if not (has_work and has_user):
        return []
        
    until = None
    if dates:
        until = max(dates)
    else:
        until = _infer_relative_until(normalized, now=now)
        if not until:
            until = now.strftime("%Y-%m-%d") # default today
            
    d_state = {
        "kind": "context_state_set",
        "key": "user_at_work",
        "value": "true",
        "until_date": until,
        "reason": "user_at_office",
        "subject_tokens": [],
        "include_tokens": _WORK_TOKENS + ["γραφειο"],
        "exclude_tokens": [],
    }
    return [d_state]


def _rule_quiet_hours(normalized: str, dates: list[str], now) -> list[dict]:
    """
    Quiet hours / sleep:
    Facts: "Ο μικρός κοιμάται", "Ησυχία τώρα"
    """
    has_sleep = "κοιμαται" in normalized or "υπνο" in normalized
    has_quiet = "ησυχια" in normalized or "σιγα" in normalized
    has_child = _contains_any(normalized, _ALEXANDROS_TOKENS) or "μικρ" in normalized or "παιδι" in normalized
    
    if not ((has_sleep and has_child) or has_quiet):
        return []
        
    # Συνήθως διαρκεί λίγες ώρες, άρα until=today
    until = now.strftime("%Y-%m-%d")
            
    d_state = {
        "kind": "context_state_set",
        "key": "quiet_hours",
        "value": "true",
        "until_date": until,
        "reason": "quiet_hours_requested",
        "subject_tokens": _ALEXANDROS_TOKENS if has_child else [],
        "include_tokens": ["ησυχια", "υπνο", "κοιμαται"],
        "exclude_tokens": [],
    }
    return [d_state]


def infer_routine_reconciliation_candidates(
    fact: str,
    *,
    category: str,
    reason: str,
    now: datetime | None = None,
) -> list[dict]:
    """
    Runs all rule groups and returns raw candidate directives,
    each tagged with rule_name. No scoring yet.

    Rule groups:
    1. seasonal_football              — ποδόσφαιρο Αλέξανδρου καλοκαίρι
    2. camp_absence                   — κατασκήνωση / απουσία Αλέξανδρου
    3. return_home                    — επιστροφή Αλέξανδρου
    4. school_break                   — σχολικές διακοπές
    5. child_activity_pause           — παιδική δραστηριότητα pause
    6. temporary_absence_other_person — Σοφία λείπει/δουλεύει
    7. shift_week                     — εβδομαδιαία αλλαγή βάρδιας
    """
    current         = now or datetime.now()
    normalized_fact = _normalize(fact)
    dates           = _extract_iso_dates(str(fact))
    candidates: list[dict] = []

    if "[user_fact]" not in normalized_fact and reason not in {"user_stated", "agent_inferred"}:
        return candidates

    rules = [
        ("seasonal_football",              _rule_seasonal_football,              (normalized_fact, dates, current)),
        ("football_season",                _rule_football_season,                (normalized_fact, dates, current)),
        ("camp_absence",                   _rule_camp_absence,                   (normalized_fact, dates, current)),
        ("alexandros_away_general",        _rule_alexandros_away_general,        (normalized_fact, dates, current)),
        ("school_break",                   _rule_school_break,                   (normalized_fact, dates, current)),
        ("child_activity_pause",           _rule_child_activity_pause,           (normalized_fact, dates, current)),
        ("temporary_absence_other_person", _rule_temporary_absence_other_person, (normalized_fact, dates, current)),
        ("shift_logic",                    _rule_shift_logic,                    (normalized_fact, current)),
        ("return_home",                    _rule_return_home,                    (normalized_fact,)),
        ("sofia_work_mode",                _rule_sofia_work_mode,                (normalized_fact, dates, current)),
        ("user_at_work",                   _rule_user_at_work,                   (normalized_fact, dates, current)),
        ("quiet_hours",                    _rule_quiet_hours,                    (normalized_fact, dates, current)),
    ]
    for rule_name, rule_fn, args in rules:
        for directive in rule_fn(*args):
            tagged = dict(directive)
            tagged["rule_name"] = rule_name
            candidates.append(tagged)

    return candidates


def infer_routine_reconciliation_directives(
    fact: str,
    *,
    category: str,
    reason: str,
    now: datetime | None = None,
) -> list[dict]:
    """
    Backward-compatible wrapper: returns only auto_apply directives (scored >= threshold).
    Callers that need the full scored picture should use reconcile_fact_to_routines().
    """
    current         = now or datetime.now()
    normalized_fact = _normalize(fact)
    candidates = infer_routine_reconciliation_candidates(
        fact, category=category, reason=reason, now=current,
    )
    scored = [
        score_candidate_directive(
            c, normalized_fact=normalized_fact, matched_rule_name=c["rule_name"],
        )
        for c in candidates
    ]
    auto_apply, _, _ = filter_directives_for_auto_apply(scored)
    return auto_apply


def _normalize_condition_payload(payload) -> str:
    import json
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            return payload
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)

def apply_routine_reconciliation_directives(directives: list[dict]) -> dict:
    from memory.routine_db import (
        find_routines_for_reconciliation,
        get_routine_muted_until,
        get_routine_schedule_meta,
        set_routine_muted_until,
        clear_routine_muted_until,
        set_routine_paused_until,
        set_routine_resume_rule,
        append_routine_condition,
        set_context_state
    )
    from memory.event_log import log_event
    import json

    stats = {
        "directives": len(directives),
        "matched_routines": 0,
        "schedule_paused": 0,
        "notifications_muted": 0,
        "notifications_unmuted": 0,
        "conditions_added": 0,
        "context_states_set": 0,
        "skipped": 0,
    }

    for directive in directives:
        kind = directive["kind"]

        if kind == "context_state_set":
            key = directive["key"]
            value = directive["value"]
            until_date = directive.get("until_date")
            set_context_state(key, value, until_date)
            stats["context_states_set"] += 1
            log_event(
                "routines", "auto_context_state_set",
                key=key, value=value, until_date=until_date,
                reason=directive.get("reason"),
            )
            continue

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
                continue
                
            if kind == "condition_add":
                cond_type = directive.get("condition_type")
                cond_payload = directive.get("condition_payload")
                cond_mode = directive.get("condition_mode")

                appended = append_routine_condition(
                    r_id,
                    condition_type=cond_type,
                    condition_payload=cond_payload,
                    condition_mode=cond_mode,
                    source_memory_ref="reconciler",
                )

                if not appended:
                    stats["skipped"] += 1
                    continue

                stats["conditions_added"] += 1

                log_event(
                    "routines",
                    "auto_condition_add",
                    routine_id=r_id,
                    event=label,
                    condition_type=cond_type,
                    condition_payload=cond_payload,
                    condition_mode=cond_mode,
                    reason=directive.get("reason"),
                )
                continue

    return stats


def reconcile_fact_to_routines(
    fact: str,
    *,
    category: str,
    reason: str,
    now: datetime | None = None,
) -> dict:
    """
    Full pipeline: candidates → score → filter → apply → rich stats.

    Returns dict with keys:
        applied, candidates, auto_apply_candidates, debug_only_candidates,
        rejected_candidates, matched_routines, schedule_paused,
        notifications_muted, notifications_unmuted, skipped, scored_directives
    """
    try:
        from memory.event_log import log_event
        _has_log = True
    except ImportError:
        _has_log = False

    current         = now or datetime.now()
    normalized_fact = _normalize(fact)

    candidates = infer_routine_reconciliation_candidates(
        fact, category=category, reason=reason, now=current,
    )

    _empty_stats: dict = {
        "applied": False,
        "candidates": 0,
        "auto_apply_candidates": 0,
        "debug_only_candidates": 0,
        "rejected_candidates": 0,
        "matched_routines": 0,
        "schedule_paused": 0,
        "notifications_muted": 0,
        "notifications_unmuted": 0,
        "skipped": 0,
        "scored_directives": [],
    }
    if not candidates:
        return _empty_stats

    scored_directives = [
        score_candidate_directive(
            c,
            normalized_fact=normalized_fact,
            matched_rule_name=c.get("rule_name", "unknown"),
        )
        for c in candidates
    ]

    auto_apply, debug_only, rejected = filter_directives_for_auto_apply(scored_directives)

    # ── Debug logging for every candidate ────────────────────────────────────
    if _has_log:
        for sd in scored_directives:
            decision = sd.get("decision", "rejected")
            action = {
                "auto_apply": "reconcile_candidate_applied",
                "debug_only": "reconcile_candidate_debug_only",
                "rejected":   "reconcile_candidate_rejected",
            }.get(decision, "reconcile_candidate_rejected")
            log_event(
                "routines", action,
                rule_name=sd.get("rule_name"),
                score=sd.get("score"),
                auto_apply=sd.get("auto_apply"),
                signals=sd.get("signals"),
                ambiguity_flags=sd.get("ambiguity_flags"),
                reason=sd.get("reason"),
                until_date=sd.get("until_date"),
            )

    # ── Apply only auto_apply directives ─────────────────────────────────────
    _no_apply_stats: dict = {
        "directives": 0,
        "matched_routines": 0,
        "schedule_paused": 0,
        "notifications_muted": 0,
        "notifications_unmuted": 0,
        "skipped": 0,
    }
    apply_stats = (
        apply_routine_reconciliation_directives(auto_apply)
        if auto_apply
        else _no_apply_stats
    )

    apply_stats.update({
        "applied":                  len(auto_apply) > 0,
        "candidates":               len(candidates),
        "auto_apply_candidates":    len(auto_apply),
        "debug_only_candidates":    len(debug_only),
        "rejected_candidates":      len(rejected),
        "scored_directives":        scored_directives,
    })
    return apply_stats
