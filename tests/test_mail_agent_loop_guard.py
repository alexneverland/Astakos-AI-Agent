"""
Tests για Mail_Agent loop guard logic (v2, v3, v4).
Δοκιμάζουμε τη λογική απευθείας χωρίς να φορτώνουμε ολόκληρο το core.agents
(εξαρτήσεις όπως ChromaDB, Vertex AI κτλ είναι βαριές και δεν υπάρχουν στο CI).
Τρέξε: pytest tests/test_mail_agent_loop_guard.py -v
"""
import re
from langchain_core.messages import HumanMessage, ToolMessage, AIMessage


# ── Εξαγωγή λογικής που αντιστοιχεί στον κώδικα του agents.py ──────────────

def _clean(x):
    return x if isinstance(x, str) else (x or "")


def _extract_known_ids(history):
    """Αντιγράφει τη λογική v4 ID extraction: newest IDs first."""
    known_ids = []
    for msg in reversed(history):
        c = _clean(getattr(msg, "content", "") or "")
        for m in re.finditer(r"ID: ([a-f0-9]{16})", c):
            eid = m.group(1)
            if eid not in known_ids:
                known_ids.append(eid)
    return known_ids


def _current_turn_mail_results(history):
    """Αντιγράφει τη λογική v3 last_human_idx (lines 564-574 agents.py)."""
    last_human_idx = next(
        (len(history) - 1 - i for i, m in enumerate(reversed(history))
         if getattr(m, "type", "") == "human"),
        0
    )
    results = []
    for msg in history[last_human_idx:]:
        if getattr(msg, "type", "") == "tool":
            content = _clean(getattr(msg, "content", "")).strip()
            if content.startswith("ID: ") or content.startswith("📩 Περιεχόμενο:"):
                results.append(content)
    return results


def _auto_read_result(mail_tool_results):
    """Αντιγράφει τη λογική v4 auto-read (lines 580-597 agents.py).
    Επιστρέφει (email_id, True) αν πρέπει auto-read, αλλιώς (None, False)."""
    search_hits = [r for r in mail_tool_results if r.startswith("ID: ")]
    read_hits = [r for r in mail_tool_results if "Περιεχόμενο:" in r]
    if search_hits and not read_hits:
        m = re.search(r"ID: ([a-f0-9]{16})", search_hits[0])
        if m:
            return m.group(1), True
    return None, False


# ═══════════════════════════════════════════════════════════════════════
# v3 tests: current-turn-only detection
# ═══════════════════════════════════════════════════════════════════════

def test_v3_empty_on_new_turn_with_no_tools():
    """Νέα ερώτηση χωρίς tool results στο current turn → κενή λίστα."""
    history = [
        HumanMessage(content="irthe neo mail"),
        AIMessage(content="Vrika to"),
        ToolMessage(content="ID: abc1234567890123 | Kaggle", tool_call_id="x"),
        AIMessage(content="Thes na to diavaso?"),
        HumanMessage(content="nai"),  # νέο turn, κανένα tool μετά
    ]
    assert _current_turn_mail_results(history) == []


def test_v3_detects_results_in_same_turn():
    """Tool result ΜΕΤΑ το τελευταίο human → ανιχνεύεται."""
    history = [
        HumanMessage(content="irthe neo mail kaggle"),
        ToolMessage(content="ID: 19ec7b7695a56646 | Kaggle | Day 1",
                    tool_call_id="search-1"),
    ]
    results = _current_turn_mail_results(history)
    assert len(results) == 1
    assert results[0].startswith("ID: 19ec7b7695a56646")


def test_v3_read_result_detected():
    """📩 Περιεχόμενο: prefix ανιχνεύεται."""
    history = [
        HumanMessage(content="diabase to"),
        ToolMessage(content="📩 Περιεχόμενο: Hello World",
                    tool_call_id="read-1"),
    ]
    results = _current_turn_mail_results(history)
    assert len(results) == 1
    assert "Περιεχόμενο:" in results[0]


def test_v3_old_results_not_included_in_new_turn():
    """ToolMessages από παλιό turn δεν μπαίνουν στα results του νέου turn."""
    history = [
        HumanMessage(content="παλιά ερώτηση"),
        ToolMessage(content="ID: abc1234567890123 | old", tool_call_id="old"),
        AIMessage(content="Ιδού"),
        HumanMessage(content="νέα ερώτηση"),
        # Κανένα tool μετά το νέο HumanMessage
    ]
    assert _current_turn_mail_results(history) == []


# ═══════════════════════════════════════════════════════════════════════
# v4 tests: auto-read
# ═══════════════════════════════════════════════════════════════════════

def test_v4_auto_read_triggers_on_search_only():
    """Μόνο search results (ID:) → auto-read με σωστό ID."""
    results = ["ID: 19ec7b7695a56646 | Kaggle | Day 1 | Sun 14 Jun"]
    eid, should = _auto_read_result(results)
    assert should is True
    assert eid == "19ec7b7695a56646"


def test_v4_auto_read_skips_when_read_result_exists():
    """Υπάρχει read result (Περιεχόμενο:) → δεν κάνει auto-read, synthesize."""
    results = [
        "ID: 19ec7b7695a56646 | Kaggle | Day 1",
        "📩 Περιεχόμενο: Αγαπητέ Λάζαρε...",
    ]
    eid, should = _auto_read_result(results)
    assert should is False
    assert eid is None


def test_v4_auto_read_skips_when_no_valid_id():
    """Αν δεν υπάρχει valid 16-char hex ID → δεν κάνει auto-read."""
    results = ["ID: SHORT | bad format"]
    eid, should = _auto_read_result(results)
    assert should is False


def test_v4_auto_read_uses_first_id_when_multiple():
    """Πολλά IDs → παίρνει το πρώτο."""
    results = [
        "ID: aaaa000000000001 | Email 1",
        "ID: bbbb000000000002 | Email 2",
    ]
    eid, should = _auto_read_result(results)
    assert should is True
    assert eid == "aaaa000000000001"


# ═══════════════════════════════════════════════════════════════════════
# v4 tests: ID hint extraction
# ═══════════════════════════════════════════════════════════════════════

def test_v4_id_extracted_from_tool_message():
    """ID εξάγεται από ToolMessage στο ιστορικό."""
    history = [
        HumanMessage(content="irthe neo mail"),
        ToolMessage(content="ID: 19ec7b7695a56646 | Kaggle | Day 1",
                    tool_call_id="s1"),
    ]
    ids = _extract_known_ids(history)
    assert "19ec7b7695a56646" in ids


def test_v4_id_extracted_from_sanitized_human_message():
    """ID εξάγεται και από sanitized HumanMessage (αποτέλεσμα sanitize_history_for_gemini)."""
    history = [
        HumanMessage(content="[Αποτέλεσμα Εργαλείου None]: ID: 19ec7b7695a56646 | Kaggle"),
    ]
    ids = _extract_known_ids(history)
    assert "19ec7b7695a56646" in ids


def test_v4_id_extracted_from_ai_message():
    """ID εξάγεται και από AIMessage (όταν o agent ανέφερε το ID στην απάντησή του)."""
    history = [
        AIMessage(content="Βρήκα email με ID: 19ec7b7695a56646 από Kaggle."),
    ]
    ids = _extract_known_ids(history)
    assert "19ec7b7695a56646" in ids


def test_v4_no_duplicate_ids():
    """Το ίδιο ID δεν εμφανίζεται δύο φορές."""
    history = [
        HumanMessage(content="ID: 19ec7b7695a56646 first"),
        ToolMessage(content="ID: 19ec7b7695a56646 | again", tool_call_id="x"),
    ]
    ids = _extract_known_ids(history)
    assert ids.count("19ec7b7695a56646") == 1


def test_v4_multiple_different_ids_collected():
    """Πολλά διαφορετικά IDs συλλέγονται."""
    history = [
        ToolMessage(content="ID: aaaa000000000001 | Email 1\nID: bbbb000000000002 | Email 2",
                    tool_call_id="x"),
    ]
    ids = _extract_known_ids(history)
    assert "aaaa000000000001" in ids
    assert "bbbb000000000002" in ids


def test_v4_latest_turn_id_is_preferred():
    """Αν υπάρχουν παλιά και νέα IDs, πρώτο πρέπει να βγαίνει το πιο πρόσφατο."""
    history = [
        ToolMessage(content="ID: aaaa000000000001 | Old Kaggle email",
                    tool_call_id="old"),
        AIMessage(content="Το παλιό email ήταν αυτό."),
        HumanMessage(content="ήρθε άλλο mail, διάβασέ το"),
        ToolMessage(content="ID: bbbb000000000002 | New Kaggle email",
                    tool_call_id="new"),
    ]
    ids = _extract_known_ids(history)
    assert ids[0] == "bbbb000000000002"
    assert ids[1] == "aaaa000000000001"


def test_v4_empty_history_no_ids():
    """Άδειο ιστορικό → κανένα ID."""
    assert _extract_known_ids([]) == []


# ═══════════════════════════════════════════════════════════════════════
# Integration: end-to-end flow simulation
# ═══════════════════════════════════════════════════════════════════════

def test_full_flow_search_then_auto_read():
    """
    Simulates the full flow:
    Turn 1: user says 'read kaggle mail' → agent searches → search result arrives
    → v3 detects search result in current turn
    → v4 auto-read fires (not synthesis)
    """
    # Turn 1 state after search tool ran
    history = [
        HumanMessage(content="irthe neo mail kaggle diabase"),
        ToolMessage(content="ID: 19ec7b7695a56646 | Sun 14 Jun | Kaggle | Day 1",
                    tool_call_id="search-1"),
    ]
    results = _current_turn_mail_results(history)
    assert results, "Should detect search result"
    eid, should_read = _auto_read_result(results)
    assert should_read, "Should trigger auto-read"
    assert eid == "19ec7b7695a56646"


def test_full_flow_read_result_then_synthesize():
    """
    Turn 2: auto-read ran → read result arrives
    → v3 detects read result
    → v4 does NOT auto-read (read result present)
    → synthesis fires
    """
    history = [
        HumanMessage(content="irthe neo mail kaggle diabase"),
        # auto-read AIMessage (tool_call)
        AIMessage(content="", tool_calls=[{
            "name": "mail_manager", "id": "auto-read-19ec7b76",
            "args": {"action": "read", "email_id": "19ec7b7695a56646"}
        }]),
        ToolMessage(content="📩 Περιεχόμενο: Καλώς ήρθες! Η μέρα 1 ξεκινά...",
                    tool_call_id="auto-read-19ec7b76"),
    ]
    results = _current_turn_mail_results(history)
    assert any("Περιεχόμενο:" in r for r in results), "Should detect read result"
    eid, should_read = _auto_read_result(results)
    assert not should_read, "Should NOT auto-read again"


def test_full_flow_second_turn_uses_hint():
    """
    Turn 2 (new human message 'ναι διάβασε'):
    → v3 returns empty (no tool results after new human)
    → v4 hint extraction finds ID from previous ToolMessage
    → hint injected into system_prompt
    """
    history = [
        # Turn 1
        HumanMessage(content="irthe neo mail"),
        AIMessage(content="", tool_calls=[{"name": "mail_manager", "id": "s1",
                                           "args": {"action": "search"}}]),
        ToolMessage(content="ID: 19ec7b7695a56646 | Kaggle | Day 1",
                    tool_call_id="s1"),
        AIMessage(content="Vrika email Kaggle Day 1."),
        # Turn 2
        HumanMessage(content="nai diabase"),
    ]
    # v3: no results in current turn
    results = _current_turn_mail_results(history)
    assert results == [], "New turn has no tool results yet"

    # v4 hint: ID available from previous turn
    ids = _extract_known_ids(history)
    assert "19ec7b7695a56646" in ids, "ID should be found in history for hint"
