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


def test_google_model_override_uses_configured_nonempty_value(monkeypatch):
    monkeypatch.setenv("ASTAKOS_GEMINI_FAST_MODEL", " gemini-3.7-flash ")

    model = brain._google_model_from_environment(
        "ASTAKOS_GEMINI_FAST_MODEL", "gemini-3.5-flash",
    )

    assert model == "gemini-3.7-flash"


def test_google_model_override_keeps_default_when_blank(monkeypatch):
    monkeypatch.setenv("ASTAKOS_GEMINI_FAST_MODEL", "   ")

    model = brain._google_model_from_environment(
        "ASTAKOS_GEMINI_FAST_MODEL", "gemini-3.5-flash",
    )

    assert model == "gemini-3.5-flash"


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
