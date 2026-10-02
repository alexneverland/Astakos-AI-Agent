"""Semantic, fail-closed behavioral context for ordinary cross-channel chat."""
from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date
import json
import logging
from pathlib import Path
from typing import Any

from core.untrusted_content import (
    external_content_source_names, format_untrusted_tool_result, is_direct_user_message,
    has_untrusted_result_in_active_history, UNTRUSTED_EXTERNAL_TOOL_RESULT_MARKER,
)
from memory.behavioral_conversation_preferences import PreferenceStore
from services.behavioral_conversation_evidence import load_behavioral_evidence

_logger = logging.getLogger(__name__)
_PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
_UNAVAILABLE = (
    "\n[BEHAVIORAL PREFERENCE STATUS]\nOptional commentary unavailable. "
    "Do not add behavioral-pattern commentary from memory on this turn. "
    "Do not claim behavioral preferences were saved or changed.\n"
)


def _classify(payload: dict[str, Any]) -> Any:
    """Use the existing tool-free model; persisted data never becomes instructions."""
    from langchain_core.messages import HumanMessage, SystemMessage
    from core.brain import llm, safe_llm_invoke
    from core.utils import extract_json_from_text

    response = safe_llm_invoke(llm, [
        SystemMessage(content=(_PROMPTS / "behavioral_reply_policy.md").read_text(encoding="utf-8")),
        HumanMessage(content=format_untrusted_tool_result(
            "behavioral decision data", json.dumps(payload, ensure_ascii=False),
        )),
    ])
    content = getattr(response, "content", "")
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return extract_json_from_text(str(content))


def _valid_decision(raw: Any, evidence: list[dict], prefs: list[dict]) -> bool:
    """Validate structure and identities, not natural-language meaning."""
    keys = {"selected_index", "blocked", "recently_discussed", "suppress", "allow_ids", "preference_confidence"}
    if not isinstance(raw, dict) or set(raw) != keys:
        return False
    index, scope, allowed = raw["selected_index"], raw["suppress"], raw["allow_ids"]
    if index is not None and (type(index) is not int or not 0 <= index < len(evidence)):
        return False
    if type(raw["blocked"]) is not bool or type(raw["recently_discussed"]) is not bool:
        return False
    if scope is not None and (not isinstance(scope, str) or not scope.strip() or len(scope) > 500):
        return False
    if not isinstance(allowed, list) or any(not isinstance(item, str) for item in allowed):
        return False
    if not set(allowed) <= {pref["id"] for pref in prefs}:
        return False
    confidence = raw["preference_confidence"]
    return type(confidence) in (int, float) and 0 <= confidence <= 1


def _preference_context(prefs: list[dict[str, str]]) -> str:
    """Keep durable scopes visible to the final reply, not only the selector."""
    if not prefs:
        return ""
    instruction = (_PROMPTS / "behavioral_reply_preferences.md").read_text(encoding="utf-8")
    data = format_untrusted_tool_result("saved commentary scopes", json.dumps(prefs, ensure_ascii=False))
    return "\n" + instruction + "\n" + data + "\n"


def prepare_behavioral_reply_context(
    history: Sequence[Any], *, channel: str | None, shared_recent: str = "",
    today: date | None = None, store: PreferenceStore | None = None,
    evidence_loader: Callable[..., list[dict[str, Any]]] = load_behavioral_evidence,
    classify: Callable[[dict[str, Any]], Any] = _classify,
) -> str:
    """Select dated evidence or persist explicit preferences without sending.

    Only a current direct user chat can change preferences. Tool continuations,
    synthetic turns and externally derived current messages are excluded.
    Re-read preference state after slow classification before exposing evidence.
    """
    if channel not in {"web", "telegram", "matrix"} or not history:
        return ""
    latest = history[-1]
    if not is_direct_user_message(latest) or external_content_source_names(getattr(latest, "additional_kwargs", {})):
        return ""
    if has_untrusted_result_in_active_history(history) or UNTRUSTED_EXTERNAL_TOOL_RESULT_MARKER in shared_recent:
        return _UNAVAILABLE
    text = getattr(latest, "content", "")
    if not isinstance(text, str) or not text.strip():
        return ""
    if len(text) > 4000:
        return _UNAVAILABLE  # Never interpret a truncated preference instruction.
    try:
        if store is None:
            from config import BASE_DIR
            store = PreferenceStore(Path(BASE_DIR) / "behavioral_conversation_preferences.json")
        prefs = store.load()
        evidence = evidence_loader(today=today or date.today(), window_days=30)
        payload = {
            "current_user": text[:4000], "preferences": prefs, "evidence": evidence,
            "recent_history": [
                {"role": getattr(message, "type", ""), "text": str(getattr(message, "content", ""))[:1000]}
                for message in history[-7:-1]
            ],
            "shared_recent_history": shared_recent[-6000:],
        }
        raw = classify(payload)
        if not _valid_decision(raw, evidence, prefs):
            return _UNAVAILABLE
        change = raw["suppress"] is not None or bool(raw["allow_ids"])
        if change:
            if raw["preference_confidence"] < 0.9:
                return _UNAVAILABLE
            updated = store.update(prefs, suppress=raw["suppress"], allow_ids=raw["allow_ids"])
            if updated is None:
                return _UNAVAILABLE
            return _preference_context(updated) + "\n[BEHAVIORAL PREFERENCE STATUS]\nThe explicit commentary preference was saved. Acknowledge naturally; no pattern comment this turn.\n"
        if store.load() != prefs:
            return _UNAVAILABLE
        index = raw["selected_index"]
        if index is None or raw["blocked"] or raw["recently_discussed"]:
            return _preference_context(prefs)
        instruction = (_PROMPTS / "behavioral_reply_context.md").read_text(encoding="utf-8")
        packet = format_untrusted_tool_result("behavioral observations", json.dumps(evidence[index], ensure_ascii=False))
        return _preference_context(prefs) + "\n" + instruction + "\n" + packet + "\n"
    except Exception as exc:
        _logger.warning("Behavioral reply context unavailable (%s)", type(exc).__name__)
        return _UNAVAILABLE
