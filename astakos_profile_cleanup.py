"""
MASTRO-CLEANUP: Καθαρίζει το astakos_profile.json από duplicates.
Τρέξε μία φορά: python astakos_profile_cleanup.py
"""
import json
import os
import sys

# Βάλε το path του project σου
PROFILE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "astakos_profile.json")

def cleanup_profile():
    if not os.path.exists(PROFILE_FILE):
        print("❌ Δεν βρέθηκε το astakos_profile.json")
        return

    with open(PROFILE_FILE, "r", encoding="utf-8") as f:
        db = json.load(f)

    total_before = sum(len(v) if isinstance(v, list) else 1 for v in db.values())
    
    for category, items in db.items():
        if category == "contacts":
            continue  # Μην αγγίζεις τα contacts
        if not isinstance(items, list):
            continue

        seen = []
        unique = []
        for item in items:
            # Παίρνουμε το κείμενο για σύγκριση
            text = item if isinstance(item, str) else item.get("fact", "")
            text_normalized = text.strip().lower()
            
            if text_normalized not in seen:
                seen.append(text_normalized)
                unique.append(item)

        # Κράτα μόνο τα τελευταία 50
        db[category] = unique[-50:]
        removed = len(items) - len(db[category])
        if removed > 0:
            print(f"  [{category}]: {len(items)} → {len(db[category])} (-{removed} duplicates)")

    total_after = sum(len(v) if isinstance(v, list) else 1 for v in db.values())
    
    # Backup πριν αποθήκευση
    backup_file = PROFILE_FILE.replace(".json", "_backup.json")
    with open(backup_file, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=4)
    print(f"\n✅ Backup αποθηκεύτηκε: {backup_file}")

    with open(PROFILE_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=4)

    print(f"\n🧹 Cleanup ολοκληρώθηκε: {total_before} → {total_after} entries (-{total_before - total_after})")

if __name__ == "__main__":
    print("🧹 Astakos Profile Cleanup...")
    cleanup_profile()
