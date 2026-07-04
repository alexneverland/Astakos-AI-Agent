import re
import json
from datetime import datetime, timedelta


# ── Subject tokens ───────────────────────────────────────────────────────────
_ALEXANDROS_TOKENS      = ["αλεξανδρ"]
_SOFIA_TOKENS           = ["σοφια"]

# ── Activity / event tokens ──────────────────────────────────────────────────
_FOOTBALL_TOKENS        = ["ποδοσφαιρο", "προπονηση", "μπαλα"]
_BASKETBALL_TOKENS      = ["μπασκετ", "μπασκεμπολ"]
_CHILD_ACTIVITY_TOKENS  = _FOOTBALL_TOKENS + _BASKETBALL_TOKENS + ["δραστηριοτητ", "τμημα", "μαθημα"]
_SUMMER_BREAK_TOKENS    = ["καλοκαιρ", "σταματ", "ξαναρχ", "σεπτεμβρ"]
_CAMP_TOKENS            = ["κατασκην", "camp"]
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
_TOGETHER_TOKENS        = [
    "μαζι",
    "ειμαι με",
    "ειμαστε με",
    "ειμαστε μαζι",
    "ολοι μαζι",
    "παρεα με",
]
_NOT_TOGETHER_TOKENS    = [
    "δεν ειμαι με",
    "δεν ειμαστε μαζι",
    "δεν ειμαστε πια μαζι",
    "δεν ειμαι πια με",
    "χωρισ",
]


_FUTURE_INTENT_TOKENS = [
    "θα ",
    "να ",
    "αν ",
    "ισως",
    "μπορει",
    "λέω να",
    "λεω να",
    "σκεφτομαι να",
]

_PRESENT_LIVE_TOKENS = [
    "ειμαι",
    "ειμαστε",
    "βρισκομαι",
    "βρισκομαστε",
    "φτασαμε",
    "ηρθαμε",
    "πηγαμε",
    "βγηκαμε",
    "ηδη",
]

_PAST_REFERENCE_TOKENS = [
    "χθες",
    "χτεσ",
    "πριν",
    "το βραδυ",
    "περασα",
    "περασαμε",
    "ηταν",
    "θυμηθηκα",
]

_DRAFT_CONTEXT_TOKENS = [
    "messenger",
    "linkedin",
    "draft",
    "προσχεδιο",
    "μηνυμα",
    "γραψε",
    "φτιαξε",
    "ετοιμασε",
]

# ── Exclude tokens ───────────────────────────────────────────────────────────
_ROUTINE_EXCLUDE_TOKENS = ["messenger", "μηνυμα"]
_MESSENGER_EXCLUDE      = ["σχολει", "ποδοσφαιρ", "μπασκετ", "κατασκην"]

# ── Work-routine conflict targets ────────────────────────────────────────────
_WORK_DEPARTURE_TOKENS  = ["αναχωρησ", "φευγ", "δουλεια", "δουλειαν"]
_SLEEP_TOKENS           = ["υπνο", "κοιμ", "νυχτ"]
_LUNCH_TOKENS           = ["μεσημερ", "φαγητ", "γευμ"]

_OUTING_TOKENS = [
    "πισιν", "μπανι", "θαλασσ", "παραλι", "εκδρομ",
    "πικνικ", "βολτα", "παιδικ", "κουνι", "παιχνιδ",
    "εξω", "club",
]

_OUTING_PROGRESS_TOKENS = [
    "ειμαστε", "πηγαμε", "παμε", "φτασαμε", "αραζ",
    "κατσαμε", "ειμαι με", "ολοι μαζι",
]

_HOME_RETURN_TOKENS = [
    "γυρισαμε σπιτι", "γυρισαμε σπιτι", "ειμαστε σπιτι",
    "ηρθαμε σπιτι", "επιστρεψαμε σπιτι", "πισω σπιτι",
]

_OUTING_ROUTINE_TOKENS = [
    "παρκο", "βολτα", "παιχνιδ", "κουνι", "παιδικ",
]

_HOME_ONLY_ROUTINE_TOKENS = [
    "μαγειρ", "φαγητ", "γευμα", "μεσημεριαν", "κουζιν",
]

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

def _has_future_intent_without_live_presence(normalized: str) -> bool:
    has_future = _contains_any(normalized, _FUTURE_INTENT_TOKENS)
    has_live = _contains_any(normalized, _PRESENT_LIVE_TOKENS)
    return has_future and not has_live

def _is_draft_or_past_reference_context(normalized: str) -> bool:
    return _contains_any(normalized, _DRAFT_CONTEXT_TOKENS) or _contains_any(normalized, _PAST_REFERENCE_TOKENS)

def _looks_like_live_presence_statement(normalized: str) -> bool:
    return _contains_any(normalized, _PRESENT_LIVE_TOKENS) and not _contains_any(normalized, _PAST_REFERENCE_TOKENS)


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

def _infer_workweek_until(now: datetime) -> str:
    days_to_friday = 4 - now.weekday()  # Mon=0 ... Fri=4
    if days_to_friday < 0:
        days_to_friday = 0
    return (now + timedelta(days=days_to_friday)).strftime("%Y-%m-%d")


def _end_of_workweek(base_dt: datetime) -> str:
    days_until_sunday = 6 - base_dt.weekday()
    end_dt = base_dt + timedelta(days=days_until_sunday)
    return end_dt.date().isoformat()


def _next_monday(dt: datetime) -> datetime:
    days_ahead = (7 - dt.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return dt + timedelta(days=days_ahead)


def _has_next_workweek_scope(normalized: str) -> bool:
    if "απο δευτερα" in normalized or "απο εβδομαδα" in normalized:
        return True
    if "ερχομεν" in normalized or "επομεν" in normalized:
        return True
    if "δευτερα" in normalized and ("αυριο" in normalized or "απο " in normalized):
        return True
    return False


def _has_this_workweek_scope(normalized: str) -> bool:
    return _contains_any(normalized, _WEEK_TOKENS)


def _has_explicit_weekday_reference(normalized: str) -> bool:
    return any(
        token in normalized
        for token in (
            "δευτερα", "τριτη", "τεταρτη", "πεμπτη", "παρασκευη",
            "monday", "tuesday", "wednesday", "thursday", "friday",
        )
    )


def _extract_explicit_weekday_scope_dt(normalized: str, now: datetime) -> datetime | None:
    weekday_aliases = {
        "δευτερα": 0,
        "τριτη": 1,
        "τεταρτη": 2,
        "πεμπτη": 3,
        "παρασκευη": 4,
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
    }
    for token, weekday_idx in weekday_aliases.items():
        if token not in normalized:
            continue
        days_ahead = (weekday_idx - now.weekday()) % 7
        if days_ahead == 0:
            return now
        return now + timedelta(days=days_ahead)
    return None


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
    """Αλέξανδρος γύρισε → context_state_set (alexandros_away_from_home = false)."""
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

def _rule_family_outing_in_progress(normalized: str, dates: list[str], now: datetime) -> list[dict]:
    """
    Family outing / already outside:
    Facts: "πάμε πισίνα", "είμαστε θάλασσα", "φτάσαμε πάρκο", "όλοι μαζί για μπάνιο"
    Effect:
      - state:alexandros:outing = in_progress
      - user_out_of_home = true
      - suppress park-like child routines while outing is in progress
      - suppress home-only routines (e.g. cooking) while user is out of home
    """
    has_child = (
        _contains_any(normalized, _ALEXANDROS_TOKENS)
        or "παιδι" in normalized
        or "μικρ" in normalized
    )

    has_outing = _contains_any(normalized, _OUTING_TOKENS)
    has_progress = _contains_any(normalized, _OUTING_PROGRESS_TOKENS)

    if _has_future_intent_without_live_presence(normalized):
        return []

    # Generic outing signal for user/family being out of home
    if not (has_outing and has_progress):
        return []

    until = max(dates) if dates else now.strftime("%Y-%m-%d")

    out = []

    # Always set generic out-of-home state
    d_user_out = {
        "kind": "context_state_set",
        "key": "user_out_of_home",
        "value": "true",
        "until_date": until,
        "reason": "family_outing_in_progress",
        "subject_tokens": [],
        "include_tokens": _OUTING_TOKENS,
        "exclude_tokens": [],
    }
    out.append(d_user_out)

    # Only set child-specific outing state if child is actually mentioned
    if has_child:
        d_child_outing = {
            "kind": "context_state_set",
            "key": "state:alexandros:outing",
            "value": "in_progress",
            "until_date": until,
            "reason": "family_outing_in_progress",
            "subject_tokens": _ALEXANDROS_TOKENS,
            "include_tokens": _OUTING_TOKENS,
            "exclude_tokens": _ROUTINE_EXCLUDE_TOKENS,
        }
        out.append(d_child_outing)

    cond_outing_progress = _build_condition_directive(
        subject_tokens=[],
        include_tokens=_OUTING_ROUTINE_TOKENS,
        exclude_tokens=_ROUTINE_EXCLUDE_TOKENS,
        condition_type="context_flag",
        condition_payload={"flag": "state:alexandros:outing", "equals": "in_progress"},
        condition_mode="suppress_when_true",
        reason="outing_in_progress_condition",
    )

    cond_outing_out_of_home = _build_condition_directive(
        subject_tokens=[],
        include_tokens=_OUTING_ROUTINE_TOKENS,
        exclude_tokens=_ROUTINE_EXCLUDE_TOKENS,
        condition_type="context_flag",
        condition_payload={"flag": "user_out_of_home", "equals": True},
        condition_mode="suppress_when_true",
        reason="out_of_home_outing_conflict_condition",
    )

    cond_home = _build_condition_directive(
        subject_tokens=[],
        include_tokens=_HOME_ONLY_ROUTINE_TOKENS,
        exclude_tokens=_ROUTINE_EXCLUDE_TOKENS,
        condition_type="context_flag",
        condition_payload={"flag": "user_out_of_home", "equals": True},
        condition_mode="suppress_when_true",
        reason="out_of_home_home_routine_condition",
    )

    if has_child and cond_outing_progress:
        out.append(cond_outing_progress)

    if cond_outing_out_of_home:
        out.append(cond_outing_out_of_home)

    if cond_home:
        out.append(cond_home)

    return out

def _rule_return_home_from_outing(normalized: str, dates: list[str], now: datetime) -> list[dict]:
    """
    Return home after outing:
    Facts: "γυρίσαμε σπίτι", "ήρθαμε σπίτι", "είμαστε σπίτι τώρα"
    Effect:
      - user_out_of_home = false
      - state:alexandros:outing = done (for the rest of today)
    Only applies if there is already an active outing/out-of-home context.
    """
    if not _contains_any(normalized, _HOME_RETURN_TOKENS):
        return []

    from memory.routine_db import get_context_state

    user_out_state = get_context_state("user_out_of_home")
    alex_outing_state = get_context_state("state:alexandros:outing")

    user_out_active = False
    if user_out_state:
        user_out_active = str(user_out_state.get("value", "")).lower() == "true"

    alex_outing_active = False
    if alex_outing_state:
        alex_outing_active = str(alex_outing_state.get("value", "")).lower() == "in_progress"

    # Do nothing unless we already know the family/child is out.
    if not (user_out_active or alex_outing_active):
        return []

    until = now.strftime("%Y-%m-%d")

    directives = [
        {
            "kind": "context_state_set",
            "key": "user_out_of_home",
            "value": "false",
            "until_date": None,
            "reason": "returned_home_from_outing",
            "subject_tokens": [],
            "include_tokens": [],
            "exclude_tokens": [],
        }
    ]

    if alex_outing_active:
        directives.append(
            {
                "kind": "context_state_set",
                "key": "state:alexandros:outing",
                "value": "done",
                "until_date": until,
                "reason": "returned_home_from_outing",
                "subject_tokens": _ALEXANDROS_TOKENS,
                "include_tokens": _OUTING_TOKENS,
                "exclude_tokens": _ROUTINE_EXCLUDE_TOKENS,
            }
        )

    return directives

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


def _rule_shift_logic(normalized: str, dates: list[str], now: datetime) -> list[dict]:
    """
    Phase 3A — shift_logic:
    Facts: "αυτή την εβδομάδα έχω απόγευμα", "δεν ισχύει το ξύπνημα 5:30 όταν είμαι απόγευμα"
    Target: conflicting departure / sleep routines
    Action: context_state_set for the week AND permanent condition_add directives.
    """
    has_work  = _contains_any(normalized, _WORK_TOKENS) or "αναχωρηση" in normalized or "δουλει" in normalized
    has_shift = _contains_any(normalized, _SHIFT_PM_TOKENS) or _contains_any(normalized, _SHIFT_AM_TOKENS)
    has_next_week = _has_next_workweek_scope(normalized)
    has_this_week = _has_this_workweek_scope(normalized)
    explicit_weekday_dt = _extract_explicit_weekday_scope_dt(normalized, now)
    has_week_scope = has_next_week or has_this_week or explicit_weekday_dt is not None

    if not has_shift:
        return []

    directives = []
    shift_val = "afternoon" if _contains_any(normalized, _SHIFT_PM_TOKENS) else "morning"

    # 1. State Update (μόνο αν αναφέρει συγκεκριμένη εβδομάδα)
    if has_week_scope and has_work:
        if dates:
            try:
                parsed_dt = datetime.strptime(dates[0], "%Y-%m-%d")
                effective_dt = parsed_dt
            except Exception:
                effective_dt = now
        elif explicit_weekday_dt is not None:
            effective_dt = explicit_weekday_dt
        elif has_next_week:
            effective_dt = _next_monday(now)
        else:
            effective_dt = now

        until = _end_of_workweek(effective_dt)
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
    # 2. Dynamic Generic Condition for specific activities mentioned (e.g. "τρέξιμο", "γυμναστήριο")
    # Instead of hardcoding morning/afternoon targets, we extract the action.
    stop_words = {
        "το", "η", "ο", "τα", "τις", "τους", "εχω", "ειμαι", "οταν", "μονο", "δεν", 
        "ισχυει", "απογευμα", "πρωι", "βαρδια", "αυτη", "την", "εβδομαδα", "και", 
        "αλλα", "οτι", "για", "να", "ξερεις", "μου", "ειναι", "θα", "παω", "οτι", "πως", "σου"
    }
    action_tokens = [w for w in normalized.split() if w not in stop_words and len(w) > 2]

    # Old logic for "morning/wakeup" routines if they are explicitly mentioned
    if _contains_any(normalized, _MORNING_TOKENS) or "ξυπνημα" in normalized or "πρωινο" in normalized:
        action_tokens.extend(["ξυπνημα", "πρωινο", "υπνος"] + _SLEEP_TOKENS)
        
    # Old logic for "departure" routines if they are explicitly mentioned
    if "αναχωρηση" in normalized or "δουλει" in normalized or _contains_any(normalized, _WORK_DEPARTURE_TOKENS):
        action_tokens.extend(["αναχωρηση", "δουλει", "φευγω"] + _WORK_DEPARTURE_TOKENS)
        
    action_tokens = list(set(action_tokens))

    # If they said "ισχύει/δεν ισχύει" and mentioned a shift, and we have an action token
    if "ισχυει" in normalized and has_shift and action_tokens:
        d_cond_generic = _build_directive(
            "condition_add",
            subject_tokens=[],
            include_tokens=action_tokens,
            exclude_tokens=_ALEXANDROS_TOKENS + _SOFIA_TOKENS,
            reason="shift_generic_rule",
        )
        if d_cond_generic:
            d_cond_generic["condition_type"] = "shift_mode"
            # If PM shift -> target afternoon. Otherwise -> morning
            if _contains_any(normalized, _SHIFT_PM_TOKENS):
                d_cond_generic["condition_payload"] = {"flag": "current_shift", "equals": "afternoon"}
            else:
                d_cond_generic["condition_payload"] = {"flag": "current_shift", "equals": "morning"}
                
            # If it says "δεν ισχύει", suppress. Otherwise allow.
            if "δεν " in normalized or "οχι" in normalized:
                d_cond_generic["condition_mode"] = "suppress_when_true"
            else:
                d_cond_generic["condition_mode"] = "allow_when_true"
                
            directives.append(d_cond_generic)

    return directives


def _sofia_state_is_active(now: datetime) -> bool:
    from memory.routine_db import get_context_state

    state_data = get_context_state("sofia_with_user")
    if not state_data:
        return False

    expires_at = state_data.get("expires_at")
    today = now.strftime("%Y-%m-%d")
    if expires_at and expires_at < today:
        return False

    return str(state_data.get("value", "")).lower() == "true"


def _rule_sofia_with_user(normalized: str, dates: list[str], now: datetime) -> list[dict]:
    """
    Phase 3A — sofia_with_user:
    Facts: "είμαι με τη Σοφία", "είμαστε μαζί με τη Σοφία", "η Σοφία είναι μαζί μου"
    Target: Messenger/Sofia proactive ρουτίνες
    Action: State + Condition (sofia_with_user = true)
    """
    has_sofia = _contains_any(normalized, _SOFIA_TOKENS)
    has_together = _contains_any(normalized, _TOGETHER_TOKENS)

    if has_sofia and has_together:
        if _is_draft_or_past_reference_context(normalized) and not _looks_like_live_presence_statement(normalized):
            return []

    group_outing_tokens = [
        "ηρθαμε", "ήρθαμε", "πηγαμε", "πήγαμε", "ειμαστε", "είμαστε",
        "ολοι", "όλοι", "οικογενειακ", "μαζι", "μαζί",
        "θαλασσα", "θάλασσα", "παραλια", "παραλία", "μπανιο", "μπάνιο",
        "βγηκαμε", "βγήκαμε", "βολτα", "βόλτα", "εκδρομ"
    ]
    has_group_outing = _contains_any(normalized, group_outing_tokens)

    # Strong path: explicit Sofia + together
    if has_sofia and has_together:
        pass
    # Softer path: group outing wording can reinforce an already-active Sofia context
    elif has_group_outing and _sofia_state_is_active(now) and _looks_like_live_presence_statement(normalized):
        pass
    else:
        return []
    until = None
    if dates:
        until = max(dates)
    elif _contains_any(normalized, _WEEK_TOKENS):
        until = _infer_week_until(now)
    else:
        until = now.strftime("%Y-%m-%d")
    if not until:
        return []
        
    d_state = {
        "kind": "context_state_set",
        "key": "sofia_with_user",
        "value": "true",
        "until_date": until,
        "reason": "sofia_with_user",
        "subject_tokens": _SOFIA_TOKENS,
        "include_tokens": ["σοφια", "messenger", "μηνυμα"],
        "exclude_tokens": _MESSENGER_EXCLUDE,
    }
    
    cond = _build_condition_directive(
        subject_tokens=_SOFIA_TOKENS,
        include_tokens=["σοφια", "messenger", "μηνυμα"],
        exclude_tokens=_MESSENGER_EXCLUDE,
        condition_type="context_flag",
        condition_payload={"flag": "sofia_with_user", "equals": True},
        condition_mode="suppress_when_true",
        reason="sofia_with_user_condition",
    )
    
    return [d_state] + ([cond] if cond else [])


def _rule_sofia_not_with_user(normalized: str, dates: list[str], now: datetime) -> list[dict]:
    """
    Phase 3A — sofia_not_with_user:
    Facts: "η Σοφία έφυγε", "η Σοφία δεν είναι εδώ", "δεν είμαστε μαζί τώρα"
    Target: clear Messenger/Sofia suppress context immediately
    Action: State only (sofia_with_user = false)
    """
    has_sofia = _contains_any(normalized, _SOFIA_TOKENS)
    has_absence = has_sofia and _contains_any(normalized, _ABSENCE_TOKENS)
    has_not_together = _contains_any(normalized, _NOT_TOGETHER_TOKENS)

    if not (has_absence or has_not_together):
        return []

    if has_not_together and not has_sofia:
        from memory.routine_db import get_context_state
        state_data = get_context_state("sofia_with_user")
        is_active = False
        if state_data:
            expires_at = state_data.get("expires_at")
            today = now.strftime("%Y-%m-%d")
            if not expires_at or expires_at >= today:
                is_active = str(state_data.get("value")).lower() == "true"
        if not is_active:
            return []

    d_state = {
        "kind": "context_state_set",
        "key": "sofia_with_user",
        "value": "false",
        "until_date": None,
        "reason": "sofia_not_with_user",
        "subject_tokens": _SOFIA_TOKENS,
        "include_tokens": ["σοφια", "messenger", "μηνυμα"],
        "exclude_tokens": _MESSENGER_EXCLUDE,
    }
    return [d_state]


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
_SPECIAL_RULES = {"seasonal_football", "camp_absence", "return_home", "family_outing_in_progress", "return_home_from_outing"}
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
    directive_key  = directive.get("key") or ""

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

    if matched_rule_name == "llm_extracted" and kind == "context_state_set":
        if directive_key in _CANONICAL_CONTEXT_KEYS:
            score += 0.15
            _append_signal(signals, "llm:canonical_context")

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

    explicit_shift_schedule = (
        matched_rule_name == "shift_logic"
        and kind == "context_state_set"
        and directive_key == "current_shift"
        and has_activity
        and has_state
        and has_scope
        and _has_explicit_weekday_reference(normalized_fact)
    )

    if matched_rule_name in _CONSERVATIVE_RULES and not explicit_shift_schedule:
        score += _P_CONSERVATIVE
        _append_flag(ambiguity_flags, f"{matched_rule_name}_conservative")
    elif explicit_shift_schedule:
        score += 0.10
        _append_signal(signals, "shift_logic:explicit_schedule")

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
    Guard: δεν πιάνει δηλώσεις βάρδιας/προγράμματος για επόμενες μέρες.
    """
    has_work = _contains_any(normalized, _WORK_TOKENS) or "γραφειο" in normalized
    has_user = "ειμαι" in normalized or "εχω" in normalized or "δουλευω" in normalized
    has_presence_phrase = (
        "ειμαι στη δουλεια" in normalized
        or "ειμαι δουλεια" in normalized
        or "δουλευω στο γραφειο" in normalized
        or "εχω παει γραφειο" in normalized
    )
    has_schedule_phrase = _has_next_workweek_scope(normalized) or _contains_any(normalized, _SHIFT_PM_TOKENS + _SHIFT_AM_TOKENS)

    if not (has_work and has_user):
        return []
    if has_schedule_phrase and not has_presence_phrase:
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


def _safe_json_list(raw: str) -> list[dict]:
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        return []
    except Exception:
        return []

_CANONICAL_CONTEXT_KEYS = {
    "user_out_of_home",
    "alexandros_away_from_home",
    "family_at_home",

    "sofia_with_user",
    "current_shift",
    "football_season",
}

def _normalize_context_key(raw: str) -> str:
    key = _normalize(raw or "")
    aliases = {
        "user_out_of_home": "user_out_of_home",
        "out_of_home": "user_out_of_home",

        "alexandros_present": "alexandros_away_from_home",
        "child_present": "alexandros_away_from_home",
        
        "alexandros_away_from_home": "alexandros_away_from_home",
        "child_away": "alexandros_away_from_home",

        "family_at_home": "family_at_home",
        "at_home": "family_at_home",

        "family_outside_activity": "user_out_of_home",
        "outside_activity": "user_out_of_home",

        "sofia_with_user": "sofia_with_user",
        "current_shift": "current_shift",
        "football_season": "football_season",
    }
    return aliases.get(key, key)

def _llm_impact_to_directives(impact: dict) -> list[dict]:
    """
    Converts one structured LLM impact object into the same directive schema
    already used by the reconciler.
    """
    entity = _normalize(impact.get("entity", ""))
    activity = _normalize(impact.get("activity", ""))
    aliases = [_normalize(x) for x in (impact.get("aliases") or []) if str(x).strip()]
    state_change = _normalize(impact.get("state_change", ""))
    impact_type = _normalize(impact.get("impact", ""))
    until_date = impact.get("until_date")
    reason = impact.get("reason") or "llm_inferred"

    raw_context_key = _normalize(impact.get("context_key", ""))
    context_key = _normalize_context_key(raw_context_key)
    context_value = impact.get("context_value", None)

    if isinstance(context_value, str):
        cv = _normalize(context_value)
        if cv == "true":
            context_value = True
        elif cv == "false":
            context_value = False
        elif cv == "null":
            context_value = None

    if raw_context_key in {"alexandros_present", "child_present"} and isinstance(context_value, bool):
        context_value = not context_value

    if not context_key and (not entity or not activity or not impact_type):
        return []

    subject_tokens = []
    if "αλεξανδρ" in entity or "alexand" in entity:
        subject_tokens = _ALEXANDROS_TOKENS
    elif "σοφ" in entity or "sofia" in entity:
        subject_tokens = _SOFIA_TOKENS
    else:
        subject_tokens = [entity]

    include_tokens = aliases[:] if aliases else ([activity] if activity else [])
    exclude_tokens = _ROUTINE_EXCLUDE_TOKENS[:]

    if context_key:
        if context_key == "alexandros_away_from_home":
            subject_tokens = _ALEXANDROS_TOKENS
        elif context_key == "sofia_with_user":
            subject_tokens = _SOFIA_TOKENS
        elif context_key in {"user_out_of_home", "family_at_home"}:
            subject_tokens = []

        if context_key not in _CANONICAL_CONTEXT_KEYS:
            return []

        return [{
            "kind": "context_state_set",
            "key": context_key,
            "value": context_value,
            "until_date": until_date,
            "reason": reason,
            "subject_tokens": subject_tokens,
            "include_tokens": include_tokens,
            "exclude_tokens": exclude_tokens,
        }]

    directives = []

    state_key = f"state:{entity}:{activity}"

    if state_change:
        directives.append({
            "kind": "context_state_set",
            "key": state_key,
            "value": state_change,
            "until_date": until_date,
            "reason": reason,
            "subject_tokens": subject_tokens,
            "include_tokens": include_tokens,
            "exclude_tokens": exclude_tokens,
        })

    if impact_type == "pause_matching_routines" and until_date:
        d = _build_directive(
            "schedule_pause",
            subject_tokens=subject_tokens,
            include_tokens=include_tokens,
            exclude_tokens=exclude_tokens,
            until_date=until_date,
            reason=reason,
        )
        if d:
            directives.append(d)

    elif impact_type == "mute_matching_notifications" and until_date:
        d = _build_directive(
            "notifications_mute",
            subject_tokens=subject_tokens,
            include_tokens=include_tokens,
            exclude_tokens=exclude_tokens,
            until_date=until_date,
            reason=reason,
        )
        if d:
            directives.append(d)

    elif impact_type == "resume_matching_routines":
        d = _build_directive(
            "notifications_unmute",
            subject_tokens=subject_tokens,
            include_tokens=include_tokens,
            exclude_tokens=exclude_tokens,
            reason=reason,
        )
        if d:
            directives.append(d)

    elif impact_type == "already_happening":
        cond = _build_condition_directive(
            subject_tokens=subject_tokens,
            include_tokens=include_tokens,
            exclude_tokens=exclude_tokens,
            condition_type="context_flag",
            condition_payload={"flag": state_key, "equals": "in_progress"},
            condition_mode="suppress_when_true",
            reason=reason,
        )
        if cond:
            directives.append(cond)

    elif impact_type == "already_done":
        cond = _build_condition_directive(
            subject_tokens=subject_tokens,
            include_tokens=include_tokens,
            exclude_tokens=exclude_tokens,
            condition_type="context_flag",
            condition_payload={"flag": state_key, "equals": "done"},
            condition_mode="suppress_when_true",
            reason=reason,
        )
        if cond:
            directives.append(cond)

    elif impact_type == "allow_only_when_active":
        cond = _build_condition_directive(
            subject_tokens=subject_tokens,
            include_tokens=include_tokens,
            exclude_tokens=exclude_tokens,
            condition_type="context_flag",
            condition_payload={"flag": state_key, "equals": "active"},
            condition_mode="allow_when_true",
            reason=reason,
        )
        if cond:
            directives.append(cond)

    return directives

def _infer_llm_reconciliation_candidates(
    fact: str,
    *,
    category: str,
    reason: str,
    now: datetime,
) -> list[dict]:
    """
    LLM-first extraction layer.
    Returns candidate directives in the same schema as rule-based candidates.
    """
    if reason not in {"user_stated", "agent_inferred"}:
        return []

    try:
        from core.brain import llm
        from langchain_core.messages import HumanMessage
    except Exception:
        return []

    today = now.strftime("%Y-%m-%d")

    prompt = f"""
Είσαι extractor για routine reconciliation.

Σήμερα είναι {today}.

Θα σου δώσω ένα fact/μήνυμα χρήστη.
Θέλω να βγάλεις ΜΟΝΟ JSON LIST.
Καμία εξήγηση.

Στόχος:
να καταλάβεις αν το fact επηρεάζει υπάρχουσες ρουτίνες ή προσωρινό context ζωής.

Επέστρεψε λίστα από objects με fields:
- entity: ποιο πρόσωπο/οντότητα αφορά ή null
- activity: γενική δραστηριότητα/τομέας, π.χ. sports_training, outing, sleep, school, work_shift, home_presence ή null
- aliases: λίστα λέξεων-κλειδιών που θα βοηθήσουν να ταιριάξουν routines
- state_change: π.χ. active, inactive, in_progress, done, off_season, away ή null
- impact:
    - pause_matching_routines
    - mute_matching_notifications
    - resume_matching_routines
    - already_happening
    - already_done
    - allow_only_when_active
    - live_context
- context_key: canonical context flag ή null
- context_value: true | false | string | null
- until_date: YYYY-MM-DD ή null
- reason: σύντομο machine-friendly reason, π.χ. summer_break, camp, returned_home, live_context

Για γενικές τρέχουσες καταστάσεις ζωής, προτίμησε canonical context flags.
Χρησιμοποίησε ΜΟΝΟ αυτά τα context_key όταν ταιριάζουν:
- user_out_of_home
- alexandros_away_from_home
- family_at_home

- sofia_with_user
- current_shift
- football_season

Κανόνες:
- Μην εφευρίσκεις νέα context keys αν υπάρχει canonical key που καλύπτει το νόημα.
- Μπορείς να επιστρέψεις περισσότερα από ένα objects αν ένα fact αλλάζει πολλά context flags.
- Αν το fact αφορά live/temporary κατάσταση ζωής, προτίμησε context_key/context_value αντί για dynamic state:{{entity}}:{{activity}}.
- Αν δεν υπάρχει καθαρό routine/context impact, γύρνα [].

Παραδείγματα:

Fact: "Το βράδυ θα πάω με τη Σοφία έξω και ο Αλέξανδρος θα είναι με τη Μαρία"
Output:
[
  {{"entity":"Λάζαρος","activity":"outing","aliases":["εξω","βραδυ"],"state_change":null,"impact":"live_context","context_key":"user_out_of_home","context_value":true,"until_date":"{today}","reason":"user_out_evening"}},
  {{"entity":"Αλέξανδρος","activity":"home_presence","aliases":["με τη μαρια"],"state_change":null,"impact":"live_context","context_key":"alexandros_away_from_home","context_value":true,"until_date":"{today}","reason":"child_with_caregiver"}},
  {{"entity":"family","activity":"home_presence","aliases":["εξω","βραδυ"],"state_change":null,"impact":"live_context","context_key":"family_at_home","context_value":false,"until_date":"{today}","reason":"family_out_evening"}},
  {{"entity":"family","activity":"outing","aliases":["εξω","βραδυ"],"state_change":null,"impact":"live_context","context_key":"user_out_of_home","context_value":true,"until_date":"{today}","reason":"family_out_evening"}}
]

Fact: "Γυρίσαμε σπίτι"
Output:
[
  {{"entity":"family","activity":"outing","aliases":["γυρισαμε σπιτι"],"state_change":null,"impact":"live_context","context_key":"user_out_of_home","context_value":false,"until_date":null,"reason":"returned_home"}}
]

Fact: "Ο Αλέξανδρος είναι μαζί μας"
Output:
[
  {{"entity":"Αλέξανδρος","activity":"home_presence","aliases":["μαζι μας"],"state_change":null,"impact":"live_context","context_key":"alexandros_away_from_home","context_value":false,"until_date":null,"reason":"child_present_again"}},
  {{"entity":"family","activity":"home_presence","aliases":["μαζι μας"],"state_change":null,"impact":"live_context","context_key":"family_at_home","context_value":true,"until_date":null,"reason":"family_home_again"}}
]

Fact:
{fact}
"""

    try:
        resp = llm.invoke([HumanMessage(content=prompt)])
        raw = getattr(resp, "content", "") or ""
    except Exception:
        return []

    impacts = _safe_json_list(raw)
    out: list[dict] = []
    for impact in impacts:
        out.extend(_llm_impact_to_directives(impact))
    return out

def _candidate_fingerprint(d: dict) -> tuple:
    return (
        d.get("kind"),
        d.get("key"),
        d.get("value"),
        d.get("until_date"),
        d.get("reason"),
        tuple(sorted(d.get("subject_tokens") or [])),
        tuple(sorted(d.get("include_tokens") or [])),
        tuple(sorted(d.get("exclude_tokens") or [])),
        d.get("condition_type"),
        d.get("condition_mode"),
        _normalize_condition_payload(d.get("condition_payload")),
    )

def _merge_candidate_lists(primary: list[dict], secondary: list[dict]) -> list[dict]:
    merged: list[dict] = []
    seen: set[tuple] = set()

    for item in primary + secondary:
        fp = _candidate_fingerprint(item)
        if fp in seen:
            continue
        seen.add(fp)
        merged.append(item)

    return merged

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
    6. sofia_with_user               — είμαστε μαζί με τη Σοφία
    7. sofia_not_with_user           — δεν είμαστε πια μαζί με τη Σοφία
    8. shift_week                     — εβδομαδιαία αλλαγή βάρδιας
    """
    current         = now or datetime.now()
    normalized_fact = _normalize(fact)
    dates           = _extract_iso_dates(str(fact))
    rule_candidates: list[dict] = []

    if "[user_fact]" not in normalized_fact and reason not in {"user_stated", "agent_inferred"}:
        return rule_candidates

    llm_candidates = _infer_llm_reconciliation_candidates(
        fact,
        category=category,
        reason=reason,
        now=current,
    )

    # llm_candidates είναι το primary semantic path
    # τα rule candidates είναι conservative fallback heuristics
    rules = [
        ("seasonal_football",              _rule_seasonal_football,              (normalized_fact, dates, current)),
        ("football_season",                _rule_football_season,                (normalized_fact, dates, current)),
        ("camp_absence",                   _rule_camp_absence,                   (normalized_fact, dates, current)),
        ("family_outing_in_progress",      _rule_family_outing_in_progress,      (normalized_fact, dates, current)),
        ("return_home",                    _rule_return_home,                    (normalized_fact,)),
        ("return_home_from_outing",        _rule_return_home_from_outing,        (normalized_fact, dates, current)),
        ("alexandros_away_general",        _rule_alexandros_away_general,        (normalized_fact, dates, current)),
        ("school_break",                   _rule_school_break,                   (normalized_fact, dates, current)),
        ("child_activity_pause",           _rule_child_activity_pause,           (normalized_fact, dates, current)),
        ("sofia_with_user",                _rule_sofia_with_user,                (normalized_fact, dates, current)),
        ("sofia_not_with_user",            _rule_sofia_not_with_user,            (normalized_fact, dates, current)),
        ("shift_logic",                    _rule_shift_logic,                    (normalized_fact, dates, current)),
        ("sofia_work_mode",                _rule_sofia_work_mode,                (normalized_fact, dates, current)),
        ("user_at_work",                   _rule_user_at_work,                   (normalized_fact, dates, current)),
        ("quiet_hours",                    _rule_quiet_hours,                    (normalized_fact, dates, current)),
    ]
    for rule_name, rule_fn, args in rules:
        for directive in rule_fn(*args):
            tagged = dict(directive)
            tagged["rule_name"] = rule_name
            rule_candidates.append(tagged)

    for d in llm_candidates:
        d.setdefault("rule_name", "llm_extracted")

    return _merge_candidate_lists(llm_candidates, rule_candidates)


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
            if isinstance(value, bool):
                value = "true" if value else "false"
            else:
                value = str(value) if value is not None else ""
            until_date = directive.get("until_date")
            set_context_state(key, value, until_date)
            stats["context_states_set"] += 1
            log_event(
                "routines", "auto_context_state_set",
                key=key, value=value, until_date=until_date,
                reason=directive.get("reason"),
                debug_type="reconciler_applied",
                debug_source="reconciler",
                debug_effect="state_only",
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
                    debug_type="reconciler_applied",
                    debug_source="reconciler",
                    debug_effect="routine_changed",
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
                    debug_type="reconciler_applied",
                    debug_source="reconciler",
                    debug_effect="routine_changed",
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
                    debug_type="reconciler_applied",
                    debug_source="reconciler",
                    debug_effect="routine_changed",
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
                    debug_type="reconciler_applied",
                    debug_source="reconciler",
                    debug_effect="routine_changed",
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
