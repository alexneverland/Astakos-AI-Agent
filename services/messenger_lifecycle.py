"""Shared native outcome boundaries for conversational Messenger draft turns."""
from typing import Any, Callable
from langchain_core.messages import AIMessage, SystemMessage
from core.i18n import t
from core.utils import AgentState


def messenger_lifecycle_boundary(state: AgentState, history: list[Any], agent: str, invoke: Callable[[list], Any]) -> tuple[list[Any], dict | None]:
    """Ground draft outcomes in native receipts and route sends through approval."""
    from core.messenger_draft import active_draft_status, clear_draft, capture_draft_write_guard, inactive_draft_message
    from core.utils import clean_message, looks_like_terminal_messenger_draft_result, build_messenger_draft_ready_reply
    from services.messenger_intent import resolve_pending_draft_action
    if history and getattr(history[-1], "type", "") == "tool":
        # Do not run a second synthesis that can repeat the write or invent a send.
        results = []
        has_draft_result = False
        for message in reversed(history):
            if getattr(message, "type", "") != "tool":
                break
            has_draft_result |= getattr(message, "name", "") == "relay_local_payload"
            text = clean_message(message.content)
            results.append(build_messenger_draft_ready_reply([text])
                           if looks_like_terminal_messenger_draft_result(text) else text)
        if has_draft_result:
            return history, {"current_agent": agent, "messages": [AIMessage(content="\n\n".join(reversed(results)))]}
    active, reason, draft = active_draft_status()
    guard = state.get("messenger_draft_write_guard")
    if not guard or guard.get("valid") is not True:
        if draft:
            key = "lifecycle_unavailable" if guard and guard.get("unavailable") else "request_superseded"
            return history, {"current_agent": agent, "messages": [AIMessage(content=t(f"core.messenger_draft.{key}"))]}
        return history, None
    action = resolve_pending_draft_action(history, draft or {}, invoke)
    if action == "none":
        return history, None
    # The classifier may have been in flight while a newer owner turn/draft arrived.
    current_guard = capture_draft_write_guard(history)
    if current_guard != guard:
        return history, {"current_agent": agent, "messages": [AIMessage(content=t("core.messenger_draft.request_superseded"))]}
    if action == "send":
        active, reason, _ = active_draft_status()
        if not active:
            response = AIMessage(content=inactive_draft_message(reason))
        else:
            from uuid import uuid4
            response = AIMessage(content="", tool_calls=[{
                "name": "execute_local_pipeline", "args": {"expected_draft_revision": draft.get("revision", "")}, "id": uuid4().hex,
            }])
        return history, {"current_agent": agent, "messages": [response]}
    if clear_draft(write_guard=guard):
        # Keep processing the entire mixed owner turn; retirement is not a routine skip.
        receipt = SystemMessage(content=(
            "[MESSENGER_DRAFT_RETIRED] The local draft was actually cleared. "
            "Acknowledge this briefly and answer the owner's remaining conversation normally. "
            "This receipt establishes no routine completion, refusal or skip."
        ))
        return [*history[:-1], receipt, history[-1]], None
    return history, {"current_agent": agent, "messages": [AIMessage(content=t("core.messenger_draft.request_superseded"))]}


def require_draft_tool_result(response: AIMessage, reason: str | None, messages: list[Any], model: Any) -> AIMessage:
    """Retry prose-only authorized preparation once with the native tool required."""
    calls = getattr(response, "tool_calls", None) or []
    if not reason or any(call.get("name") == "relay_local_payload" for call in calls):
        return response
    from tools.web import relay_local_payload
    try:
        forced = model.bind_tools([relay_local_payload], tool_choice="relay_local_payload").invoke(messages)
        forced_calls = getattr(forced, "tool_calls", []) or []
        if len(forced_calls) == 1 and forced_calls[0].get("name") == "relay_local_payload":
            return AIMessage(content="", tool_calls=[*calls, *forced_calls])
    except Exception as exc:
        print(f"[Messenger Draft]: required preparation unavailable ({type(exc).__name__}).")
    return AIMessage(content=t("core.messenger_draft.preparation_failed"))
