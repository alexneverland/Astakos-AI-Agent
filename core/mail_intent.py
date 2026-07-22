"""Pure helpers for Mail_Agent read-action and result classification."""

from collections.abc import Mapping, Sequence


def select_mail_read_action(
    user_query: str,
    intents: Mapping[str, Sequence[str]],
) -> str | None:
    """Return the safe mail read action implied by the configured intent terms."""
    normalized_query = user_query.lower()
    if not any(term in normalized_query for term in intents.get("read_words", [])):
        return None

    thread_terms = (
        list(intents.get("thread_words", []))
        + list(intents.get("thread_review_words", []))
    )
    return "read_thread" if any(
        term in normalized_query for term in thread_terms
    ) else "read_full"


def is_mail_body_result(
    content: str,
    content_prefix: str,
    thread_prefix: str,
) -> bool:
    """Return whether a tool result contains readable email content."""
    return content.startswith(content_prefix) or content.startswith(thread_prefix)


def is_mail_tool_result(
    content: str,
    content_prefix: str,
    thread_prefix: str,
) -> bool:
    """Return whether a tool result belongs to the mail search/read flow."""
    return content.startswith("ID: ") or is_mail_body_result(
        content,
        content_prefix,
        thread_prefix,
    )
