import config
from services.gemini import safe_gemini_call
from core.utils import clean_message, extract_json_from_text
from memory.routine_db import set_context_state
from datetime import datetime
from services.routine_reconciler import (
    reconcile_fact_to_routines,
    apply_routine_reconciliation_directives,
)

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

Rules:
- Return ONLY a JSON object.
- Include only flags that are clearly confirmed by the message.
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
AI Answer (recent/current): "{ai_text}"
"""


def extract_and_update_context_flags(user_text: str, ai_text: str = "", channel: str = "telegram"):
    """
    Calls the LLM to extract context flags based on the user's message,
    and directly updates astakos_routines.db context states.
    """
    if not user_text or len(user_text.strip()) < 3:
        return

    if "[VISUAL ANALYSIS]" in user_text.upper():
        print("[ContextExtractor] Skipped visual-analysis payload without explicit live-state text")
        return

    try:
        prompt = _CONTEXT_EXTRACTION_PROMPT.format(
            bot_name=config.BOT_NAME,
            user_name=config.USER_NAME,
            partner_name=config.PARTNER_NAME,
            kid1_name=config.KID1_NAME,
            user_text=user_text,
            ai_text=ai_text,
        )
        response = safe_gemini_call(prompt)
        text = response.text if hasattr(response, "text") else str(response)
        cleaned = clean_message(text).strip()

        payload = extract_json_from_text(cleaned)
        if payload is None:
            return # No valid JSON found
        
        # Validate and apply only known flags
        valid_keys = {
            "user_out_of_home",
            "family_at_home",
            "partner_with_user",
            "kid1_away_from_home",
            "user_at_work",
            "kid1_with_user",
            "kid1_with_partner",
            "partner_at_work",
        }
        valid_shifts = {"morning", "afternoon", "night"}
        valid_partner_work_modes = {"office", "remote"}
        
        # Only update if the payload is a dictionary
        if not isinstance(payload, dict):
            return
            
        # Get current date for expiration of certain daily flags
        # Usually these states reset the next day, so we could set an expires_at to midnight,
        # but for now, we just set them. The existing rules or nightly reset will clear them.
        today_str = datetime.now().strftime("%Y-%m-%d")
            
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
            payload["user_out_of_home"] = False
            payload["user_at_work"] = False

        if payload.get("kid1_with_user") is True and payload.get("partner_with_user") is True:
            payload["kid1_with_partner"] = True

        for key, value in payload.items():
            if key in valid_keys and isinstance(value, bool):
                # Save to database
                str_val = "true" if value else "false"
                set_context_state(key, str_val, expires_at=today_str)
                print(f"[ContextExtractor] Updated {key} = {str_val}")

        if "current_shift" in payload:
            set_context_state("current_shift", payload["current_shift"], expires_at=today_str)
            print(f"[ContextExtractor] Updated current_shift = {payload['current_shift']}")

        if "partner_work_mode" in payload:
            set_context_state(
                "partner_work_mode",
                payload["partner_work_mode"],
                expires_at=today_str,
            )
            print(
                "[ContextExtractor] Updated partner_work_mode = "
                f"{payload['partner_work_mode']}"
            )

        recon = reconcile_fact_to_routines(
            user_text,
            category="family",
            reason="live_message_context",
            now=datetime.now(),
        )

        # Live whereabouts and co-presence belong exclusively to the semantic
        # extractor above.  The reconciler remains responsible for durable
        # routine changes (for example a weekly shift), but must not overwrite
        # a current-state decision through token matching.
        llm_owned_live_state_keys = {
            "user_out_of_home",
            "family_at_home",
            "partner_with_user",
            "kid1_away_from_home",
            "user_at_work",
            "kid1_with_user",
            "kid1_with_partner",
            "partner_at_work",
        }
        directives = []
        for item in recon.get("scored_directives", []):
            if item.get("decision") == "auto_apply":
                directive = item.get("directive")
                if (
                    directive
                    and not (
                        directive.get("kind") == "context_state_set"
                        and directive.get("key") in llm_owned_live_state_keys
                    )
                ):
                    directives.append(directive)

        if directives:
            apply_routine_reconciliation_directives(directives)
            print(
                f"[ContextExtractor] Applied {len(directives)} reconciler directive(s) "
                f"from live message"
            )

    except Exception as exc:
        print(f"[ContextExtractor Error]: {exc!r}")
