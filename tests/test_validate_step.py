"""
Tests για validate_step_node() στο core/planner.py
Τρέξε: pytest tests/test_validate_step.py -v
"""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── Helpers ──────────────────────────────────────────────────────

def _stub_deps():
    for mod_name in ["services", "services.gemini", "services.reflection_engine", "config"]:
        if mod_name not in sys.modules:
            sys.modules[mod_name] = types.ModuleType(mod_name)
    cfg = sys.modules["config"]
    if not hasattr(cfg, "WORKING_MEMORY_FILE"):
        cfg.WORKING_MEMORY_FILE = "/tmp/wm.json"
        cfg.BASE_DIR = "/tmp"


def _import_validate():
    _stub_deps()
    if "core.planner" in sys.modules:
        del sys.modules["core.planner"]
    from core.planner import validate_step_node
    return validate_step_node


def _make_state(plan_active=True, idx=0, agent_response="Ολοκληρώθηκε επιτυχώς.", tasks=None):
    """Βοηθητική συνάρτηση για δημιουργία mock state."""
    from langchain_core.messages import HumanMessage, AIMessage

    if tasks is None:
        tasks = [
            {"step": 1, "description": "Ανάλυση δεδομένων", "instruction": "Ανάλυσε τα δεδομένα"},
            {"step": 2, "description": "Δημιουργία report",  "instruction": "Φτιάξε report"},
        ]

    messages = [
        HumanMessage(content="[PLAN ΒΗΜΑ 1/2]: Ανάλυσε τα δεδομένα"),
        AIMessage(content=agent_response),
    ]

    return {
        "messages":    messages,
        "plan_active": plan_active,
        "plan_tasks":  tasks,
        "plan_index":  idx,
        "plan_results": [],
        "plan_goal":   "test goal",
    }


# ═══════════════════════════════════════════════════════════════
# Tests: όχι-plan state
# ═══════════════════════════════════════════════════════════════

def test_skip_when_not_plan_active():
    """Αν plan_active=False → επιστρέφει {} χωρίς να κάνει τίποτα."""
    validate = _import_validate()
    state = _make_state(plan_active=False)
    result = validate(state)
    assert result == {}


def test_skip_when_idx_out_of_bounds():
    """Αν idx >= len(tasks) → skip."""
    validate = _import_validate()
    state = _make_state(plan_active=True, idx=99)
    result = validate(state)
    assert result == {}


# ═══════════════════════════════════════════════════════════════
# Tests: success detection
# ═══════════════════════════════════════════════════════════════

def test_success_response_returns_false_flag():
    """Κανονική επιτυχημένη απάντηση → plan_step_failed=False."""
    validate = _import_validate()
    state = _make_state(agent_response="Η ανάλυση ολοκληρώθηκε με επιτυχία.")
    result = validate(state)
    assert result.get("plan_step_failed") is False
    assert "messages" not in result  # δεν στέλνουμε warning


def test_success_no_warning_message():
    """Καλή απάντηση → δεν προστίθεται AIMessage warning."""
    validate = _import_validate()
    state = _make_state(agent_response="Εδώ είναι τα αποτελέσματα που ζητήθηκαν.")
    result = validate(state)
    assert "messages" not in result


# ═══════════════════════════════════════════════════════════════
# Tests: failure detection
# ═══════════════════════════════════════════════════════════════

def test_detects_greek_failure_word():
    """Απάντηση με 'σφάλμα' → plan_step_failed=True."""
    validate = _import_validate()
    state = _make_state(agent_response="Παρουσιάστηκε σφάλμα κατά την εκτέλεση.")
    result = validate(state)
    assert result.get("plan_step_failed") is True


def test_detects_english_error():
    """Απάντηση με 'error' → plan_step_failed=True."""
    validate = _import_validate()
    state = _make_state(agent_response="An error occurred while processing.")
    result = validate(state)
    assert result.get("plan_step_failed") is True


def test_detects_failed_signal():
    """Απάντηση με 'failed' → plan_step_failed=True."""
    validate = _import_validate()
    state = _make_state(agent_response="The operation failed unexpectedly.")
    result = validate(state)
    assert result.get("plan_step_failed") is True


def test_detects_greek_den_mporesa():
    """'δεν μπόρεσα' → plan_step_failed=True."""
    validate = _import_validate()
    state = _make_state(agent_response="Δεν μπόρεσα να βρω το αρχείο.")
    result = validate(state)
    assert result.get("plan_step_failed") is True


def test_failure_includes_warning_message():
    """Αποτυχία → προστίθεται AIMessage με ⚠️ warning."""
    from langchain_core.messages import AIMessage
    validate = _import_validate()
    state = _make_state(agent_response="Παρουσιάστηκε αποτυχία.")
    result = validate(state)
    assert "messages" in result
    msgs = result["messages"]
    assert len(msgs) == 1
    assert isinstance(msgs[0], AIMessage)
    assert "⚠️" in msgs[0].content


def test_warning_contains_step_info():
    """Το warning περιέχει τον αριθμό βήματος και περιγραφή."""
    validate = _import_validate()
    state = _make_state(agent_response="error occurred", idx=0)
    result = validate(state)
    warning_text = result["messages"][0].content
    # Πρέπει να αναφέρει βήμα 1
    assert "1" in warning_text


# ═══════════════════════════════════════════════════════════════
# Tests: edge cases
# ═══════════════════════════════════════════════════════════════

def test_progress_message_ignored():
    """Το ⏳ progress AIMessage ΔΕΝ θεωρείται agent response."""
    from langchain_core.messages import HumanMessage, AIMessage
    validate = _import_validate()

    # State όπου το τελευταίο AIMessage είναι progress indicator
    # και πριν αυτό υπάρχει η πραγματική agent απάντηση
    state = {
        "messages": [
            HumanMessage(content="instruction"),
            AIMessage(content="Η εργασία ολοκληρώθηκε επιτυχώς."),   # agent response
            AIMessage(content="⏳ **Βήμα 1/2:** Ανάλυση δεδομένων"),  # progress (ignored)
        ],
        "plan_active": True,
        "plan_tasks":  [{"step": 1, "description": "Ανάλυση", "instruction": "Ανάλυσε"}],
        "plan_index":  0,
        "plan_results": [],
        "plan_goal": "test",
    }
    result = validate(state)
    # Πρέπει να διαβάσει την επιτυχημένη απάντηση, όχι το progress
    assert result.get("plan_step_failed") is False


def test_empty_agent_response():
    """Κενή απάντηση → δεν αποτυγχάνει (δεν έχει failure signals)."""
    validate = _import_validate()
    state = _make_state(agent_response="")
    result = validate(state)
    # Κενό response → plan_step_failed=False (δεν υπάρχουν failure signals)
    assert result.get("plan_step_failed") is False


def test_case_insensitive_detection():
    """Failure detection case-insensitive: 'ERROR' → αναγνωρίζεται."""
    validate = _import_validate()
    state = _make_state(agent_response="An ERROR was detected in the process.")
    result = validate(state)
    assert result.get("plan_step_failed") is True
