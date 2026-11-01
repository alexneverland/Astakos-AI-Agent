from __future__ import annotations

from typing import Any, Sequence
from unittest.mock import patch

import pytest

import core.brain as brain


class _FakeLLM:
    def __init__(self, effects: Sequence[Any]) -> None:
        self._effects: list[Any] = list(effects)

    def invoke(self, _input: Any) -> Any:
        effect = self._effects.pop(0)
        if isinstance(effect, Exception):
            raise effect
        return effect


class _FakeResponse:
    def __init__(self) -> None:
        self.content: str = "ok"


def test_google_model_override_uses_configured_nonempty_value(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ASTAKOS_GEMINI_FAST_MODEL", " gemini-3.7-flash ")

    model: str = brain._google_model_from_environment(
        "ASTAKOS_GEMINI_FAST_MODEL", "gemini-3.5-flash",
    )

    assert model == "gemini-3.7-flash"
    assert "ASTAKOS_GEMINI_FAST_MODEL='gemini-3.7-flash'" in capsys.readouterr().out


def test_google_model_override_keeps_default_when_blank(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ASTAKOS_GEMINI_FAST_MODEL", "   ")

    model: str = brain._google_model_from_environment(
        "ASTAKOS_GEMINI_FAST_MODEL", "gemini-3.5-flash",
    )

    assert model == "gemini-3.5-flash"
    assert capsys.readouterr().out == ""


def test_safe_llm_invoke_retries_on_quota_then_succeeds() -> None:
    llm = _FakeLLM([
        Exception("429 RESOURCE_EXHAUSTED"),
        _FakeResponse(),
    ])

    with patch("core.brain.time.sleep") as sleep_mock:
        response: Any = brain.safe_llm_invoke(llm, "hello", retries=3, base_delay=0.01)

    assert isinstance(response, _FakeResponse)
    sleep_mock.assert_called_once()


def test_safe_llm_invoke_raises_after_quota_retries_exhausted() -> None:
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


def test_resolve_gemini_safety_threshold_defaults_to_block_none(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("ASTAKOS_GEMINI_SAFETY_THRESHOLD", raising=False)
    threshold: Any = brain._resolve_gemini_safety_threshold()
    assert threshold == brain.HarmBlockThreshold.BLOCK_NONE
    assert capsys.readouterr().out == ""


def test_resolve_gemini_safety_threshold_parses_valid_option(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ASTAKOS_GEMINI_SAFETY_THRESHOLD", "BLOCK_ONLY_HIGH")
    threshold: Any = brain._resolve_gemini_safety_threshold()
    assert threshold == brain.HarmBlockThreshold.BLOCK_ONLY_HIGH
    assert "Gemini safety threshold active (BLOCK_ONLY_HIGH)" in capsys.readouterr().out


def test_resolve_gemini_safety_threshold_falls_back_on_invalid_option(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ASTAKOS_GEMINI_SAFETY_THRESHOLD", "INVALID_SETTING")
    threshold: Any = brain._resolve_gemini_safety_threshold()
    assert threshold == brain.HarmBlockThreshold.BLOCK_NONE
    assert "Unknown safety threshold 'INVALID_SETTING', falling back to BLOCK_NONE" in capsys.readouterr().out


def test_safe_adapter_call_retries_on_transient_error_then_succeeds() -> None:
    """Verifies safe_adapter_call retries transient network/timeout errors with backoff."""
    calls: list[str] = []

    def mock_fn(val: str) -> str:
        calls.append(val)
        if len(calls) == 1:
            raise ConnectionResetError("Connection reset by peer (10054)")
        return f"result: {val}"

    with patch("core.brain.time.sleep") as sleep_mock:
        res: str = brain.safe_adapter_call(mock_fn, "test_input", retries=3, base_delay=0.01)

    assert res == "result: test_input"
    assert len(calls) == 2
    sleep_mock.assert_called_once()


def test_safe_adapter_call_retries_on_rate_limit_error_then_succeeds() -> None:
    """Verifies safe_adapter_call retries RateLimitError and uses retry_after when provided."""
    from core.ai_provider import RateLimitError

    calls: list[int] = []

    def mock_fn() -> str:
        calls.append(1)
        if len(calls) == 1:
            raise RateLimitError("openai", "Rate limit reached", retry_after=0.5)
        return "success"

    with patch("core.brain.time.sleep") as sleep_mock:
        res: str = brain.safe_adapter_call(mock_fn, retries=3, base_delay=0.01)

    assert res == "success"
    assert len(calls) == 2
    sleep_mock.assert_called_once_with(0.5)


def test_safe_adapter_call_raises_immediately_on_auth_or_unsupported_error() -> None:
    """Verifies safe_adapter_call does NOT retry fatal ProviderAuthError or CapabilityNotSupportedError."""
    from core.ai_provider import CapabilityNotSupportedError, ProviderAuthError

    auth_calls: list[int] = []

    def auth_fail() -> None:
        auth_calls.append(1)
        raise ProviderAuthError("vertex", "Invalid credentials")

    with patch("core.brain.time.sleep") as sleep_mock:
        try:
            brain.safe_adapter_call(auth_fail, retries=3)
        except ProviderAuthError:
            pass

    assert len(auth_calls) == 1
    sleep_mock.assert_not_called()

    cap_calls: list[int] = []

    def cap_fail() -> None:
        cap_calls.append(1)
        raise CapabilityNotSupportedError("anthropic", "image_gen")

    with patch("core.brain.time.sleep") as sleep_mock:
        try:
            brain.safe_adapter_call(cap_fail, retries=3)
        except CapabilityNotSupportedError:
            pass

    assert len(cap_calls) == 1
    sleep_mock.assert_not_called()
