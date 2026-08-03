import sqlite3
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from config import STATE_DB

def create_tables(conn):
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS capabilities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT,
            description TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task TEXT,
            time TEXT,
            status TEXT DEFAULT 'pending',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            external_content_sources_json TEXT NOT NULL DEFAULT '[]'
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS lists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            list_name TEXT,
            item TEXT,
            added_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_date TEXT,
            channel TEXT,
            summary TEXT,
            completed TEXT,
            pending TEXT,
            next_session_hint TEXT,
            mood TEXT
        )
    ''')
    conn.commit()

def migrate_capabilities(conn):
    cap_file = os.path.join(BASE_DIR, "astakos_capabilities.json")
    if not os.path.exists(cap_file):
        return
    with open(cap_file, 'r', encoding='utf-8') as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            data = {}
    
    cursor = conn.cursor()
    cursor.execute("DELETE FROM capabilities")
    count = 0
    for can in data.get('can_do', []):
        cursor.execute("INSERT INTO capabilities (type, description) VALUES (?, ?)", ('can_do', can))
        count += 1
    for cannot in data.get('cannot_do', []):
        cursor.execute("INSERT INTO capabilities (type, description) VALUES (?, ?)", ('cannot_do', cannot))
        count += 1
    conn.commit()
    print(f"Migrated {count} capabilities.")

def migrate_reminders(conn):
    rem_file = os.path.join(BASE_DIR, "astakos_reminders.json")
    if not os.path.exists(rem_file):
        return
    with open(rem_file, 'r', encoding='utf-8') as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            data = []
    
    cursor = conn.cursor()
    cursor.execute("DELETE FROM reminders")
    count = 0
    for rem in data:
        task = rem.get('task', '')
        time_str = rem.get('time', '')
        status = rem.get('status', 'pending')
        cursor.execute("INSERT INTO reminders (task, time, status) VALUES (?, ?, ?)", (task, time_str, status))
        count += 1
    conn.commit()
    print(f"Migrated {count} reminders.")

def migrate_lists(conn):
    list_file = os.path.join(BASE_DIR, "astakos_lists.json")
    if not os.path.exists(list_file):
        return
    with open(list_file, 'r', encoding='utf-8') as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            data = {}
    
    cursor = conn.cursor()
    cursor.execute("DELETE FROM lists")
    count = 0
    for list_name, items in data.items():
        for item in items:
            cursor.execute("INSERT INTO lists (list_name, item) VALUES (?, ?)", (list_name, item))
            count += 1
    conn.commit()
    print(f"Migrated {count} list items.")

def migrate_sessions(conn):
    sess_file = os.path.join(BASE_DIR, "astakos_sessions.json")
    if not os.path.exists(sess_file):
        return
    with open(sess_file, 'r', encoding='utf-8') as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            data = []
    
    cursor = conn.cursor()
    cursor.execute("DELETE FROM sessions")
    count = 0
    for sess in data:
        cursor.execute('''
            INSERT INTO sessions (session_date, channel, summary, completed, pending, next_session_hint, mood)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            sess.get('date', ''),
            sess.get('channel', ''),
            sess.get('summary', ''),
            json.dumps(sess.get('completed', [])),
            json.dumps(sess.get('pending', [])),
            sess.get('next_session_hint', ''),
            sess.get('mood', '')
        ))
        count += 1
    conn.commit()
    print(f"Migrated {count} sessions.")

if __name__ == "__main__":
    conn = sqlite3.connect(STATE_DB)
    create_tables(conn)
    migrate_capabilities(conn)
    migrate_reminders(conn)
    migrate_lists(conn)
    migrate_sessions(conn)
    conn.close()
    print("Migration complete!")
