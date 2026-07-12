import json
import config
from core import nl_config
from core.i18n import t
from services.gemini import safe_gemini_call
from core.utils import clean_message
from memory.routine_db import set_context_state
from memory.conversation_history import load_recent_context
from datetime import datetime
from services.routine_reconciler import (
    reconcile_fact_to_routines,
    apply_routine_reconciliation_directives,
)

_CONTEXT_EXTRACTION_PROMPT = f"""
You are {config.BOT_NAME}, an AI assistant. The user ({config.USER_NAME}) sends you a message.
You need to understand from the context if any of the following states (context flags) are changing.

Available flags:
1. "user_out_of_home": (boolean) The user is out of the house now (e.g., walk, shopping, trip, swimming).
2. "family_at_home": (boolean) The family is at home now.
3. "partner_with_user": (boolean) The partner is with the user now.
4. "kid1_away_from_home": (boolean) The kid1 is away from home without being with the user.
5. "user_at_work": (boolean) The user is at work now.
6. "kid1_with_user": (boolean) The kid1 is with the user now.
7. "kid1_with_partner": (boolean) The kid1 is with the partner now, without necessarily meaning that the user is also with them.

Rules:
- Return ONLY a JSON object.
- Include only flags that are clearly confirmed by the message.
- If you are not sure enough, do not include the flag at all.
- DO NOT convert future intention into a current state.
- If the user says they will leave in a bit, that they will go somewhere later, or that they are planning to go, this DOES NOT mean they are already out of the house.
- If the user is talking about a draft message, a plan, an idea, or what to write, this DOES NOT necessarily mean that the state is currently true.
- If the user says they are all out together now, then user_out_of_home=true and partner_with_user=true may apply.
- If the user is at work, then usually user_at_work=true and user_out_of_home=true.

- If the user says they are with Alexandros now, then kid1_with_user=true may apply.
- If the user says The kid1 is with the partner now, then kid1_with_partner=true may apply.
- If the user says The partner and kid1 are out somewhere and they themselves are not with them, then partner_with_user=false.
- If the user clearly says Alexandros is with Sofia without them, then kid1_away_from_home=true.
- If the user says they will go to meet them later, this DOES NOT mean they are already with them now.

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

User Message: "{{user_text}}"
AI Answer (recent/current): "{{ai_text}}"
"""


def _looks_like_future_departure(text: str) -> bool:
    t = clean_message(text or "").strip().lower()
    future_markers = nl_config.CE_IN_A_WHILE
    return any(marker in t for marker in future_markers)

def _normalize_live_text(text: str) -> str:
    return clean_message(text or "").strip().lower()


def _has_park_live_presence(text: str) -> bool:
    t = _normalize_live_text(text)
    park_tokens = nl_config.CE_PARK
    live_tokens = nl_config.CE_NOW_SITTING
    return any(p in t for p in park_tokens) and any(l in t for l in live_tokens)


def _looks_like_found_them_reply(text: str) -> bool:
    t = _normalize_live_text(text)
    markers = nl_config.CE_FOUND_THEM
    return any(m in t for m in markers)


def _looks_like_everyone_together(text: str) -> bool:
    t = _normalize_live_text(text)
    markers = nl_config.CE_ALL_TOGETHER
    return any(m in t for m in markers)


def _recent_family_context_hint(channel: str = "telegram") -> str:
    try:
        entries = load_recent_context(limit=6, channel=channel) or []
    except Exception:
        return ""

    parts = []
    for item in entries[-6:]:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or "").strip()
        if content:
            parts.append(content.lower())
    return "\n".join(parts)


def extract_and_update_context_flags(user_text: str, ai_text: str = "", channel: str = "telegram"):
    """
    Calls the LLM to extract context flags based on the user's message,
    and directly updates astakos_routines.db context states.
    """
    if not user_text or len(user_text.strip()) < 3:
        return

    try:
        prompt = _CONTEXT_EXTRACTION_PROMPT.format(
            user_text=user_text,
            ai_text=ai_text,
        )
        response = safe_gemini_call(prompt)
        text = response.text if hasattr(response, "text") else str(response)
        cleaned = clean_message(text).strip()

        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return # No JSON found
            
        payload = json.loads(cleaned[start:end + 1])
        
        # Validate and apply only known flags
        valid_keys = {
            "user_out_of_home",
            "family_at_home",
            "partner_with_user",
            "kid1_away_from_home",
            "user_at_work",
            "kid1_with_user",
            "kid1_with_partner",
        }
        
        # Only update if the payload is a dictionary
        if not isinstance(payload, dict):
            return
            
        # Get current date for expiration of certain daily flags
        # Usually these states reset the next day, so we could set an expires_at to midnight,
        # but for now, we just set them. The existing rules or nightly reset will clear them.
        today_str = datetime.now().strftime("%Y-%m-%d")
            
        # Derived consistency rules for family presence
        normalized_user = _normalize_live_text(user_text)
        has_home_presence = any(
            marker in normalized_user
            for marker in nl_config.CE_HOME
        )

        if payload.get("kid1_with_user") is True:
            payload["kid1_away_from_home"] = False
            
        if payload.get("family_at_home") is True:
            payload["kid1_away_from_home"] = False

        if payload.get("kid1_with_user") is True and payload.get("partner_with_user") is True:
            payload["kid1_with_partner"] = True

        # Context-aware enrichment for short live follow-up replies like:
        # "I found them", "we are all together", "we are still at the park"
        normalized_user = _normalize_live_text(user_text)

        if _has_park_live_presence(user_text):
            payload.setdefault("user_out_of_home", True)

        if _looks_like_everyone_together(user_text):
            payload["user_out_of_home"] = True
            payload["partner_with_user"] = True
            payload["kid1_with_user"] = True
            payload["kid1_with_partner"] = True
            payload["kid1_away_from_home"] = False

        elif _looks_like_found_them_reply(user_text) and _has_park_live_presence(user_text):
            payload["user_out_of_home"] = True
            payload["kid1_with_user"] = True
            payload["kid1_away_from_home"] = False

            recent_hint = _recent_family_context_hint(channel=channel)
            has_recent_sofia = (
                any(w in normalized_user for w in nl_config.CE_PARTNER_NAMES)
                or any(w in recent_hint for w in nl_config.CE_PARTNER_NAMES)
            )
            has_recent_alexandros = (
                any(w in normalized_user for w in nl_config.CE_KID1_NAMES)
                or any(w in recent_hint for w in nl_config.CE_KID1_NAMES)
            )

            if has_recent_sofia:
                payload["partner_with_user"] = True

            if has_recent_sofia and has_recent_alexandros:
                payload["kid1_with_partner"] = True


        for key, value in payload.items():
            if key in valid_keys and isinstance(value, bool):
                if key == "user_out_of_home" and value is True:
                    if _looks_like_future_departure(user_text):
                        print("[ContextExtractor] Ignored user_out_of_home=true due to future departure phrasing")
                        continue
                
                # Save to database
                str_val = "true" if value else "false"
                set_context_state(key, str_val, expires_at=today_str)
                print(f"[ContextExtractor] Updated {key} = {str_val}")

        recon = reconcile_fact_to_routines(
            user_text,
            category="family",
            reason="live_message_context",
            now=datetime.now(),
        )

        directives = []
        for item in recon.get("scored_directives", []):
            if item.get("decision") == "auto_apply":
                directive = item.get("directive")
                if directive:
                    directives.append(directive)

        if directives:
            apply_routine_reconciliation_directives(directives)
            print(
                f"[ContextExtractor] Applied {len(directives)} reconciler directive(s) "
                f"from live message"
            )

    except Exception as exc:
        print(f"[ContextExtractor Error]: {exc!r}")
