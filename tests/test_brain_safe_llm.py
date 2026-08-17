from unittest.mock import patch

import core.brain as brain


class _FakeLLM:
    def __init__(self, effects):
        self._effects = list(effects)

    def invoke(self, _input):
        effect = self._effects.pop(0)
        if isinstance(effect, Exception):
            raise effect
        return effect


class _FakeResponse:
    def __init__(self):
        self.content = "ok"


def test_google_model_override_uses_configured_nonempty_value(monkeypatch, capsys):
    monkeypatch.setenv("ASTAKOS_GEMINI_FAST_MODEL", " gemini-3.7-flash ")

    model = brain._google_model_from_environment(
        "ASTAKOS_GEMINI_FAST_MODEL", "gemini-3.5-flash",
    )

    assert model == "gemini-3.7-flash"
    assert "ASTAKOS_GEMINI_FAST_MODEL='gemini-3.7-flash'" in capsys.readouterr().out


def test_google_model_override_keeps_default_when_blank(monkeypatch, capsys):
    monkeypatch.setenv("ASTAKOS_GEMINI_FAST_MODEL", "   ")

    model = brain._google_model_from_environment(
        "ASTAKOS_GEMINI_FAST_MODEL", "gemini-3.5-flash",
    )

    assert model == "gemini-3.5-flash"
    assert capsys.readouterr().out == ""


def test_safe_llm_invoke_retries_on_quota_then_succeeds():
    llm = _FakeLLM([
        Exception("429 RESOURCE_EXHAUSTED"),
        _FakeResponse(),
    ])

    with patch("core.brain.time.sleep") as sleep_mock:
        response = brain.safe_llm_invoke(llm, "hello", retries=3, base_delay=0.01)

    assert isinstance(response, _FakeResponse)
    sleep_mock.assert_called_once()


def test_safe_llm_invoke_raises_after_quota_retries_exhausted():
    llm = _FakeLLM([
        Exception("429 RESOURCE_EXHAUSTED"),
        Exception("429 RESOURCE_EXHAUSTED"),
    ])

    with patch("core.brain.time.sleep"):
        try:
            brain.safe_llm_invoke(llm, "hello", retries=2, base_delay=0.01)
        except Exception as exc:
            assert "429" in str(exc)
        else:
            raise AssertionError("Expected safe_llm_invoke to raise after exhausting retries")


def test_resolve_gemini_safety_threshold_defaults_to_block_none(monkeypatch, capsys):
    monkeypatch.delenv("ASTAKOS_GEMINI_SAFETY_THRESHOLD", raising=False)
    threshold = brain._resolve_gemini_safety_threshold()
    assert threshold == brain.HarmBlockThreshold.BLOCK_NONE
    assert capsys.readouterr().out == ""


def test_resolve_gemini_safety_threshold_parses_valid_option(monkeypatch, capsys):
    monkeypatch.setenv("ASTAKOS_GEMINI_SAFETY_THRESHOLD", "BLOCK_ONLY_HIGH")
    threshold = brain._resolve_gemini_safety_threshold()
    assert threshold == brain.HarmBlockThreshold.BLOCK_ONLY_HIGH
    assert "Gemini safety threshold active (BLOCK_ONLY_HIGH)" in capsys.readouterr().out


def test_resolve_gemini_safety_threshold_falls_back_on_invalid_option(monkeypatch, capsys):
    monkeypatch.setenv("ASTAKOS_GEMINI_SAFETY_THRESHOLD", "INVALID_SETTING")
    threshold = brain._resolve_gemini_safety_threshold()
    assert threshold == brain.HarmBlockThreshold.BLOCK_NONE
    assert "Unknown safety threshold 'INVALID_SETTING', falling back to BLOCK_NONE" in capsys.readouterr().out
