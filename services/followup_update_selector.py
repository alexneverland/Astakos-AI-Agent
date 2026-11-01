"""One bounded semantic decision for conversational follow-up lifecycle updates."""
from __future__ import annotations

import json
from typing import Any


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject duplicate protocol keys rather than silently choosing one value."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate follow-up decision key")
        result[key] = value
    return result


def select_followup_updates(
    *, user_text: str, candidates: list[dict[str, Any]], recent_context: str = "",
) -> list[dict[str, Any]]:
    """Classify at most twenty records in one model call; invalid batches do nothing."""
    from core.i18n import load_prompt
    from services.gemini import safe_gemini_call
    from memory.pending_followups import _FOLLOWUP_TARGET_WINDOWS

    if not candidates or len(candidates) > 20 or len(user_text) > 4000:
        return []
    try:
        identities = {row["id"]: row["status"] for row in candidates}
        if len(identities) != len(candidates) or any(type(rid) is not int for rid in identities):
            return []
        data = {"user_text": user_text, "recent_context": recent_context[:7000],
                "candidates": [{key: (str(row[key])[:1200] if key in {"subject", "source_user_text"} else row[key])
                                for key in ("id", "topic", "subject", "source_user_text", "status")}
                               for row in candidates]}
        prompt = load_prompt("followup_updates.md").replace("{input_json}", json.dumps(data, ensure_ascii=False))
        response = safe_gemini_call(prompt)
        raw = str(response.text if hasattr(response, "text") else response).strip()
        if raw.startswith("```json") and raw.endswith("```"):
            raw = raw[7:-3].strip()
        payload = json.loads(raw, object_pairs_hook=_unique_object)
        if not isinstance(payload, dict) or set(payload) != {"updates"}:
            return []
        updates = payload["updates"]
        if not isinstance(updates, list) or len(updates) > len(candidates):
            return []
        seen, accepted = set(), []
        for item in updates:
            if not isinstance(item, dict):
                return []
            rid, action, confidence = item.get("id"), item.get("action"), item.get("confidence")
            if type(rid) is not int or rid not in identities or rid in seen:
                return []
            seen.add(rid)
            if (type(confidence) not in (int, float) or not 0 <= confidence <= 1
                    or not isinstance(item.get("reason"), str) or len(item["reason"]) > 400):
                return []
            common = {"id", "action", "confidence", "reason"}
            if action == "resolve":
                if (set(item) != common | {"resolution_type"}
                        or item["resolution_type"] not in ("completed", "canceled", "superseded", "irrelevant")):
                    return []
                if confidence >= 0.55:
                    accepted.append(item)
            elif action == "defer":
                if (set(item) != common | {"delay_minutes", "target_window"}
                        or identities[rid] != "pending" or type(item["delay_minutes"]) is not int
                        or not 0 <= item["delay_minutes"] <= 2880
                        or not isinstance(item["target_window"], str)
                        or item["target_window"] not in _FOLLOWUP_TARGET_WINDOWS):
                    return []
                if confidence >= 0.60:
                    accepted.append(item)
            else:
                return []
        return accepted
    except Exception:
        return []
