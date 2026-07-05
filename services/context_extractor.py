import json
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
Είσαι ο Αστακός, ένα AI assistant. Ο χρήστης (Λάζαρος) σου στέλνει ένα μήνυμα.
Πρέπει να καταλάβεις από τα συμφραζόμενα αν αλλάζει κάποια από τις παρακάτω καταστάσεις (context flags).

Διαθέσιμα flags:
1. "user_out_of_home": (boolean) Ο χρήστης είναι εκτός σπιτιού τώρα (π.χ. βόλτα, ψώνια, ταξίδι, μπάνιο).
2. "family_at_home": (boolean) Η οικογένεια είναι στο σπίτι τώρα.
3. "sofia_with_user": (boolean) Η Σοφία είναι μαζί με τον χρήστη τώρα.
4. "alexandros_away_from_home": (boolean) Ο Αλέξανδρος λείπει από το σπίτι χωρίς να είναι μαζί με τον χρήστη.
5. "user_at_work": (boolean) Ο χρήστης είναι στη δουλειά του τώρα.
6. "alexandros_with_user": (boolean) Ο Αλέξανδρος είναι μαζί με τον χρήστη τώρα.
7. "alexandros_with_sofia": (boolean) Ο Αλέξανδρος είναι μαζί με τη Σοφία τώρα, χωρίς να σημαίνει απαραίτητα ότι είναι και ο χρήστης μαζί.

Κανόνες:
- Επέστρεψε ΜΟΝΟ JSON object.
- Βάλε μόνο flags που επιβεβαιώνονται καθαρά από το μήνυμα.
- Αν δεν είσαι αρκετά σίγουρος, μην βάλεις το flag καθόλου.
- ΜΗΝ μετατρέπεις μελλοντική πρόθεση σε τωρινή κατάσταση.
- Αν ο χρήστης λέει ότι θα φύγει σε λίγο, ότι θα πάνε κάπου αργότερα ή ότι σχεδιάζουν να πάνε, αυτό ΔΕΝ σημαίνει ότι είναι ήδη εκτός σπιτιού.
- Αν ο χρήστης μιλάει για draft μηνύματος, σχέδιο, ιδέα ή τι να γράψει, αυτό ΔΕΝ σημαίνει απαραίτητα ότι η κατάσταση ισχύει τώρα.
- Αν ο χρήστης λέει ότι είναι όλοι μαζί έξω τώρα, τότε μπορεί να ισχύει user_out_of_home=true και sofia_with_user=true.
- Αν ο χρήστης είναι στη δουλειά, τότε συνήθως user_at_work=true και user_out_of_home=true.

- Αν ο χρήστης λέει ότι είναι μαζί με τον Αλέξανδρο τώρα, τότε μπορεί να ισχύει alexandros_with_user=true.
- Αν ο χρήστης λέει ότι ο Αλέξανδρος είναι με τη Σοφία τώρα, τότε μπορεί να ισχύει alexandros_with_sofia=true.
- Αν ο χρήστης λέει ότι η Σοφία με τον Αλέξανδρο είναι κάπου έξω και ο ίδιος δεν είναι μαζί τους, τότε sofia_with_user=false.
- Αν ο χρήστης λέει ξεκάθαρα ότι ο Αλέξανδρος είναι με τη Σοφία χωρίς τον ίδιο, τότε alexandros_away_from_home=true.
- Αν ο χρήστης λέει ότι ο ίδιος θα πάει να τους βρει αργότερα, αυτό ΔΕΝ σημαίνει ότι είναι ήδη μαζί τους τώρα.

Παράδειγμα 1:
Μήνυμα: "Καλημέρα, ξεκινήσαμε, είμαστε στον δρόμο, πάμε για μπάνιο όλοι μαζί."
Απάντηση:
{{"user_out_of_home": true, "sofia_with_user": true, "family_at_home": false}}

Παράδειγμα 2:
Μήνυμα: "Έφτασα γραφείο, τα λέμε."
Απάντηση:
{{"user_at_work": true, "user_out_of_home": true, "sofia_with_user": false}}

Παράδειγμα 3:
Μήνυμα: "Σε κάνα 15 λεπτά φεύγουμε για το πάρκο."
Απάντηση:
{{}}

Παράδειγμα 4:
Μήνυμα: "Είμαστε τώρα όλοι μαζί στην παραλία."
Απάντηση:
{{"user_out_of_home": true, "sofia_with_user": true, "family_at_home": false}}

Παράδειγμα 5:
Μήνυμα: "Εγώ είμαι σπίτι, η Σοφία με τον Αλέξανδρο είναι στο πάρκο."
Απάντηση:
{{"user_out_of_home": false, "sofia_with_user": false, "alexandros_with_sofia": true, "alexandros_away_from_home": true}}

Παράδειγμα 6:
Μήνυμα: "Πάμε τώρα μαζί με τον Αλέξανδρο πάρκο."
Απάντηση:
{{"user_out_of_home": true, "alexandros_with_user": true, "alexandros_away_from_home": false}}

Μήνυμα Χρήστη: "{user_text}"
Απάντηση AI (πρόσφατη/τρέχουσα): "{ai_text}"
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


def _recent_family_context_hint() -> str:
    try:
        entries = load_recent_context(limit=6, channel="telegram") or []
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


def extract_and_update_context_flags(user_text: str, ai_text: str = ""):
    """
    Calls the LLM to extract context flags based on the user's message,
    and directly updates astakos_routines.db context states.
    """
    if not user_text or len(user_text.strip()) < 3:
        return

    prompt = _CONTEXT_EXTRACTION_PROMPT.format(user_text=user_text, ai_text=ai_text)
    
    try:
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
        if payload.get("alexandros_with_user") is True:
            payload["alexandros_away_from_home"] = False

        if payload.get("alexandros_with_sofia") is True and payload.get("alexandros_with_user") is not True:
            payload["alexandros_away_from_home"] = True

        if payload.get("alexandros_with_user") is True and payload.get("sofia_with_user") is True:
            payload["alexandros_with_sofia"] = True

        # Context-aware enrichment for short live follow-up replies like:
        # "τους βρήκα", "είμαστε όλοι μαζί", "είμαστε ακόμα πάρκο"
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

            recent_hint = _recent_family_context_hint()
            has_recent_sofia = (
                "σοφια" in normalized_user or "σοφία" in normalized_user
                or "σοφια" in recent_hint or "σοφία" in recent_hint
            )
            has_recent_alexandros = (
                "αλεξανδρ" in normalized_user
                or "αλεξανδρ" in recent_hint
                or "μικρο" in recent_hint
                or "μικρό" in recent_hint
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
        print(f"[ContextExtractor Error]: {exc}")
