"""Optional comments for blocked routines, never action or feedback permission."""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
import json
import logging
import random
from typing import Any

from memory.routine_context_clarification import ClarificationStore
from services.external_assistant_delivery import AssistantHistoryError

logger = logging.getLogger(__name__)
NOTE_PROBABILITY = 0.30


def classify_context_note(packet: dict[str, Any]) -> Any:
    """Ask one tool-free model using bounded provenance-wrapped reference data."""
    from langchain_core.messages import HumanMessage, SystemMessage
    from core.brain import llm, safe_llm_invoke
    from core.i18n import load_prompt
    from core.utils import extract_json_from_text, load_agent_prompt
    from core.untrusted_content import format_untrusted_tool_result
    from config import RESPONSE_LANGUAGE, USER_NAME
    from services.routine_context_clarification_scheduler import _question_wording_history

    personality = load_agent_prompt("Chat_Agent").partition("═══ PERSONALITY ═══")[2].partition("═══")[0].strip()
    reference = {**packet, "language": RESPONSE_LANGUAGE, "user_name": USER_NAME,
                 "recent_conversation": _question_wording_history()}
    response = safe_llm_invoke(llm, [
        SystemMessage(content=personality + "\n\n" + load_prompt("routine_context_note.md")),
        HumanMessage(content=format_untrusted_tool_result(
            "blocked routine note reference", json.dumps(reference, ensure_ascii=False, default=str))),
    ])
    content = response.content
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return extract_json_from_text(str(content))


def send_context_note(
    *, packet: dict[str, Any], store: ClarificationStore, now: datetime,
    fresh: Callable[[], bool], deliver: Callable[[str], Any],
    classify: Callable[[dict[str, Any]], Any] | None = None,
    draw: Callable[[], float] | None = None,
    queue_history_repair: Callable[[Callable[[], None]], Any] | None = None,
    budget: Callable[[], bool] = lambda: True,
) -> str:
    """Reserve before chance/inference/send; uncertain attempts remain held.

    The caller supplies canonical eligibility including explicit silence and
    current evidence. This path writes no routine feedback or confirmation.
    """
    try:
        if packet.get("channel") not in {"matrix", "telegram"} or not fresh():
            return "deferred"
        routine = packet["routine"]
        if not store.claim_context_note(routine["id"], datetime.fromisoformat(routine["slot_at"]), now=now):
            return "already_evaluated"
        if (draw or random.random)() >= NOTE_PROBABILITY:
            return "chance_skip"
        result = (classify or classify_context_note)(packet)
        if not isinstance(result, dict) or set(result) != {"message"}:
            return "no_note"
        message = result["message"]
        if not isinstance(message, str) or not message.strip() or len(message) > 500:
            return "no_note"
        if not fresh():
            return "stale"
        if not budget():
            return "rate_limit"
        try:
            receipt = deliver(message.strip())
        except AssistantHistoryError as exc:
            logger.info("Routine note confirmed: channel=%s receipt=%s; history pending",
                        exc.receipt.channel, exc.receipt.external_id)
            if queue_history_repair is not None:
                try:
                    queue_history_repair(exc.repair)
                except Exception:
                    logger.exception("Confirmed routine note history repair could not be queued")
            return "sent_history_pending"
        except Exception:
            logger.exception("Routine note delivery uncertain; reservation retained")
            return "uncertain"
        return "sent" if receipt else "uncertain"
    except Exception:
        logger.exception("Routine note evaluation failed closed")
        return "error"
