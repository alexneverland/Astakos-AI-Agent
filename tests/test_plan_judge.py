"""
Tests για core/plan_judge.py
Τρέξε: pytest tests/test_plan_judge.py -v
"""
import os
import sys
import types
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── Helpers ──────────────────────────────────────────────────────

def _stub_deps():
    """Stubbing βαριών dependencies ώστε να μπορεί να γίνει import χωρίς config/bot."""
    for mod_name in ["services", "services.gemini", "config"]:
        if mod_name not in sys.modules:
            sys.modules[mod_name] = types.ModuleType(mod_name)
    cfg = sys.modules["config"]
    if not hasattr(cfg, "WORKING_MEMORY_FILE"):
        cfg.WORKING_MEMORY_FILE = "/tmp/wm.json"
        cfg.BASE_DIR = "/tmp"


def _make_gemini_mock(text: str):
    result = MagicMock()
    result.text = text
    return MagicMock(return_value=result)


def _import_judge():
    _stub_deps()
    # Force re-import αν ήδη φορτώθηκε
    if "core.plan_judge" in sys.modules:
        del sys.modules["core.plan_judge"]
    from core.plan_judge import should_auto_plan, _needs_llm_evaluation
    return should_auto_plan, _needs_llm_evaluation


# ═══════════════════════════════════════════════════════════════
# Heuristic tests — χωρίς LLM call
# ═══════════════════════════════════════════════════════════════

def test_heuristic_short_simple_message_skips_llm():
    """Κοντό απλό μήνυμα → heuristic False → δεν καλείται το LLM."""
    _, needs_eval = _import_judge()
    assert needs_eval("τι καιρό κάνει;") is False


def test_heuristic_long_message_triggers_llm():
    """Μήνυμα με πολλές λέξεις → heuristic True → πάει στο LLM."""
    _, needs_eval = _import_judge()
    long_msg = "θέλω να δημιουργήσεις ένα report για τα έξοδα του μήνα και να το στείλεις με email στον λογιστή μου αφού πρώτα το αναλύσεις"
    assert needs_eval(long_msg) is True


def test_heuristic_short_but_two_markers_triggers_llm():
    """Κοντό μήνυμα με ≥2 multi-step markers → heuristic True."""
    _, needs_eval = _import_judge()
    assert needs_eval("πρώτα αρχικά κάνε κάτι") is True


def test_heuristic_short_one_marker_skips_llm():
    """Κοντό μήνυμα με 1 marker → heuristic False."""
    _, needs_eval = _import_judge()
    assert needs_eval("πρώτα απ' όλα γεια σου") is False


def test_heuristic_empty_message():
    """Κενό μήνυμα → False άμεσα."""
    judge, _ = _import_judge()
    assert judge("") is False
    assert judge("   ") is False


# ═══════════════════════════════════════════════════════════════
# LLM judge tests — με mock Gemini
# ═══════════════════════════════════════════════════════════════

def test_judge_returns_true_on_plan():
    """Gemini επιστρέφει PLAN → should_auto_plan = True."""
    judge, _ = _import_judge()
    mock_fn = _make_gemini_mock("PLAN")
    long_msg = "θέλω να αναλύσεις τα έξοδα του Ιουνίου, να φτιάξεις ένα Excel report και μετά να το στείλεις με email στη Σοφία"
    with patch("services.gemini.safe_gemini_call", mock_fn, create=True):
        assert judge(long_msg) is True


def test_judge_returns_false_on_no():
    """Gemini επιστρέφει NO → should_auto_plan = False."""
    judge, _ = _import_judge()
    mock_fn = _make_gemini_mock("NO")
    long_msg = "θέλω να αναλύσεις τα έξοδα του Ιουνίου μέσω ανάλυσης κατηγοριοποίησης λογιστικής"
    with patch("services.gemini.safe_gemini_call", mock_fn, create=True):
        assert judge(long_msg) is False


def test_judge_normalizes_lowercase_plan():
    """Gemini επιστρέφει 'plan' lowercase → αναγνωρίζεται ως PLAN."""
    judge, _ = _import_judge()
    mock_fn = _make_gemini_mock("plan")
    long_msg = " ".join(["κάνε"] * 25)  # 25 λέξεις → περνάει heuristic
    with patch("services.gemini.safe_gemini_call", mock_fn, create=True):
        assert judge(long_msg) is True


def test_judge_ignores_extra_words_after_verdict():
    """'PLAN sure go ahead' → παίρνει μόνο το πρώτο token."""
    judge, _ = _import_judge()
    mock_fn = _make_gemini_mock("PLAN sure go ahead")
    long_msg = " ".join(["task"] * 25)
    with patch("services.gemini.safe_gemini_call", mock_fn, create=True):
        assert judge(long_msg) is True


def test_judge_unknown_verdict_returns_false():
    """Άγνωστο verdict ('MAYBE') → False (conservative)."""
    judge, _ = _import_judge()
    mock_fn = _make_gemini_mock("MAYBE")
    long_msg = " ".join(["word"] * 25)
    with patch("services.gemini.safe_gemini_call", mock_fn, create=True):
        assert judge(long_msg) is False


def test_judge_exception_returns_false():
    """Αν το Gemini ρίξει exception → False, δεν κρασάρει."""
    judge, _ = _import_judge()
    mock_fn = MagicMock(side_effect=Exception("network error"))
    long_msg = " ".join(["fail"] * 25)
    with patch("services.gemini.safe_gemini_call", mock_fn, create=True):
        assert judge(long_msg) is False


def test_judge_llm_not_called_for_short_simple():
    """Βεβαιωνόμαστε ότι το LLM ΔΕΝ καλείται για κοντά, απλά μηνύματα."""
    judge, _ = _import_judge()
    mock_fn = MagicMock()
    with patch("services.gemini.safe_gemini_call", mock_fn, create=True):
        judge("γεια σου")
    mock_fn.assert_not_called()


def test_judge_prompt_contains_message():
    """Το prompt που στέλνεται στο LLM περιέχει το μήνυμα του χρήστη."""
    judge, _ = _import_judge()
    captured = []

    def capture(prompt, **kwargs):
        captured.append(prompt)
        r = MagicMock()
        r.text = "NO"
        return r

    long_msg = "θέλω να κάνεις αυτό και εκείνο και το άλλο και κάτι ακόμα και επίσης αρχικά βήμα"
    with patch("services.gemini.safe_gemini_call", capture, create=True):
        judge(long_msg)

    assert len(captured) == 1
    assert long_msg in captured[0]


# ═══════════════════════════════════════════════════════════════
# Edge cases
# ═══════════════════════════════════════════════════════════════

def test_judge_explicit_plan_command_not_needed():
    """
    Ο judge δεν χρειάζεται να χειρίζεται /plan — αυτό γίνεται πριν.
    Αλλά αν περαστεί "/plan κάτι" → ελέγχουμε ότι δεν κρασάρει.
    """
    judge, _ = _import_judge()
    mock_fn = _make_gemini_mock("PLAN")
    with patch("services.gemini.safe_gemini_call", mock_fn, create=True):
        # Δεν πρέπει να ρίξει exception
        result = judge("/plan κάνε κάτι κάτι κάτι κάτι κάτι κάτι κάτι κάτι κάτι κάτι κάτι κάτι")
        assert isinstance(result, bool)
