"""Channel-neutral LLM summarization for extracted user documents."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain_core.messages import HumanMessage

from core.untrusted_content import USER_PROVIDED_ASSET_SOURCE, format_untrusted_tool_result
from core.utils import clean_message


def summarize_document_text(
    *,
    document_text: str,
    file_name: str,
    caption: str,
    channel: str,
    language: str,
    user_name: str,
    missing_context: str,
    missing_caption: str,
    empty_reply: str,
    llm_model: Any | None = None,
    llm_invoke: Callable[..., Any] | None = None,
    context_loader: Callable[[str], str] | None = None,
    prompt_loader: Callable[[str], str] | None = None,
) -> str:
    """Summarize bounded document text while preserving external provenance."""
    if llm_model is None or llm_invoke is None:
        from core.brain import llm, safe_llm_invoke

        llm_model = llm_model or llm
        llm_invoke = llm_invoke or safe_llm_invoke
    if context_loader is None:
        from memory.conversation_history import build_asset_context_text

        context_loader = build_asset_context_text
    if prompt_loader is None:
        from core.i18n import load_prompt

        prompt_loader = load_prompt

    untrusted_text = format_untrusted_tool_result(
        USER_PROVIDED_ASSET_SOURCE,
        str(document_text or ""),
    )
    conversation_context = context_loader(channel)
    prompt = prompt_loader("telegram_bot_document_analysis.md").format(
        language=language,
        user_name=user_name,
        conversation_context=conversation_context or missing_context,
        caption=str(caption or "").strip() or missing_caption,
        file_name=str(file_name or "").strip(),
        doc_text=untrusted_text,
    )
    response = llm_invoke(llm_model, [HumanMessage(content=prompt)])
    content = getattr(response, "content", "") if response is not None else ""
    return clean_message(content).strip() or empty_reply
