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
    start_ms = int(start.timestamp() * 1000)
    end_ms   = int(end.timestamp() * 1000)
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
    Διαβάζει απευθείας από Samsung Health data source για αξιοπιστία.
    Returns: {"total_minutes": int, "deep_minutes": int, "light_minutes": int, "rem_minutes": int}
    """
    creds   = _get_credentials()
    service = build("fitness", "v1", credentials=creds)

    # Παράθυρο: από 20:00 της προηγούμενης μέρας έως 14:00 της επόμενης
    # Καλύπτει οποιαδήποτε ώρα ύπνου/αφύπνισης
    now    = datetime.datetime.now()
    target = now - datetime.timedelta(days=days_ago)
    start  = (target - datetime.timedelta(days=1)).replace(hour=20, minute=0, second=0, microsecond=0)
    end    = target.replace(hour=14, minute=0, second=0, microsecond=0)
    start_ns = int(start.timestamp() * 1_000_000_000)
    end_ns   = int(end.timestamp()   * 1_000_000_000)
    dataset_id = f"{start_ns}-{end_ns}"

    # Sleep segment values: 1=awake, 2=sleep, 3=out-of-bed, 4=light, 5=deep, 6=REM
    total = deep = light = rem = 0

    # Πρώτα δοκιμάζουμε Samsung Health απευθείας
    SAMSUNG_SOURCE = "raw:com.google.sleep.segment:com.sec.android.app.shealth:health_platform"
    MERGED_SOURCE  = "derived:com.google.sleep.segment:com.google.android.gms:merged"

    for source_id in [SAMSUNG_SOURCE, MERGED_SOURCE]:
        try:
            res = service.users().dataSources().datasets().get(
                userId="me",
                dataSourceId=source_id,
                datasetId=dataset_id
            ).execute()
            points = res.get("point", [])
            if not points:
                continue
            for point in points:
                s_ns = int(point.get("startTimeNanos", 0))
                e_ns = int(point.get("endTimeNanos",   0))
                dur  = (e_ns - s_ns) / 1_000_000_000 / 60
                for val in point.get("value", []):
                    seg = val.get("intVal", 0)
                    if seg in (2, 4, 5, 6):
                        total += dur
                    if   seg == 5: deep  += dur
                    elif seg == 4: light += dur
                    elif seg == 6: rem   += dur
            if total > 0:
                break  # Βρήκαμε δεδομένα, σταματάμε
        except Exception:
            continue

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
    import sys
    # Χρήση: python google_fit.py [steps|sleep|heart|summary] [days_ago]
    # Π.χ.: python google_fit.py steps 0  → βήματα σήμερα
    #        python google_fit.py sleep 1  → ύπνος χθες
    cmd      = sys.argv[1] if len(sys.argv) > 1 else "summary"
    days_ago = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    if cmd == "steps":
        print(f"Βήματα: {get_steps(days_ago)}")
    elif cmd == "sleep":
        print(get_sleep(days_ago))
    elif cmd == "heart":
        print(get_heart_rate(days_ago))
    else:
        print(get_daily_summary(days_ago))