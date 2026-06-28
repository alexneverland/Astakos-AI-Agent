import json
import os
import sqlite3

_BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(_BASE, "..", "astakos_routines.db")

def load_conditions(raw: str | None) -> list[dict]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def dump_conditions(conds: list[dict]) -> str:
    return json.dumps(conds, ensure_ascii=False)


def has_context_flag(
    conds: list[dict],
    *,
    flag: str,
    mode: str | None = None,
    equals=None,
) -> bool:
    for c in conds:
        if c.get("condition_type") != "context_flag":
            continue
        payload = c.get("condition_payload") or {}
        if payload.get("flag") != flag:
            continue
        if mode is not None and c.get("condition_mode") != mode:
            continue
        if equals is not None and payload.get("equals") != equals:
            continue
        return True
    return False


def remove_context_flag(conds: list[dict], flag: str) -> list[dict]:
    out = []
    for c in conds:
        payload = c.get("condition_payload") or {}
        if c.get("condition_type") == "context_flag" and payload.get("flag") == flag:
            continue
        out.append(c)
    return out


def append_user_out_of_home_suppress_if_missing(conds: list[dict]) -> list[dict]:
    if has_context_flag(
        conds,
        flag="user_out_of_home",
        mode="suppress_when_true",
        equals=True,
    ):
        return conds

    conds.append(
        {
            "condition_type": "context_flag",
            "condition_payload": {"flag": "user_out_of_home", "equals": True},
            "condition_mode": "suppress_when_true",
            "source_memory_ref": "backfill_user_out_of_home",
        }
    )
    return conds


def normalize_routine_conditions(routine_id: int, event_name: str, conds: list[dict]) -> list[dict]:
    event_l = (event_name or "").lower()

    is_sleep = "υπν" in event_l or "sleep" in event_l
    is_park_like = "παρκ" in event_l or "βολτ" in event_l or "παιχν" in event_l
    is_home_only = "μαγειρ" in event_l or "φαγητ" in event_l or "γευμ" in event_l or "κουζιν" in event_l

    if routine_id == 2 or is_sleep:
        conds = remove_context_flag(conds, "family_outside_activity")
        conds = append_user_out_of_home_suppress_if_missing(conds)

    elif routine_id in {3, 10} or is_park_like:
        conds = append_user_out_of_home_suppress_if_missing(conds)

    elif routine_id == 15 or is_home_only:
        conds = append_user_out_of_home_suppress_if_missing(conds)

    return conds


def run_backfill() -> dict:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    rows = cursor.execute(
        """
        SELECT id, event_name, conditions_json
        FROM routines
        ORDER BY id
        """
    ).fetchall()

    updated = []

    for row in rows:
        rid = row["id"]
        event_name = row["event_name"]
        old_conds = load_conditions(row["conditions_json"])
        new_conds = normalize_routine_conditions(rid, event_name, list(old_conds))

        old_cmp = json.dumps(old_conds, ensure_ascii=False, sort_keys=True)
        new_cmp = json.dumps(new_conds, ensure_ascii=False, sort_keys=True)

        if old_cmp == new_cmp:
            continue

        cursor.execute(
            "UPDATE routines SET conditions_json=? WHERE id=?",
            (dump_conditions(new_conds), rid),
        )
        updated.append(
            {
                "id": rid,
                "event_name": event_name,
                "conditions": new_conds,
            }
        )

    conn.commit()
    conn.close()

    return {
        "updated_count": len(updated),
        "updated": updated,
    }


if __name__ == "__main__":
    result = run_backfill()
    print(json.dumps(result, ensure_ascii=False, indent=2))
