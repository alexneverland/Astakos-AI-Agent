import sqlite3
import json
import threading
from datetime import datetime
from config import STATE_DB

_db_lock = threading.Lock()

def _init_db():
    with _db_lock:
        with sqlite3.connect(STATE_DB) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pending_plans (
                    user_id TEXT PRIMARY KEY,
                    goal TEXT NOT NULL,
                    tasks_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)

_init_db()

def save_pending_plan(goal: str, tasks: list, user_id: str = "default"):
    tasks_json = json.dumps(tasks, ensure_ascii=False)
    created_at = datetime.now().isoformat()
    with _db_lock:
        with sqlite3.connect(STATE_DB) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO pending_plans (user_id, goal, tasks_json, created_at)
                VALUES (?, ?, ?, ?)
            """, (user_id, goal, tasks_json, created_at))

def get_pending_plan(user_id: str = "default") -> dict | None:
    with _db_lock:
        with sqlite3.connect(STATE_DB) as conn:
            cur = conn.execute("SELECT goal, tasks_json, created_at FROM pending_plans WHERE user_id = ?", (user_id,))
            row = cur.fetchone()
            if row:
                return {
                    "goal": row[0],
                    "tasks": json.loads(row[1]),
                    "created_at": row[2]
                }
            return None

def clear_pending_plan(user_id: str = "default"):
    with _db_lock:
        with sqlite3.connect(STATE_DB) as conn:
            conn.execute("DELETE FROM pending_plans WHERE user_id = ?", (user_id,))
