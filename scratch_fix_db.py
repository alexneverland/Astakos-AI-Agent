import sqlite3
import json

def fix():
    conn = sqlite3.connect('c:/astakos_v2/astakos_routines.db')
    cursor = conn.cursor()
    
    # Fix ID 100 (Roblox)
    roblox_conds = [{
        "condition_type": "context_flag",
        "condition_payload": {"flag": "user_out_of_home", "equals": False},
        "condition_mode": "allow_when_true",
        "source_memory_ref": "llm_agent"
    }]
    cursor.execute("UPDATE routines SET conditions_json=? WHERE id=100", (json.dumps(roblox_conds),))
    
    # Fix ID 96 (rabbit cage)
    rabbit_conds = [
        {
            "condition_type": "shift_mode",
            "condition_payload": {"flag": "current_shift", "equals": "morning"},
            "condition_mode": "suppress_when_true",
            "source_memory_ref": "llm_agent"
        },
        {
            "condition_type": "context_flag",
            "condition_payload": {"flag": "user_out_of_home", "equals": False},
            "condition_mode": "allow_when_true",
            "source_memory_ref": "llm_agent"
        }
    ]
    cursor.execute("UPDATE routines SET conditions_json=? WHERE id=96", (json.dumps(rabbit_conds),))
    
    conn.commit()
    conn.close()

if __name__ == '__main__':
    fix()
