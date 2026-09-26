import re

from langchain_core.messages import AIMessage, HumanMessage

from core.i18n import t
from core.utils import clean_message, strip_transport_metadata


def is_capability_proposal_text(content: object) -> bool:
    """Return whether content starts with the canonical localized proposal prefix."""
    proposal_prefix = t("core.approval.capability_proposal_prefix")
    if not isinstance(proposal_prefix, str) or not proposal_prefix.strip():
        return False

    text = strip_transport_metadata(clean_message(content)).casefold()
    return text.startswith(proposal_prefix.strip().casefold())


def is_bug_proposal_text(content: object) -> bool:
    """Recognize a diagnosis offer without granting capability-draft authority."""
    proposal_prefix = t("core.approval.bug_proposal_prefix")
    if not isinstance(proposal_prefix, str) or not proposal_prefix.strip():
        return False
    text = strip_transport_metadata(clean_message(content)).casefold()
    return text.startswith(proposal_prefix.strip().casefold())


def render_capability_followup(kind: str, description: str) -> str | None:
    """Render one localized follow-up without granting bug reports draft authority."""
    if kind == "missing_capability":
        prefix = t("core.approval.capability_proposal_prefix")
        marker = t("core.approval.draft_markers")[0]
        return f"{prefix} {description} {marker}"
    if kind == "existing_behavior_bug":
        return t("core.approval.bug_proposal", description=description)
    return None


def has_pending_capability_proposal(state: dict) -> bool:
    """Return whether the newest user turn immediately follows a capability proposal."""
    messages = state.get("messages", [])
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if getattr(message, "type", "") == "human" or isinstance(message, HumanMessage):
            if index == 0:
                return False
            preceding = messages[index - 1]
            if not (
                getattr(preceding, "type", "") == "ai"
                or isinstance(preceding, AIMessage)
            ):
                return False
            return is_capability_proposal_text(getattr(preceding, "content", ""))
    return False


def has_capability_draft_authorization(state: dict) -> bool:
    """Return whether the newest user message explicitly authorizes a skill draft
    following a canonical capability-gap proposal.

    Authorization requires BOTH:
    1. The nearest preceding message is an AIMessage whose text starts with the
       canonical localized proposal prefix.
    2. The newest message is a HumanMessage that matches a valid draft marker
       with no revocation or condition.
    """
    messages = state.get("messages", [])
    if not messages:
        return False

    # 1. Find the newest HumanMessage and its index
    human_msg_idx = -1
    human_text = ""
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if getattr(msg, "type", "") == "human" or isinstance(msg, HumanMessage):
            human_msg_idx = i
            raw_text = clean_message(getattr(msg, "content", ""))
            human_text = strip_transport_metadata(raw_text).casefold()
            break

    if human_msg_idx < 0:
        return False

    # 2. Check draft markers and revocations
    markers = t("core.approval.draft_markers")
    revoke_markers = t("core.approval.draft_revoke_markers")
    if not isinstance(markers, list) or not isinstance(revoke_markers, list):
        return False

    human_authorized = False
    for marker in markers:
        if not isinstance(marker, str):
            continue
        marker = marker.strip().casefold()
        if human_text == marker:
            human_authorized = True
            break
        if human_text.startswith(marker) and len(human_text) > len(marker):
            suffix = human_text[len(marker):]
            if not (suffix[0].isspace() or suffix[0] in (".", "!", ",", ":", ";")):
                continue
            if any(
                isinstance(revoke_marker, str)
                and re.search(rf"(?<!\w){re.escape(revoke_marker.casefold())}(?!\w)", suffix)
                for revoke_marker in revoke_markers
            ):
                return False  # Failed due to revocation
            human_authorized = True
            break

    if not human_authorized:
        return False

    # 3. Verify the immediately preceding message is an AIMessage proposing a draft
    if human_msg_idx == 0:
        return False

    preceding_msg = messages[human_msg_idx - 1]
    if not (getattr(preceding_msg, "type", "") == "ai" or isinstance(preceding_msg, AIMessage)):
        return False

    if not is_capability_proposal_text(getattr(preceding_msg, "content", "")):
        return False

    return True
