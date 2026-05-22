import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "astakos_routines.db")

def get_connection():
    return sqlite3.connect(DB_PATH)

def setup_db():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS routines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            day_of_week TEXT,
            time_str TEXT,
            event_name TEXT,
            event_type TEXT,
            confidence REAL,
            last_triggered TEXT,
            decay_counter INTEGER,
            is_active BOOLEAN DEFAULT 1
        )
    ''')
    conn.commit()
    conn.close()

def upsert_routine(day, time, event, ev_type="general", confidence_boost=0.1):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, confidence FROM routines
        WHERE day_of_week=? AND time_str=? AND event_name=?
    ''', (day, time, event))
    row = cursor.fetchone()
    if row:
        r_id, current_conf = row
        new_conf = min(1.0, current_conf + confidence_boost)
        cursor.execute('UPDATE routines SET confidence=?, decay_counter=0, is_active=1 WHERE id=?', (new_conf, r_id))
        result = "updated"
    else:
        cursor.execute('''
            INSERT INTO routines (day_of_week, time_str, event_name, event_type, confidence, decay_counter)
            VALUES (?, ?, ?, ?, ?, 0)
        ''', (day, time, event, ev_type, 0.5))
        result = "created"
    conn.commit()
    conn.close()
    return result

def confirm_routine(routine_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT confidence FROM routines WHERE id=?', (routine_id,))
    row = cursor.fetchone()
    if row:
        new_conf = min(1.0, row[0] + 0.2)
        cursor.execute('UPDATE routines SET confidence=?, decay_counter=0, is_active=1 WHERE id=?', (new_conf, routine_id))
    conn.commit()
    conn.close()

def decay_routine(routine_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT confidence, decay_counter FROM routines WHERE id=?', (routine_id,))
    row = cursor.fetchone()
    if row:
        new_conf = max(0.0, row[0] - 0.2)
        new_decay = row[1] + 1
        is_active = 0 if new_conf < 0.1 else 1
        cursor.execute('UPDATE routines SET confidence=?, decay_counter=?, is_active=? WHERE id=?', (new_conf, new_decay, is_active, routine_id))
    conn.commit()
    conn.close()

def get_routines_for_day(day: str) -> list:
    conn = get_connection()
    cursor = conn.cursor()
    day = day.capitalize()
    cursor.execute('''
        SELECT id, time_str, event_name, event_type, confidence
        FROM routines
        WHERE (day_of_week=? OR day_of_week='Everyday' OR day_of_week='Καθημερινά')
        AND is_active=1
        ORDER BY time_str ASC
    ''', (day,))
    rows = cursor.fetchall()
    conn.close()
    return [
        {"id": r[0], "time": r[1], "event": r[2], "type": r[3], "confidence": round(r[4], 2)}
        for r in rows
    ]

setup_db()
