import json


MAX_TOOL_ROUNDS_PER_TURN = 8
MAX_REPEATED_TOOL_CALLS = 3


def _tool_call_signature(tool_call: dict) -> str:
    name = tool_call.get("name", "")
    args = tool_call.get("args", {})
    try:
        args_text = json.dumps(args, ensure_ascii=False, sort_keys=True, default=str)
    except TypeError:
        args_text = repr(args)
    return f"{name}:{args_text}"


def _slice_messages_since_last_human(messages: list) -> list:
    if not messages:
        return []

    last_human_idx = -1
    for i in range(len(messages) - 1, -1, -1):
        if getattr(messages[i], "type", "") == "human":
            last_human_idx = i
            break

    if last_human_idx == -1:
        return messages

    return messages[last_human_idx:]


def _looks_like_factual_update(text: str) -> bool:
    t = str(text or "").lower()
    markers = (
        "ηρθε", "ήρθε", "τωρα", "τώρα", "μηνυμα 112", "112",
        "μολις", "μόλις", "νεο", "νέο", "μου ηρθε", "μου ήρθε",
    )
    return any(m in t for m in markers)


def inspect_tool_loop(
    messages: list,
    max_tool_rounds: int = MAX_TOOL_ROUNDS_PER_TURN,
    max_repeated_calls: int = MAX_REPEATED_TOOL_CALLS,
) -> tuple[bool, str]:
    """Return (allowed, reason) for the latest pending tool call batch."""
    window = _slice_messages_since_last_human(messages or [])

    last_human_text = ""
    for msg in reversed(window):
        if getattr(msg, "type", "") == "human":
            last_human_text = getattr(msg, "content", "")
            break

    if _looks_like_factual_update(last_human_text):
        max_repeated_calls = max(max_repeated_calls, 4)

    tool_rounds = []
    for msg in window:
        tool_calls = getattr(msg, "tool_calls", None)
        if tool_calls:
            tool_rounds.append(list(tool_calls))

    if not tool_rounds:
        return True, ""

    if len(tool_rounds) > max_tool_rounds:
        last_tools = [c.get("name", "unknown") for c in (tool_rounds[-1] if tool_rounds else [])]
        last_tool_str = ", ".join(last_tools) if last_tools else "unknown"
        return (
            False,
            f"Tool loop stopped after {len(tool_rounds)} tool rounds in one turn. Last tool(s): {last_tool_str}.",
        )

    counts: dict[str, int] = {}
    for calls in tool_rounds:
        for call in calls:
            signature = _tool_call_signature(call)
            counts[signature] = counts.get(signature, 0) + 1

    latest_calls = tool_rounds[-1]
    for call in latest_calls:
        signature = _tool_call_signature(call)
        if counts.get(signature, 0) > max_repeated_calls:
            return (
                False,
                f"Repeated tool call blocked: {call.get('name', 'unknown')}.",
            )

    return True, ""
