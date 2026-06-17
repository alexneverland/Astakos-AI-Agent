import os
import sys
import sqlite3
import json
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

def normalize_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    today = datetime.now().strftime("%Y-%m-%d")

    # Fetch routines
    routines = cursor.execute("SELECT * FROM routines").fetchall()
    
    for r in routines:
        r_id = r["id"]
        event = (r["event_name"] or "").lower()
        paused_until = r["paused_until"]
        pause_reason = r["pause_reason"]
        resume_rule = r["resume_rule"]
        muted_until = r["muted_until"]

        updates = {}
        cond_updates = {}
        
        # 1. School Break
        if paused_until and paused_until >= today and pause_reason == "school_break":
            cond_updates = {
                "type": "context_flag",
                "payload": json.dumps({"flag": "school_open", "equals": True}, ensure_ascii=False),
                "mode": "allow_when_true"
            }
            updates["paused_until"] = None
            updates["pause_reason"] = None
            
        # 2. Summer Break (Football)
        elif (resume_rule == "every_september" or pause_reason == "summer_break") and ("ποδοσφαιρ" in event or "μπαλα" in event):
            cond_updates = {
                "type": "context_flag",
                "payload": json.dumps({"flag": "football_season", "equals": True}, ensure_ascii=False),
                "mode": "allow_when_true"
            }
            if paused_until and paused_until >= today:
                updates["paused_until"] = None
                updates["pause_reason"] = None
                
        # 3. Camp Absence
        elif (paused_until and paused_until >= today and pause_reason == "camp_absence"):
            cond_updates = {
                "type": "context_flag",
                "payload": json.dumps({"flag": "alexandros_at_camp", "equals": True}, ensure_ascii=False),
                "mode": "suppress_when_true"
            }
            if paused_until and paused_until >= today and pause_reason == "camp_absence":
                updates["paused_until"] = None
                updates["pause_reason"] = None

        if cond_updates or updates:
            # Check existing condition
            existing_type = r["condition_type"]
            existing_payload = r["condition_payload"]
            existing_mode = r["condition_mode"]
            
            if cond_updates:
                same_cond = (
                    existing_type == cond_updates["type"] and 
                    _normalize_condition_payload(existing_payload) == _normalize_condition_payload(cond_updates["payload"]) and
                    existing_mode == cond_updates["mode"]
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
                for k, v in updates.items():
                    set_clauses.append(f"{k} = ?")
                    params.append(v)
                params.append(r_id)
                
                query = f"UPDATE routines SET {', '.join(set_clauses)} WHERE id = ?"
                cursor.execute(query, params)
                print(f"Updated routine {r_id} with: {updates}")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    normalize_db()
    print("Done")
