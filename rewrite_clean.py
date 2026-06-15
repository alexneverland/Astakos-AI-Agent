import os
import re

def rewrite_clean_py():
    with open('clean.py', 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Remove working memory from main help
    content = content.replace(
        '''    parser.add_argument("--working-memory", action="store_true",
                        help="Σύμπτυξη working memory (dedup + LLM)")\n''',
        ''
    )
    
    # 2. Update all tasks execution logic
    content = content.replace(
        '''    no_specific = not any([
        args.capabilities, args.conversation_db,
        args.sessions, args.working_memory, args.profile, args.photos, args.memory_audit
    ])''',
        '''    no_specific = not any([
        args.capabilities, args.conversation_db,
        args.sessions, args.profile, args.photos, args.memory_audit
    ])'''
    )
    
    # 3. Remove working_memory execution
    content = content.replace(
        '''    if run_all or args.working_memory:
        results["working_memory"] = consolidate_working_memory(
            dry_run=args.dry_run, backup=backup_enabled
        )''',
        ''
    )

    # 4. Replace consolidate_capabilities
    capabilities_old = re.search(r'def consolidate_capabilities.*?(?=def maintain_conversation_db)', content, re.DOTALL).group(0)
    capabilities_new = '''def consolidate_capabilities(dry_run: bool = False, backup: bool = True) -> bool:
    import sqlite3
    try:
        from config import STATE_DB
    except ImportError:
        STATE_DB = os.path.join(PROJECT_ROOT, "astakos_state.db")
        
    header("Σύμπτυξη capabilities (can_do / cannot_do) σε STATE_DB")
    
    if not os.path.exists(STATE_DB):
        log("⚠️ Δεν βρέθηκε το STATE_DB.", "warn")
        return False
        
    conn = sqlite3.connect(STATE_DB, timeout=30)
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS capabilities (id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT NOT NULL, description TEXT NOT NULL UNIQUE)")
    c.execute("SELECT type, description FROM capabilities")
    rows = c.fetchall()
    
    can_do = [r[1] for r in rows if r[0] == "can"]
    cannot_do = [r[1] for r in rows if r[0] == "cannot"]
    
    log(f"📊 Πριν: {len(can_do)} can_do  |  {len(cannot_do)} cannot_do", "info")

    llm = _load_llm()
    if llm is None:
        log("❌ Δεν φόρτωσε το LLM — παρακάμπτεται η σύμπτυξη.", "err")
        conn.close()
        return False

    prompt = f"""Είσαι ο μηχανικός συντήρησης για τη μνήμη ενός AI agent.

Σου δίνω 2 λίστες:
  - "can_do": πράγματα που μπορεί να κάνει
  - "cannot_do": περιορισμοί και αδυναμίες

Δουλειά σου:
  1. Συγχώνευσε διπλότυπα και πολύ παρόμοια entries σε ένα σαφές.
  2. Αφαίρεσε αντιφάσεις (αν κάτι είναι ταυτόχρονα can_do και cannot_do, κρίνε με βάση την πιο πρόσφατη/συγκεκριμένη γραφή).
  3. Δώσε γενικευμένη, καθαρή διατύπωση (όχι 5 παραλλαγές της ίδιας ιδέας).
  4. Κράτα την αρχική γλώσσα (Ελληνικά).

ΕΠΕΣΤΡΕΨΕ ΑΠΟΚΛΕΙΣΤΙΚΑ valid JSON με αυτή τη μορφή, χωρίς markdown:
{{"can_do": [...], "cannot_do": [...]}}

ΛΙΣΤΑ CAN_DO:
{json.dumps(can_do, ensure_ascii=False, indent=2)}

ΛΙΣΤΑ CANNOT_DO:
{json.dumps(cannot_do, ensure_ascii=False, indent=2)}
"""

    log("🤖 Κλήση LLM για consolidation...", "info")
    try:
        response = llm.invoke(prompt)
        from core.utils import clean_message
        raw = clean_message(response.content)
        raw = strip_markdown_json(raw)
        new_data = json.loads(raw)
    except Exception as e:
        log(f"❌ Σφάλμα κατά τη σύμπτυξη: {e}", "err")
        conn.close()
        return False

    if not isinstance(new_data, dict) or "can_do" not in new_data or "cannot_do" not in new_data:
        log("❌ Το LLM γύρισε άκυρο schema. Δεν γράφω.", "err")
        conn.close()
        return False

    new_can    = len(new_data["can_do"])
    new_cannot = len(new_data["cannot_do"])
    
    log(f"📊 Μετά: {new_can} can_do | {new_cannot} cannot_do", "ok")

    if dry_run:
        log("🧪 DRY-RUN — δες παρακάτω τι θα γραφόταν:", "warn")
        print(json.dumps(new_data, ensure_ascii=False, indent=2))
        conn.close()
        return True

    backup_file(STATE_DB, enabled=backup)
    c.execute("DELETE FROM capabilities")
    for item in new_data["can_do"]:
        c.execute("INSERT OR IGNORE INTO capabilities (type, description) VALUES ('can', ?)", (str(item),))
    for item in new_data["cannot_do"]:
        c.execute("INSERT OR IGNORE INTO capabilities (type, description) VALUES ('cannot', ?)", (str(item),))
    
    conn.commit()
    conn.close()
    log("✅ Αποθηκεύτηκαν στο STATE_DB (capabilities)", "ok")
    return True

'''
    content = content.replace(capabilities_old, capabilities_new)

    # 5. Replace trim_sessions
    sessions_old = re.search(r'def trim_sessions.*?(?=def consolidate_working_memory)', content, re.DOTALL).group(0)
    sessions_new = '''def trim_sessions(keep: int = DEFAULT_SESSIONS_KEEP, dry_run: bool = False, backup: bool = True) -> bool:
    import sqlite3
    try:
        from config import STATE_DB
    except ImportError:
        STATE_DB = os.path.join(PROJECT_ROOT, "astakos_state.db")
        
    header(f"Trim sessions σε STATE_DB (κρατά τις {keep} πιο πρόσφατες)")
    
    if not os.path.exists(STATE_DB):
        log("⚠️ Δεν βρέθηκε το STATE_DB.", "warn")
        return False
        
    conn = sqlite3.connect(STATE_DB, timeout=30)
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, tag TEXT NOT NULL, details TEXT NOT NULL, sentiment TEXT, time_started TEXT NOT NULL, time_ended TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    c.execute("SELECT COUNT(*) FROM sessions")
    total = c.fetchone()[0]

    log(f"📊 Πριν: {total} sessions", "info")

    if total <= keep:
        log(f"ℹ️  Δεν χρειάζεται trim (≤ {keep}).", "dim")
        conn.close()
        return True

    if dry_run:
        log(f"🧪 DRY-RUN: Θα διεγράφοντο {total - keep} παλιές sessions.", "warn")
        conn.close()
        return True

    backup_file(STATE_DB, enabled=backup)
    c.execute(f"""
        DELETE FROM sessions 
        WHERE id NOT IN (
            SELECT id FROM sessions ORDER BY created_at DESC LIMIT {keep}
        )
    """)
    conn.commit()
    conn.close()
    
    removed = total - keep
    log(f"📊 Μετά: {keep} sessions (−{removed})", "ok")
    return True

'''
    content = content.replace(sessions_old, sessions_new)

    # 6. Delete consolidate_working_memory
    working_memory_old = re.search(r'def consolidate_working_memory.*?(?=def consolidate_profile)', content, re.DOTALL).group(0)
    content = content.replace(working_memory_old, '')

    with open('clean.py', 'w', encoding='utf-8') as f:
        f.write(content)
        
if __name__ == '__main__':
    rewrite_clean_py()
