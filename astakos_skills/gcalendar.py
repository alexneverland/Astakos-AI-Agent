# ================================================================
# Project: Astakos AI Agent 🦞
# Module:  Google Calendar Tool
# Auth: OAuth2 token.json (same as mail/drive/tasks)
# ================================================================

import os
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
from langchain_core.tools import tool
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

TIMEZONE = "Europe/Athens"
CALENDAR_ID = "primary"

TOKEN_PATH       = r"C:\astakos_v2\credentials\token.json"
CREDENTIALS_PATH = r"C:\astakos_v2\credentials\credentials.json"
_CALENDAR_SCOPE  = "https://www.googleapis.com/auth/calendar"


def _get_service():
    """Returns an authenticated Google Calendar service (via token.json)."""
    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, [_CALENDAR_SCOPE])
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            raise Exception(
                "Google Calendar: δεν υπάρχει έγκυρο token. "
                "Διέγραψε credentials/token.json και κάνε νέο login (OAuth)."
            )
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _parse_dt(dt_str: str, tz: ZoneInfo) -> datetime:
    """
    Parses datetime string in various formats:
    - "2026-06-15 18:00"
    - "2026-06-15T18:00:00"
    - "15/06/2026 18:00"
    - "tomorrow 18:00" / "tomorrow"
    - "Friday 18:00"
    """
    s = dt_str.strip()
    now = datetime.now(tz)

    low = s.lower()
    day_offset = None
    time_part = None

    if low.startswith("αύριο") or low.startswith("αυριο"):
        day_offset = 1
        rest = s[5:].strip()
        time_part = rest if rest else "09:00"
    elif low.startswith("σήμερα") or low.startswith("σημερα"):
        day_offset = 0
        rest = s[6:].strip()
        time_part = rest if rest else "09:00"
    else:
        _DAYS_EL = {
            "δευτέρα": 0, "δευτερα": 0,
            "τρίτη": 1,   "τριτη": 1,
            "τετάρτη": 2, "τεταρτη": 2,
            "πέμπτη": 3,  "πεμπτη": 3,
            "παρασκευή": 4, "παρασκευη": 4,
            "σάββατο": 5, "σαββατο": 5,
            "κυριακή": 6, "κυριακη": 6,
        }
        for day_name, weekday in _DAYS_EL.items():
            if low.startswith(day_name):
                days_ahead = (weekday - now.weekday()) % 7 or 7
                day_offset = days_ahead
                rest = s[len(day_name):].strip()
                time_part = rest if rest else "09:00"
                break

    if day_offset is not None:
        target_date = (now + timedelta(days=day_offset)).date()
        try:
            t = datetime.strptime(time_part, "%H:%M").time()
        except ValueError:
            t = datetime.strptime("09:00", "%H:%M").time()
        return datetime.combine(target_date, t, tzinfo=tz)

    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
                "%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=tz)
        except ValueError:
            continue

    raise ValueError(f"Δεν μπόρεσα να παρσάρω ημερομηνία: '{dt_str}'")


def _format_event(e: dict) -> str:
    """Formats an event for display."""
    title = e.get("summary", "(χωρίς τίτλο)")
    start = e.get("start", {})
    end   = e.get("end", {})
    loc   = e.get("location", "")
    desc  = e.get("description", "")
    eid   = e.get("id", "")

    if "dateTime" in start:
        dt = datetime.fromisoformat(start["dateTime"])
        start_str = dt.strftime("%d/%m %H:%M")
    else:
        start_str = start.get("date", "")

    if "dateTime" in end:
        dt = datetime.fromisoformat(end["dateTime"])
        end_str = dt.strftime("%H:%M")
    else:
        end_str = end.get("date", "")

    parts = [f"📅 **{title}** — {start_str}–{end_str}"]
    if loc:
        parts.append(f"📍 {loc}")
    if desc:
        parts.append(f"📝 {desc[:100]}")
    parts.append(f"🆔 `{eid}`")
    return "\n".join(parts)


@tool
def google_calendar_tool(
    action: str,
    title: str = "",
    start_time: str = "",
    end_time: str = "",
    description: str = "",
    location: str = "",
    event_id: str = "",
    days_ahead: int = 1,
) -> str:
    """
    Google Calendar Management. Actions:
    - list: Display events (days_ahead=1 for today, 7 for week, etc.)
    - today: Events today (shortcut)
    - week: Events for the next 7 days (shortcut)
    - create: Create event (requires: title, start_time, end_time)
    - update: Modify event (requires: event_id + fields to change)
    - delete: Delete event (requires: event_id)
    - search: Search by keyword (title as query)

    start_time / end_time formats: "2026-06-15 18:00", "tomorrow 18:00", "Friday 20:00"
    """
    try:
        tz  = ZoneInfo(TIMEZONE)
        svc = _get_service()
        action = action.strip().lower()

        # ── LIST / TODAY / WEEK ──────────────────────────────────────
        if action in ("list", "today", "week"):
            now = datetime.now(tz)
            if action == "today":
                time_min = now.replace(hour=0, minute=0, second=0, microsecond=0)
                time_max = now.replace(hour=23, minute=59, second=59)
                label = "σήμερα"
            elif action == "week":
                time_min = now
                time_max = now + timedelta(days=7)
                label = "επόμενες 7 μέρες"
            else:
                time_min = now
                time_max = now + timedelta(days=max(1, days_ahead))
                label = f"επόμενες {days_ahead} μέρες"

            events_result = svc.events().list(
                calendarId=CALENDAR_ID,
                timeMin=time_min.isoformat(),
                timeMax=time_max.isoformat(),
                singleEvents=True,
                orderBy="startTime",
                maxResults=20,
            ).execute()

            events = events_result.get("items", [])
            if not events:
                return f"📅 Δεν υπάρχουν events ({label})."

            lines = [f"📅 **{len(events)} events {label}:**\n"]
            for e in events:
                lines.append(_format_event(e))
                lines.append("")
            return "\n".join(lines)

        # ── SEARCH ──────────────────────────────────────────────────
        if action == "search":
            if not title:
                return "❌ Δώσε λέξη αναζήτησης στο πεδίο title."
            now = datetime.now(tz)
            events_result = svc.events().list(
                calendarId=CALENDAR_ID,
                q=title,
                timeMin=(now - timedelta(days=30)).isoformat(),
                timeMax=(now + timedelta(days=90)).isoformat(),
                singleEvents=True,
                orderBy="startTime",
                maxResults=10,
            ).execute()
            events = events_result.get("items", [])
            if not events:
                return f"🔍 Δεν βρέθηκαν events για '{title}'."
            lines = [f"🔍 **{len(events)} αποτελέσματα για '{title}':**\n"]
            for e in events:
                lines.append(_format_event(e))
                lines.append("")
            return "\n".join(lines)

        # ── CREATE ──────────────────────────────────────────────────
        if action == "create":
            if not title:
                return "❌ Λείπει ο τίτλος (title)."
            if not start_time:
                return "❌ Λείπει η ώρα έναρξης (start_time)."

            try:
                dt_start = _parse_dt(start_time, tz)
            except ValueError as e:
                return f"❌ {e}"

            if end_time:
                try:
                    dt_end = _parse_dt(end_time, tz)
                except ValueError as e:
                    return f"❌ {e}"
            else:
                dt_end = dt_start + timedelta(hours=1)

            body = {
                "summary": title,
                "start":   {"dateTime": dt_start.isoformat(), "timeZone": TIMEZONE},
                "end":     {"dateTime": dt_end.isoformat(),   "timeZone": TIMEZONE},
            }
            if description:
                body["description"] = description
            if location:
                body["location"] = location

            created = svc.events().insert(calendarId=CALENDAR_ID, body=body).execute()
            start_fmt = dt_start.strftime("%d/%m/%Y %H:%M")
            return (
                f"✅ Event δημιουργήθηκε!\n"
                f"📅 **{title}** — {start_fmt}\n"
                f"🆔 `{created['id']}`"
            )

        # ── UPDATE ──────────────────────────────────────────────────
        if action == "update":
            if not event_id:
                return "❌ Λείπει το event_id."
            existing = svc.events().get(calendarId=CALENDAR_ID, eventId=event_id).execute()

            if title:
                existing["summary"] = title
            if description:
                existing["description"] = description
            if location:
                existing["location"] = location
            if start_time:
                try:
                    dt_start = _parse_dt(start_time, tz)
                    existing["start"] = {"dateTime": dt_start.isoformat(), "timeZone": TIMEZONE}
                except ValueError as e:
                    return f"❌ {e}"
            if end_time:
                try:
                    dt_end = _parse_dt(end_time, tz)
                    existing["end"] = {"dateTime": dt_end.isoformat(), "timeZone": TIMEZONE}
                except ValueError as e:
                    return f"❌ {e}"

            updated = svc.events().update(
                calendarId=CALENDAR_ID, eventId=event_id, body=existing
            ).execute()
            return f"✅ Event ενημερώθηκε: **{updated.get('summary')}**\n🆔 `{event_id}`"

        # ── DELETE ──────────────────────────────────────────────────
        if action == "delete":
            if not event_id:
                return "❌ Λείπει το event_id."
            try:
                evt = svc.events().get(calendarId=CALENDAR_ID, eventId=event_id).execute()
                evt_title = evt.get("summary", "(χωρίς τίτλο)")
            except Exception:
                evt_title = event_id
            svc.events().delete(calendarId=CALENDAR_ID, eventId=event_id).execute()
            return f"🗑️ Event διαγράφηκε: **{evt_title}**"

        return f"❌ Άγνωστο action: '{action}'. Χρησιμοποίησε: list, today, week, create, update, delete, search."

    except Exception as e:
        return f"❌ Google Calendar σφάλμα: {str(e)}"
