import config
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from services.gemini import safe_gemini_call
from core.utils import clean_message, extract_json_from_text
from core.untrusted_content import external_content_source_names, format_untrusted_tool_result
from memory.conversation_history import load_recent_state_messages, load_daily_state_messages, get_max_rowid
from memory.routine_db import get_context_state, set_context_states_if_unchanged
from datetime import datetime
from zoneinfo import ZoneInfo
from services.routine_reconciler import (
    infer_routine_reconciliation_directives,
    apply_routine_reconciliation_directives,
)

_CONTEXT_BOOLEAN_FLAGS = {
    "user_out_of_home", "family_at_home", "partner_with_user",
    "kid1_away_from_home", "user_at_work", "kid1_with_user",
    "kid1_with_partner", "partner_at_work", "quiet_hours",
}
_CONTEXT_ENUM_VALUES = {
    "current_shift": {"morning", "afternoon", "night"},
    "partner_work_mode": {"office", "remote"},
    "kid1_absence_scope": {"extended", "temporary", "home"},
}

_CONTEXT_EXTRACTION_PROMPT = """
You are {bot_name}, an AI assistant. The user ({user_name}) sends you a message.
You need to understand from the context if any of the following states (context flags) are changing.

Available flags:
1. "user_out_of_home": (boolean) The user is out of the house now (e.g., walk, shopping, trip, swimming).
2. "family_at_home": (boolean) The family is at home now.
3. "partner_with_user": (boolean) The partner is with the user now.
4. "kid1_away_from_home": (boolean) The kid1 is away from home without being with the user.
5. "user_at_work": (boolean) The user is at work now.
6. "kid1_with_user": (boolean) The kid1 is with the user now.
7. "kid1_with_partner": (boolean) The kid1 is with the partner now, without necessarily meaning that the user is also with them.
8. "current_shift": one of "morning", "afternoon", or "night" only when the user directly confirms their active work shift now.
9. "partner_at_work": (boolean) The partner is at work now.
10. "partner_work_mode": "office" or "remote" only when the user directly states that the partner is working at their workplace or remotely/from home.
11. "quiet_hours": (boolean) The user requests quiet or no interruptions now, or clearly says the child is already asleep now. A future bedtime does not activate quiet hours.
12. "kid1_absence_scope": "extended" when the child is explicitly away from the family for a stay/overnight period and cannot take part in their routines; "temporary" for school or a short outing; "home" when the child has returned or is with the user. Do not infer an extended absence merely from being outside the house. Omit this key when the new message does not establish a different absence scope.

Rules:
- Return ONLY a JSON object.
- Include only flags that are clearly confirmed by the message.
- Recent timestamped user messages across all channels are supplied to resolve
  unambiguous pronoun or reference in the current message. They are not current
  state by themselves: never carry a previous location or relationship forward
  unless the current message clearly says it still applies or changed.
- Interpret completed transitions chronologically using the current report and
  the timed history. Separate past movement, present whereabouts and future
  intentions. A completed departure changes presence, not arrival at a destination.
  Habit or a typical schedule alone never proves current location. Omit flags
  when the current statement and its reference do not establish a state clearly.
- If you are not sure enough, do not include the flag at all.
- DO NOT deduce unstated whereabouts. For example, if the user says the kids are alone, DO NOT deduce that the partner is with the user. Only update states explicitly stated.
- DO NOT convert future intention into a current state.
- If the user says they will leave in a bit, that they will go somewhere later, or that they are planning to go, this DOES NOT mean they are already out of the house.
- Preparing, eating, drinking coffee, or getting ready in order to leave for work means the user is still at their current location until they explicitly say they left or arrived at work.
- If the user is talking about a draft message, a plan, an idea, or what to write, this DOES NOT necessarily mean that the state is currently true.
- If the user says they are all out together now, then user_out_of_home=true and partner_with_user=true may apply.
- If the user is at work, then usually user_at_work=true and user_out_of_home=true.
- If the user directly confirms they are at work now, their active shift may be current_shift="morning", current_shift="afternoon", or current_shift="night". Do not infer a shift from a routine name, a future plan, or a past shift.
- An active work statement supersedes older co-presence: do not leave partner_with_user=true or kid1_with_user=true unless the user explicitly says they are also at work with the user.
- If the user directly says the partner is at work now, set partner_at_work=true, partner_with_user=false, kid1_with_partner=false, and family_at_home=false. If the user says the partner is not at work, set only partner_at_work=false; do not assume that the partner is home or with the user.
- Treat a clear, current statement that the whole household is home as family_at_home=true. The user's own presence at home alone does not establish anyone else's location.

- If the user says they are with {kid1_name} now, then kid1_with_user=true may apply.
- If the user says {kid1_name} is with {partner_name} now, then kid1_with_partner=true may apply.
- If the user says {partner_name} and {kid1_name} are out somewhere and they themselves are not with them, then partner_with_user=false.
- If the user clearly says {kid1_name} is with {partner_name} without them, then kid1_away_from_home=true.
- If the user says they will go to meet them later, this DOES NOT mean they are already with them now.
- If the user says they returned home, or are engaged in non-work activities (e.g., shopping, playing with kids, cooking, park), then they are definitely NOT at work, so user_at_work=false.
- If the message contains [VISUAL ANALYSIS] or describes a photo, DO NOT use the contents of the photo to deduce current location or context states. Photos can be from the past or different locations. Unless the user explicitly writes text indicating their current state (e.g. "we are here now"), ignore the photo and return {{}}.

Example 1:
Message: "Good morning, we started, we are on the road, we are going swimming all together."
Answer:
{{"user_out_of_home": true, "partner_with_user": true, "family_at_home": false}}

Example 2:
Message: "I arrived at the office, talk to you later."
Answer:
{{"user_at_work": true, "user_out_of_home": true, "partner_with_user": false}}

Example 3:
Message: "In about 15 minutes we are leaving for the park."
Answer:
{{}}

Example 4:
Message: "We are all together at the beach now."
Answer:
{{"user_out_of_home": true, "partner_with_user": true, "family_at_home": false}}

Example 5:
Message: "I am at home, Partner and Kid1 are at the park."
Answer:
{{"user_out_of_home": false, "partner_with_user": false, "kid1_with_partner": true, "kid1_away_from_home": true}}

Example 6:
Message: "We are going to the park now with Kid1."
Answer:
{{"user_out_of_home": true, "kid1_with_user": true, "kid1_away_from_home": false}}

Example 7:
Message: "I finished work and I am at the supermarket now."
Answer:
{{"user_at_work": false, "user_out_of_home": true}}

Example 8:
Message: "I came back home after shopping and we are playing with the kid."
Answer:
{{"user_out_of_home": false, "user_at_work": false, "kid1_with_user": true}}

Example 9:
Message: "I have the kid here with me, I am having coffee and food before I leave for work. My partner is working today."
Answer:
{{"user_out_of_home": false, "user_at_work": false, "kid1_with_user": true, "partner_with_user": false}}

Example 10:
Message: "I am at work on the afternoon shift."
Answer:
{{"user_at_work": true, "user_out_of_home": true, "partner_with_user": false, "kid1_with_user": false, "current_shift": "afternoon"}}

Example 11:
Message: "The kids are home alone and my partner is at work."
Answer:
{{"partner_at_work": true, "partner_work_mode": "office", "partner_with_user": false, "kid1_with_partner": false, "family_at_home": false}}

User Message: "{user_text}"
Recent shared user context (historical reference, not current-state authority):
{recent_user_context}
AI Answer (recent/current): "{ai_text}"
"""


def _recent_user_context_hint(channel: str, limit: int = 4) -> str:
    """Return a bounded, user-authored context window for pronoun resolution.

    Assistant, tool, and external-content messages are deliberately excluded so
    they cannot alter live-state extraction. The current user message remains
    the sole authority for whether a state is current.
    """
    try:
        entries = load_recent_state_messages(now=datetime.now(ZoneInfo("Europe/Athens")))
    except Exception:
        return "(none)"

    messages = [
        {"at": entry.get("timestamp"), "channel": entry.get("channel"),
         "text": str(entry.get("content") or "").strip()[:500]}
        for entry in entries
        if (
            entry.get("role") == "user"
            and not external_content_source_names(entry.get("metadata"))
        )
    ]
    messages = [message for message in messages if message["text"]][-limit:]
    if not messages:
        return "(none)"
    return format_untrusted_tool_result("shared owner history reference",
                                       json.dumps(messages, ensure_ascii=False))


@dataclass(frozen=True)
class ContextExtractionResult:
    """Confirmed canonical writes, not an inferred acknowledgement of success."""

    relation: str = "uncertain"
    applied_flags: frozenset[str] = frozenset()
    continue_conversation: bool = False


def extract_and_update_context_flags(
    user_text: str, ai_text: str = "", channel: str = "telegram", *,
    clarification_context: dict | None = None,
    clarification_still_current: Callable[[], bool] | None = None,
    clarification_commit: Callable[[Callable[[], frozenset[str] | None]], frozenset[str] | None] | None = None,
    now: datetime | None = None,
    conversation_db_path: str | None = None,
    daily_resolution_flags: tuple[str, ...] | None = None,
) -> ContextExtractionResult | None:
    """
    Calls the LLM to extract context flags based on the user's message,
    and directly updates astakos_routines.db context states.
    """
    clarification = clarification_context is not None
    continue_conversation = False
    empty_result = ContextExtractionResult() if clarification else None
    if not user_text or (not clarification and len(user_text.strip()) < 3):
        return empty_result

    if "[VISUAL ANALYSIS]" in user_text.upper():
        print("[ContextExtractor] Skipped visual-analysis payload without explicit live-state text")
        return empty_result

    try:
        current = now or datetime.now(ZoneInfo("Europe/Athens"))
        history_options = {"db_path": conversation_db_path or config.CONVERSATION_DB_FILE}
        source_version = get_max_rowid(**history_options)
        try:
            daily_rows = load_daily_state_messages(now=current, **history_options)
        except (ValueError, OSError):
            if daily_resolution_flags is not None:
                return None
            # A bounded view failure must not disable an explicit current report.
            # The missing day reference is never permission to infer an old plan.
            daily_rows = []
        expected = {key: get_context_state(key) for key in
                    _CONTEXT_BOOLEAN_FLAGS | set(_CONTEXT_ENUM_VALUES) | {"kid1_away_reason"}}
        prompt = _CONTEXT_EXTRACTION_PROMPT.format(
            bot_name=config.BOT_NAME,
            user_name=config.USER_NAME,
            partner_name=config.PARTNER_NAME,
            kid1_name=config.KID1_NAME,
            user_text=user_text,
            recent_user_context=_recent_user_context_hint(channel),
            ai_text=ai_text,
        )
        prompt += "\n" + (Path(__file__).resolve().parents[1] / "prompts" /
                            "daily_context_reference.md").read_text(encoding="utf-8")
        prompt += "\n" + format_untrusted_tool_result("daily owner context reference", json.dumps({
            "now": current.isoformat(),
            "sources": [{"rowid": row["rowid"], "at": row["timestamp"],
                         "channel": row["channel"], "text": row["content"]} for row in daily_rows],
            "stored_context": expected,
        }, ensure_ascii=False))
        if daily_resolution_flags is not None:
            from services.routine_context_evidence import VOLATILE_FLAGS
            if (clarification or not daily_resolution_flags
                    or not set(daily_resolution_flags) <= set(VOLATILE_FLAGS)):
                return None
            prompt += "\n" + (Path(__file__).resolve().parents[1] / "prompts" /
                                "daily_context_resolution.md").read_text(encoding="utf-8")
            prompt += "\nAllowed flags: " + json.dumps(daily_resolution_flags)
        if clarification:
            from services.routine_context_evidence import VOLATILE_FLAGS

            context = clarification_context
            if (not isinstance(context, dict) or set(context) != {"question", "flags"}
                    or not isinstance(context["question"], str)
                    or not 1 <= len(context["question"].strip()) <= 500
                    or not isinstance(context["flags"], list)
                    or not 1 <= len(context["flags"]) <= 5
                    or any(not isinstance(flag, str) or flag not in VOLATILE_FLAGS
                           for flag in context["flags"])
                    or len(set(context["flags"])) != len(context["flags"])):
                return empty_result
            instructions = (Path(__file__).resolve().parents[1] / "prompts" /
                            "routine_context_answer.md").read_text(encoding="utf-8")
            prompt += "\n" + instructions + "\n" + format_untrusted_tool_result(
                "routine clarification reference",
                json.dumps(context, ensure_ascii=False),
            )
        response = safe_gemini_call(prompt)
        text = response.text if hasattr(response, "text") else str(response)
        cleaned = clean_message(text).strip()

        payload = extract_json_from_text(cleaned)
        if payload is None:
            return empty_result
        if daily_resolution_flags is not None:
            return _commit_daily_resolution(payload, daily_rows, expected,
                allowed=set(daily_resolution_flags), now=current,
                still_current=lambda: (get_max_rowid(**history_options) == source_version
                    and (clarification_still_current is None or clarification_still_current())))
        if clarification:
            if (not isinstance(payload, dict)
                    or set(payload) not in ({"relation", "flags"}, {"relation", "flags", "continue_conversation"})
                    or not isinstance(payload["relation"], str)
                    or payload["relation"] not in {"related", "unrelated", "uncertain", "refused"}
                    or not isinstance(payload["flags"], dict)
                    or type(payload.get("continue_conversation", False)) is not bool):
                return empty_result
            relation = payload["relation"]
            # Missing routing metadata is not evidence of a standalone answer.
            continue_conversation = payload.get("continue_conversation", True)
            if relation != "related":
                return ContextExtractionResult(relation, continue_conversation=continue_conversation)
            explicit_mixed = payload.get("continue_conversation") is True
            payload = payload["flags"]
            allowed = set(context["flags"])
            if explicit_mixed:
                # Additional explicit facts use the existing bounded schema,
                # never arbitrary model-selected state keys.
                allowed |= _CONTEXT_BOOLEAN_FLAGS | set(_CONTEXT_ENUM_VALUES)
            enum_values = _CONTEXT_ENUM_VALUES
            if (not payload or not set(payload) <= allowed
                    or any((type(value) is not str or value not in enum_values[key])
                           if key in enum_values else type(value) is not bool
                           for key, value in payload.items())
                    or (clarification_still_current is not None
                        and not clarification_still_current())):
                return empty_result
        
        # Validate and apply only known flags
        valid_keys = _CONTEXT_BOOLEAN_FLAGS
        valid_shifts = _CONTEXT_ENUM_VALUES["current_shift"]
        valid_partner_work_modes = _CONTEXT_ENUM_VALUES["partner_work_mode"]
        valid_absence_scopes = _CONTEXT_ENUM_VALUES["kid1_absence_scope"]
        
        # Only update if the payload is a dictionary
        if not isinstance(payload, dict):
            return
            
        # Get current date for expiration of certain daily flags
        # Usually these states reset the next day, so we could set an expires_at to midnight,
        # but for now, we just set them. The existing rules or nightly reset will clear them.
        today_str = current.date().isoformat()
            
        current_shift = payload.get("current_shift")
        if current_shift is not None:
            normalized_shift = str(current_shift).strip().lower()
            if normalized_shift in valid_shifts:
                payload["current_shift"] = normalized_shift
            else:
                payload.pop("current_shift", None)

        partner_work_mode = payload.get("partner_work_mode")
        if partner_work_mode is not None:
            normalized_work_mode = str(partner_work_mode).strip().lower()
            if normalized_work_mode in valid_partner_work_modes:
                payload["partner_work_mode"] = normalized_work_mode
            else:
                payload.pop("partner_work_mode", None)

        # Derived consistency rules operate on the LLM's semantic state, rather
        # than attempting to re-interpret user wording with phrase lists.
        if payload.get("user_at_work") is True:
            payload["user_out_of_home"] = True
            payload["family_at_home"] = False
            payload["partner_with_user"] = False
            payload["kid1_with_user"] = False

        if payload.get("partner_at_work") is True:
            if payload.get("partner_work_mode") not in valid_partner_work_modes:
                payload["partner_work_mode"] = "office"
            if payload["partner_work_mode"] == "office":
                payload["family_at_home"] = False
                payload["partner_with_user"] = False
                payload["kid1_with_partner"] = False

        if payload.get("kid1_with_user") is True:
            payload["kid1_away_from_home"] = False
            
        if payload.get("family_at_home") is True and payload.get("user_at_work") is not True:
            payload["kid1_away_from_home"] = False
            payload["kid1_with_user"] = True
            payload["partner_with_user"] = True
            payload["user_out_of_home"] = False
            payload["user_at_work"] = False

        if payload.get("kid1_with_user") is True and payload.get("partner_with_user") is True:
            payload["kid1_with_partner"] = True

        # The routine decision is one persisted state, not a join of two
        # independently updated whereabouts/reason flags.
        if payload.get("kid1_away_from_home") is False:
            payload["kid1_absence_scope"] = "home"
        elif payload.get("kid1_absence_scope") == "extended":
            payload["kid1_away_from_home"] = True
        elif payload.get("kid1_absence_scope") not in valid_absence_scopes:
            payload.pop("kid1_absence_scope", None)

        def persist() -> frozenset[str] | None:
            """Apply the already validated semantic state through canonical writers."""
            if get_max_rowid(**history_options) != source_version:
                return None
            return _persist_context_payload(payload, valid_keys, today_str, expected)

        applied_flags = (
            clarification_commit(persist)
            if clarification and clarification_commit is not None else persist()
        )
        if applied_flags is None:
            # Interpretation owns this reply even if another worker resolved
            # the question or it expired before this worker could commit it.
            return ContextExtractionResult("related", continue_conversation=continue_conversation) if clarification else None

        if clarification:
            # No second reconciler interpretation of a short answer. Existing
            # consistency rules and the canonical writer above remain authoritative.
            return ContextExtractionResult("related", frozenset(applied_flags), continue_conversation)

        reconcile_context_message(user_text)

    except Exception as exc:
        print(f"[ContextExtractor Error]: {exc!r}")
        return empty_result


def reconcile_context_message(user_text: str) -> None:
    """Apply durable routine updates without reinterpreting guarded live flags."""
    try:
        inferred = infer_routine_reconciliation_directives(
            user_text, category="family", reason="live_message_context", now=datetime.now(),
        )
        live_keys = _CONTEXT_BOOLEAN_FLAGS | {"kid1_absence_scope"}
        directives = [item for item in inferred if not (
            item.get("kind") == "context_state_set" and item.get("key") in live_keys)]
        if directives:
            apply_routine_reconciliation_directives(directives)
            print(f"[ContextExtractor] Applied {len(directives)} reconciler directive(s) from live message")
    except Exception as exc:
        print(f"[ContextReconciler Error]: {type(exc).__name__}")


def _commit_daily_resolution(
    payload: object, rows: list[dict], expected: dict, *, allowed: set[str],
    now: datetime, still_current: Callable[[], bool],
) -> ContextExtractionResult | None:
    """Validate source identity/time, then reuse the canonical conditional writer."""
    from services.routine_context_evidence import STORED_VALIDITY, _recorded_time
    if not isinstance(payload, dict) or set(payload) != {"flags", "event_rowid", "support_rowids"}:
        return None
    flags, event_id, support = payload["flags"], payload["event_rowid"], payload["support_rowids"]
    sources = {row["rowid"]: row for row in rows}
    if (not isinstance(flags, dict) or not flags or not set(flags) <= allowed
            or any(type(value) is not bool for value in flags.values())
            or type(event_id) is not int or event_id not in sources
            or not isinstance(support, list) or not support or len(support) > 12
            or any(type(value) is not int or value not in sources for value in support)
            or len(set(support)) != len(support) or event_id not in support):
        return None
    event_at = datetime.fromisoformat(sources[event_id]["timestamp"])
    if not 0 <= now.timestamp() - event_at.timestamp() < STORED_VALIDITY.total_seconds():
        return None
    # Do not replace newer canonical evidence with an older interpreted event.
    for key in flags:
        previous = expected.get(key)
        if previous:
            previous_at = _recorded_time(previous.get("updated_at"), now)
            if previous_at is None or previous_at.timestamp() >= event_at.timestamp():
                return None
    if not still_current():
        return None
    updates = {key: (str(value).lower(), event_at.date().isoformat()) for key, value in flags.items()}
    if not set_context_states_if_unchanged(updates, expected, recorded_at=event_at):
        return None
    return ContextExtractionResult("related", frozenset(flags))


def resolve_daily_context_before_question(
    flags: tuple[str, ...], *, now: datetime, still_current: Callable[[], bool],
    channel: str, conversation_db_path: str | None = None,
) -> bool:
    """Resolve unknown flags from owner-day sources without replaying conversation."""
    path = conversation_db_path or config.CONVERSATION_DB_FILE
    try:
        rows = load_daily_state_messages(now=now, db_path=path)
        if not rows:
            return False
        result = extract_and_update_context_flags(rows[-1]["content"], channel=channel,
            now=now, conversation_db_path=path, daily_resolution_flags=flags,
            clarification_still_current=still_current)
        return isinstance(result, ContextExtractionResult) and bool(result.applied_flags)
    except Exception:
        return False


def _persist_context_payload(
    payload: dict, valid_keys: set[str], today: str, expected: dict[str, dict | None],
) -> frozenset[str] | None:
    """Preserve the shared flag-writing path for ordinary and clarification turns."""
    updates = {}
    for key, value in payload.items():
        if key in valid_keys and isinstance(value, bool):
            str_val = "true" if value else "false"
            updates[key] = (str_val, today)
    if "kid1_absence_scope" in payload:
        expiry = None if payload["kid1_absence_scope"] == "extended" else today
        updates["kid1_absence_scope"] = (payload["kid1_absence_scope"], expiry)
        updates["kid1_away_reason"] = ("", today)
    for key in ("current_shift", "partner_work_mode"):
        if key in payload:
            updates[key] = (payload[key], today)
    if not set_context_states_if_unchanged(updates, expected):
        return None
    for key, (value, _) in updates.items():
        print(f"[ContextExtractor] Updated {key} = {value}")
    return frozenset(set(updates) - {"kid1_away_reason"})
