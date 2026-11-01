"""Fail-closed semantic grounding of a local reminder in trusted owner text."""

import json
from datetime import datetime
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject ambiguous duplicate decision keys."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate decision key")
        result[key] = value
    return result


def is_grounded_reminder_request(
    user_text: str, tool_args: dict[str, Any], trusted_context: list[str],
) -> bool:
    """Check a proposed creation without granting authority to any external text.

    Only an unbound model's strict boolean decision can exempt stale-history
    escalation. Failure retains approval; this function never invokes tools.
    """
    if not isinstance(user_text, str) or not user_text.strip() or len(user_text) > 4096:
        return False
    allowed = {"task", "action", "minutes_from_now", "exact_time", "location",
        "match_task", "external_content_sources_json"}
    if not isinstance(tool_args, dict) or set(tool_args) - allowed:
        return False
    if tool_args.get("action", "add") != "add":
        return False
    if tool_args.get("match_task") is not None:
        return False
    if tool_args.get("external_content_sources_json", "") not in ("", "[]"):
        return False
    task = tool_args.get("task")
    if not isinstance(task, str) or not task.strip():
        return False
    if not isinstance(trusted_context, list) or any(not isinstance(t, str) for t in trusted_context):
        return False
    if len(trusted_context) > 6 or sum(map(len, trusted_context)) > 3200:
        return False
    try:
        args_json = json.dumps(tool_args, ensure_ascii=False, allow_nan=False)
        if len(args_json) > 2048:
            return False
        from core.brain import llm, safe_llm_invoke
        from core.i18n import load_prompt

        payload = json.dumps({"latest_owner_request": user_text,
            "earlier_owner_messages": trusted_context, "proposed_reminder": tool_args,
            "local_now": datetime.now().isoformat(timespec="minutes")}, ensure_ascii=False)
        response = safe_llm_invoke(llm, [SystemMessage(content=load_prompt("reminder_request_grounding.md")),
            HumanMessage(content=payload)], retries=1)
        if getattr(response, "tool_calls", None):
            return False
        decision = json.loads(response.content, object_pairs_hook=_unique_object)
        return (isinstance(decision, dict)
            and set(decision) == {"direct_request", "arguments_grounded"}
            and decision["direct_request"] is True
            and decision["arguments_grounded"] is True)
    except Exception:
        return False
