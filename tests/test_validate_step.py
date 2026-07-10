"""
Tests for validate_step_node() in core/planner.py
Run: pytest tests/test_validate_step.py -v
"""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── Helpers ──────────────────────────────────────────────────────

_original_modules = {}

def setup_module(module):
    for mod_name in ["services", "services.gemini", "services.reflection_engine", "config"]:
        _original_modules[mod_name] = sys.modules.get(mod_name)
        if mod_name not in sys.modules:
            sys.modules[mod_name] = types.ModuleType(mod_name)
    cfg = sys.modules["config"]
    if not hasattr(cfg, "WORKING_MEMORY_FILE"):
        cfg.WORKING_MEMORY_FILE = "/tmp/wm.json"
        cfg.BASE_DIR = "/tmp"

def teardown_module(module):
    for mod_name, orig in _original_modules.items():
        if orig is None:
            sys.modules.pop(mod_name, None)
        else:
            sys.modules[mod_name] = orig


def _import_validate():
    if "core.planner" in sys.modules:
        del sys.modules["core.planner"]
    from core.planner import validate_step_node
    return validate_step_node


def _make_state(plan_active=True, idx=0, agent_response="Ολοκληρώθηκε επιτυχώς.", tasks=None):
    """Helper function to create a mock state."""
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
# Tests: non-plan state
# ═══════════════════════════════════════════════════════════════

def test_skip_when_not_plan_active():
    """If plan_active=False → returns {} without doing anything."""
    validate = _import_validate()
    state = _make_state(plan_active=False)
    result = validate(state)
    assert result == {}


def test_skip_when_idx_out_of_bounds():
    """If idx >= len(tasks) → skip."""
    validate = _import_validate()
    state = _make_state(plan_active=True, idx=99)
    result = validate(state)
    assert result == {}


# ═══════════════════════════════════════════════════════════════
# Tests: success detection
# ═══════════════════════════════════════════════════════════════

def test_success_response_returns_false_flag():
    """Normal successful response → plan_step_failed=False."""
    validate = _import_validate()
    state = _make_state(agent_response="Η ανάλυση ολοκληρώθηκε με επιτυχία.")
    result = validate(state)
    assert result.get("plan_step_failed") is False
    assert "messages" not in result  # we do not send a warning


def test_success_no_warning_message():
    """Good response → no AIMessage warning is added."""
    validate = _import_validate()
    state = _make_state(agent_response="Εδώ είναι τα αποτελέσματα που ζητήθηκαν.")
    result = validate(state)
    assert "messages" not in result


# ═══════════════════════════════════════════════════════════════
# Tests: failure detection
# ═══════════════════════════════════════════════════════════════

def test_detects_greek_failure_word():
    """Response with 'error' → plan_step_failed=True."""
    validate = _import_validate()
    state = _make_state(agent_response="Παρουσιάστηκε σφάλμα κατά την εκτέλεση.")
    result = validate(state)
    assert result.get("plan_step_failed") is True


def test_detects_english_error():
    """Response with 'error' → plan_step_failed=True."""
    validate = _import_validate()
    state = _make_state(agent_response="An error occurred while processing.")
    result = validate(state)
    assert result.get("plan_step_failed") is True


def test_detects_failed_signal():
    """Response with 'failed' → plan_step_failed=True."""
    validate = _import_validate()
    state = _make_state(agent_response="The operation failed unexpectedly.")
    result = validate(state)
    assert result.get("plan_step_failed") is True


def test_detects_greek_den_mporesa():
    """'could not' -> plan_step_failed=True."""
    validate = _import_validate()
    state = _make_state(agent_response="Δεν μπόρεσα να βρω το αρχείο.")
    result = validate(state)
    assert result.get("plan_step_failed") is True


def test_failure_includes_warning_message():
    """Failure → AIMessage is added with a ⚠️ warning."""
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
    """The warning contains the step number and description."""
    validate = _import_validate()
    state = _make_state(agent_response="error occurred", idx=0)
    result = validate(state)
    warning_text = result["messages"][0].content
    # Must report step 1
    assert "1" in warning_text


# ═══════════════════════════════════════════════════════════════
# Tests: edge cases
# ═══════════════════════════════════════════════════════════════

def test_progress_message_ignored():
    """The ⏳ progress AIMessage is NOT considered an agent response."""
    from langchain_core.messages import HumanMessage, AIMessage
    validate = _import_validate()

    # State where the last AIMessage is a progress indicator
    # and before this there is the actual agent response
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
    # Must read the successful response, not the progress
    assert result.get("plan_step_failed") is False


def test_empty_agent_response():
    """Empty response → does not fail (has no failure signals)."""
    validate = _import_validate()
    state = _make_state(agent_response="")
    result = validate(state)
    # Empty response → plan_step_failed=False (no failure signals exist)
    assert result.get("plan_step_failed") is False


def test_case_insensitive_detection():
    """Failure detection case-insensitive: 'ERROR' → recognized."""
    validate = _import_validate()
    state = _make_state(agent_response="An ERROR was detected in the process.")
    result = validate(state)
    assert result.get("plan_step_failed") is True
