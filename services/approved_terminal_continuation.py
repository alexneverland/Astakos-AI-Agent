"""Bounded, tool-free interpretation of an already approved terminal result."""

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

import config
from core.brain import llm, safe_llm_invoke
from core.i18n import load_prompt
from core.untrusted_content import (
    external_content_source_names, format_untrusted_tool_result, is_direct_user_message,
)
from core.utils import clean_message, load_agent_prompt

_AGENTS = frozenset({"Git_Agent", "Tech_Agent", "Dev_Agent", "Chat_Agent", "Home_Agent", "Web_Agent", "Mail_Agent"})


def normalize_terminal_context(context: Any) -> dict[str, str] | None:
    """Validate only bounded structured provenance, never natural-language meaning."""
    if not isinstance(context, dict) or set(context) != {"agent", "user_request"}:
        return None
    agent, request = context["agent"], context["user_request"]
    if not isinstance(agent, str) or agent not in _AGENTS or not isinstance(request, str) or not request.strip():
        return None
    return {"agent": agent, "user_request": request[:4096]}


def capture_terminal_context(state: dict) -> dict[str, str] | None:
    """Capture the latest actual owner request, excluding asset/synthetic turns."""
    for message in reversed(state.get("messages", [])):
        if is_direct_user_message(message):
            if external_content_source_names(getattr(message, "additional_kwargs", {})):
                return None
            return normalize_terminal_context({"agent": state.get("current_agent"),
                "user_request": getattr(message, "content", None)})
    return None


def analyze_approved_terminal_result(context: Any, output: Any) -> str | None:
    """Answer with the original agent's instructions, without binding any tools.

    No graph, executor or approval path is entered here. Failure preserves the
    caller's original output; a provider-generated tool call is never executed.
    """
    validated = normalize_terminal_context(context)
    if validated is None or not isinstance(output, str) or not output.strip():
        return None
    try:
        prompt = load_prompt("approved_terminal_result.md").format(
            agent=validated["agent"], language=config.RESPONSE_LANGUAGE,
            agent_prompt=load_agent_prompt(validated["agent"]).replace("{BASE_DIR}", config.BASE_DIR),
        )
        response = safe_llm_invoke(llm, [SystemMessage(content=prompt),
            HumanMessage(content=format_untrusted_tool_result("recorded original user request", validated["user_request"])),
            HumanMessage(content=format_untrusted_tool_result("run_terminal_command", output[:10000]))])
        if getattr(response, "tool_calls", None):
            return None
        text = clean_message(getattr(response, "content", ""))
        return text.strip()[:10000] if isinstance(text, str) and text.strip() else None
    except Exception as exc:
        print(f"[Terminal Analysis]: unavailable ({type(exc).__name__}); retaining execution output")
        return None


def approved_terminal_reply(execution: dict) -> str | None:
    """Render only a successful terminal execution, preserving legacy output."""
    if not execution.get("ok") or execution.get("tool") != "run_terminal_command":
        return None
    output = execution.get("result")
    analysis = analyze_approved_terminal_result(execution.get("continuation_context"), output)
    if analysis:
        return analysis
    return output[:10000] if isinstance(output, str) and output.strip() else None


def record_terminal_reply(context: Any, channel: str, text: str, tool_call_id: str = "") -> None:
    """Persist the result in its originating history with terminal provenance."""
    if channel not in {"web", "telegram", "matrix"} or not text:
        return
    from core.untrusted_content import external_content_history_metadata

    validated = normalize_terminal_context(context)
    agent = validated["agent"] if validated else "approval_check"
    metadata = external_content_history_metadata(["run_terminal_command"])
    try:
        if channel == "web":
            from api.server import append_to_chat_history
            append_to_chat_history("assistant", text, agent=agent, metadata=metadata)
        else:
            from hashlib import sha256
            from memory.conversation_history import append_message
            message_id = "terminal-result-" + sha256(tool_call_id.encode()).hexdigest() if tool_call_id else None
            append_message(role="assistant", content=text, channel=channel, agent=agent,
                           metadata=metadata, message_id=message_id)
    except Exception as exc:
        print(f"[Terminal Analysis]: Result history failed ({type(exc).__name__})")
