# ================================================================
# Project: Astakos AI Agent 🦞
# Module:  Google Fit REST API
# Auth:    OAuth2 token.json (same as mail/drive/calendar)
#
# Note: Google Fit API is deprecated but functional.
# For reliable background sync without opening the app:
#   Samsung Health → Settings → Connected services → Google Fit → ON
# ================================================================

import datetime
import json
import os
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from core.i18n import t

import config
TOKEN_PATH       = config.TOKEN_PATH
CREDENTIALS_PATH = config.CREDENTIALS_PATH

SHARED_GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/tasks",
]

FIT_SCOPES = [
    "https://www.googleapis.com/auth/fitness.activity.read",
    "https://www.googleapis.com/auth/fitness.sleep.read",
    "https://www.googleapis.com/auth/fitness.heart_rate.read",
]

SCOPES = SHARED_GOOGLE_SCOPES + FIT_SCOPES


class GoogleFitAuthError(RuntimeError):
    """Raised when the shared Google token cannot authorize Google Fit reads."""


def _read_token_scopes() -> set[str]:
    if not os.path.exists(TOKEN_PATH):
        return set()

    try:
        with open(TOKEN_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return set()

    scopes = data.get("scopes") or data.get("scope") or []
    if isinstance(scopes, str):
        scopes = scopes.split()
    return {scope for scope in scopes if isinstance(scope, str)}


def _missing_fit_scopes(token_scopes: set[str]) -> list[str]:
    return [scope for scope in FIT_SCOPES if scope not in token_scopes]


def _ensure_fit_token_scopes() -> None:
    token_scopes = _read_token_scopes()
    if not token_scopes:
        return

    missing = _missing_fit_scopes(token_scopes)
    if not missing:
        return

    has_google_health = any("googlehealth." in scope for scope in token_scopes)
    if has_google_health:
        raise GoogleFitAuthError(
            t("skills.google_fit.msg_auth_warning_1") + " " + t("skills.google_fit.msg_auth_warning_2")
        )

    raise GoogleFitAuthError(
        t("skills.google_fit.missing_scopes")
        + ", ".join(missing)
    )


def _save_credentials(creds: Credentials) -> None:
    with open(TOKEN_PATH, "w", encoding="utf-8") as token:
        token.write(creds.to_json())


def authorize_google_fit() -> str:
    if not os.path.exists(CREDENTIALS_PATH):
        raise GoogleFitAuthError(t("skills.google_fit.missing_creds"))

    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
    _save_credentials(creds)
    return t("skills.google_fit.token_updated")


def _get_credentials():
    creds = None
    if os.path.exists(TOKEN_PATH):
        _ensure_fit_token_scopes()
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                _save_credentials(creds)
            except RefreshError as e:
                if "invalid_scope" in str(e).lower():
                    raise GoogleFitAuthError(
                        t("skills.google_fit.msg_auth_rejected")
                    ) from e
                raise
        else:
            raise Exception(t("skills.google_fit.token_expired"))
    return creds


def _fit_auth_summary(title: str) -> str | None:
    try:
        _get_credentials()
    except GoogleFitAuthError as e:
        return "\n".join([
            title,
            "",
            f"⚠️ Google Fit auth: {e}",
            t("skills.google_fit.msg_auth_other_tools_2"),
        ])
    return None


def _ns_to_ms(ns: int) -> int:
    return ns // 1_000_000

def _ms_to_ns(ms: int) -> int:
    return ms * 1_000_000


def _fitness_service():
    return build("fitness", "v1", credentials=_get_credentials(), cache_discovery=False)


def _list_data_sources(service, data_type_name: str) -> list[str]:
    sources = service.users().dataSources().list(userId="me").execute().get("dataSource", [])
    return [
        s.get("dataStreamId", "")
        for s in sources
        if s.get("dataType", {}).get("name") == data_type_name and s.get("dataStreamId")
    ]


def _day_range_ms(days_ago: int = 0):
    """Returns (start_ms, end_ms) for X days back (0 = today, 1 = yesterday)."""
    now = datetime.datetime.now()
    target = now - datetime.timedelta(days=days_ago)
    start = target.replace(hour=0, minute=0, second=0, microsecond=0)
    end   = target.replace(hour=23, minute=59, second=59, microsecond=999999)
    start_ms = int(start.timestamp() * 1000)
    end_ms   = int(end.timestamp() * 1000)
    return start_ms, end_ms


def get_steps(days_ago: int = 0) -> int:
    """Returns the number of steps for the day."""
    service = _fitness_service()
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
    Returns sleep data for the night (default: last night).
    Returns: {"total_minutes": int, "deep_minutes": int, "light_minutes": int, "rem_minutes": int}
    """
    service = _fitness_service()

    now    = datetime.datetime.now()
    target = now - datetime.timedelta(days=days_ago)
    start  = (target - datetime.timedelta(days=1)).replace(hour=20, minute=0, second=0, microsecond=0)
    end    = min(target.replace(hour=14, minute=0, second=0, microsecond=0), now)
    start_ns = int(start.timestamp() * 1_000_000_000)
    end_ns   = int(end.timestamp()   * 1_000_000_000)
    dataset_id = f"{start_ns}-{end_ns}"

    total = deep = light = rem = 0

    preferred_sources = [
        "derived:com.google.sleep.segment:com.google.android.gms:merged",
        "raw:com.google.sleep.segment:com.sec.android.app.shealth:health_platform",
        "raw:com.google.sleep.segment:com.urbandroid.sleep:saa-generic",
    ]
    dynamic_sources = _list_data_sources(service, "com.google.sleep.segment")
    source_ids = []
    for source_id in preferred_sources + dynamic_sources:
        if source_id and source_id not in source_ids:
            source_ids.append(source_id)

    for source_id in source_ids:
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
                break
        except Exception:
            continue

    return {
        "total_minutes": round(total),
        "deep_minutes":  round(deep),
        "light_minutes": round(light),
        "rem_minutes":   round(rem),
    }


def _collect_raw_heart_rates(service, start_ms: int, end_ms: int) -> list[float]:
    dataset_id = f"{_ms_to_ns(start_ms)}-{_ms_to_ns(end_ms)}"
    values = []
    for source_id in _list_data_sources(service, "com.google.heart_rate.bpm"):
        try:
            res = service.users().dataSources().datasets().get(
                userId="me",
                dataSourceId=source_id,
                datasetId=dataset_id,
            ).execute()
        except Exception:
            continue
        for point in res.get("point", []):
            for val in point.get("value", []):
                bpm = val.get("fpVal", 0)
                if bpm > 0:
                    values.append(float(bpm))
    return values


def get_heart_rate(days_ago: int = 0) -> dict:
    """Returns average and maximum heart rate."""
    service = _fitness_service()
    start_ms, end_ms = _day_range_ms(days_ago)
    if days_ago == 0:
        end_ms = min(end_ms, int(datetime.datetime.now().timestamp() * 1000))

    body = {
        "aggregateBy": [{"dataTypeName": "com.google.heart_rate.bpm"}],
        "bucketByTime": {"durationMillis": 86400000},
        "startTimeMillis": start_ms,
        "endTimeMillis":   end_ms,
    }
    res = service.users().dataset().aggregate(userId="me", body=body).execute()
    avg_values = []
    max_values = []
    raw_values = []
    for bucket in res.get("bucket", []):
        for dataset in bucket.get("dataset", []):
            for point in dataset.get("point", []):
                point_values = [val.get("fpVal", 0) for val in point.get("value", [])]
                if point.get("dataTypeName") == "com.google.heart_rate.summary" and len(point_values) >= 3:
                    avg, max_bpm, _min_bpm = point_values[:3]
                    if avg > 0:
                        avg_values.append(float(avg))
                    if max_bpm > 0:
                        max_values.append(float(max_bpm))
                    continue
                for fp in point_values:
                    if fp > 0:
                        raw_values.append(float(fp))
    if avg_values or max_values:
        avg_bpm = sum(avg_values) / len(avg_values) if avg_values else 0
        max_bpm = max(max_values) if max_values else 0
    else:
        raw_values = raw_values or _collect_raw_heart_rates(service, start_ms, end_ms)
        avg_bpm = sum(raw_values) / len(raw_values) if raw_values else 0
        max_bpm = max(raw_values) if raw_values else 0
    return {"avg_bpm": round(avg_bpm), "max_bpm": round(max_bpm)}


def get_morning_summary() -> str:
    auth_problem = _fit_auth_summary("🌅 *Morning Google Fit briefing:*")
    if auth_problem:
        return auth_problem

    lines = ["🌅 *Morning Google Fit briefing:*\n"]

    try:
        steps = get_steps(1)
        if steps > 0:
            emoji = "🔥" if steps >= 10000 else "👣" if steps >= 5000 else "🐌"
            lines.append(f"{emoji} " + t("skills.google_fit.msg_steps_yest", steps=f"{steps:,}"))
        else:
            lines.append(t("skills.google_fit.msg_steps_yest_none"))
    except Exception as e:
        lines.append(t("skills.google_fit.msg_steps_yest_err", e=e))

    try:
        sleep = get_sleep(1)
        if sleep["total_minutes"] > 0:
            h = sleep["total_minutes"] // 60
            m = sleep["total_minutes"] % 60
            emoji = "😴" if h >= 7 else "😐" if h >= 5 else "😵"
            detail = []
            if sleep["deep_minutes"] > 0:
                detail.append(t("skills.google_fit.detail_deep", m=sleep["deep_minutes"]))
            if sleep["rem_minutes"] > 0:
                detail.append(f"REM {sleep['rem_minutes']}′")
            detail_str = f" ({', '.join(detail)})" if detail else ""
            lines.append(f"{emoji} " + t("skills.google_fit.msg_sleep_yest", h=h, m=m, detail=detail_str))
        else:
            lines.append(t("skills.google_fit.msg_sleep_yest_none"))
    except Exception as e:
        lines.append(t("skills.google_fit.msg_sleep_yest_err", e=e))

    try:
        hr = get_heart_rate(1)
        if hr["avg_bpm"] == 0:
            hr = get_heart_rate(0)
        if hr["avg_bpm"] > 0:
            lines.append(t("skills.google_fit.msg_hr_yest", avg=hr["avg_bpm"], max=hr["max_bpm"]))
        else:
            lines.append(t("skills.google_fit.msg_hr_yest_none"))
    except Exception as e:
        lines.append(t("skills.google_fit.msg_hr_yest_err", e=e))

    return "\n".join(lines)


def get_daily_summary(days_ago: int = 1) -> str:
    label = t("skills.google_fit.label_today") if days_ago == 0 else t("skills.google_fit.label_yest")
    title = t("skills.google_fit.msg_summary_title", label=label)
    auth_problem = _fit_auth_summary(title)
    if auth_problem:
        return auth_problem

    lines = [f"{title}\n"]

    try:
        steps = get_steps(days_ago)
        if steps > 0:
            emoji = "🔥" if steps >= 10000 else "👣" if steps >= 5000 else "🐌"
            lines.append(f"{emoji} " + t("skills.google_fit.msg_steps_today", steps=f"{steps:,}"))
        else:
            lines.append(t("skills.google_fit.msg_steps_today_none"))
    except Exception as e:
        lines.append(t("skills.google_fit.msg_steps_today_err", e=e))

    try:
        sleep = get_sleep(days_ago if days_ago > 0 else 1)
        if sleep["total_minutes"] > 0:
            h = sleep["total_minutes"] // 60
            m = sleep["total_minutes"] % 60
            emoji = "😴" if h >= 7 else "😐" if h >= 5 else "😵"
            detail = []
            if sleep["deep_minutes"] > 0:
                detail.append(t("skills.google_fit.detail_deep", m=sleep["deep_minutes"]))
            if sleep["rem_minutes"] > 0:
                detail.append(f"REM {sleep['rem_minutes']}′")
            detail_str = f" ({', '.join(detail)})" if detail else ""
            lines.append(f"{emoji} " + t("skills.google_fit.msg_sleep_yest", h=h, m=m, detail=detail_str))
        else:
            lines.append(t("skills.google_fit.msg_sleep_yest_none"))
    except Exception as e:
        lines.append(t("skills.google_fit.msg_sleep_yest_err", e=e))

    try:
        hr = get_heart_rate(days_ago)
        if hr["avg_bpm"] > 0:
            lines.append(t("skills.google_fit.msg_hr_today", avg=hr["avg_bpm"], max=hr["max_bpm"]))
        else:
            lines.append(t("skills.google_fit.msg_hr_yest_none"))
    except Exception as e:
        lines.append(t("skills.google_fit.msg_hr_yest_err", e=e))

    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    cmd      = sys.argv[1] if len(sys.argv) > 1 else "summary"
    days_ago = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    if cmd == "auth":
        print(authorize_google_fit())
    elif cmd == "steps":
        print(f"Steps: {get_steps(days_ago)}")
    elif cmd == "sleep":
        print(get_sleep(days_ago))
    elif cmd == "heart":
        print(get_heart_rate(days_ago))
    else:
        print(get_daily_summary(days_ago))
