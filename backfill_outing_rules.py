from core.i18n import t
import json
import sqlite3

from config import NLP_CONFIG
routines = NLP_CONFIG.get("routines", {})
tokens = routines.get("tokens", {})
OUTING_ROUTINE_TOKENS = tokens.get("_OUTING_ROUTINE_TOKENS", [t("prompts.ext_str_574"), t("prompts.ext_str_569"), t("prompts.ext_str_390"), t("prompts.ext_str_651"), t("prompts.ext_str_444")])
HOME_ONLY_ROUTINE_TOKENS = tokens.get("_HOME_ONLY_ROUTINE_TOKENS", [t("prompts.ext_str_441"), t("prompts.ext_str_662"), t("prompts.ext_str_620"), t("prompts.ext_str_221"), t("prompts.ext_str_547")])

conn = sqlite3.connect("astakos_routines.db")
cur = conn.cursor()

rows = cur.execute("""
    SELECT id, event_name, conditions_json
    FROM routines
""").fetchall()

def ensure_condition(conditions, condition_type, payload, mode):
    for c in conditions:
        if (
            c.get("condition_type") == condition_type
            and c.get("condition_payload") == payload
            and c.get("condition_mode") == mode
        ):
            return conditions
    conditions.append({
        "condition_type": condition_type,
        "condition_payload": payload,
        "condition_mode": mode,
    })
    return conditions

updated = 0

for rid, event_name, conditions_json in rows:
    event_l = (event_name or "").lower()
    conditions = json.loads(conditions_json) if conditions_json else []
    before = json.dumps(conditions, ensure_ascii=False, sort_keys=True)

    if any(tok in event_l for tok in OUTING_ROUTINE_TOKENS):
        conditions = ensure_condition(
            conditions,
            "context_flag",
            {"flag": "state:alexandros:outing", "equals": "in_progress"},
            "suppress_when_true",
        )
        conditions = ensure_condition(
            conditions,
            "context_flag",
            {"flag": "user_out_of_home", "equals": True},
            "suppress_when_true",
        )

    if any(tok in event_l for tok in HOME_ONLY_ROUTINE_TOKENS):
        conditions = ensure_condition(
            conditions,
            "context_flag",
            {"flag": "user_out_of_home", "equals": True},
            "suppress_when_true",
        )

    after = json.dumps(conditions, ensure_ascii=False, sort_keys=True)

    if after != before:
        cur.execute(
            "UPDATE routines SET conditions_json=? WHERE id=?",
            (json.dumps(conditions, ensure_ascii=False), rid),
        )
        updated += 1
        print(f"updated #{rid}: {event_name}")

conn.commit()
conn.close()
print(f"done, updated={updated}")

