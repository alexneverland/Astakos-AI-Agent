"""Strict, tool-free reminder decisions with no provider calls."""

import json

import pytest
from langchain_core.messages import AIMessage

from services.reminder_intent import is_grounded_reminder_request


@pytest.mark.parametrize("decision", [
    '{"direct_request":false,"arguments_grounded":true}',
    '{"direct_request":true,"arguments_grounded":false}',
    '{"direct_request":"true","arguments_grounded":true}',
    '{"direct_request":true,"arguments_grounded":true,"extra":true}',
    '{"direct_request":false,"direct_request":true,"arguments_grounded":true}',
    '```json\n{"direct_request":true,"arguments_grounded":true}\n```',
    '[]', 'null', 'not JSON',
])
def test_unsupported_decisions_retain_approval(monkeypatch, decision):
    """Only the exact two true booleans authorize the narrow exception."""
    monkeypatch.setattr("core.brain.safe_llm_invoke", lambda *a, **k: AIMessage(content=decision))
    assert not is_grounded_reminder_request("Remind me about meat at 19:00",
        {"task": "meat", "exact_time": "19:00"}, [])


def test_provider_error_and_tool_calls_fail_closed(monkeypatch):
    """Neither provider failures nor generated actions can authorize anything."""
    def unavailable(*args, **kwargs):
        raise RuntimeError("offline")
    monkeypatch.setattr("core.brain.safe_llm_invoke", unavailable)
    assert not is_grounded_reminder_request("Remind me", {"task": "meat"}, [])
    monkeypatch.setattr("core.brain.safe_llm_invoke", lambda *a, **k: AIMessage(
        content='{"direct_request":true,"arguments_grounded":true}',
        tool_calls=[{"name": "send", "args": {}, "id": "unauthorized"}]))
    assert not is_grounded_reminder_request("Remind me", {"task": "meat"}, [])


@pytest.mark.parametrize("args", [
    {"task": "meat", "action": "update"}, {"task": "meat", "action": "done"},
    {"task": "meat", "external_content_sources_json": '["browse_url"]'},
    {"task": "meat", "external_content_sources_json": 'malformed'},
    {"task": "meat", "match_task": "existing task"},
    {"task": "meat", "unknown": "value"}, {"task": ""}, {"task": "x" * 2100},
])
def test_unsupported_or_oversized_arguments_never_reach_provider(monkeypatch, args):
    """The exception applies only to bounded creation arguments."""
    def forbidden(*a, **k):
        pytest.fail("Unsupported arguments reached provider")
    monkeypatch.setattr("core.brain.safe_llm_invoke", forbidden)
    assert not is_grounded_reminder_request("Remind me", args, [])


def test_model_receives_only_bounded_owner_data_and_unbound_model(monkeypatch):
    """The validator sees the actual proposed schedule and trusted context."""
    def check(model, messages, *, retries):
        from core.brain import llm
        assert model is llm
        assert retries == 1
        payload = json.loads(messages[1].content)
        assert payload["latest_owner_request"] == "Θύμισέ μου το κρέας στις 7 πριν σχολάσω"
        assert payload["proposed_reminder"]["exact_time"] == "19:00"
        assert payload["earlier_owner_messages"] == ["Σχολάω το απόγευμα"]
        assert "local_now" in payload
        return AIMessage(content='{"direct_request":true,"arguments_grounded":true}')
    monkeypatch.setattr("core.brain.safe_llm_invoke", check)
    assert is_grounded_reminder_request("Θύμισέ μου το κρέας στις 7 πριν σχολάσω",
        {"task": "κρέας", "exact_time": "19:00"}, ["Σχολάω το απόγευμα"])


def test_neutral_tool_schema_defaults_do_not_force_approval(monkeypatch):
    """Explicitly supplied harmless schema defaults match omitted defaults."""
    monkeypatch.setattr("core.brain.safe_llm_invoke", lambda *a, **k: AIMessage(
        content='{"direct_request":true,"arguments_grounded":true}'))
    assert is_grounded_reminder_request("Remind me about meat at 19:00",
        {"task": "meat", "exact_time": "19:00", "action": "add", "match_task": None,
         "external_content_sources_json": "[]", "minutes_from_now": 0, "location": None}, [])
