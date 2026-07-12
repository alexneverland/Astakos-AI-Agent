from core.i18n import t
import json
import os
import sqlite3
import sys
import unicodedata
from datetime import datetime

_BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(_BASE, "..", "astakos_routines.db")


def _normalize_condition_payload(payload):
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            return payload
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _normalize_text(text: str) -> str:
    raw = str(text or "").strip().lower()
    normalized = unicodedata.normalize("NFD", raw)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _is_football_routine(event_name: str) -> bool:
    event = _normalize_text(event_name)
    return any(token in event for token in (t("prompts.ext_str_275"), t("prompts.ext_str_338"), t("prompts.ext_str_550")))


def normalize_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    today = datetime.now().strftime("%Y-%m-%d")
    routines = cursor.execute("SELECT * FROM routines").fetchall()

    for r in routines:
        r_id = r["id"]
        event = _normalize_text(r["event_name"] or "")
        paused_until = r["paused_until"]
        pause_reason = r["pause_reason"]
        resume_rule = r["resume_rule"]

        updates = {}
        cond_updates = {}

        # 1. School break -> convert to context-gated condition
        if paused_until and paused_until >= today and pause_reason == "school_break":
            cond_updates = {
                "type": "context_flag",
                "payload": json.dumps({"flag": "school_open", "equals": True}, ensure_ascii=False),
                "mode": "allow_when_true",
            }
            updates["paused_until"] = None
            updates["pause_reason"] = None

        # 2. Summer football break -> convert to football_season condition
        elif (resume_rule == "every_september" or pause_reason == "summer_break") and _is_football_routine(r["event_name"]):
            cond_updates = {
                "type": "context_flag",
                "payload": json.dumps({"flag": "football_season", "equals": True}, ensure_ascii=False),
                "mode": "allow_when_true",
            }
            if paused_until and paused_until >= today:
                updates["paused_until"] = None
                updates["pause_reason"] = None

        # 3. Temporary absence -> convert to generic away_from_home condition
        elif paused_until and paused_until >= today and pause_reason == "camp_absence":
            cond_updates = {
                "type": "context_flag",
                "payload": json.dumps({"flag": "alexandros_away_from_home", "equals": True}, ensure_ascii=False),
                "mode": "suppress_when_true",
            }
            updates["paused_until"] = None
            updates["pause_reason"] = None

        if cond_updates or updates:
            existing_type = r["condition_type"]
            existing_payload = r["condition_payload"]
            existing_mode = r["condition_mode"]

            if cond_updates:
                same_cond = (
                    existing_type == cond_updates["type"]
                    and _normalize_condition_payload(existing_payload) == _normalize_condition_payload(cond_updates["payload"])
                    and existing_mode == cond_updates["mode"]
                )
                if not same_cond:
                    updates["condition_type"] = cond_updates["type"]
                    updates["condition_payload"] = cond_updates["payload"]
                    updates["condition_mode"] = cond_updates["mode"]
                    updates["source_memory_ref"] = "normalization_script"
                    print(f"Adding condition to routine {r_id} ({event}): {cond_updates['payload']}")

            if updates:
                set_clauses = []
                params = []
                for key, value in updates.items():
                    set_clauses.append(f"{key} = ?")
                    params.append(value)
                params.append(r_id)

                query = f"UPDATE routines SET {', '.join(set_clauses)} WHERE id = ?"
                cursor.execute(query, params)
                print(f"Updated routine {r_id} with: {updates}")

    conn.commit()
    conn.close()


if __name__ == "__main__":
    normalize_db()
    print("Done")

