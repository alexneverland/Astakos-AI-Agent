from core.i18n import t
import json
import os
import sys
import unicodedata

# Ensure astakos_v2 is in PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from memory.routine_db import db_write_lock, get_connection


def normalize_text(text: str) -> str:
    raw = str(text or "").strip().lower()
    normalized = unicodedata.normalize("NFD", raw)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def is_football_routine(event_name: str) -> bool:
    event_name_norm = normalize_text(event_name)
    keywords = (t("prompts.ext_str_275"), t("prompts.ext_str_338"), t("prompts.ext_str_550"))
    return any(keyword in event_name_norm for keyword in keywords)


def _parse_payload(payload):
    if isinstance(payload, str):
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return payload
    return payload


def migrate_legacy_conditions():
    """
    Migrate legacy single-column conditions to the new `conditions_json` list structure.
    Also:
    - rewrites alexandros_at_camp -> alexandros_away_from_home
    - injects away_from_home + football_season conditions into football routines
    """
    conn = get_connection(write=True)
    cursor = conn.cursor()

    with db_write_lock:
        cursor.execute(
            """
            SELECT id, condition_type, condition_payload, condition_mode, event_name, conditions_json
            FROM routines
            """
        )
        rows = cursor.fetchall()

        migrated_count = 0
        rewritten_count = 0
        football_count = 0

        for r_id, c_type, c_payload_str, c_mode, event_name, c_json in rows:
            conditions_list = []

            if c_json:
                try:
                    conditions_list = json.loads(c_json)
                except json.JSONDecodeError:
                    conditions_list = []

            needs_update = False

            if c_type and not conditions_list:
                conditions_list.append(
                    {
                        "condition_type": c_type,
                        "condition_payload": _parse_payload(c_payload_str),
                        "condition_mode": c_mode,
                    }
                )
                needs_update = True
                migrated_count += 1

            rewritten = False
            for cond in conditions_list:
                if cond.get("condition_type") != "context_flag":
                    continue

                payload = _parse_payload(cond.get("condition_payload", {}))
                if isinstance(payload, dict) and payload.get("flag") == "alexandros_at_camp":
                    payload["flag"] = "alexandros_away_from_home"
                    cond["condition_payload"] = payload
                    rewritten = True

            if rewritten:
                needs_update = True
                rewritten_count += 1

            if is_football_routine(event_name):
                has_away_cond = False
                has_football_season_cond = False

                for cond in conditions_list:
                    if cond.get("condition_type") != "context_flag":
                        continue

                    payload = _parse_payload(cond.get("condition_payload", {}))
                    if not isinstance(payload, dict):
                        continue

                    if payload.get("flag") == "alexandros_away_from_home":
                        has_away_cond = True
                    if payload.get("flag") == "football_season":
                        has_football_season_cond = True

                if not has_away_cond:
                    conditions_list.append(
                        {
                            "condition_type": "context_flag",
                            "condition_payload": {
                                "flag": "alexandros_away_from_home",
                                "equals": True,
                            },
                            "condition_mode": "suppress_when_true",
                        }
                    )
                    needs_update = True
                    football_count += 1

                if not has_football_season_cond:
                    conditions_list.append(
                        {
                            "condition_type": "context_flag",
                            "condition_payload": {
                                "flag": "football_season",
                                "equals": True,
                            },
                            "condition_mode": "allow_when_true",
                        }
                    )
                    needs_update = True
                    football_count += 1

            if needs_update:
                cursor.execute(
                    "UPDATE routines SET conditions_json = ? WHERE id = ?",
                    (json.dumps(conditions_list, ensure_ascii=False), r_id),
                )

        conn.commit()

    print(f"Migrated {migrated_count} routines with legacy conditions to conditions_json.")
    print(f"Rewrote {rewritten_count} legacy alexandros_at_camp conditions.")
    print(f"Injected {football_count} football conditions.")


if __name__ == "__main__":
    migrate_legacy_conditions()

