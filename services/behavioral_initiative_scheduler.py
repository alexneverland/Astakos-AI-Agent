"""Queue a bounded initiative check on the existing selected-channel worker."""
from __future__ import annotations

import json
import logging
from pathlib import Path
import threading
from typing import Any

_lock = threading.Lock()
_queued = False
_logger = logging.getLogger(__name__)


def schedule_behavioral_initiative(enqueue: Any) -> None:
    """Coalesce polls while a slow decision is queued or executing."""
    global _queued
    with _lock:
        if _queued:
            return
        _queued = True
    try:
        enqueue(run_behavioral_initiative_job)
    except Exception:
        _reset_for_tests()
        raise


def _classify(payload: dict[str, Any]) -> Any:
    """Use the existing tool-free model with a provenance-wrapped data packet."""
    from langchain_core.messages import HumanMessage, SystemMessage
    from core.brain import llm, safe_llm_invoke
    from core.untrusted_content import format_untrusted_tool_result
    from core.utils import extract_json_from_text
    prompt = Path(__file__).resolve().parent.parent / "prompts" / "behavioral_initiative.md"
    result = safe_llm_invoke(llm, [SystemMessage(content=prompt.read_text(encoding="utf-8")),
        HumanMessage(content=format_untrusted_tool_result("behavioral initiative data", json.dumps(payload, ensure_ascii=False)))])
    content = getattr(result, "content", "")
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return extract_json_from_text(str(content))


def run_behavioral_initiative_job() -> None:
    """Run only in the active external worker; never start a second scheduler."""
    try:
        from datetime import datetime
        from config import BASE_DIR
        from core.messaging_channel import resolve_external_channel
        from clients import telegram_bot as bot
        from memory.behavioral_conversation_preferences import PreferenceStore
        from memory.behavioral_initiative_state import InitiativeStore
        from memory.conversation_history import append_message, load_messages
        from memory.event_log import has_recent_reminder_delivery
        from services.behavioral_conversation_evidence import load_behavioral_evidence
        from services.behavioral_conversation_initiative import run_initiative
        from services.external_delivery import external_delivery_router as router
        from services.routine_context import build_runtime_routine_context

        def unavailable() -> bool:
            """Reuse owner quiet/mute state and stop/inactive-process gates."""
            return (bot.shutdown_event.is_set() or bot._external_background_runtime_channel != resolve_external_channel()
                    or bot.is_quiet_hours() or bot.is_proactive_muted()
                    or has_recent_reminder_delivery(datetime.now()))

        def send(channel: str, text: str, identity: str) -> Any:
            """Use stable Matrix identity; Telegram is single-attempt only."""
            if channel == "matrix":
                return router.send_idempotent_matrix_text(text, transaction_id=identity)
            return router.send_text_to(channel, text)

        run_initiative(store=InitiativeStore(Path(BASE_DIR) / "behavioral_initiative_state.json"),
            preferences=PreferenceStore(Path(BASE_DIR) / "behavioral_conversation_preferences.json"),
            history_loader=lambda: load_messages(limit=20), evidence_loader=load_behavioral_evidence,
            classify=_classify, sender=send, record=append_message, clock=datetime.now,
            selected_channel=resolve_external_channel, unavailable=unavailable,
            budget=bot.can_send_proactive, current_context=build_runtime_routine_context)
    except Exception as exc:
        _logger.warning("Behavioral initiative worker skipped (%s)", type(exc).__name__)
    finally:
        _reset_for_tests()


def _reset_for_tests() -> None:
    """Release process-local debounce; durable delivery state is untouched."""
    global _queued
    with _lock:
        _queued = False
