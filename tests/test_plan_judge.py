"""
Tests for core/plan_judge.py
Run: pytest tests/test_plan_judge.py -v
"""
import os
import sys
import types
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── Helpers ──────────────────────────────────────────────────────

def _stub_deps():
    """Stubbing heavy dependencies so that it can be imported without a config/bot."""
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
    # Force re-import if already loaded
    if "core.plan_judge" in sys.modules:
        del sys.modules["core.plan_judge"]
    from core.plan_judge import should_auto_plan, _needs_llm_evaluation
    return should_auto_plan, _needs_llm_evaluation


# ═══════════════════════════════════════════════════════════════
# Heuristic tests — without LLM call
# ═══════════════════════════════════════════════════════════════

def test_heuristic_short_simple_message_skips_llm():
    """Short simple message → heuristic False → LLM is not called."""
    _, needs_eval = _import_judge()
    assert needs_eval("τι καιρό κάνει;") is False


def test_heuristic_long_message_triggers_llm():
    """Message with many words → heuristic True → goes to the LLM."""
    _, needs_eval = _import_judge()
    long_msg = "θέλω να δημιουργήσεις ένα report για τα έξοδα του μήνα και να το στείλεις με email στον λογιστή μου αφού πρώτα το αναλύσεις"
    assert needs_eval(long_msg) is True


def test_heuristic_short_but_two_markers_triggers_llm():
    """Short message with ≥2 multi-step markers → heuristic True."""
    _, needs_eval = _import_judge()
    assert needs_eval("πρώτα αρχικά κάνε κάτι") is True


def test_heuristic_short_one_marker_skips_llm():
    """Short message with 1 marker → heuristic False."""
    _, needs_eval = _import_judge()
    assert needs_eval("πρώτα απ' όλα γεια σου") is False


def test_heuristic_empty_message():
    """Empty message → False immediately."""
    judge, _ = _import_judge()
    assert judge("") is False
    assert judge("   ") is False


# ═══════════════════════════════════════════════════════════════
# LLM judge tests — with mock Gemini
# ═══════════════════════════════════════════════════════════════

def test_judge_returns_true_on_plan():
    """Gemini returns PLAN → should_auto_plan = True."""
    judge, _ = _import_judge()
    mock_fn = _make_gemini_mock("PLAN")
    long_msg = "θέλω να αναλύσεις τα έξοδα του Ιουνίου, να φτιάξεις ένα Excel report και μετά να το στείλεις με email στη Σοφία"
    with patch("services.gemini.safe_gemini_call", mock_fn, create=True):
        assert judge(long_msg) is True


def test_judge_returns_false_on_no():
    """Gemini returns NO → should_auto_plan = False."""
    judge, _ = _import_judge()
    mock_fn = _make_gemini_mock("NO")
    long_msg = "θέλω να αναλύσεις τα έξοδα του Ιουνίου μέσω ανάλυσης κατηγοριοποίησης λογιστικής"
    with patch("services.gemini.safe_gemini_call", mock_fn, create=True):
        assert judge(long_msg) is False


def test_judge_normalizes_lowercase_plan():
    """Gemini returns 'plan' lowercase → recognized as PLAN."""
    judge, _ = _import_judge()
    mock_fn = _make_gemini_mock("plan")
    long_msg = " ".join(["κάνε"] * 25)  # 25 words → passes heuristic
    with patch("services.gemini.safe_gemini_call", mock_fn, create=True):
        assert judge(long_msg) is True


def test_judge_ignores_extra_words_after_verdict():
    """'PLAN sure go ahead' → takes only the first token."""
    judge, _ = _import_judge()
    mock_fn = _make_gemini_mock("PLAN sure go ahead")
    long_msg = " ".join(["task"] * 25)
    with patch("services.gemini.safe_gemini_call", mock_fn, create=True):
        assert judge(long_msg) is True


def test_judge_unknown_verdict_returns_false():
    """Unknown verdict ('MAYBE') → False (conservative)."""
    judge, _ = _import_judge()
    mock_fn = _make_gemini_mock("MAYBE")
    long_msg = " ".join(["word"] * 25)
    with patch("services.gemini.safe_gemini_call", mock_fn, create=True):
        assert judge(long_msg) is False


def test_judge_exception_returns_false():
    """If Gemini throws an exception → False, it does not crash."""
    judge, _ = _import_judge()
    mock_fn = MagicMock(side_effect=Exception("network error"))
    long_msg = " ".join(["fail"] * 25)
    with patch("services.gemini.safe_gemini_call", mock_fn, create=True):
        assert judge(long_msg) is False


def test_judge_llm_not_called_for_short_simple():
    """We ensure that the LLM is NOT called for short, simple messages."""
    judge, _ = _import_judge()
    mock_fn = MagicMock()
    with patch("services.gemini.safe_gemini_call", mock_fn, create=True):
        judge("γεια σου")
    mock_fn.assert_not_called()


def test_judge_prompt_contains_message():
    """The prompt sent to the LLM contains the user's message."""
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
    The judge does not need to handle /plan — this is done beforehand.
    But if "/plan something" is passed → we check that it does not crash.
    """
    judge, _ = _import_judge()
    mock_fn = _make_gemini_mock("PLAN")
    with patch("services.gemini.safe_gemini_call", mock_fn, create=True):
        # Should not throw an exception
        result = judge("/plan κάνε κάτι κάτι κάτι κάτι κάτι κάτι κάτι κάτι κάτι κάτι κάτι κάτι")
        assert isinstance(result, bool)

def test_reference_document_does_not_trigger_plan():
    from unittest.mock import patch
    judge, _ = _import_judge()
    mock_fn = _make_gemini_mock("REFERENCE")
    document = "Getting Started. Initialize an attack template and run a smoke test. " * 5

    with patch("services.gemini.safe_gemini_call", mock_fn, create=True):
        assert judge(document) is False
