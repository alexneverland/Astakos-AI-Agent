import pytest
import json
import os
import shutil

TEST_CUSTOM_INTENTS_PATH = os.path.join(os.path.dirname(__file__), '..', 'astakos_custom_intents.json')
BACKUP_PATH = os.path.join(os.path.dirname(__file__), '..', 'astakos_custom_intents.json.bak')

MOCK_CUSTOM_INTENTS = {
    "system_tool": {
        "family_markers": ["kid1", "partner", "σοφια", "αλεξανδρος"]
    },
    "context_builder": {
        "partner_gift_words": ["σοφια", "ρολοι", "ρολόι", "δώρο", "παρτνερ", "partner"],
        "partner_gift_context": ["rosefield", "bangle", "δώρα", "ρολόι", "παρτνερ", "partner"]
    },
    "context_extractor": {
        "park_words": ["πάρκο", "παιδική χαρά", "πλατεία", "park"],
        "home_words": ["σπίτι", "βρίσκομαι σπίτι", "γύρισα", "έφτασα", "home"],
        "work_words": ["δουλειά", "γραφείο", "βάρδια", "work"],
        "partner_names": ["Σοφία", "σοφία", "sofia", "partner"],
        "kid1_names": ["Αλέξανδρος", "αλέξανδρος", "alexandros", "άλεξ", "kid1"],
        "leaving_words": ["αναχώρηση", "έφυγα", "φεύγω"],
        "now_sitting_words": ["κάθομαι", "άραξα"],
        "found_them_words": ["βρήκα", "συνάντησα"],
        "all_together_words": ["μαζί", "όλοι"]
    },
    "routine_intent": {
        "control_verbs": ["παύση", "σταμάτα", "ακύρωση", "συνέχισε", "κοιμήθηκε", "ξύπνησε", "pause", "stop", "cancel", "continue"],
        "routine_nouns": ["πρόγραμμα", "ρουτίνα", "ειδοποιήσεις", "routine"],
        "time_condition_words": ["αύριο", "σήμερα", "επόμενη βδομάδα", "το βράδυ", "νωρίς", "today", "tomorrow"],
        "context_update_phrases": ["πάμε", "ξεκινάμε", "έφυγα", "σχόλασα", "γύρισα", "έφτασα"],
        "cooldown_reset_words": ["επανέφερε", "μηδένισε"]
    },
    "messenger_intent": {
        "cancel_words": ["άκυρο", "μην το στείλεις", "cancel"],
        "send_approval_words": ["στείλτο", "send", "ναι", "ναι στείλτο", "yes"],
        "cleanup_words": ["καθάρισε", "clear"],
        "compose_words": ["στείλε", "γράψε", "μήνυμα"]
    },
    "utils": {
        "fast_path_blocked_tokens": ["alexandros", "sofia", "kid1", "partner", "αλέξανδρος", "σοφία"]
    }
}

def pytest_configure(config):
    # Backup existing if any
    if os.path.exists(TEST_CUSTOM_INTENTS_PATH):
        shutil.copy2(TEST_CUSTOM_INTENTS_PATH, BACKUP_PATH)
    
    with open(TEST_CUSTOM_INTENTS_PATH, "w", encoding="utf-8") as f:
        json.dump(MOCK_CUSTOM_INTENTS, f, ensure_ascii=False, indent=2)

def pytest_unconfigure(config):
    if os.path.exists(BACKUP_PATH):
        shutil.move(BACKUP_PATH, TEST_CUSTOM_INTENTS_PATH)
    elif os.path.exists(TEST_CUSTOM_INTENTS_PATH):
        os.remove(TEST_CUSTOM_INTENTS_PATH)

@pytest.fixture(autouse=True)
def mock_dbs(monkeypatch, tmp_path):
    # Mock all database paths to a temporary directory so tests don't pollute production data
    monkeypatch.setattr('config.STATE_DB', str(tmp_path / 'test_state.db'))
    monkeypatch.setattr('config.PROFILE_DB', str(tmp_path / 'test_profile.db'))
    monkeypatch.setattr('config.EMBEDDINGS_CACHE_DB', str(tmp_path / 'test_embeddings.db'))
    monkeypatch.setattr('config.CHROMA_DB_DIR', str(tmp_path / 'chroma_db'))
    monkeypatch.setattr('config.CONVERSATION_DB_FILE', str(tmp_path / 'test_history.db'))
    monkeypatch.setattr('config.ROUTINES_DB', str(tmp_path / 'test_routines.db'))
    monkeypatch.setattr('config.MEMORY_AUDIT_DIR', str(tmp_path / 'memory_audit'))
    
    # Reload vector_store modules to pick up new config if needed
    import sys
    if 'memory.vector_store' in sys.modules:
        pass # We might need to re-initialize the store, or it uses config lazily
