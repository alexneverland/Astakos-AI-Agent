import os
import json
import sqlite3
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JSON_FILE = os.path.join(BASE_DIR, "astakos_profile.json")
DB_FILE = os.path.join(BASE_DIR, "astakos_profile.db")

def migrate():
    if not os.path.exists(JSON_FILE):
        print(f"Δεν βρέθηκε το {JSON_FILE}. Τίποτα για migration.")
        return

    with open(JSON_FILE, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except Exception as e:
            print(f"Σφάλμα ανάγνωσης JSON: {e}")
            return

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    # Create table
    c.execute('''
        CREATE TABLE IF NOT EXISTS profile_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            fact TEXT NOT NULL,
            photo_path TEXT,
            date TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    count = 0
    for category, items in data.items():
        if isinstance(items, dict):
            # For the contacts category which is a dictionary {name: phone}
            for k, v in items.items():
                fact_str = f"{k}: {v}"
                c.execute('''
                    INSERT INTO profile_facts (category, fact, date)
                    VALUES (?, ?, ?)
                ''', (category, fact_str, datetime.now().strftime("%Y-%m-%d")))
                count += 1
        elif isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    fact = item.get("fact", "")
                    photo_path = item.get("photo_path")
                    date = item.get("date", datetime.now().strftime("%Y-%m-%d"))
                else:
                    fact = str(item)
                    photo_path = None
                    date = datetime.now().strftime("%Y-%m-%d")

                c.execute('''
                    INSERT INTO profile_facts (category, fact, photo_path, date)
                    VALUES (?, ?, ?, ?)
                ''', (category, fact, photo_path, date))
                count += 1

    conn.commit()
    conn.close()
    
    # Rename the old json for backup
    backup_file = JSON_FILE + ".backup"
    os.replace(JSON_FILE, backup_file)
    print(f"Το migration ολοκληρώθηκε! Μεταφέρθηκαν {count} εγγραφές.")
    print(f"Το παλιό αρχείο μετονομάστηκε σε {backup_file}")

if __name__ == "__main__":
    migrate()
