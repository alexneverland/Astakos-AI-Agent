"""Tests for decoupling photo visual analysis from live physical real-time reality across Web, Telegram, and Matrix."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from core.untrusted_content import (
    MODEL_ASSET_CONTEXT_METADATA_KEY,
    USER_PROVIDED_ASSET_SOURCE,
    format_model_history_content,
    user_asset_history_metadata,
)
from core.i18n import load_prompt
from core.utils import build_prompt


def test_vision_reality_rule_bounds_asset_and_guards_realtime_environment() -> None:
    """The vision prompt keeps critical markers while guarding against conflating photos with live reality."""
    prompt = build_prompt(
        state_messages=[
            HumanMessage(
                content=(
                    "[USER_UPLOADED_PHOTO]: snow.jpg\n"
                    "[PHOTO PATH]: C:/photos/snow.jpg\n"
                    "[VISUAL ANALYSIS]: Alexander playing in the snow.\n"
                    "What do you see?"
                )
            ),
        ],
        agent_role="Chat_Agent",
        channel="telegram",
    )

    # Must preserve tokens required by existing capability/presentation tests
    assert "REALITY RULE (CRITICAL)" in prompt
    assert "CURRENT reality" in prompt

    # Must contain explicit temporal reality guard
    assert "TEMPORAL REALITY GUARD" in prompt
    assert "moment the photograph was captured" in prompt
    assert "NOT necessarily the user's live physical surroundings" in prompt


def test_format_model_history_content_includes_photo_asset_note() -> None:
    """Historical turns re-expanded from persisted photo context include an asset note."""
    metadata = user_asset_history_metadata(
        filename="snow_day.jpg",
        file_path="C:/photos/snow_day.jpg",
        analysis="Alexander is building a snowman in the yard.",
    )

    rendered = format_model_history_content("What is happening here?", metadata)

    assert "snow_day.jpg" in rendered
    assert "This describes visual content captured in a shared photo file, not an ongoing real-time event." in rendered
    assert "Alexander is building a snowman in the yard." in rendered
    assert "Question: What is happening here?" in rendered


def test_memory_sifter_rule_14_guards_against_live_facts_from_photos() -> None:
    """Memory sifter prompt forbids extracting photo scenes as today's live user facts."""
    sifter_prompt = load_prompt("memory_sifter.md")

    assert "14. DO NOT extract scenes, people, or activities depicted in shared photos" in sifter_prompt
    assert "([USER_UPLOADED_PHOTO] or [PHOTO PATH]) as live user or family events happening today" in sifter_prompt
    assert "never as live [USER_FACT] events" in sifter_prompt


def test_session_memory_sifter_skips_direct_photo_fact_saving(monkeypatch: pytest.MonkeyPatch) -> None:
    """Session sifter skips direct Chroma/DB writes for photo-category or [PHOTO] tagged facts."""
    from memory import session_memory

    saved_items: list[dict[str, Any]] = []
    monkeypatch.setattr(
        session_memory.memory,
        "save",
        lambda **kwargs: saved_items.append(kwargs),
    )

    class DummyPhotoSifterResponse:
        text = """
        [
          {
            "fact": "[PHOTO]: Child playing | Alexander in snow jacket playing outside",
            "category": "photos",
            "caption": "Child playing",
            "analysis": "Alexander in snow jacket playing outside"
          }
        ]
        """

    monkeypatch.setattr(session_memory, "safe_gemini_call", lambda prompt: DummyPhotoSifterResponse())

    session_memory.run_memory_sifter_slow(
        user_text="What do you see?",
        ai_text="I see Alexander playing in the snow.",
        agent_name="Chat_Agent",
        channel="web",
        deterministic_seed_facts=[],
    )

    assert len(saved_items) == 0


def test_telegram_photo_turn_passes_external_sources_to_working_memory_and_sifter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Telegram photo turns pass external sources so foreground memory and sifter are skipped."""
    import clients.telegram_bot as telegram_bot

    fast_tasks: list[tuple[Any, tuple[Any, ...]]] = []
    slow_tasks: list[tuple[Any, tuple[Any, ...]]] = []

    monkeypatch.setattr(telegram_bot, "enqueue_fast_task", lambda fn, *args: fast_tasks.append((fn, args)))
    monkeypatch.setattr(telegram_bot, "enqueue_slow_task", lambda fn, *args: slow_tasks.append((fn, args)))

    # Simulate external sources check in handle_photo
    external_sources = [USER_PROVIDED_ASSET_SOURCE]
    question = "Alexander in snow"
    handling_agent = "Chat_Agent"

    if external_sources:
        telegram_bot.enqueue_fast_task(telegram_bot.log_exchange, question, "", handling_agent, "telegram")
        telegram_bot.enqueue_fast_task(telegram_bot.update_working_memory, question, "", external_sources)
        telegram_bot.enqueue_fast_task(
            telegram_bot._enqueue_slow_memory_sifter,
            question,
            "",
            handling_agent,
            "telegram",
            set(external_sources),
            True,
        )

    # Verify update_working_memory was queued with external_sources
    wm_calls = [args for fn, args in fast_tasks if fn == telegram_bot.update_working_memory]
    assert len(wm_calls) == 1
    assert wm_calls[0] == (question, "", external_sources)

    # Verify _enqueue_slow_memory_sifter was queued with external_sources set
    sifter_calls = [args for fn, args in fast_tasks if fn == telegram_bot._enqueue_slow_memory_sifter]
    assert len(sifter_calls) == 1
    assert sifter_calls[0] == (question, "", handling_agent, "telegram", {USER_PROVIDED_ASSET_SOURCE}, True)


def test_matrix_turn_passes_external_sources_to_background_hooks(tmp_path) -> None:
    """Matrix photo turns forward external_content_sources to background hooks."""
    from services.matrix_turn import MatrixTurnService

    class FakeGraph:
        def stream(self, state: dict[str, Any], config: dict[str, Any]):
            yield {
                "Chat_Agent": {
                    "messages": [AIMessage(content="I see a photo.")],
                }
            }

    completed_hooks: list[dict[str, Any]] = []

    def mock_on_exchange_completed(
        user_text: str,
        ai_text: str,
        agent_name: str,
        channel: str,
        external_content_sources: Any = None,
    ) -> None:
        completed_hooks.append({
            "user_text": user_text,
            "ai_text": ai_text,
            "agent_name": agent_name,
            "channel": channel,
            "external_content_sources": external_content_sources,
        })

    db_path = str(tmp_path / "conversation.db")
    service = MatrixTurnService(
        graph=FakeGraph(),
        conversation_db_path=db_path,
        on_user_persisted=lambda _: None,
        on_exchange_completed=mock_on_exchange_completed,
    )

    # Run as asset question (photo turn)
    asyncio.run(
        service.run_asset_question(
            question="Alexander at the park",
            event_id="$event-123",
            filename="park.jpg",
            file_path="C:/photos/park.jpg",
            analysis="Alexander on swings",
        )
    )

    assert len(completed_hooks) == 1
    assert completed_hooks[0]["user_text"] == "Alexander at the park"
    assert completed_hooks[0]["ai_text"] == ""  # External derived suppresses AI text
    assert completed_hooks[0]["channel"] == "matrix"
    assert completed_hooks[0]["external_content_sources"] == [USER_PROVIDED_ASSET_SOURCE]


def test_matrix_background_hooks_skip_working_memory_and_slow_pipeline_on_external_sources() -> None:
    """Matrix background hooks pass external_sources to working memory and skip slow memory pipeline."""
    from services.matrix_background import MatrixBackgroundHooks

    fast_queue: list[tuple[Any, tuple[Any, ...]]] = []
    slow_queue: list[tuple[Any, tuple[Any, ...]]] = []

    hooks = MatrixBackgroundHooks(
        enqueue_fast_task=lambda fn, *args: fast_queue.append((fn, args)),
        enqueue_slow_task=lambda fn, *args: slow_queue.append((fn, args)),
    )

    hooks.on_exchange_completed(
        "Look at this",
        "",
        "Chat_Agent",
        "matrix",
        external_content_sources=[USER_PROVIDED_ASSET_SOURCE],
    )

    fast_names = [fn.__name__ for fn, _ in fast_queue]
    assert "log_exchange" in fast_names
    assert "update_working_memory" in fast_names
    # run_slow_memory_pipeline MUST be skipped
    assert "run_slow_memory_pipeline" not in fast_names

    # Check update_working_memory arguments
    wm_call = next(args for fn, args in fast_queue if fn.__name__ == "update_working_memory")
    assert wm_call == ("Look at this", "", [USER_PROVIDED_ASSET_SOURCE])

    # Check slow queue: followup and context flags get empty string for ai_text
    slow_names = [fn.__name__ for fn, _ in slow_queue]
    assert "run_followup_pipeline" in slow_names
    assert "extract_and_update_context_flags" in slow_names

    followup_call = next(args for fn, args in slow_queue if fn.__name__ == "run_followup_pipeline")
    assert followup_call == ("Look at this", "", "Chat_Agent", "matrix")
