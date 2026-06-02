# ================================================================
# Project: Astakos AI Agent 🦞
# Skill: Google Fit — βήματα, ύπνος, καρδιακοί παλμοί
# ================================================================

import os
import json
import datetime
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

TOKEN_PATH       = r"C:\astakos_v2\credentials\token.json"
CREDENTIALS_PATH = r"C:\astakos_v2\credentials\credentials.json"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/fitness.activity.read",
    "https://www.googleapis.com/auth/fitness.sleep.read",
    "https://www.googleapis.com/auth/fitness.heart_rate.read",
]

def _get_credentials():
    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            raise Exception("Token λήξε ή δεν υπάρχει. Διέγραψε token.json και κάνε νέο login.")
    return creds


def _ns_to_ms(ns: int) -> int:
    return ns // 1_000_000

def _ms_to_ns(ms: int) -> int:
    return ms * 1_000_000

def _day_range_ms(days_ago: int = 0):
    """Επιστρέφει (start_ms, end_ms) για X ημέρες πίσω (0 = σήμερα, 1 = χθες)."""
    now = datetime.datetime.now()
    target = now - datetime.timedelta(days=days_ago)
    start = target.replace(hour=0, minute=0, second=0, microsecond=0)
    end   = target.replace(hour=23, minute=59, second=59, microsecond=999999)
    epoch = datetime.datetime(1970, 1, 1)
    start_ms = int((start - epoch).total_seconds() * 1000)
    end_ms   = int((end   - epoch).total_seconds() * 1000)
    return start_ms, end_ms


def get_steps(days_ago: int = 0) -> int:
    """Επιστρέφει αριθμό βημάτων για την ημέρα."""
    creds   = _get_credentials()
    service = build("fitness", "v1", credentials=creds)
    start_ms, end_ms = _day_range_ms(days_ago)

    body = {
        "aggregateBy": [{"dataTypeName": "com.google.step_count.delta"}],
        "bucketByTime": {"durationMillis": 86400000},
        "startTimeMillis": start_ms,
        "endTimeMillis":   end_ms,
    }
    res = service.users().dataset().aggregate(userId="me", body=body).execute()
    total = 0
    for bucket in res.get("bucket", []):
        for dataset in bucket.get("dataset", []):
            for point in dataset.get("point", []):
                for val in point.get("value", []):
                    total += val.get("intVal", 0)
    return total


def get_sleep(days_ago: int = 1) -> dict:
    """
    Επιστρέφει ύπνο για τη νύχτα (default: χθες βράδυ).
    Returns: {"total_minutes": int, "deep_minutes": int, "light_minutes": int, "rem_minutes": int}
    """
    creds   = _get_credentials()
    service = build("fitness", "v1", credentials=creds)

    # Ύπνος: από 18:00 χθες μέχρι 12:00 σήμερα
    now    = datetime.datetime.now()
    target = now - datetime.timedelta(days=days_ago)
    epoch  = datetime.datetime(1970, 1, 1)
    start  = target.replace(hour=18, minute=0, second=0, microsecond=0)
    end    = (target + datetime.timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0)
    start_ms = int((start - epoch).total_seconds() * 1000)
    end_ms   = int((end   - epoch).total_seconds() * 1000)

    body = {
        "aggregateBy": [{"dataTypeName": "com.google.sleep.segment"}],
        "bucketByTime": {"durationMillis": int((end - start).total_seconds() * 1000)},
        "startTimeMillis": start_ms,
        "endTimeMillis":   end_ms,
    }
    res = service.users().dataset().aggregate(userId="me", body=body).execute()

    # Sleep segment values: 1=awake, 2=sleep, 3=out-of-bed, 4=light, 5=deep, 6=REM
    total = deep = light = rem = 0
    for bucket in res.get("bucket", []):
        for dataset in bucket.get("dataset", []):
            for point in dataset.get("point", []):
                start_ns = point.get("startTimeNanos", 0)
                end_ns   = point.get("endTimeNanos", 0)
                duration_min = (int(end_ns) - int(start_ns)) / 1_000_000_000 / 60
                for val in point.get("value", []):
                    seg = val.get("intVal", 0)
                    if seg in (2, 4, 5, 6):  # κάποιο είδος ύπνου
                        total += duration_min
                    if seg == 5:
                        deep  += duration_min
                    elif seg == 4:
                        light += duration_min
                    elif seg == 6:
                        rem   += duration_min

    return {
        "total_minutes": round(total),
        "deep_minutes":  round(deep),
        "light_minutes": round(light),
        "rem_minutes":   round(rem),
    }


def get_heart_rate(days_ago: int = 0) -> dict:
    """Επιστρέφει μέσο και μέγιστο καρδιακό παλμό."""
    creds   = _get_credentials()
    service = build("fitness", "v1", credentials=creds)
    start_ms, end_ms = _day_range_ms(days_ago)

    body = {
        "aggregateBy": [{"dataTypeName": "com.google.heart_rate.bpm"}],
        "bucketByTime": {"durationMillis": 86400000},
        "startTimeMillis": start_ms,
        "endTimeMillis":   end_ms,
    }
    res = service.users().dataset().aggregate(userId="me", body=body).execute()
    avg_bpm = max_bpm = 0
    for bucket in res.get("bucket", []):
        for dataset in bucket.get("dataset", []):
            for point in dataset.get("point", []):
                for val in point.get("value", []):
                    fp = val.get("fpVal", 0)
                    if fp > 0:
                        if avg_bpm == 0:
                            avg_bpm = fp
                        else:
                            avg_bpm = (avg_bpm + fp) / 2
                        max_bpm = max(max_bpm, fp)
    return {"avg_bpm": round(avg_bpm), "max_bpm": round(max_bpm)}


def get_daily_summary(days_ago: int = 1) -> str:
    """
    Πλήρης σύνοψη για μία μέρα — βήματα + ύπνος + παλμοί.
    Επιστρέφει έτοιμο κείμενο για τον Αστακό.
    days_ago=0 → σήμερα, days_ago=1 → χθες
    """
    label = "σήμερα" if days_ago == 0 else "χθες"
    lines = [f"📊 *Σύνοψη {label}:*\n"]

    try:
        steps = get_steps(days_ago)
        if steps > 0:
            emoji = "🔥" if steps >= 10000 else "👣" if steps >= 5000 else "🐌"
            lines.append(f"{emoji} Βήματα: *{steps:,}*")
        else:
            lines.append("👣 Βήματα: δεν βρέθηκαν δεδομένα")
    except Exception as e:
        lines.append(f"👣 Βήματα: σφάλμα ({e})")

    try:
        sleep = get_sleep(days_ago if days_ago > 0 else 1)
        if sleep["total_minutes"] > 0:
            h = sleep["total_minutes"] // 60
            m = sleep["total_minutes"] % 60
            sleep_emoji = "😴" if h >= 7 else "😐" if h >= 5 else "😵"
            detail = []
            if sleep["deep_minutes"] > 0:
                detail.append(f"βαθύς {sleep['deep_minutes']}′")
            if sleep["rem_minutes"] > 0:
                detail.append(f"REM {sleep['rem_minutes']}′")
            detail_str = f" ({', '.join(detail)})" if detail else ""
            lines.append(f"{sleep_emoji} Ύπνος: *{h}ω {m}′*{detail_str}")
        else:
            lines.append("😴 Ύπνος: δεν βρέθηκαν δεδομένα")
    except Exception as e:
        lines.append(f"😴 Ύπνος: σφάλμα ({e})")

    try:
        hr = get_heart_rate(days_ago)
        if hr["avg_bpm"] > 0:
            lines.append(f"❤️ Καρδιά: μέσος *{hr['avg_bpm']} bpm* / max {hr['max_bpm']} bpm")
        else:
            lines.append("❤️ Καρδιά: δεν βρέθηκαν δεδομένα")
    except Exception as e:
        lines.append(f"❤️ Καρδιά: σφάλμα ({e})")

    return "\n".join(lines)


if __name__ == "__main__":
    print(get_daily_summary(days_ago=1))
