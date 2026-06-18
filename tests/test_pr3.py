"""
Tests για replan_node() και end_check_node() στο core/planner.py
Τρέξε: pytest tests/test_pr3.py -v
"""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── Helpers ──────────────────────────────────────────────────────
#
# NOTE: sys.modules stubs MUST be set up/torn down at module scope
# (setup_module/teardown_module), never stubbed-in-place with no restore.
# A bare `sys.modules["services.reflection_engine"] = types.ModuleType(...)`
# that's never undone leaks into every other test file that runs afterward
# (alphabetically, this file runs before test_reflection_engine_pending.py)
# and shadows the real module, causing AttributeError there.

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


def _import_nodes():
    if "core.planner" in sys.modules:
        del sys.modules["core.planner"]
    from core.planner import replan_node, end_check_node
    return replan_node, end_check_node


def _base_state(idx=0, tasks=None, results=None, skipped=None):
    if tasks is None:
        tasks = [
            {"step": 1, "description": "Ανάλυση δεδομένων", "instruction": "Ανάλυσε"},
            {"step": 2, "description": "Δημιουργία report",  "instruction": "Φτιάξε report"},
            {"step": 3, "description": "Αποστολή email",    "instruction": "Στείλε email"},
        ]
    return {
        "messages":             [],
        "plan_active":          True,
        "plan_tasks":           tasks,
        "plan_index":           idx,
        "plan_results":         results or [],
        "plan_goal":            "Ανάλυσε, φτιάξε report και στείλε email",
        "plan_step_failed":     True,
        "replan_skipped_steps": skipped or [],
    }


# ══════════════════════════════════════════════════════════════════
# Tests: replan_node
# ══════════════════════════════════════════════════════════════════

def test_replan_increments_index():
    """replan_node αυξάνει plan_index κατά 1."""
    replan, _ = _import_nodes()
    state  = _base_state(idx=0)
    result = replan(state)
    assert result["plan_index"] == 1


def test_replan_appends_to_results():
    """replan_node προσθέτει skip entry στα αποτελέσματα."""
    replan, _ = _import_nodes()
    state  = _base_state(idx=1, results=["ok βήμα 1"])
    result = replan(state)
    assert len(result["plan_results"]) == 2
    assert "⚠️" in result["plan_results"][1]
    assert "Δημιουργία report" in result["plan_results"][1]


def test_replan_records_skipped_index():
    """replan_node καταγράφει το idx στη λίστα skipped."""
    replan, _ = _import_nodes()
    state  = _base_state(idx=1)
    result = replan(state)
    assert 1 in result["replan_skipped_steps"]


def test_replan_accumulates_multiple_skips():
    """Πολλαπλά skips: η λίστα μεγαλώνει σωστά."""
    replan, _ = _import_nodes()
    state  = _base_state(idx=2, skipped=[0, 1])
    result = replan(state)
    assert result["replan_skipped_steps"] == [0, 1, 2]


def test_replan_plan_active_true_when_more_steps():
    """Αν υπάρχουν επόμενα βήματα → plan_active=True."""
    replan, _ = _import_nodes()
    state  = _base_state(idx=0)  # 3 tasks, skip idx=0 → idx=1 < 3
    result = replan(state)
    assert result["plan_active"] is True


def test_replan_plan_active_false_when_last_step():
    """Αν skip στο τελευταίο βήμα → plan_active=False."""
    replan, _ = _import_nodes()
    state  = _base_state(idx=2)  # 3 tasks, skip idx=2 → idx=3 >= 3
    result = replan(state)
    assert result["plan_active"] is False


def test_replan_clears_step_failed():
    """Μετά το replan → plan_step_failed=False."""
    replan, _ = _import_nodes()
    state  = _base_state(idx=0)
    result = replan(state)
    assert result["plan_step_failed"] is False


def test_replan_emits_warning_message():
    """replan_node εκπέμπει AIMessage με ⚠️."""
    from langchain_core.messages import AIMessage
    replan, _ = _import_nodes()
    state  = _base_state(idx=0)
    result = replan(state)
    msgs   = result["messages"]
    assert len(msgs) == 1
    assert isinstance(msgs[0], AIMessage)
    assert "⚠️" in msgs[0].content


def test_replan_message_mentions_step_desc():
    """Το warning αναφέρει το description του βήματος."""
    replan, _ = _import_nodes()
    state  = _base_state(idx=0)
    result = replan(state)
    assert "Ανάλυση δεδομένων" in result["messages"][0].content


# ══════════════════════════════════════════════════════════════════
# Tests: end_check_node
# ══════════════════════════════════════════════════════════════════

def test_end_check_success_header():
    """Χωρίς skips → header ✅."""
    _, end_check = _import_nodes()
    state = {
        "plan_goal":            "test goal",
        "plan_tasks":           [{"step": 1, "description": "Do A", "instruction": "A"}],
        "plan_results":         ["Done A"],
        "replan_skipped_steps": [],
    }
    result = end_check(state)
    content = result["messages"][0].content
    assert "✅" in content


def test_end_check_warning_header_with_skips():
    """Με skips → header ⚠️ με count."""
    _, end_check = _import_nodes()
    state = {
        "plan_goal":            "test goal",
        "plan_tasks":           [
            {"step": 1, "description": "Do A", "instruction": "A"},
            {"step": 2, "description": "Do B", "instruction": "B"},
        ],
        "plan_results":         ["Done A", "⚠️ Παραλείφθηκε: Do B"],
        "replan_skipped_steps": [1],
    }
    result = end_check(state)
    content = result["messages"][0].content
    assert "⚠️" in content
    assert "1/2" in content


def test_end_check_lists_all_steps():
    """end_check_node αναφέρει όλα τα βήματα."""
    _, end_check = _import_nodes()
    state = {
        "plan_goal":            "g",
        "plan_tasks":           [
            {"step": 1, "description": "Alpha", "instruction": "a"},
            {"step": 2, "description": "Beta",  "instruction": "b"},
        ],
        "plan_results":         ["r1", "r2"],
        "replan_skipped_steps": [],
    }
    result = end_check(state)
    content = result["messages"][0].content
    assert "Alpha" in content
    assert "Beta"  in content


def test_end_check_marks_skipped_step():
    """Το skip βήμα έχει badge 'παραλείφθηκε' στο summary."""
    _, end_check = _import_nodes()
    state = {
        "plan_goal":            "g",
        "plan_tasks":           [
            {"step": 1, "description": "Skip Me", "instruction": "x"},
        ],
        "plan_results":         ["⚠️ Παραλείφθηκε: Skip Me"],
        "replan_skipped_steps": [0],
    }
    result = end_check(state)
    content = result["messages"][0].content
    assert "παραλείφθηκε" in content.lower()


def test_end_check_resets_state():
    """end_check_node επιστρέφει plan_active=False και καθαρίζει state."""
    _, end_check = _import_nodes()
    state = {
        "plan_goal":            "g",
        "plan_tasks":           [{"step": 1, "description": "A", "instruction": "a"}],
        "plan_results":         ["ok"],
        "replan_skipped_steps": [0],
    }
    result = end_check(state)
    assert result["plan_active"] is False
    assert result["plan_tasks"] == []
    assert result["plan_index"] == 0
    assert result["plan_results"] == []
    assert result["replan_skipped_steps"] == []


def test_end_check_handles_empty_plan():
    """end_check_node με κενά tasks/results δεν crashάρει."""
    _, end_check = _import_nodes()
    state = {
        "plan_goal":            "",
        "plan_tasks":           [],
        "plan_results":         [],
        "replan_skipped_steps": [],
    }
    result = end_check(state)
    assert result["plan_active"] is False
    assert "messages" in result
