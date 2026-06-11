# ================================================================
# Project: Astakos AI Agent 🦞
# Developer: Lazaros (Piston-7)
# Description: Modular LLM-agnostic multi-agent framework
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

import os
import json
import threading
from datetime import datetime
import unicodedata
from memory.vector_store import memory
from services.gemini import safe_gemini_call
import re
from core.utils import clean_message
from core.event_bus import bus
from config import PHOTOS_INDEX_FILE, PHOTOS_DIR, SESSIONS_FILE
from memory.conversation_history import (
    append_exchange,
    load_unsummarized_exchanges,
    mark_exchanges_summarized,
)
# ════════════════════════════════════════════════════════════════
# SESSION SUMMARY — "Ημερολόγιο Συνεργάτη"
# ════════════════════════════════════════════════════════════════

SESSION_LOGS: list = []  # Ενιαίο log — όλα τα channels μαζί
AUTO_SESSION_SUMMARY_EXCHANGE_THRESHOLD = 40
_auto_summary_lock = threading.Lock()


def log_exchange(user_text, ai_text, agent: str, channel: str = "web"):
    """Προσθέτει ένα ζεύγος ερώτησης-απάντησης στο session log (per channel)."""
    now = datetime.now()
    safe_user = clean_message(user_text)
    safe_ai = clean_message(ai_text)
    entry = {
        "time": now.strftime("%H:%M"),
        "agent": agent,
        "channel": channel,
        "user": safe_user[:300],
        "ai": safe_ai[:300],
    }
    SESSION_LOGS.append(entry)
    saved_exchange = None
    try:
        saved_exchange = append_exchange(
            user_text=entry["user"],
            ai_text=entry["ai"],
            agent=agent,
            channel=channel,
            timestamp=now,
        )
    except Exception as e:
        print(f"\033[93m[SessionLog]: Shared exchange write failed: {e}\033[0m")
    if saved_exchange:
        _maybe_trigger_auto_session_summary(channel)


def _maybe_trigger_auto_session_summary(channel: str) -> None:
    if is_summarizing:
        return
    try:
        pending = load_unsummarized_exchanges(limit=AUTO_SESSION_SUMMARY_EXCHANGE_THRESHOLD)
    except Exception as e:
        print(f"\033[93m[SessionLog]: Auto-summary check failed: {e}\033[0m")
        return
    if len(pending) < AUTO_SESSION_SUMMARY_EXCHANGE_THRESHOLD:
        return
    if not _auto_summary_lock.acquire(blocking=False):
        return

    def _worker():
        try:
            _run_session_summary(channel=channel)
        finally:
            _auto_summary_lock.release()

    threading.Thread(target=_worker, daemon=True).start()


def load_last_session_hint(channel: str = "web") -> str:
    """Φορτώνει το hint της τελευταίας session."""
    try:
        import os
        if not os.path.exists(SESSIONS_FILE):
            return ""
        with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
            sessions = json.load(f)
        if not sessions:
            return ""
        filtered = sessions
        if not filtered:
            return ""
        last = filtered[-1]
        hint = last.get("next_session_hint", "")
        pending = last.get("pending", [])
        date = last.get("date", "")
        if not hint and not pending:
            return ""
        parts = [f"[Τελευταία session: {date}]"]
        if hint:
            parts.append(f"Να θυμάσαι: {hint}")
        if pending:
            parts.append(f"Εκκρεμή: {', '.join(pending[:3])}")
        return " | ".join(parts)
    except:
        return ""


is_summarizing = False  # Πρέπει να οριστεί έξω από τη συνάρτηση


def _normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFD", str(value or "").lower())
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return " ".join(text.split())


def _extract_event_memory_candidate(
    user_text: str,
    ai_text: str,
    *,
    agent_name: str = "Unknown",
    channel: str = "web",
    now: datetime | None = None,
) -> dict | None:
    """Deterministic safety net for day-specific events the LLM sifter may skip."""
    safe_user = clean_message(user_text)
    safe_ai = clean_message(ai_text)
    combined = f"{safe_user} {safe_ai}".lower()

    family_markers = ("αλέξανδρ", "αλεξανδρ", "σοφία", "σοφια", "μικρό", "μικρο", "μικρός", "μικρος")
    personal_markers = (
        "εγώ",
        "εγω",
        "εμένα",
        "εμενα",
        "μου",
        "δουλειά",
        "δουλεια",
        "συνέντευξη",
        "συνεντευξη",
        "υγεία",
        "υγεια",
        "ύπνο",
        "υπνο",
    )
    event_markers = (
        "ποδόσφ",
        "ποδοσφ",
        "αγών",
        "αγων",
        "τελικό",
        "τελικο",
        "μετάλλ",
        "μεταλλ",
        "πάρκο",
        "παρκο",
        "βόλτα",
        "βολτα",
        "σχολείο",
        "σχολειο",
        "δουλειά",
        "δουλεια",
        "συνέντευξη",
        "συνεντευξη",
        "γιατρό",
        "γιατρο",
        "υγεία",
        "υγεια",
        "ύπνο",
        "υπνο",
        "γυμναστήριο",
        "γυμναστηριο",
        "δουλεύω",
        "δουλευω",
    )
    statement_markers = (
        "είμαστε",
        "ειμαστε",
        "πήγαμε",
        "πηγαμε",
        "πήγε",
        "πηγε",
        "είχα",
        "ειχα",
        "πήρε",
        "πηρε",
        "τέλος",
        "τελος",
        "γυρνάμε",
        "γυρναμε",
        "φεύγουμε",
        "φευγουμε",
        "πάμε",
        "παμε",
        "είναι στη",
        "ειναι στη",
    )

    has_family_marker = any(marker in combined for marker in family_markers)
    has_personal_marker = any(marker in combined for marker in personal_markers)
    if not (has_family_marker or has_personal_marker):
        return None
    if not any(marker in combined for marker in event_markers):
        return None
    if not any(marker in combined for marker in statement_markers):
        return None

    source_text = " ".join(safe_user.split())
    if not source_text:
        return None
    if len(source_text) > 280:
        source_text = source_text[:277].rstrip() + "..."

    ts = now or datetime.now()
    fact = f"[USER_FACT]: Στις {ts.strftime('%Y-%m-%d')}, {source_text}"
    return {
        "memory_type": "fact",
        "fact": fact,
        "category": "family" if has_family_marker else "lazaros",
        "agent_name": agent_name,
        "source": channel,
        "reason": "user_stated",
        "confidence": 0.85,
    }


def _infer_memory_category(text: str) -> str:
    clean = _normalize_text(text)
    if any(marker in clean for marker in ("σοφια", "αλεξανδρ", "μαρια", "μικρο", "παιδι", "γενεθλια", "δωρο")):
        return "family"
    if any(marker in clean for marker in ("mastroapp", "praxis", "astakos", "αστακο", "github", "project", "repo")):
        return "projects"
    if any(marker in clean for marker in ("σπιτι", "κουζινα", "ψυγειο", "αφυγραντηρ", "σκουπα", "ρολοι", "συσκευ")):
        return "home"
    if any(marker in clean for marker in ("κανόνας", "κανονας", "bug", "tool", "prompt", "lesson", "μαθημα")):
        return "lesson"
    return "lazaros"


def _extract_confirmed_memory_candidate(
    user_text: str,
    ai_text: str,
    *,
    agent_name: str = "Unknown",
    channel: str = "web",
    now: datetime | None = None,
) -> dict | None:
    """Capture explicit save/remember confirmations without relying only on the LLM sifter."""
    safe_user = clean_message(user_text)
    safe_ai = clean_message(ai_text)
    combined = _normalize_text(f"{safe_user} {safe_ai}")

    if not any(marker in combined for marker in ("αποθηκευ", "μνημη", "σημειω", "υποψιν", "κρατα")):
        return None
    if any(marker in combined for marker in ("draft", "προσχεδιο", "προσχεδια", "να το στειλω", "να το στείλω")):
        return None

    source_text = " ".join(safe_user.split())
    confirmation_text = " ".join(safe_ai.split())
    if not source_text and not confirmation_text:
        return None
    if len(source_text) < 8 and len(confirmation_text) < 20:
        return None

    # Απαιτείται ρητή επιβεβαίωση από τον AI — ΔΕΝ αποθηκεύουμε raw user text ως fact
    detail = None
    if confirmation_text:
        memory_match = re.search(
            r"(?:αποθηκεύτηκε|αποθηκευτηκε|σημειώθηκε|σημειωθηκε|κρατήθηκε|κρατηθηκε)[^\n]{0,220}",
            confirmation_text,
            flags=re.IGNORECASE,
        )
        if memory_match:
            detail = memory_match.group(0).strip()
    if not detail:
        # Ο AI δεν επιβεβαίωσε ρητά → παράκαμψη, ο LLM sifter θα αποφασίσει
        return None
    if len(detail) > 300:
        detail = detail[:297].rstrip() + "..."

    category = _infer_memory_category(f"{safe_user} {safe_ai}")

    ts = now or datetime.now()
    fact = (
        f"[USER_FACT]: Στις {ts.strftime('%Y-%m-%d')}, ο Λάζαρος ζήτησε ή επιβεβαίωσε "
        f"να αποθηκευτεί στη μνήμη: {detail}"
    )
    return {
        "memory_type": "fact",
        "fact": fact,
        "category": category,
        "agent_name": agent_name,
        "source": channel,
        "reason": "user_stated",
        "confidence": 0.9,
    }


def _run_session_summary(channel: str = "web"):
    """Αρχειοθετεί τη συνεδρία (per channel) με προστασία από διπλοεγγραφές."""
    global is_summarizing, SESSION_LOGS

    try:
        persistent_log = load_unsummarized_exchanges(limit=200)
    except Exception as e:
        print(f"\033[93m[SessionLog]: Shared exchange read failed, using memory log: {e}\033[0m")
        persistent_log = []
    using_persistent_log = bool(persistent_log)
    current_log = persistent_log if using_persistent_log else list(SESSION_LOGS)
    # 1. Ασπίδα: Αν ήδη τρέχει ή αν δεν υπάρχουν μηνύματα, βγες αμέσως
    if is_summarizing or not current_log:
        return

    try:
        is_summarizing = True
        print(f"\n\033[94m[Session/{channel}]: Έναρξη αρχειοθέτησης...\033[0m")
        
        # 2. Αδειάζουμε ΑΜΕΣΩΣ για να μην το ξαναπιάσει άλλος worker
        current_batch = list(current_log)
        SESSION_LOGS.clear()
        channels = sorted({e.get("channel", channel) for e in current_batch})
        summary_channel = channels[0] if len(channels) == 1 else "mixed"

        dialogue_text = "\n".join([
            f"[{e['time']} / {e.get('channel', channel)} / {e['agent']}] Λάζαρος: {e['user']} | Αστακός: {e['ai']}"
            for e in current_batch
        ])

        # 3. Το prompt με αυστηρό format ημερομηνίας (για να ταιριάζει με τα παλιά σου logs)
        summary_prompt = f"""
Ανάλυσε αυτή τη συνομιλία μεταξύ Λάζαρου και Αστακού και συμπλήρωσε ένα JSON αναφοράς.
Απάντησε ΜΟΝΟ με το JSON.

{{
  "date": "{datetime.now().strftime('%Y-%m-%d %H:%M')}",
  "channel": "{summary_channel}",
  "summary": "2-3 προτάσεις τι συζητήθηκε σήμερα",
  "completed": ["λίστα από πράγματα που ολοκληρώθηκαν"],
  "pending": ["λίστα από πράγματα που έμειναν ημιτελή"],
  "next_session_hint": "Τι πρέπει να θυμάται ο Αστακός για την επόμενη φορά",
  "mood": "productive|relaxed|debugging|planning"
}}

[ΣΥΝΟΜΙΛΙΑ]
{dialogue_text}
"""
        response = safe_gemini_call(summary_prompt)
        raw = re.sub(r"```json|```", "", response.text.strip()).strip()

        try:
            summary = json.loads(raw)
        except json.JSONDecodeError:
            # Αν αποτύχει, ξαναβάζουμε τα μηνύματα πίσω για να μην τα χάσουμε
            if not using_persistent_log:
                SESSION_LOGS[:0] = current_batch  # Επαναφορά στην αρχή
                print("\033[91m[Session]: Μη έγκυρο format. Τα μηνύματα επεστράφησαν στο log.\033[0m")
            else:
                print("\033[91m[Session]: Μη έγκυρο format. Τα shared exchanges έμειναν unsummarized.\033[0m")
            return

        # 4. Εμπλουτισμός του κειμένου για τη Vector DB
        session_text = (
            f"[SESSION {summary.get('date', '')}] {summary.get('summary', '')} "
            f"Εκκρεμότητες: {', '.join(summary.get('pending', [])) if summary.get('pending') else 'καμία'}. "
            f"Hint: {summary.get('next_session_hint', '')}"
        )

        # 5. Αποθήκευση (Εδώ ο MemoryManager θα κάνει και το overwrite αν χρειαστεί)
        memory.save(memory_type="session", summary=summary, session_text=session_text)
        if using_persistent_log:
            mark_exchanges_summarized([e["id"] for e in current_batch])
        print(f"\033[92m[Session]: ✅ Αρχειοθετήθηκε επιτυχώς! Mood: {summary.get('mood', '?')}\033[0m")
        bus.emit("session_ended", channel=summary_channel, mood=summary.get("mood", "unknown"), summary=summary.get("summary", ""))

    except Exception as e:
        # Recovery σε περίπτωση σφάλματος
        if not using_persistent_log:
            SESSION_LOGS[:0] = current_batch  # Επαναφορά στην αρχή
        print(f"\033[91m[Session Error]: {e}\033[0m")
    finally:
        is_summarizing = False


# ════════════════════════════════════════════════════════════════
# MEMORY SIFTER — "Αρχειοθέτης"
# ════════════════════════════════════════════════════════════════

def _run_memory_sifter(user_text: str, ai_text: str, agent_name: str = "Unknown", channel: str = "web"):
    """
    Αναλύει τον διάλογο, εξάγει μνήμες για τη ChromaDB 
    και ενημερώνει το JSON index φωτογραφιών με πλήρη ανάλυση.
    """
    MEMORY_CATS = {
        "lazaros":  "Προτιμήσεις, συνήθειες, τρόπος σκέψης, δουλειά του Λάζαρου",
        "family":   "Πληροφορίες για Σοφία, Αλέξανδρο, Μαρία, κατοικίδια",
        "projects": "Mastroapp, PraxisERP, Αστακός, Paletes, Shiftmaster",
        "home":     "Σπίτι, εξοπλισμός, συσκευές, Piston-7",
        "lesson":   "Τεχνικά μαθήματα, λύσεις bugs, κανόνες για τον Αστακό",
        "photos":   "Φωτογραφίες, περιγραφή και paths",
    }

    try:
        deterministic_candidates = (
            _extract_event_memory_candidate(
                user_text,
                ai_text,
                agent_name=agent_name,
                channel=channel,
            ),
            _extract_confirmed_memory_candidate(
                user_text,
                ai_text,
                agent_name=agent_name,
                channel=channel,
            ),
        )
        for candidate in deterministic_candidates:
            if candidate:
                memory.save(**candidate)

        # 1. Προετοιμασία Prompt για το Gemini
        cats_desc = "\n".join([f'  - "{k}": {v}' for k, v in MEMORY_CATS.items()])
        
        # ── Sliding-window context: τελευταία exchanges πριν το τρέχον ──
        # Ο sifter μπαίνει στην ουρά ΠΡΙΝ το log_exchange (βλ. enqueue σειρά
        # στο api/server.py), άρα το SESSION_LOGS εδώ ΔΕΝ περιέχει ακόμα το
        # τρέχον exchange -> καμία διπλοεγγραφή/race condition.
        recent_context_block = ""
        try:
            recent_entries = SESSION_LOGS[-4:]
            if recent_entries:
                ctx_lines = "\n".join(
                    f"Λάζαρος: {e['user']} | Αστακός: {e['ai']}"
                    for e in recent_entries
                )
                recent_context_block = (
                    "\n[ΠΡΟΗΓΟΥΜΕΝΟ ΠΛΑΙΣΙΟ — μόνο για να καταλάβεις τη ροή της "
                    "συζήτησης, ΜΗΝ εξάγεις facts από αυτό το τμήμα]\n"
                    f"{ctx_lines}\n"
                )
        except Exception:
            recent_context_block = ""

        sifter_prompt = f"""
Είσαι ο Αρχειοθέτης του Αστακού. Εξάγεις ΜΟΝΟ αξιόλογες, νέες μνήμες.
Δεν περιμένεις να πει ο χρήστης "αποθήκευσέ το". Κρίνεις μόνος σου από το περιεχόμενο
αν κάτι αξίζει μακροπρόθεσμη μνήμη και σε ποια κατηγορία ανήκει.

Αν ο χρήστης ανέβασε φωτογραφία (σήμα [USER_UPLOADED_PHOTO] ή [PHOTO PATH]), ΠΡΕΠΕΙ να βγάλεις:
- caption: Μια σύντομη λεζάντα στα Ελληνικά (π.χ. 'Ο Αλέξανδρος και το κουνέλι').
- analysis: Μια πλήρη περιγραφή στα Αγγλικά βασισμένη σε όσα είπε ο Αστακός.

ΚΑΤΗΓΟΡΙΕΣ:
{cats_desc}

ΚΑΝΟΝΕΣ:
1. Κάθε μνήμη (fact) ΠΡΕΠΕΙ να ξεκινάει με: [USER_FACT], [CAPABILITY], [LESSON], ή [PHOTO].
2. ΜΟΡΦΗ JSON array: [{{"fact": "[TAG]: ...", "category": "...", "caption": "...", "analysis": "..."}}]
3. Αν δεν υπάρχει νέα πληροφορία → απάντησε ΜΟΝΟ: ΚΕΝΟ.
4. Κράτα ημερομηνία για ημερήσια γεγονότα/οικογενειακές δραστηριότητες (π.χ. αγώνες, πάρκο, σχολείο, δουλειά): "Στις YYYY-MM-DD, ...".
5. Μην αποθηκεύεις απλά drafts/προσχέδια μηνυμάτων ως facts. Αποθήκευσε μόνο πραγματικά γεγονότα, προτιμήσεις, αποφάσεις ή μαθήματα.
6. Αποθήκευσε χωρίς ρητή εντολή όταν ο διάλογος περιέχει:
   - προσωπικό ή οικογενειακό γεγονός/πλάνο/απόφαση (Σοφία, Αλέξανδρος, γενέθλια, δώρα, υγεία, σχολείο, δουλειά),
   - σταθερή προτίμηση, συνήθεια, περιορισμό ή κάτι που θα βοηθήσει μελλοντικά,
   - σημαντικό project/tool/bug/κανόνα που μάθαμε,
   - link ή προϊόν που συνδέεται με μελλοντική αγορά/δώρο/εκκρεμότητα.
7. Διάλεξε category από το νόημα:
   - "family": Σοφία, Αλέξανδρος, οικογένεια, δώρα, γενέθλια, σχολείο, δραστηριότητες.
   - "lazaros": προτιμήσεις, υγεία, δουλειά, συνήθειες, προσωπικοί στόχοι του Λάζαρου.
   - "projects": Mastroapp, Astakos, GitHub, κώδικας, προϊόντα, πελατειακά/project θέματα.
   - "home": σπίτι, συσκευές, ψώνια, εργασίες σπιτιού, αυτοματισμοί.
   - "lesson": κανόνες λειτουργίας, bugs που λύθηκαν, συμπεριφορές που πρέπει να θυμάται ο Αστακός.
   - "photos": φωτογραφίες/αρχεία με περιγραφές.
8. Μην αποθηκεύεις απλές απαντήσεις ευγένειας, προσωρινά drafts, αστεία χωρίς μελλοντική αξία,
   ή πληροφορίες που είναι ήδη γνωστές εκτός αν η νέα εκδοχή είναι πιο πλούσια/ακριβής.
9. ΑΠΑΓΟΡΕΥΕΤΑΙ να αποθηκεύεις ερωτήσεις του χρήστη — αν το μήνυμα είναι ερώτηση (τελειώνει με ";" ή "?"
   ή ξεκινά με "τι", "πώς", "γιατί", "πού", "ποιος", "πόσο", "πότε") → ΚΕΝΟ.
   Ειδικά αν αφορά τη λειτουργία του Αστακού, debug, logs, ή τεχνικές ερωτήσεις για το σύστημα → ΚΕΝΟ.
10. ΑΠΑΓΟΡΕΥΕΤΑΙ να αποθηκεύεις δεδομένα code editing session: diffs, file paths αλλαγών, αποτελέσματα
    terminal commands, grep output, syntax errors, γραμμές κώδικα, αριθμούς γραμμών (π.χ. "Διόρθωσα
    serializers.py γραμμή 408", "edit_project_file επέστρεψε +5 γραμμές") → ΚΕΝΟ.
    ΕΞΑΙΡΕΣΗ: Αποθήκευσε ΜΟΝΟ υψηλού επιπέδου γεγονότα χωρίς τεχνικές λεπτομέρειες:
    π.χ. "Το project mastro_app βρίσκεται στο C:\mastro_app" ή
    "Στο mastro_app υπάρχει πρόβλημα με get_or_create όταν temp_id=None" (lesson/projects).

{recent_context_block}
[ΤΡΕΧΟΥΣΑ ΑΝΤΑΛΛΑΓΗ — εδώ, και ΜΟΝΟ εδώ, εξάγεις νέα facts]
[Ημερομηνία/Ώρα: {datetime.now().strftime('%Y-%m-%d %H:%M')} | Channel: {channel}]
[Agent: {agent_name}]
Λάζαρος: {user_text}
Αστακός: {ai_text}
"""
        response = safe_gemini_call(sifter_prompt)
        raw_text = response.text.strip()
        
        if "ΚΕΝΟ" in raw_text or not raw_text:
            return

        raw_clean = re.sub(r"```json|```", "", raw_text).strip()
        if not raw_clean.startswith("["):
            return
            
        # --- [MASTRO-JSON-SHIELD]: Αυτόματη διόρθωση για ξεχασμένα κόμματα του LLM ---
        try:
            memories = json.loads(raw_clean)
        except json.JSONDecodeError:
            try:
                # Καθαρίζουμε trailing commas πριν από κλείσιμο λίστας ή αντικειμένου
                fixed_raw = re.sub(r',\s*\]', ']', raw_clean)
                fixed_raw = re.sub(r',\s*\}', '}', fixed_raw)
                memories = json.loads(fixed_raw)
                print("\033[93m[Sifter Fixer]: ✅ Το JSON επισκευάστηκε αυτόματα!\033[0m")
            except:
                print("\033[91m⚠️ [Sifter Error]: Το LLM έβγαλε εντελώς κακογραμμένο JSON. Παράκαμψη εγγραφής.\033[0m")
                return

        for mem in memories:
            fact = mem.get("fact", "").strip()
            category = mem.get("category", "lazaros")

            # [QUESTION GUARD]: Αν το fact είναι ερώτηση, παράκαμψε το
            _fact_body = re.sub(r"^\[USER_FACT\]:\s*", "", fact).strip()
            _question_starters = ("τι ", "πώς ", "πως ", "γιατί ", "γιατι ", "πού ",
                                  "που ", "ποιος ", "ποια ", "ποιο ", "πόσο ", "ποσο ",
                                  "πότε ", "ποτε ", "εδω ", "αυτο ")
            _is_question = (
                _fact_body.endswith("?") or _fact_body.endswith(";") or
                any(_fact_body.lower().startswith(s) for s in _question_starters)
            )
            if _is_question:
                print(f"\033[93m[Sifter]: Question guard — skipping fact: {_fact_body[:60]}\033[0m")
                continue

            # 2. --- ΤΟ ΣΩΣΤΟ JSON INDEXING (Mastro-Restore) ---
            if "[PHOTO]" in fact or category == "photos":
                # Regex για να βρούμε το filename από το user_text
                match = re.search(r"(?:USER_UPLOADED_PHOTO|PHOTO PATH)\]:\s*([^\s\n\]]+)", user_text)
                if match:
                    filename = os.path.basename(match.group(1).strip().replace("]", ""))
                else:
                    # Fallback: ψάξε για πραγματικό filename (.jpg/.png/κλπ) στα texts
                    file_match = re.search(
                        r"\b([a-zA-Z0-9_\-]+\.(?:jpg|jpeg|png|gif|webp|pdf|txt|md))\b",
                        user_text + " " + ai_text,
                        re.IGNORECASE,
                    )
                    if file_match:
                        filename = file_match.group(1)
                    else:
                        # Δεν βρέθηκε έγκυρο filename — αποφυγή corrupted entry
                        print(f"\033[93m[Sifter]: [PHOTO] χωρίς έγκυρο filename — παράκαμψη photo index.\033[0m")
                        filename = None

                if not filename:
                    # Συνέχισε στο ChromaDB save, αλλά μην γράψεις στο photos index
                    memory.save(memory_type="fact", fact=fact, category=category, agent_name=agent_name)
                    continue

                file_path = os.path.join(PHOTOS_DIR, filename)

                # Αν το Gemini δεν έβγαλε analysis, παίρνουμε την απάντηση του AI ως analysis
                analysis_val = mem.get("analysis")
                if not analysis_val or analysis_val == "No analysis provided.":
                    analysis_val = ai_text # Backup από τον διάλογο

                photo_entry = {
                    "file_path": file_path,
                    "analysis": analysis_val,
                    "caption": mem.get("caption", "Φωτογραφία από τον Λάζαρο"),
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "timestamp": datetime.now().isoformat()
                }

                # Φόρτωση και ενημέρωση του κεντρικού JSON
                photo_index = []
                if os.path.exists(PHOTOS_INDEX_FILE):
                    with open(PHOTOS_INDEX_FILE, "r", encoding="utf-8") as f:
                        try: photo_index = json.load(f)
                        except: photo_index = []
                
                save_confirmed = any(w in ai_text.lower() for w in ["αρχειοθετ", "αποθηκεύ", "καταγράφ", "σώθηκε", "index"])

                if not any(p.get("file_path") == file_path for p in photo_index) and save_confirmed:
                    photo_index.append(photo_entry)
                    with open(PHOTOS_INDEX_FILE, "w", encoding="utf-8") as f:
                        json.dump(photo_index, f, indent=4, ensure_ascii=False)
                    print(f"\033[92m📸 [Index]: Η φωτογραφία {filename} αρχειοθετήθηκε επιτυχώς.\033[0m")

            # 3. Αποθήκευση στη ChromaDB
            memory.save(
                memory_type="fact",
                fact=fact,
                category=category,
                agent_name=agent_name
            )

    except Exception as e:
        print(f"⚠️ [Sifter Error]: {e}")


def trigger_memory_sifter(user_text: str, ai_text: str, agent_name: str = "Unknown", channel: str = "web"):
    """Wrapper — εκτελείται μέσω Queue Worker."""
    _run_memory_sifter(user_text, ai_text, agent_name, channel)


# ════════════════════════════════════════════════════════════════
# STARTUP STALE CLEANUP
# ════════════════════════════════════════════════════════════════

def startup_stale_cleanup(channel: str = "telegram") -> bool:
    """
    Εκτελείται κατά την εκκίνηση.
    Αν το astakos_working_memory.json έχει entries από προηγούμενη μέρα
    (δηλ. δεν έτρεξε /end λόγω hard restart), τρέχει πρώτα session summary
    (για να αποθηκευτούν οι ανεπεξέργαστοι exchanges) και μετά σβήνει τα tags.

    Επιστρέφει True αν εκτελέστηκε cleanup, False αν δεν χρειαζόταν.
    """
    try:
        from config import WORKING_MEMORY_FILE
        from datetime import date as _date

        if not os.path.exists(WORKING_MEMORY_FILE):
            print("\033[90m[Startup]: Δεν βρέθηκε working memory file — παράκαμψη.\033[0m")
            return False

        # Έλεγξε αν το αρχείο έχει entries
        try:
            with open(WORKING_MEMORY_FILE, "r", encoding="utf-8") as f:
                tags = json.load(f)
        except Exception:
            tags = []

        if not tags:
            print("\033[90m[Startup]: Working memory κενό — παράκαμψη.\033[0m")
            return False

        # Έλεγξε αν το αρχείο τροποποιήθηκε πριν από σήμερα
        mtime = os.path.getmtime(WORKING_MEMORY_FILE)
        file_date = _date.fromtimestamp(mtime)
        today = _date.today()

        if file_date >= today:
            print(f"\033[90m[Startup]: Working memory είναι από σήμερα ({file_date}) — παράκαμψη.\033[0m")
            return False

        print(
            f"\033[93m[Startup]: ⚠️  Βρέθηκαν {len(tags)} stale tags από {file_date} "
            f"(hard restart εντοπίστηκε). Εκτέλεση session summary πριν τον καθαρισμό...\033[0m"
        )

        # 1. Τρέξε πρώτα το session summary (αποθηκεύει unsummarized exchanges)
        _run_session_summary(channel=channel)

        # 2. Σβήσε τα stale tags
        try:
            with open(WORKING_MEMORY_FILE, "w", encoding="utf-8") as f:
                json.dump([], f, ensure_ascii=False, indent=2)
            print(
                f"\033[92m[Startup]: ✅ Working memory cleared — {len(tags)} stale tags "
                f"από {file_date} επεξεργάστηκαν και αφαιρέθηκαν.\033[0m"
            )
            return True
        except Exception as e:
            print(f"\033[91m[Startup]: ❌ Αποτυχία καθαρισμού working memory: {e}\033[0m")
            return False

    except Exception as e:
        print(f"\033[91m[Startup Cleanup Error]: {e}\033[0m")
        return False
