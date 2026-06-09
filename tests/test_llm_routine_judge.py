"""
Tests για _llm_routine_judge() στο clients/telegram_bot.py
Τρέξε: pytest tests/test_llm_routine_judge.py -v
"""
import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _import_judge():
    """Import μόνο της συνάρτησης — χωρίς να φορτωθεί όλο το bot."""
    import importlib, types
    # Stub βαριά dependencies
    for mod in ["telegram", "telegram.ext", "services.gemini"]:
        if mod not in sys.modules:
            sys.modules[mod] = types.ModuleType(mod)
    # Stub config
    if "config" not in sys.modules:
        cfg = types.ModuleType("config")
        cfg.TELEGRAM_TOKEN = "fake"
        cfg.TELEGRAM_CHAT_ID = "123"
        cfg.ASTAKOS_API_URL = "http://localhost"
        cfg.ASTAKOS_TOKEN = "token"
        sys.modules["config"] = cfg

    # Import μόνο της συνάρτησης με exec σε isolation
    src_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "clients", "telegram_bot.py")
    with open(src_path, encoding="utf-8") as f:
        src = f.read()

    # Εξαγωγή μόνο της _llm_routine_judge function
    import ast
    tree = ast.parse(src)
    fn_node = next(
        (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_llm_routine_judge"),
        None,
    )
    assert fn_node is not None, "_llm_routine_judge not found in telegram_bot.py"

    # Compile και execute μόνο τη function
    fn_src = ast.unparse(fn_node)
    ns = {}
    exec(fn_src, ns)
    return ns["_llm_routine_judge"]


def _make_gemini_mock(text: str):
    mock_result = MagicMock()
    mock_result.text = text
    mock_fn = MagicMock(return_value=mock_result)
    return mock_fn


# ═══════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════

def test_judge_returns_yes():
    judge = _import_judge()
    mock_fn = _make_gemini_mock("YES")
    with patch("services.gemini.safe_gemini_call", mock_fn):
        result = judge("ναι πήγαμε στο πάρκο", ["park_walk"])
    assert result == "YES"

def test_judge_returns_no():
    judge = _import_judge()
    mock_fn = _make_gemini_mock("NO")
    with patch("services.gemini.safe_gemini_call", mock_fn):
        result = judge("όχι δεν πήγαμε", ["park_walk"])
    assert result == "NO"

def test_judge_returns_unclear():
    judge = _import_judge()
    mock_fn = _make_gemini_mock("UNCLEAR")
    with patch("services.gemini.safe_gemini_call", mock_fn):
        result = judge("μάλλον", ["park_walk"])
    assert result == "UNCLEAR"

def test_judge_normalizes_lowercase():
    judge = _import_judge()
    mock_fn = _make_gemini_mock("yes")
    with patch("services.gemini.safe_gemini_call", mock_fn):
        result = judge("ναι", ["park_walk"])
    assert result == "YES"

def test_judge_handles_extra_words():
    """Αν επιστραφεί 'YES please' → παίρνει μόνο το πρώτο word."""
    judge = _import_judge()
    mock_fn = _make_gemini_mock("YES please ignore rest")
    with patch("services.gemini.safe_gemini_call", mock_fn):
        result = judge("ναι", ["park_walk"])
    assert result == "YES"

def test_judge_invalid_verdict_falls_back_to_unclear():
    """Αν το LLM επιστρέψει κάτι άσχετο → UNCLEAR."""
    judge = _import_judge()
    mock_fn = _make_gemini_mock("MAYBE")
    with patch("services.gemini.safe_gemini_call", mock_fn):
        result = judge("ίσως", ["park_walk"])
    assert result == "UNCLEAR"

def test_judge_on_gemini_exception_returns_unclear():
    """Αν το Gemini ρίξει exception → UNCLEAR (δεν κρασάρει)."""
    judge = _import_judge()
    mock_fn = MagicMock(side_effect=Exception("network error"))
    with patch("services.gemini.safe_gemini_call", mock_fn):
        result = judge("ναι", ["park_walk"])
    assert result == "UNCLEAR"

def test_judge_multiple_events_passed():
    """Ελέγχει ότι όλα τα events περνάνε στο prompt."""
    judge = _import_judge()
    captured_prompts = []
    def capture_call(prompt, **kwargs):
        captured_prompts.append(prompt)
        r = MagicMock(); r.text = "YES"; return r
    with patch("services.gemini.safe_gemini_call", capture_call):
        judge("πήγαμε", ["park_walk", "sleep_routine", "gym"])
    assert len(captured_prompts) == 1
    prompt = captured_prompts[0]
    assert "park_walk" in prompt
    assert "sleep_routine" in prompt
    assert "gym" in prompt
