import pytest
import json
import os
import shutil
import sys
import tempfile

# Ensure root is in path for config import
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

_PREVIOUS_CUSTOM_INTENTS_PATH = os.environ.get("ASTAKOS_CUSTOM_INTENTS_PATH")
_TEST_CUSTOM_INTENTS_DIR = tempfile.mkdtemp(prefix="astakos_test_intents_")
TEST_CUSTOM_INTENTS_PATH = os.path.join(
    _TEST_CUSTOM_INTENTS_DIR,
    "astakos_custom_intents.json",
)
os.environ["ASTAKOS_CUSTOM_INTENTS_PATH"] = TEST_CUSTOM_INTENTS_PATH

MOCK_CUSTOM_INTENTS = {
    "system_tool": {
        "family_markers": ["kid1", "partner", "σοφια", "αλεξανδρος"]
    },
    "routines": {
        "tokens": {
            "_KID1_TOKENS": ["αλεξανδρ"],
            "_PARTNER_TOKENS": ["σοφια"],
        },
        "inline": {
            "partner_aliases": ["sofia", "σοφ"],
        },
    },
    "context_builder": {
        "partner_gift_words": ["σοφια", "ρολοι", "ρολόι", "δώρο", "παρτνερ", "partner"],
        "partner_gift_context": ["rosefield", "bangle", "δώρα", "ρολόι", "παρτνερ", "partner"]
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

def pytest_configure(config: pytest.Config) -> None:
    """Create an isolated custom-intents overlay for the test session."""
    with open(TEST_CUSTOM_INTENTS_PATH, "w", encoding="utf-8") as f:
        json.dump(MOCK_CUSTOM_INTENTS, f, ensure_ascii=False, indent=2)

def pytest_unconfigure(config: pytest.Config) -> None:
    """Remove only the isolated test overlay and restore the prior environment."""
    if _PREVIOUS_CUSTOM_INTENTS_PATH is None:
        os.environ.pop("ASTAKOS_CUSTOM_INTENTS_PATH", None)
    else:
        os.environ["ASTAKOS_CUSTOM_INTENTS_PATH"] = _PREVIOUS_CUSTOM_INTENTS_PATH
    shutil.rmtree(_TEST_CUSTOM_INTENTS_DIR, ignore_errors=True)

@pytest.fixture(autouse=True)
def mock_dbs(monkeypatch, tmp_path):
    # Mock all database paths to a temporary directory so tests don't pollute production data
    monkeypatch.setattr('config.STATE_DB', str(tmp_path / 'test_state.db'), raising=False)
    monkeypatch.setattr('config.PROFILE_DB', str(tmp_path / 'test_profile.db'), raising=False)
    monkeypatch.setattr('config.EMBEDDINGS_CACHE_DB', str(tmp_path / 'test_embeddings.db'), raising=False)
    monkeypatch.setattr('config.CHROMA_DB_DIR', str(tmp_path / 'chroma_db'), raising=False)
    monkeypatch.setattr('config.CONVERSATION_DB_FILE', str(tmp_path / 'test_history.db'), raising=False)
    monkeypatch.setattr('config.ROUTINES_DB', str(tmp_path / 'test_routines.db'), raising=False)
    monkeypatch.setattr('config.MEMORY_AUDIT_DIR', str(tmp_path / 'memory_audit'), raising=False)
    
    # Reload vector_store modules to pick up new config if needed
    import sys
    if 'memory.vector_store' in sys.modules:
        monkeypatch.setattr(sys.modules['memory.vector_store'], 'MEMORY_AUDIT_DIR', str(tmp_path / 'memory_audit'), raising=False)
        
    import memory.event_log as event_log
    monkeypatch.setattr(event_log, 'LOGS_DIR', str(tmp_path / 'events'), raising=False)
