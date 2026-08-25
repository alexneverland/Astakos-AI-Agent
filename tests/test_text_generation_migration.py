# ================================================================
# Project: Astakos AI Agent 🦞
# Module:  Tests for Text Generation Migration (PR 3B)
# Description: Offline deterministic tests for reflection_engine and story_maker migration
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

import json
from typing import Any, Self

import pytest

from core.ai_provider import (
    AIProviderError,
)
from tests.fixtures.provider_mocks import (
    MockOpenAIAdapter,
    MockGeminiAPIAdapter,
    MockVertexAIAdapter,
    MockAnthropicAdapter,
)


class TestReflectionEngineMigration:
    """Validates reflection_engine._analyze_with_llm integration with AI provider adapter."""

    def test_reflection_engine_vertex_success(self: Self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Routes a Vertex-style reflection response through the heavy adapter model."""
        import services.reflection_engine as ref_eng

        reflections_payload = [
            {
                "observation": "User asks for news in the morning",
                "action": "save_to_memory",
                "confidence": 0.85,
                "lesson": "Provide news summary during morning routine",
                "source": "routine",
            }
        ]

        captured_args: dict[str, str] = {}

        class CustomVertexAdapter(MockVertexAIAdapter):
            """Returns deterministic reflection JSON while recording adapter arguments."""

            def generate_text(
                self: Self,
                prompt: str,
                model_type: str = "fast",
                system_prompt: str | None = None,
                temperature: float | None = None,
            ) -> str:
                """Return a deterministic reflection payload for this migration test."""
                captured_args["prompt"] = prompt
                captured_args["model_type"] = model_type
                return json.dumps(reflections_payload)

        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: CustomVertexAdapter())

        traces = [{"channel": "telegram", "agent": "chat", "user_message": "Good morning", "response": "Hello"}]
        routines = [{"id": 1, "event": "Morning alarm", "day": "daily", "time": "08:00", "state": "active", "ignore_count": 0, "mention_count": 5, "cooldown_hours": 24}]

        result = ref_eng._analyze_with_llm([], routines, traces)

        assert len(result) == 1
        assert result[0]["observation"] == "User asks for news in the morning"
        assert result[0]["confidence"] == 0.85
        assert captured_args["model_type"] == "heavy"
        assert "Morning alarm" in captured_args["prompt"]
        assert "Good morning" in captured_args["prompt"]

    def test_reflection_engine_openai_success(self: Self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Accepts a fenced OpenAI-style JSON reflection response."""
        import services.reflection_engine as ref_eng

        reflections_payload = [
            {
                "observation": "Routine #2 frequently ignored",
                "action": "increase_cooldown",
                "confidence": 0.65,
                "lesson": "Increase cooldown to 48h",
                "source": "routine",
                "routine_id": 2,
                "action_value": 48,
            }
        ]

        class CustomOpenAIAdapter(MockOpenAIAdapter):
            """Returns deterministic fenced JSON for the reflection parser."""

            def generate_text(
                self: Self,
                prompt: str,
                model_type: str = "fast",
                system_prompt: str | None = None,
                temperature: float | None = None,
            ) -> str:
                """Return a fenced JSON payload without contacting a provider."""
                return f"```json\n{json.dumps(reflections_payload)}\n```"

        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: CustomOpenAIAdapter())

        result = ref_eng._analyze_with_llm([], [], [])
        assert len(result) == 1
        assert result[0]["action"] == "increase_cooldown"
        assert result[0]["action_value"] == 48

    def test_reflection_engine_auth_error_returns_empty_and_does_not_crash(
        self: Self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Returns no findings when reflection-provider authentication fails."""
        import services.reflection_engine as ref_eng

        monkeypatch.setattr(
            "core.brain.get_active_provider_adapter",
            lambda: MockVertexAIAdapter(should_fail_auth=True),
        )

        result = ref_eng._analyze_with_llm([], [], [])
        assert result == []

    def test_reflection_engine_rate_limit_returns_empty_and_does_not_crash(
        self: Self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Returns no findings when the reflection provider is rate limited."""
        import services.reflection_engine as ref_eng

        monkeypatch.setattr(
            "core.brain.get_active_provider_adapter",
            lambda: MockGeminiAPIAdapter(should_rate_limit=True),
        )

        result = ref_eng._analyze_with_llm([], [], [])
        assert result == []

    def test_reflection_engine_generic_provider_error_returns_empty(
        self: Self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Returns no findings for a non-typed provider failure."""
        import services.reflection_engine as ref_eng

        class FailingAdapter(MockVertexAIAdapter):
            """Raises a deterministic generic provider error."""

            def generate_text(
                self: Self,
                prompt: str,
                model_type: str = "fast",
                system_prompt: str | None = None,
                temperature: float | None = None,
            ) -> str:
                """Raise the failure the reflection engine must handle safely."""
                raise AIProviderError("Backend connection reset", provider="vertex")

        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: FailingAdapter())

        result = ref_eng._analyze_with_llm([], [], [])
        assert result == []

    def test_reflection_engine_brain_error_does_not_raise_unbound_local_error(
        self: Self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Handles a core.brain import failure without an unbound exception name."""
        import builtins
        import services.reflection_engine as ref_eng

        original_import = builtins.__import__

        def fail_brain_import(
            name: str,
            globals: dict[str, Any] | None = None,
            locals: dict[str, Any] | None = None,
            fromlist: tuple[str, ...] = (),
            level: int = 0,
        ) -> Any:
            """Fail only the adapter import needed to reproduce the regression."""
            if name == "core.brain":
                raise ImportError("Simulated failure during core.brain import")
            return original_import(name, globals, locals, fromlist, level)

        monkeypatch.setattr(builtins, "__import__", fail_brain_import)

        result = ref_eng._analyze_with_llm([], [], [])
        assert result == []


class TestStoryMakerMigration:
    """Validates astakos_skills/story_maker integration with AI provider adapter."""

    def test_story_maker_vertex_success(self: Self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Routes story generation through the fast active-provider model."""
        import astakos_skills.story_maker as sm

        captured_args: dict[str, str] = {}

        class CustomVertexAdapter(MockVertexAIAdapter):
            """Returns a deterministic story and three image-scene prompts."""

            def generate_text(
                self: Self,
                prompt: str,
                model_type: str = "fast",
                system_prompt: str | None = None,
                temperature: float | None = None,
            ) -> str:
                """Return the story fixture while recording adapter arguments."""
                captured_args["prompt"] = prompt
                captured_args["model_type"] = model_type
                return (
                    "Once upon a time in a magical forest, a brave little crab went on a quest.\n"
                    "SCENE1: A cute little crab standing near a crystal river in a lush forest\n"
                    "SCENE2: The crab finding a glowing pearl inside an ancient cave\n"
                    "SCENE3: Friendly forest animals celebrating together with the crab"
                )

        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: CustomVertexAdapter())

        result = sm._generate_story_and_prompts("magical forest", characters="Astakos the crab")

        assert result["story"] is not None
        assert "Once upon a time in a magical forest" in result["story"]
        assert len(result["scenes"]) == 3
        assert "A cute little crab standing" in result["scenes"][0]
        assert captured_args["model_type"] == "fast"
        assert "magical forest" in captured_args["prompt"]
        assert "Astakos the crab" in captured_args["prompt"]

    def test_story_maker_openai_success(self: Self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Parses a successful OpenAI-style story response."""
        import astakos_skills.story_maker as sm

        class CustomOpenAIAdapter(MockOpenAIAdapter):
            """Returns a deterministic story fixture for the active adapter."""

            def generate_text(
                self: Self,
                prompt: str,
                model_type: str = "fast",
                system_prompt: str | None = None,
                temperature: float | None = None,
            ) -> str:
                """Return a story response without invoking a real provider."""
                return (
                    "In a sunny kingdom, there lived a curious kitten.\n"
                    "SCENE1: Kitten playing in the royal garden\n"
                    "SCENE2: Kitten discovering a secret door\n"
                    "SCENE3: Kitten finding a treasure box of yarn"
                )

        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: CustomOpenAIAdapter())

        result = sm._generate_story_and_prompts("curious kitten", characters="")
        assert result["story"] == "In a sunny kingdom, there lived a curious kitten."
        assert len(result["scenes"]) == 3

    def test_story_maker_fallback_scenes_when_scene_markers_missing(
        self: Self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Builds fallback scene prompts when the text response lacks markers."""
        import astakos_skills.story_maker as sm

        class PlainStoryAdapter(MockVertexAIAdapter):
            """Returns a story without scene markers."""

            def generate_text(
                self: Self,
                prompt: str,
                model_type: str = "fast",
                system_prompt: str | None = None,
                temperature: float | None = None,
            ) -> str:
                """Return a plain story to exercise fallback-scene construction."""
                return "This is a simple bedtime story without scene tags."

        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: PlainStoryAdapter())

        result = sm._generate_story_and_prompts("space adventure")
        assert result["story"] == "This is a simple bedtime story without scene tags."
        assert len(result["scenes"]) == 3
        assert "space adventure" in result["scenes"][0]

    def test_story_maker_auth_error_handled_gracefully(
        self: Self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Returns the established structured story failure on authentication errors."""
        import astakos_skills.story_maker as sm

        monkeypatch.setattr(
            "core.brain.get_active_provider_adapter",
            lambda: MockVertexAIAdapter(should_fail_auth=True),
        )

        result = sm._generate_story_and_prompts("dragons")
        assert result["story"] is None
        assert result["scenes"] == []

        # make_story must return structured error
        full_res = sm.make_story("dragons")
        assert full_res["story"] is None
        assert full_res["images"] == []
        assert full_res["error"] is not None

    def test_story_maker_rate_limit_error_handled_gracefully(
        self: Self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Returns the established structured story failure on rate limits."""
        import astakos_skills.story_maker as sm

        monkeypatch.setattr(
            "core.brain.get_active_provider_adapter",
            lambda: MockGeminiAPIAdapter(should_rate_limit=True),
        )

        result = sm._generate_story_and_prompts("dragons")
        assert result["story"] is None
        assert result["scenes"] == []

        full_res = sm.make_story("dragons")
        assert full_res["story"] is None
        assert full_res["error"] is not None

    def test_story_maker_generic_provider_error_handled_gracefully(
        self: Self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Returns a structured failure for a generic provider exception."""
        import astakos_skills.story_maker as sm

        class FailingAdapter(MockAnthropicAdapter):
            """Raises a deterministic generic provider error."""

            def generate_text(
                self: Self,
                prompt: str,
                model_type: str = "fast",
                system_prompt: str | None = None,
                temperature: float | None = None,
            ) -> str:
                """Raise the failure the Story Maker must handle gracefully."""
                raise AIProviderError("Service temporarily unavailable", provider="anthropic")

        monkeypatch.setattr("core.brain.get_active_provider_adapter", lambda: FailingAdapter())

        result = sm._generate_story_and_prompts("dragons")
        assert result["story"] is None
        assert result["scenes"] == []

    def test_story_maker_brain_error_does_not_raise_unbound_local_error(
        self: Self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Handles a core.brain import failure without an unbound exception name."""
        import builtins
        import astakos_skills.story_maker as sm

        original_import = builtins.__import__

        def fail_brain_import(
            name: str,
            globals: dict[str, Any] | None = None,
            locals: dict[str, Any] | None = None,
            fromlist: tuple[str, ...] = (),
            level: int = 0,
        ) -> Any:
            """Fail only the adapter import needed to reproduce the regression."""
            if name == "core.brain":
                raise ImportError("Simulated failure during core.brain import")
            return original_import(name, globals, locals, fromlist, level)

        monkeypatch.setattr(builtins, "__import__", fail_brain_import)

        result = sm._generate_story_and_prompts("dragons")
        assert result["story"] is None
        assert result["scenes"] == []
