import json
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

_CONTEXT_EXTRACTION_PROMPT = """
You are Astakos, an AI assistant. The user (Lazaros) sends you a message.
You need to understand from the context if any of the following states (context flags) are changing.

Available flags:
1. "user_out_of_home": (boolean) The user is out of the house now (e.g., walk, shopping, trip, swimming).
2. "family_at_home": (boolean) The family is at home now.
3. "sofia_with_user": (boolean) Sofia is with the user now.
4. "alexandros_away_from_home": (boolean) Alexandros is away from home without being with the user.
5. "user_at_work": (boolean) The user is at work now.
6. "alexandros_with_user": (boolean) Alexandros is with the user now.
7. "alexandros_with_sofia": (boolean) Alexandros is with Sofia now, without necessarily meaning that the user is also with them.

Rules:
- Return ONLY a JSON object.
- Include only flags that are clearly confirmed by the message.
- If you are not sure enough, do not include the flag at all.
- DO NOT convert future intention into a current state.
- If the user says they will leave in a bit, that they will go somewhere later, or that they are planning to go, this DOES NOT mean they are already out of the house.
- If the user is talking about a draft message, a plan, an idea, or what to write, this DOES NOT necessarily mean that the state is currently true.
- If the user says they are all out together now, then user_out_of_home=true and sofia_with_user=true may apply.
- If the user is at work, then usually user_at_work=true and user_out_of_home=true.

- If the user says they are with Alexandros now, then alexandros_with_user=true may apply.
- If the user says Alexandros is with Sofia now, then alexandros_with_sofia=true may apply.
- If the user says Sofia and Alexandros are out somewhere and they themselves are not with them, then sofia_with_user=false.
- If the user clearly says Alexandros is with Sofia without them, then alexandros_away_from_home=true.
- If the user says they will go to meet them later, this DOES NOT mean they are already with them now.

Example 1:
Message: "Good morning, we started, we are on the road, we are going swimming all together."
Answer:
{{"user_out_of_home": true, "sofia_with_user": true, "family_at_home": false}}

Example 2:
Message: "I arrived at the office, talk to you later."
Answer:
{{"user_at_work": true, "user_out_of_home": true, "sofia_with_user": false}}

Example 3:
Message: "In about 15 minutes we are leaving for the park."
Answer:
{{}}

Example 4:
Message: "We are all together at the beach now."
Answer:
{{"user_out_of_home": true, "sofia_with_user": true, "family_at_home": false}}

Example 5:
Message: "I am at home, Sofia and Alexandros are at the park."
Answer:
{{"user_out_of_home": false, "sofia_with_user": false, "alexandros_with_sofia": true, "alexandros_away_from_home": true}}

Example 6:
Message: "We are going to the park now with Alexandros."
Answer:
{{"user_out_of_home": true, "alexandros_with_user": true, "alexandros_away_from_home": false}}

User Message: "{user_text}"
AI Answer (recent/current): "{ai_text}"
"""


def _looks_like_future_departure(text: str) -> bool:
    t = clean_message(text or "").strip().lower()
    future_markers = (
        "σε λιγο",
        "σε λίγο",
        "σε κανα",
        "σε κάνα",
        "σε λιγα λεπτα",
        "σε λίγα λεπτά",
        "σε 10 λεπτα",
        "σε 10 λεπτά",
        "σε 15 λεπτα",
        "σε 15 λεπτά",
        "σε μιση ωρα",
        "σε μισή ώρα",
        "σε μια ωρα",
        "σε μία ώρα",
        "θα παω",
        "θα πάω",
        "θα παμε",
        "θα πάμε",
        "θα φυγω",
        "θα φύγω",
        "θα φυγουμε",
        "θα φύγουμε",
        "φευγουμε σε",
        "φεύγουμε σε",
    )
    return any(marker in t for marker in future_markers)

def _normalize_live_text(text: str) -> str:
    return clean_message(text or "").strip().lower()


def _has_park_live_presence(text: str) -> bool:
    t = _normalize_live_text(text)
    park_tokens = (
        "στο παρκο",
        "στο πάρκο",
        "παρκο",
        "πάρκο",
        "παιδικη χαρα",
        "παιδική χαρά",
        "κουνιες",
        "κούνιες",
    )
    live_tokens = (
        "τωρα",
        "τώρα",
        "ειμαστε",
        "είμαστε",
        "καθομαστε",
        "καθόμαστε",
        "κατσαμε",
        "κάτσαμε",
        "θα κατσουμε",
        "θα κάτσουμε",
        "ακομα",
        "ακόμα",
        "εδω",
        "εδώ",
    )
    return any(p in t for p in park_tokens) and any(l in t for l in live_tokens)


def _looks_like_found_them_reply(text: str) -> bool:
    t = _normalize_live_text(text)
    markers = (
        "τους βρηκα",
        "τους βρήκα",
        "πηγα και τους βρηκα",
        "πήγα και τους βρήκα",
        "τωρα στο παρκο και τους βρηκα",
        "τώρα στο πάρκο και τους βρήκα",
    )
    return any(m in t for m in markers)


def _looks_like_everyone_together(text: str) -> bool:
    t = _normalize_live_text(text)
    markers = (
        "ολοι μαζι",
        "όλοι μαζί",
        "ειμαστε ολοι μαζι",
        "είμαστε όλοι μαζί",
        "μαζι ολοι",
        "μαζί όλοι",
    )
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
            "sofia_with_user",
            "alexandros_away_from_home",
            "user_at_work",
            "alexandros_with_user",
            "alexandros_with_sofia",
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
            for marker in (
                "σπιτι",
                "σπίτι",
                "στο σπιτι",
                "στο σπίτι",
                "ειναι στο σπιτι",
                "είναι στο σπίτι",
            )
        )

        if payload.get("alexandros_with_user") is True:
            payload["alexandros_away_from_home"] = False
            
        if payload.get("family_at_home") is True:
            payload["alexandros_away_from_home"] = False

        if payload.get("alexandros_with_user") is True and payload.get("sofia_with_user") is True:
            payload["alexandros_with_sofia"] = True

        # Context-aware enrichment for short live follow-up replies like:
        # "I found them", "we are all together", "we are still at the park"
        normalized_user = _normalize_live_text(user_text)

        if _has_park_live_presence(user_text):
            payload.setdefault("user_out_of_home", True)

        if _looks_like_everyone_together(user_text):
            payload["user_out_of_home"] = True
            payload["sofia_with_user"] = True
            payload["alexandros_with_user"] = True
            payload["alexandros_with_sofia"] = True
            payload["alexandros_away_from_home"] = False

        elif _looks_like_found_them_reply(user_text) and _has_park_live_presence(user_text):
            payload["user_out_of_home"] = True
            payload["alexandros_with_user"] = True
            payload["alexandros_away_from_home"] = False

            recent_hint = _recent_family_context_hint(channel=channel)
            has_recent_sofia = (
                "σοφια" in normalized_user or "σοφία" in normalized_user
                or "σοφια" in recent_hint or "σοφία" in recent_hint
            )
            has_recent_alexandros = (
                "αλεξανδρ" in normalized_user or "αλέξανδρ" in normalized_user
                or "αλεξανδρ" in recent_hint or "αλέξανδρ" in recent_hint
                or "μικρο" in recent_hint or "μικρό" in recent_hint
            )

            if has_recent_sofia:
                payload["sofia_with_user"] = True

            if has_recent_sofia and has_recent_alexandros:
                payload["alexandros_with_sofia"] = True


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
