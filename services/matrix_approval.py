"""Trusted Matrix reaction handling for pending Astakos approvals."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from core.approval import (
    execute_approved_pending,
    find_pending_by_delivery,
    pop_pending,
)


APPROVE_REACTION_KEYS = frozenset({"👍", "✅"})
REJECT_REACTION_KEYS = frozenset({"👎", "❌"})
_EMOJI_VARIATION_SELECTORS = {"\ufe0e", "\ufe0f"}


def normalize_approval_reaction_key(key: str) -> str:
    """Normalize presentation selectors and skin tones on approval reactions."""
    normalized = "".join(
        char for char in str(key or "") if char not in _EMOJI_VARIATION_SELECTORS
    )
    return "".join(
        char for char in normalized if not 0x1F3FB <= ord(char) <= 0x1F3FF
    )


@dataclass(frozen=True)
class ApprovalReactionResult:
    """Channel-neutral outcome of one trusted approval reaction."""

    status: str
    tool_name: str
    origin_channel: str
    execution_result: Any = None
    error: str | None = None


class MatrixApprovalReactionService:
    """Execute or reject only reactions bound to one pending Matrix prompt."""

    def __init__(
        self,
        *,
        allowed_user_id: str,
        allowed_room_id: str,
        tools_provider: Callable[[], Sequence[Any]],
    ) -> None:
        self._allowed_user_id = self._required_id(allowed_user_id, "allowed_user_id")
        self._allowed_room_id = self._required_id(allowed_room_id, "allowed_room_id")
        self._tools_provider = tools_provider

    @staticmethod
    def _required_id(value: str, field: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError(f"Matrix approval requires {field}")
        return normalized

    def handle_reaction(
        self,
        *,
        room_id: str,
        sender_id: str,
        encrypted: bool,
        reacts_to: str,
        key: str,
    ) -> ApprovalReactionResult | None:
        """Handle a reaction in the encrypted room from the allowed Matrix user.

        ``encrypted`` describes the room, not the reaction event: Element may
        send m.reaction in cleartext even when room messages use E2EE.
        """
        if encrypted is not True:
            return None
        if str(room_id or "") != self._allowed_room_id:
            return None
        if str(sender_id or "") != self._allowed_user_id:
            return None
        normalized_key = normalize_approval_reaction_key(key)
        if normalized_key not in APPROVE_REACTION_KEYS | REJECT_REACTION_KEYS:
            return None

        pending = find_pending_by_delivery(
            delivery_channel="matrix",
            external_message_id=str(reacts_to or "").strip(),
        )
        if pending is None:
            return None

        tool_call_id = str(pending["tool_call_id"])
        tool_name = str(pending.get("tool_name") or "")
        origin_channel = str(pending.get("channel") or "matrix")
        if normalized_key in REJECT_REACTION_KEYS:
            popped = pop_pending(tool_call_id)
            if popped is None:
                return None
            return ApprovalReactionResult(
                status="rejected",
                tool_name=tool_name,
                origin_channel=origin_channel,
            )

        execution = execute_approved_pending(tool_call_id, list(self._tools_provider()))
        if execution.get("ok"):
            if tool_name == "execute_local_pipeline":
                from tools.web import messenger_send_result_succeeded

                if not messenger_send_result_succeeded(execution.get("result")):
                    return ApprovalReactionResult(
                        status="failed",
                        tool_name=tool_name,
                        origin_channel=origin_channel,
                        error=str(execution.get("result") or "Messenger send failed"),
                    )
            return ApprovalReactionResult(
                status="executed",
                tool_name=tool_name,
                origin_channel=origin_channel,
                execution_result=execution.get("result"),
            )
        return ApprovalReactionResult(
            status=str(execution.get("status") or "failed"),
            tool_name=tool_name,
            origin_channel=origin_channel,
            error=str(execution.get("error") or "approval execution failed"),
        )
