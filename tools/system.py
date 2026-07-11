# ================================================================
# Project: Astakos AI Agent 🦞
# Developer: Lazaros (Piston-7)
# Description: Modular LLM-agnostic multi-agent framework
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

import os
import re
import json
from core.i18n import t
import sys
import math
import subprocess
import base64
import unicodedata
from types import SimpleNamespace
from datetime import datetime, timedelta
from email.message import EmailMessage
from services.routine_intent import classify_routine_intent
from langchain_core.tools import tool
from pypdf import PdfReader
from github import Github
from google.oauth2.credentials import Credentials
from google.auth.exceptions import RefreshError
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from miio import Device
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import docx
import pandas as pd
import sqlite3
from config import (
    STATE_DB, WORKSPACE_DIR, PHOTOS_INDEX_FILE, PHOTOS_DIR,
    EMAIL_ADDRESS, EMAIL_PASSWORD, GITHUB_TOKEN, VACUUM_IP, VACUUM_TOKEN, GPS_STORAGE_FILE
)
from astakos_skills.linkedin_state_manager import update_pending_linkedin_post, process_and_clear_linkedin_post
from astakos_skills.research_last30days import research_last30days
from memory.vector_store import vector_store, vector_lock, memory
_lexical_cache: dict = {}  # {cache_key: (timestamp, data)} — TTL 60s
from services.embeddings import embeddings
from tools.web import (
    get_news, get_weather_forecast, search_supermarket_prices,
    search_goldmall_offers, execute_local_pipeline, get_navigation_info,
    relay_local_payload, search_google_places, browse_url, duckduckgo_search
)
from astakos_skills.search_flights import search_flights
from astakos_skills.recipe_expert import recipe_expert, log_meal
from astakos_skills.repo_mapper import repo_mapper
from tools.project_tools import (
    grant_project_access, list_project_files, read_project_file,
    edit_project_file, write_project_file, grep_project_files,
    list_recent_files,
)
from astakos_skills.file_generator import (
    generate_excel, generate_word_doc, generate_pdf, generate_csv,
)
from astakos_skills.register_tool import register_tool
from astakos_skills.text_stats import text_stats
from astakos_skills.scan_receipt import scan_receipt
from astakos_skills.officecli_skill import run_officecli
from astakos_skills.read_agent_skill import list_agent_skills, read_agent_skill

# ────────────────────────────────────────────────────────────────
# CREDENTIALS PATHS
# ────────────────────────────────────────────────────────────────
_BASE = os.path.dirname(os.path.abspath(__file__))
TOKEN_PATH = os.path.join(_BASE, '..', 'credentials', 'token.json')
CREDS_PATH = os.path.join(_BASE, '..', 'credentials', 'credentials.json')

# ────────────────────────────────────────────────────────────────
# PROTECTED SANDBOX
# ────────────────────────────────────────────────────────────────
PROTECTED_FILES = ["main.py", "telegram_bot.py", "update.py", ".env"]
DANGEROUS_WORDS = [
    "os.remove", "os.rmdir", "shutil.rmtree", "format c:",
    "exec(", "eval(", "compile(", "__import__", "subprocess.run",
    "subprocess.call", "subprocess.Popen", "os.system"
]


# ────────────────────────────────────────────────────────────────
# MEMORY TOOLS
# ────────────────────────────────────────────────────────────────
@tool
def archive_file(filename: str, content_summary: str) -> str:
    """
    Permanently archives a file (photo, document, PDF) in memory (JSON + ChromaDB).
    filename: The exact technical name of the file (e.g., web_xxx.pdf or web_xxx.png).
    content_summary: Summary of the document's content or the analysis of the image.
    """
    try:
        import os
        from config import BASE_DIR, PHOTOS_DIR
        from memory.vector_store import memory

        search_dirs = [
            PHOTOS_DIR,
            os.path.join(BASE_DIR, "outputs"),
            os.path.join(BASE_DIR, "telegram_uploads"),
            os.path.join(BASE_DIR, "telegram_photos"),
            os.path.join(BASE_DIR, "uploads")
        ]

        full_path = None
        for d in search_dirs:
            test_path = os.path.join(d, filename)
            if os.path.exists(test_path) and os.path.isfile(test_path):
                full_path = test_path
                break

        if not full_path:
            return t("tools.system.archive_not_found", filename=filename)

        ext = os.path.splitext(full_path)[1].lower()
        m_type = "photo" if ext in [".jpg", ".jpeg", ".png", ".webp", ".gif"] else "document"

        memory.save(
            memory_type=m_type,
            file_path=full_path,
            analysis=content_summary,
            caption=f"Αρχειοθέτηση ({m_type}): {filename}"
        )
        return t("tools.system.archive_success", filename=filename, m_type=m_type)
    except Exception as e:
        return t("tools.system.archive_error", error=str(e))

# Channel for Memory Provenance — defined by server.py/telegram_bot.py
_CURRENT_CHANNEL: str = "unknown"


def _normalize_memory_query(value: str) -> str:
    text = unicodedata.normalize("NFD", str(value or "").lower())
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return " ".join(text.split())


def _expand_memory_query(query: str) -> tuple[list[str], str | None]:
    clean = _normalize_memory_query(query)
    expanded = [query]

    family_markers = ("σοφια", "αλεξανδρ", "μαρια", "μικρο", "παιδι", "γενεθλια")
    project_markers = ("astakos", "αστακο", "mastroapp", "github", "repo", "tool", "skill", "bug", "prompt")
    home_markers = ("σπιτι", "συσκευ", "αφυγραντηρ", "κουζινα", "ψυγειο", "ρολοι", "google fit")
    lesson_markers = ("κανονας", "διορθωσ", "bug", "lesson", "λαθος", "πρεπει")

    inferred_category = None
    if any(marker in clean for marker in family_markers):
        inferred_category = "family"
        expanded.append(f"{query} οικογένεια Σοφία Αλέξανδρος γενέθλια πλάνο γεγονός")
    elif any(marker in clean for marker in project_markers):
        inferred_category = "projects"
        expanded.append(f"{query} project tool skill bug κανόνας αλλαγή υλοποίηση")
    elif any(marker in clean for marker in home_markers):
        inferred_category = "home"
        expanded.append(f"{query} σπίτι συσκευή συντήρηση εργασία κατάσταση")
    elif any(marker in clean for marker in lesson_markers):
        inferred_category = "lesson"
        expanded.append(f"{query} μάθημα κανόνας bug λύση συμπεριφορά")

    is_gift_or_product = any(
        marker in clean
        for marker in ("δωρο", "γενεθλια", "αγορα", "προιον", "ρολοι", "watch", "link", "λινκ")
    )
    if is_gift_or_product:
        expanded.append(f"{query} μελλοντικό δώρο ιδέα αγορά προϊόν σύνδεσμος link γενέθλια υπενθύμιση")
        if inferred_category is None and any(marker in clean for marker in family_markers):
            inferred_category = "family"

    # Keep order, remove exact duplicates.
    unique = []
    seen = set()
    for item in expanded:
        key = _normalize_memory_query(item)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique, inferred_category


def _memory_query_tokens(query: str) -> list[str]:
    stopwords = {
        "και", "που", "την", "τον", "τους", "στις", "στα", "στο", "για", "κατι",
        "θυμασαι", "ειχαμε", "σημειωσει", "παρω", "μου", "σου", "what", "with",
    }
    tokens = re.findall(r"[a-zA-Zα-ωΑ-Ωάέήίόύώϊϋΐΰ]+", _normalize_memory_query(query))
    return [token for token in tokens if len(token) >= 4 and token not in stopwords]


def _stem_token(token: str) -> str:
    """Rough Greek stemming: cuts off the most common inflectional endings
    (cases/number: -ος/-ου/-ο/-οι/-ων/-ους, -α/-ας/-ες etc.) so that
    'γενεθλια' matches 'γενεθλιων' and 'αλεξανδρος' matches 'αλεξανδρου'.
    Always keeps a stem of >= 4 characters (the same limit as tokens) to
    prevent noise from increasing due to very short stems.
    """
    if len(token) >= 7:
        return token[:-2]
    if len(token) >= 5:
        return token[:-1]
    return token


def _lexical_memory_matches(query: str, category: str = "", limit: int = 4) -> list:
    """Keyword fallback over Chroma docs; complements embeddings for exact user terms.
    L1 cache (60s TTL) avoids full collection.get() on every call."""
    import time as _time
    tokens = _memory_query_tokens(query)
    if len(tokens) < 2:
        return []
    try:
        cache_key = category or "__all__"
        cached = _lexical_cache.get(cache_key)
        if cached and (_time.monotonic() - cached[0]) < 60:
            data = cached[1]
        else:
            kwargs = {"include": ["documents", "metadatas"]}
            if category:
                kwargs["where"] = {"category": category}
            data = vector_store._collection.get(**kwargs)
            _lexical_cache[cache_key] = (_time.monotonic(), data)
    except Exception:
        return []

    clean_query = _normalize_memory_query(query)
    scored = []
    for document, metadata in zip(data.get("documents", []), data.get("metadatas", [])):
        clean_doc = _normalize_memory_query(document)
        score = sum(1 for token in tokens if _stem_token(token) in clean_doc)
        if "link" in clean_query or "λινκ" in clean_query:
            score += 1 if ("http" in clean_doc or "link" in clean_doc) else 0
        if "δωρο" in clean_query:
            score += 1 if ("δωρο" in clean_doc or "αγορα" in clean_doc or "μελλοντικ" in clean_doc) else 0
        if "γενεθλια" in clean_query:
            score += 1 if ("γενεθλια" in clean_doc or "υπενθυμιση" in clean_doc) else 0
        if score < 2:
            continue
        scored.append((score, len(str(document)), document, metadata or {}))

    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [
        SimpleNamespace(page_content=document, metadata=metadata)
        for _, _, document, metadata in scored[:limit]
    ]

@tool
def search_memory(query: str, category: str = "") -> str:
    """Search in long-term memory. Call this ONCE ONLY. If you already have [Information from search] in the context DO NOT call it again. Use it before answering:
    1. Questions about Lazaros, family, home, habits, or projects.
    2. Issues that require suggestions, advice, or solutions.
    3. References to the past or to existing equipment.

    Args:
        query: Keywords (e.g., 'Alexandros food', 'Mastroapp backend')
        category: Optional filter: 'lazaros', 'family', 'projects', 'home', 'lesson', 'photos'
    """
    VALID_CATS = {"lazaros", "family", "projects", "home", "lesson", "session", "photos"}
    try:
        search_queries, inferred_category = _expand_memory_query(query)
        primary_query = search_queries[-1]
        effective_category = category if category in VALID_CATS else (inferred_category or "")
        sql_lines = []
        try:
            from memory.context_builder import temporal_history_for_query
            from tools import system as _self

            sql_lines = temporal_history_for_query(
                primary_query,
                channel=getattr(_self, "_CURRENT_CHANNEL", "telegram") or "telegram",
                limit=8,
            )
        except Exception:
            sql_lines = []

        with vector_lock:
            merged_results = []
            seen_docs = set()
            for doc in _lexical_memory_matches(primary_query, effective_category, limit=4):
                key = getattr(doc, "page_content", str(doc))
                if key in seen_docs:
                    continue
                seen_docs.add(key)
                merged_results.append(doc)
            # [PERF]: 1 similarity_search instead of 3 — primary_query is sufficient (expanded queries do not improve significantly)
            for search_query in search_queries[:1]:
                if effective_category:
                    batch = vector_store.similarity_search(search_query, k=6, filter={"category": effective_category})
                else:
                    batch = vector_store.similarity_search(search_query, k=6)
                for doc in batch:
                    key = getattr(doc, "page_content", str(doc))
                    if key in seen_docs:
                        continue
                    seen_docs.add(key)
                    merged_results.append(doc)
            results = merged_results[:8 if effective_category else 6]

        from memory.vector_store import (
            get_latest_state_for_query,
            build_profile_memory_summary,
        )
        latest = get_latest_state_for_query(primary_query, category=effective_category or None)
        profile_lines = build_profile_memory_summary(
            primary_query,
            category=effective_category or None,
            limit=5,
        )

        if not results and not sql_lines and not latest and not profile_lines:
            return t("tools.system.memory_no_results")

        # bump retrieval_count async — does not block the response
        if results:
            import threading as _thr
            def _bump_async():
                try:
                    from memory.vector_store import bump_retrieval_count
                    with vector_lock:
                        kwargs = {"n_results": min(6, len(results))}
                        if effective_category:
                            kwargs["where"] = {"category": effective_category}
                        raw = vector_store._collection.query(
                            query_embeddings=[embeddings.embed_query(primary_query)], **kwargs
                        )
                    if raw.get("ids") and raw["ids"][0]:
                        bump_retrieval_count(raw["ids"][0])
                except Exception:
                    pass
            _thr.Thread(target=_bump_async, daemon=True).start()

        by_cat: dict = {}
        for res in results:
            cat = res.metadata.get("category", "general")
            content = res.page_content
            photo_path = res.metadata.get("photo_path")
            if photo_path:
                content += f" [PHOTO_PATH: {photo_path}]"
            by_cat.setdefault(cat, []).append(content)

        output_parts = [t("tools.system.memory_found")]
        
        # 1. Profile: Latest matching state (generic, query-driven)
        if latest and latest.get("fact"):
            output_parts.append("\n[LATEST MATCHING STATE]")
            output_parts.append(f"  • {latest['fact']}")

        # 2. Structured profile memory summary
        if profile_lines:
            output_parts.append("\n[STRUCTURED PROFILE MEMORY]")
            output_parts.extend(profile_lines)

        if sql_lines:
            output_parts.append(t("tools.system.sqlite_history"))
            output_parts.extend(f"  • {line}" for line in sql_lines)

        output_parts.append(t("tools.system.chroma_memory"))
        if by_cat:
            for cat, facts in by_cat.items():
                output_parts.append(f"\n[{cat.upper()}]")
                output_parts.extend(f"  • {f}" for f in facts)
        else:
            output_parts.append(t("tools.system.no_chroma"))

        output_parts.append(
            t("tools.system.instruction")
        )
        return "\n".join(output_parts).strip()
    except Exception as e:
        return t("tools.system.memory_error", error=str(e))
@tool
def run_terminal_command(command: str, already_approved: bool = False) -> str:
    """
    Executes PowerShell commands on Lazaros's PC (Piston-7) and returns the result.
    Ideal for:
    - Reading logs (e.g., 'Get-Content C:\\path\\to\\mastroapp\\logs\\error.log -Tail 50').
    - Checking ports (e.g., 'netstat -ano | findstr 8000').
    - Running tests (e.g., 'python manage.py test').
    already_approved=True: bypasses only the confirmation gate, not BLOCKED commands.
    """
    import subprocess
    from core.safe_executor import safe_execute, classify_command, ExecPolicy
    print(f"\033[93m[Terminal Execution]: {command}\033[0m")

    def _executor(cmd):
        try:
            result = subprocess.run(
                ["powershell", "-Command", cmd],
                capture_output=True, text=True, timeout=30,
                encoding='utf-8', errors='ignore'
            )
            output = result.stdout or ""
            if result.returncode != 0:
                output += f"\nERROR:\n{result.stderr}"
            elif result.stderr:
                output += f"\nWARNINGS:\n{result.stderr}"

            if not output.strip():
                return {"status": "ok", "output": "[SUCCESS] Η εντολή εκτελέστηκε επιτυχώς (χωρίς output). ΠΑΡΑΚΑΛΩ ΠΡΟΧΩΡΗΣΤΕ ΣΤΟ ΕΠΟΜΕΝΟ ΒΗΜΑ/ΕΡΓΑΛΕΙΟ."}

            if len(output) > 10000:
                output = output[:10000] + "\n... [output truncated]"

            return {"status": "ok", "output": f"💻 Terminal Output:\n{output}"}
        except subprocess.TimeoutExpired:
            return {"status": "ok", "output": "❌ Timeout: >30 δευτερόλεπτα."}
        except Exception as e:
            return {"status": "ok", "output": f"❌ Terminal Error: {str(e)}"}

    # Even after approval, hard-blocked commands are never executed.
    if already_approved:
        policy, reason = classify_command(command)
        if policy == ExecPolicy.BLOCKED:
            result = {"status": "blocked", "reason": reason}
        else:
            result = _executor(command)
    else:
        result = safe_execute(command, _executor)

    if result.get("status") == "blocked":
        return f"🛡️ [SAFE EXECUTOR - BLOCKED]: {result['reason']}"
    if result.get("status") == "cancelled":
        return f"⚠️ [SAFE EXECUTOR]: Η εντολή απαιτεί επιβεβαίωσή σου. Ξαναστείλε με `/confirm {command}`"
    return result.get("output", "")

@tool
def save_to_memory(fact: str, entities: str = "", category: str = "other", reason: str = "agent_inferred") -> str:
    """
    Saves information SEMANTICALLY.
    fact: The fact (e.g., "Alexandros only eats lentils").
    entities: Keywords separated by commas (e.g., "Alexandros, Food, Preference").
    category: The category (e.g., 'family', 'home', 'lazaros', 'tech', 'work').
    reason: Why it is being saved — 'user_stated' if explicitly said by the user, 'agent_inferred' otherwise.

    ⚡ Fire-and-forget: ChromaDB/Vertex AI work is done in a background thread.
    Returns immediately so that the agent does not block the user for ~11s.
    """
    import datetime
    import threading
    from tools import system as _self

    # Capture channel context BEFORE the thread (module-level var, thread-unsafe if read later)
    _source = _self._CURRENT_CHANNEL

    def _do_save():
        try:
            from memory.vector_store import memory
            from memory.session_memory import build_canonical_memory_candidate

            canonical_fact = fact.strip()
            if not canonical_fact.startswith(("[USER_FACT]", "[LESSON]", "[CAPABILITY]")):
                canonical_fact = f"[USER_FACT]: {canonical_fact}"

            raw_entities = [x.strip() for x in entities.split(",") if x.strip()]

            candidate = build_canonical_memory_candidate(
                memory_type="fact",
                fact=canonical_fact,
                category=category,
                entities=raw_entities,
                agent_name="Tool_save_to_memory",
                source=_source,
                reason=reason,
                confidence=0.85 if reason == "user_stated" else 0.7,
            )

            saved = memory.save(**candidate)

            if saved:
                _lexical_cache.clear()
        except Exception as e:
            print(f"⚠️ [save_to_memory bg]: {e}")

    threading.Thread(target=_do_save, daemon=True).start()
    return f"✅ Αποθηκεύεται σε background: [{entities}]"


@tool
def delete_from_memory(query: str) -> str:
    """PERMANENTLY deletes information from memory (Chroma).

    USE THIS TOOL (not save_to_memory) whenever the user explicitly requests
    to erase/delete/remove already stored information because it is
    incorrect, outdated, or irrelevant — e.g., "erase the memory that says X", "delete this
    about Y", "what I said about X is wrong, remove it" etc.
    The save_to_memory tool ONLY adds new entries; upon a deletion/correction request,
    it leaves the incorrect entry in place — which is why in such cases you should always
    prefer delete_from_memory (if needed, you can subsequently call
    save_to_memory with the correct content in a separate step).

    query: Provide a BRIEF, SPECIFIC phrase that identifies ONLY the incorrect entry
    (e.g., "old wrong address"), not the user's entire sentence/correction.
    """
    try:
        def _norm(t: str) -> str:
            t = unicodedata.normalize("NFD", str(t or "").lower())
            return "".join(ch for ch in t if unicodedata.category(ch) != "Mn")

        norm_query = _norm(query).strip()

        with vector_lock:
            collection = vector_store._collection
            data = collection.get(include=["documents", "metadatas"])

        # 1) Exact substring match FIRST — more reliable than embeddings when_
        # the phrases are close/similar (e.g. old incorrect vs correct address:
        # the embeddings see them as almost identical and a wrong record might be deleted).
        literal_hits = [
            (doc_id, doc) for doc_id, doc in zip(data.get("ids", []), data.get("documents", []))
            if norm_query and norm_query in _norm(doc)
        ]

        if len(literal_hits) == 1:
            target_id, content = literal_hits[0]
            with vector_lock:
                collection.delete(ids=[target_id])
            print(f"\n🔥 [DATABASE ACTION]: DELETED (exact match): {content}")
            return f"Η μνήμη '{content}' διαγράφηκε επιτυχώς."

        if len(literal_hits) > 1:
            previews = "\n".join(f"  • {str(c).strip()[:140]}" for _, c in literal_hits[:6])
            return (
                f"⚠️ Βρήκα {len(literal_hits)} records που ταιριάζουν με '{query}'. "
                f"Πες μου πιο συγκεκριμένα ποια να σβήσω:\n{previews}"
            )

        # 2) Fallback: semantic search (embeddings), only when no
        # there is no literal match. u_00ad_ u_00ad__
        query_emb = embeddings.embed_query(query)
        with vector_lock:
            results = collection.query(query_embeddings=[query_emb], n_results=1)

            if not results['ids'] or not results['ids'][0]:
                return "Δεν βρήκα κάτι σχετικό για διαγραφή."

            content = results['documents'][0][0]
            distance = results['distances'][0][0] if 'distances' in results and results['distances'] else 1.0

            if distance > 0.40:
                return (
                    f"⚠️ Δεν το διέγραψα. Το πιο κοντινό (Απόσταση: {distance:.2f}): "
                    f"'{content}'. Γίνε πιο συγκεκριμένος."
                )

            target_id = results['ids'][0][0]
            collection.delete(ids=[target_id])

        print(f"\n🔥 [DATABASE ACTION]: DELETED (Dist: {distance:.2f}): {content}")
        return f"Η μνήμη '{content}' διαγράφηκε επιτυχώς."
    except Exception as e:
        return f"Error διαγραφής: {e}"


@tool
def retrieve_photo(query: str) -> str:
    """Retrieves a photo from memory. WHEN it returns [SEND_PHOTO: path], INCLUDE IT EXACTLY AS IS in your response."""
    try:
        import numpy as np

        with vector_lock:
            results = vector_store.similarity_search(query, k=10)

        for doc in results:
            photo_path = doc.metadata.get("photo_path")
            if photo_path and os.path.exists(photo_path):
                return (
                    f"Βρήκα τη φωτογραφία!\n"
                    f"Περιγραφή: {doc.page_content}\n"
                    f"[SEND_PHOTO: {photo_path}]"
                )

        if os.path.exists(PHOTOS_INDEX_FILE):
            with open(PHOTOS_INDEX_FILE, "r", encoding="utf-8") as f:
                index = json.load(f)

            if index:
                query_emb = np.array(embeddings.embed_query(query))
                best_score = -1.0
                best_entry = None

                for entry in index:
                    candidate = f"{entry.get('caption', '')} {entry.get('analysis', '')}".strip()
                    if not candidate:
                        continue
                    cand_emb = np.array(embeddings.embed_query(candidate))
                    norm_q = np.linalg.norm(query_emb)
                    norm_c = np.linalg.norm(cand_emb)
                    if norm_q and norm_c:
                        sim = float(np.dot(query_emb, cand_emb) / (norm_q * norm_c))
                        if sim > best_score:
                            best_score = sim
                            best_entry = entry

                if best_score < 0.35:
                    return "System: Δεν βρέθηκε σχετική φωτογραφία για το query αυτό."

                if best_entry:
                    fp = best_entry.get("file_path", "")
                    note = "" if best_score >= 0.5 else " (Δεν βρήκα ακριβή αντιστοιχία — δίνω την πιο κοντινή.)"
                    if not fp:
                        best_entry = index[-1]
                        fp = best_entry.get("file_path", "")
                        note = " (Fallback: πιο πρόσφατη φωτογραφία.)"

                    if fp and os.path.exists(fp):
                        return (
                            f"Βρήκα φωτογραφία from {best_entry.get('date', 'άγνωστη ημερομηνία')}{note}\n"
                            f"[SEND_PHOTO: {fp}]"
                        )

        return "System: Δεν βρέθηκε φωτογραφία."

    except Exception as e:
        return f"Error: Error ανάκτησης φωτογραφίας: {str(e)}"


# ────────────────────────────────────────────────────────────────
# REMINDERS & LISTS
# ────────────────────────────────────────────────────────────────

def _normalize_reminder_text(text: str) -> str:
    import re

    value = str(text or "").lower().strip()

    replacements = {
        "θύμισε μου": "",
        "θυμησε μου": "",
        "να πάρεις": "",
        "να παρεις": "",
        "πριν φύγεις from τη δουλειά": "",
        "πριν φυγεις απο τη δουλεια": "",
        "from τη δουλειά": "",
        "απο τη δουλεια": "",
        "όταν φύγω from τη δουλειά": "",
        "οταν φυγω απο τη δουλεια": "",
    }

    for old, new in replacements.items():
        value = value.replace(old, new)

    value = re.sub(r"[^\w\sάέήίόύώα-ω]", " ", value, flags=re.UNICODE)
    value = re.sub(r"\s+", " ", value).strip()
    return value

def _same_pending_reminder(existing_task: str, new_task: str, existing_time: str, new_time: str) -> bool:
    if str(existing_time or "").strip() != str(new_time or "").strip():
        return False

    a = _normalize_reminder_text(existing_task)
    b = _normalize_reminder_text(new_task)

    if not a or not b:
        return False

    if a == b:
        return True

    a_tokens = {tok for tok in a.split() if len(tok) >= 4}
    b_tokens = {tok for tok in b.split() if len(tok) >= 4}

    if not a_tokens or not b_tokens:
        return False

    overlap = len(a_tokens & b_tokens)
    min_len = min(len(a_tokens), len(b_tokens))

    return overlap >= max(2, min_len)

@tool
def set_local_reminder(task: str, minutes_from_now: int = 0, exact_time: str = None, action: str = "add", location: str = None) -> str:
    """
    Manages local reminders.
    action: 'add' (new), 'read' (read pending ONLY), 'done' (completion)
    task: For 'add' → description. For 'done' → keyword of the reminder being completed.
    location: ONLY for location-based reminders. Use 'home' when
              Lazaros says 'when I get home', 'as soon as I go home' etc.
              When location is provided, DO NOT provide minutes_from_now or exact_time.
    """
    conn = None
    try:
        conn = sqlite3.connect(STATE_DB)
        cursor = conn.cursor()

        # ── READ: Returns ONLY pending ──────────────────────
        if action == "read":
            cursor.execute("SELECT task, time FROM reminders WHERE status='pending'")
            pending = cursor.fetchall()
            if not pending:
                return "✅ Δεν υπάρχουν εκκρεμείς υπενθυμίσεις."
            lines = []
            for t, tm in pending:
                if tm and tm.startswith("loc:"):
                    loc = tm.split(":", 1)[1]
                    lines.append(f"• [📍 {loc}] {t}")
                else:
                    lines.append(f"• [{tm}] {t}")
            return "📋 Εκκρεμείς υπενθυμίσεις:\n" + "\n".join(lines)

        # ── DONE: Closes reminder with keyword ────────────────
        elif action == "done":
            cursor.execute("SELECT id, task FROM reminders WHERE status='pending'")
            pending = cursor.fetchall()
            found_id = None
            for rid, rtask in pending:
                if task.lower() in rtask.lower():
                    found_id = rid
                    break
            
            if not found_id:
                return f"⚠️ Δεν βρήκα pending υπενθύμιση με '{task}'."
                
            cursor.execute("UPDATE reminders SET status='done' WHERE id=?", (found_id,))
            conn.commit()
            return f"✅ Η υπενθύμιση '{task}' completed."

        # ── ADD: New reminder ─────────────────────────────────
        else:
            from datetime import datetime, timedelta

            if minutes_from_now > 0:
                target_time = (datetime.now() + timedelta(minutes=minutes_from_now)).strftime("%Y-%m-%d %H:%M")
            elif exact_time:
                exact_time = exact_time.strip()
                if len(exact_time) <= 5 and ":" in exact_time:
                    today_str = datetime.now().strftime("%Y-%m-%d")
                    target_time = f"{today_str} {exact_time}"
                else:
                    try:
                        datetime.strptime(exact_time, "%Y-%m-%d %H:%M")
                        target_time = exact_time
                    except ValueError:
                        return "Error: Η ακριβής ώρα (exact_time) πρέπει να είναι ΜΟΝΟ ώρα (HH:MM) ή πλήρης ημερομηνία (YYYY-MM-DD HH:MM)."
            elif location:
                target_time = f"loc:{location}"
            else:
                return "Error: Πρέπει να δώσεις λεπτά, ακριβή ώρα, ή τοποθεσία (e.g. location='home')."

            cursor.execute("SELECT id, task, time FROM reminders WHERE status='pending'")
            pending_rows = cursor.fetchall()

            for rid, existing_task, existing_time in pending_rows:
                if _same_pending_reminder(existing_task, task, existing_time, target_time):
                    return f"ℹ️ Υπάρχει ήδη παρόμοια εκκρεμής υπενθύμιση για τις {target_time}: {existing_task}"

            cursor.execute(
                "INSERT INTO reminders (task, time, status) VALUES (?, ?, 'pending')",
                (task, target_time),
            )
            conn.commit()
            
            if location:
                return f"✅ Υπενθύμιση τοποθεσίας αποθηκεύτηκε! Θα χτυπήσει όταν φτάσεις {location}."
            return f"✅ Υπενθύμιση ρυθμίστηκε για τις {target_time}!"

    except Exception as e:
        return f"Error υπενθύμισης: {e}"
    finally:
        if conn:
            conn.close()
from langchain_core.tools import tool
from memory.routine_db import upsert_routine

@tool
def learn_routine(day_of_week: str, time_str: str, event_name: str, event_type: str = "general") -> str:
    """
    [CRITICAL]: Use this WHEN Lazaros mentions a habit,
    a routine, or something that is repeated (e.g., "Every Friday at 13:00 I go to the farmers market").

    RULES FOR ARGUMENTS:
    - day_of_week: English canonical ("Monday"…"Sunday") or "Everyday" for a daily routine.
    - time_str: Time in HH:MM (e.g., "13:00"). If no time is mentioned, DO NOT call the tool.
    - event_name: BRIEF canonical description in 2-4 words (e.g., "message Kostas", "farmers market",
      "gym"). DO NOT include "Every day", "Every morning", or time phrases — these belong
      to day_of_week/time_str. The event_name must be CONSISTENT for the same activity.
    - event_type: "family", "work", "hobby", "general".

    ATTENTION: Call this ONLY for recurring activities. Ignore one-off events
    ("today I went…", "tomorrow I have…").
    """
    from datetime import datetime

    VALID_DAYS = {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday", "Everyday"}
    VALID_TYPES = {"family", "work", "hobby", "general"}

    if day_of_week not in VALID_DAYS:
        return f"❌ Μη έγκυρη μέρα: '{day_of_week}'. Χρησιμοποίησε αγγλικό όνομα (e.g. 'Friday') ή 'Everyday'."

    try:
        datetime.strptime(time_str, "%H:%M")
    except ValueError:
        return f"❌ Λάθος format ώρας: '{time_str}'. Χρησιμοποίησε 'HH:MM'."

    if len(event_name.strip()) < 3:
        return "❌ Το event_name είναι πολύ σύντομο. Δώσε 2-4 λέξεις περιγραφή."

    if event_type not in VALID_TYPES:
        event_type = "general"

    try:
        res = upsert_routine(day_of_week, time_str, event_name, event_type, confidence_boost=0.3)

        if res == "created":
            return f"✅ Ρουτίνα '{event_name}' καταγράφηκε (θα ενεργοποιηθεί μετά from 2η επιβεβαίωση)."
        elif res == "merged":
            return f"✅ Ρουτίνα '{event_name}' αναγνωρίστηκε ως παρόμοια με υπάρχουσα και ενοποιήθηκε."
        else:
            return f"✅ Ρουτίνα '{event_name}' ενισχύθηκε! (Confidence Boosted)."
    except Exception as e:
        return f"❌ Error αποθήκευσης ρουτίνας: {e}"


@tool
def delete_routine(event_name: str, day_of_week: str = "", time_str: str = "") -> str:
    """
    [ACTION]: Permanently deletes a routine from the scheduler (routine database).
    Use this WHEN Lazarus explicitly asks to delete / cancel / abolish 
    a recurring routine (not a calendar event, not a simple memory, but a routine!).
    - event_name: The name or part of the name of the routine.
    - day_of_week: (Optional) Day for a more precise search.
    - time_str: (Optional) Time (HH:MM) for a more precise search.
    """
    try:
        from memory.routine_db import find_routines_for_schedule_control, delete_routine_db

        routines = find_routines_for_schedule_control(
            event_name, 
            day_of_week=day_of_week if day_of_week else None, 
            time_str=time_str if time_str else None
        )

        if not routines:
            return f"⚠️ Δεν βρέθηκε ρουτίνα που να ταιριάζει στο '{event_name}' για διαγραφή."

        if len(routines) > 1:
            opts = "\n".join(f"- {r['event']} ({r.get('day','')}, {r.get('time','')})" for r in routines)
            return f"⚠️ Βρέθηκαν πολλές ρουτίνες. Διευκρίνισε ποια εννοείς:\n{opts}"

        r_id = routines[0]["id"]
        success = delete_routine_db(r_id)
        if success:
            return f"✅ Η ρουτίνα '{routines[0]['event']}' διαγράφηκε οριστικά."
        return "❌ Η διαγραφή failed."
    except Exception as e:
        return f"❌ Error κατά τη διαγραφή ρουτίνας: {e}"


@tool
def edit_routine(
    event_name: str,
    new_time_str: str = "",
    new_day_of_week: str = "",
    day_of_week: str = "",
    time_str: str = "",
) -> str:
    """
    [ACTION]: Changes the time and/or day of an existing routine in the scheduler.
    Use this instead of learn_routine when Lazaros asks to CHANGE the time 
    or day of something that already exists!
    - event_name: The name (or part) of the existing routine.
    - new_time_str: The new time (e.g., "23:00"). Leave empty if it does not change.
    - new_day_of_week: The new day (e.g., "Everyday", "Monday"). Leave empty if it does not change.
    - day_of_week: (Optional) Day of the existing routine for clarification.
    - time_str: (Optional) Time of the existing routine for clarification.
    """
    if not new_time_str and not new_day_of_week:
        return "⚠️ Πρέπει να δώσεις νέα ώρα ή νέα ημέρα για να γίνει η αλλαγή."

    try:
        from memory.routine_db import find_routines_for_schedule_control, update_routine_db
        import re

        routines = find_routines_for_schedule_control(
            event_name,
            day_of_week=day_of_week if day_of_week else None,
            time_str=time_str if time_str else None,
        )

        if not routines:
            return f"⚠️ Δεν βρέθηκε ρουτίνα που να ταιριάζει στο '{event_name}' για επεξεργασία."

        if len(routines) > 1:
            opts = "\n".join(f"- {r['event']} ({r.get('day','')}, {r.get('time','')})" for r in routines)
            return f"⚠️ Βρέθηκαν πολλές ρουτίνες. Διευκρίνισε ποια εννοείς:\n{opts}"

        r_id = routines[0]["id"]
        
        # If new_time_str was provided, make sure it is HH:MM
        if new_time_str:
            if not re.match(r"^([01]\d|2[0-3]):([0-5]\d)$", new_time_str):
                return f"❌ Λάθος format νέας ώρας: '{new_time_str}'. Χρησιμοποίησε 'HH:MM'."

        success = update_routine_db(r_id, new_time=new_time_str, new_day=new_day_of_week)
        if success:
            return f"✅ Η ρουτίνα '{routines[0]['event']}' updated επιτυχώς (νέα ώρα: {new_time_str or 'ίδια'}, νέα μέρα: {new_day_of_week or 'ίδια'})."
        return "❌ Η ενημέρωση failed."
    except Exception as e:
        return f"❌ Error κατά την επεξεργασία ρουτίνας: {e}"
@tool
def get_routines(day_of_week: str) -> str:
    """
    [QUERY]: Returns the recorded routines for a specific day.
    Use this when Lazaros asks "what do I have on Friday?" or "which routines do you know?".
    - day_of_week: e.g. "Monday", "Friday", "Everyday"
    """
    try:
        from memory.routine_db import get_routines_for_day
        routines = get_routines_for_day(day_of_week)
        if not routines:
            return f"Δεν έχω καταγεγραμμένες ρουτίνες για {day_of_week}."
        
        lines = [f"📅 Ρουτίνες για {day_of_week}:"]
        for r in routines:
            conf_pct = int(r['confidence'] * 100)
            mentions = r.get('mentions', 1)
            lines.append(f"  • {r['time']} — {r['event']} ({r['type']}, {conf_pct}% conf, {mentions}x αναφ.)")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ Error ανάκτησης ρουτινών: {e}"


def _get_routine_names_for_intent_classification() -> list[str]:
    try:
        from memory.routine_db import get_connection
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT event_name FROM routines WHERE event_name IS NOT NULL AND event_name != ''")
        rows = cur.fetchall()
        conn.close()
        return [r[0] for r in rows if r and r[0]]
    except Exception:
        return []


def _looks_like_manual_followup_control(text: str) -> bool:
    normalized = unicodedata.normalize("NFKD", str(text or "").lower())
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    control_markers = (
        "pending followup",
        "followup",
        "follow-up",
        "ακολουθ",
        "εκκρεμ",
        "σβησ",
        "διαγραφ",
        "ακυρωσ",
        "μεταθεσ",
        "αλλαξ",
        "ξαναβαλ",
    )
    action_markers = (
        "σβησ",
        "διαγραφ",
        "ακυρωσ",
        "μεταθεσ",
        "αλλαξ",
        "μετακινησ",
        "ριξ",
        "βαλ",
    )
    return any(m in normalized for m in control_markers) and any(m in normalized for m in action_markers)


@tool
def control_routine_notifications(event_name: str, action: str, until_date: str = "", source_text: str = "") -> str:
    """
    [OVERRIDE]: Manual control of a routine's proactive reminders, ONLY when
    Lazaros EXPLICITLY requests it within the conversation (not automatically by you or by the
    scheduled job — this is a separate channel, the user takes control).

    VERY IMPORTANT — NEVER call this just because the user told you a piece of INFORMATION
    (e.g., "Alexandros is away at camp", "he returns in 9 days"). A piece of information IS
    NOT a request. Call this ONLY when there is an explicit request to check notifications — words/
    meaning like "don't send me", "mute", "leave alone", "stop notifications",
    "reactivate". If the user is simply informing you about something, reply normally in the
    conversation — DO NOT guess that they want to mute and DO NOT scan other routines "just in case".
    One call per routine explicitly requested — no repetition of the same call in the same turn.

    EXAMPLES OF EXPLICIT REQUESTS (only these patterns, do not generalize to every routine):
    - "No need to send me about the park until Alexandros returns on 26/6"
      → action="mute", until_date="2026-06-26"
    - "Leave the alarm alone all week, I'm on afternoon shift at work"
      → action="mute", until_date=<calculate it YOURSELF from the context, e.g., next Sunday>
    - "Reactivate the notifications for the park" or "Alexandros is back"
      → action="unmute"
    - "Don't send ANYTHING, not even a warm message, for the park until he returns"
      → action="silence_emotional"
    - "You can send some message for the park again while he is away"
      → action="allow_emotional"

    ARGUMENTS:
    - event_name: the name of the routine as spoken by the user (e.g., "park", "work
      alarm") — DOES NOT need to be exact, a fuzzy match is performed in memory.
    - action: one of "mute", "unmute", "silence_emotional", "allow_emotional".
    - until_date: ONLY for action="mute". Format YYYY-MM-DD. Calculate it YOURSELF from the
      context (today + X days, "this week" etc) — DO NOT ask the
      user to explicitly state it in ISO format.
    - source_text: The exact original message/sentence of the user that led to
      this call (ALWAYS MANDATORY).
    """
    from datetime import datetime
    from memory.routine_db import (
        find_routines_for_schedule_control, set_routine_muted_until, clear_routine_muted_until,
        set_sentimental_silenced, get_sentimental_info, get_routine_muted_until,
    )
    
    routine_names = _get_routine_names_for_intent_classification()
    intent_result = classify_routine_intent(source_text, routine_names=routine_names)
    if intent_result.intent == "context_update":
        return (
            "ℹ️ Αυτό μοιάζει με context/fact update και όχι με ρητή χειροκίνητη εντολή αλλαγής ειδοποιήσεων ρουτίνας. "
            "Δεν έγινε notification change."
        )

    VALID_ACTIONS = {"mute", "unmute", "silence_emotional", "allow_emotional"}
    if action not in VALID_ACTIONS:
        return f"❌ Μη έγκυρο action: '{action}'. Επιτρεπτά: {', '.join(sorted(VALID_ACTIONS))}."

    changed = 0
    already_ok = 0

    try:
        routines = find_routines_for_schedule_control(event_name)
    except Exception as e:
        return f"❌ Error αναζήτησης ρουτίνας: {e}"

    if not routines:
        return f"ℹ️ Δεν βρέθηκε σαφής ρουτίνα για: {event_name}"

    results = []

    try:
        if action == "mute":
            until_date = (until_date or "").strip()
            if not until_date:
                return "❌ Χρειάζομαι until_date (YYYY-MM-DD) — υπολόγισέ το from τα συμφραζόμενα της κουβέντας."
            try:
                datetime.strptime(until_date, "%Y-%m-%d")
            except ValueError:
                return f"❌ Λάθος format ημερομηνίας: '{until_date}'. Χρησιμοποίησε YYYY-MM-DD."
            for routine in routines:
                r_id = routine["id"]
                label = routine["event"]
                day = routine.get("day") or "?"
                existing_until = get_routine_muted_until(r_id)
                if existing_until and existing_until >= until_date:
                    results.append(f"ℹ️ [{day}] Η ρουτίνα '{label}' είναι ήδη σιγασμένη μέχρι {existing_until} — δεν έκανα τίποτα.")
                    already_ok += 1
                    continue
                set_routine_muted_until(r_id, until_date)
                results.append(f"🔇 [{day}] Η ρουτίνα '{label}' σιγάστηκε μέχρι {until_date}.")
                changed += 1
            
            if changed == 0 and already_ok > 0:
                return f"ℹ️ Οι ρουτίνες ήταν ήδη στην επιθυμητή κατάσταση για: {event_name}"
            if changed == 0:
                return f"ℹ️ Δεν έγινε καμία αλλαγή ρουτίνας για: {event_name}"
            return "\n".join(results)

        if action == "unmute":
            for routine in routines:
                r_id = routine["id"]
                label = routine["event"]
                day = routine.get("day") or "?"
                clear_routine_muted_until(r_id)
                results.append(f"🔔 [{day}] Η ρουτίνα '{label}' ξαναενεργοποιήθηκε κανονικά.")
                changed += 1
            if changed == 0:
                return f"ℹ️ Δεν έγινε καμία αλλαγή ρουτίνας για: {event_name}"
            return "\n".join(results)

        if action == "silence_emotional":
            for routine in routines:
                r_id = routine["id"]
                label = routine["event"]
                day = routine.get("day") or "?"
                info = get_sentimental_info(r_id)
                if not info["muted_until"]:
                    results.append(f"⚠️ [{day}] Η ρουτίνα '{label}' δεν είναι σε σίγαση αυτή τη στιγμή — δεν exists κάτι να σιγάσω.")
                    already_ok += 1
                    continue
                set_sentimental_silenced(r_id, True)
                results.append(f"🤫 [{day}] Εντάξει, δεν θα στείλω τίποτα (ούτε συναισθηματικό message) για '{label}' μέχρι να λήξει η σίγαση.")
                changed += 1
            if changed == 0 and already_ok > 0:
                return f"ℹ️ Οι ρουτίνες ήταν ήδη στην επιθυμητή κατάσταση για: {event_name}"
            if changed == 0:
                return f"ℹ️ Δεν έγινε καμία αλλαγή ρουτίνας για: {event_name}"
            return "\n".join(results)

        if action == "allow_emotional":
            for routine in routines:
                r_id = routine["id"]
                label = routine["event"]
                day = routine.get("day") or "?"
                set_sentimental_silenced(r_id, False)
                results.append(f"💬 [{day}] Εντάξει, θα ξαναστέλνω περιστασιακά ένα ζεστό message για '{label}' όσο διαρκεί η σίγαση.")
                changed += 1
            if changed == 0:
                return f"ℹ️ Δεν έγινε καμία αλλαγή ρουτίνας για: {event_name}"
            return "\n".join(results)
    except Exception as e:
        return f"❌ Error ενημέρωσης ρουτίνας: {e}"

    return "❌ Άγνωστο σφάλμα."


@tool
def control_routine_condition(event_name: str, action: str, condition_type: str = "", payload_json: str = "", condition_mode: str = "", source_text: str = "", day_of_week: str = "", time_str: str = "") -> str:
    """
    [OVERRIDE]: Adds or Removes "conditions" from a routine.
    Use this WHEN the user requests a routine to depend on an external factor
    (e.g., shift, weather, location) or when they state that something "does not apply when..."

    ARGUMENTS:
    - event_name: The name of the target routine as spoken by the user — fuzzy matched.
    - action: "add" (to add a condition) or "remove" (to clear the condition).
    - condition_type: e.g., "shift_mode" (shift dependency), "context_flag" (dependency on a general flag like school_open).
    - payload_json: JSON string with the parameters (e.g., '{"flag": "current_shift", "equals": "afternoon"}').
    - condition_mode: "allow_when_true" (allowed ONLY if true) or "suppress_when_true" (CANCELLED when true).
    - source_text: The exact original message/sentence of the user (ALWAYS MANDATORY).
    - day_of_week: (Optional) If the user specified a day (e.g., "Sunday", "Monday").
    - time_str: (Optional) If the user specified a time (e.g., "13:00").


    EXAMPLES:
    "When I have an afternoon shift, Sofia takes the park" (meaning the park for me does NOT apply in the afternoon)
    -> action="add", condition_type="shift_mode", payload_json='{"flag": "current_shift", "equals": "afternoon"}', condition_mode="suppress_when_true"

    "Training only applies when I have a morning shift"
    -> action="add", condition_type="shift_mode", payload_json='{"flag": "current_shift", "equals": "morning"}', condition_mode="allow_when_true"
    """
    import json
    from memory.routine_db import (
        find_routines_for_schedule_control, append_routine_condition, set_routine_condition
    )

    routine_names = _get_routine_names_for_intent_classification()
    intent_result = classify_routine_intent(source_text, routine_names=routine_names)
    if intent_result.intent == "context_update":
        return (
            "ℹ️ Αυτό μοιάζει με context/fact update και όχι με ρητή χειροκίνητη εντολή αλλαγής ρουτίνας. "
            "Δεν έγινε προσθήκη ή αφαίρεση condition."
        )

    VALID_ACTIONS = {"add", "remove"}
    if action not in VALID_ACTIONS:
        return f"❌ Μη έγκυρο action: '{action}'. Επιτρεπτά: add, remove."

    routines = find_routines_for_schedule_control(event_name, day_of_week=day_of_week if day_of_week else None, time_str=time_str if time_str else None)
    if not routines:
        return f"❌ Δεν βρέθηκε καμία ρουτίνα που να ταιριάζει στο '{event_name}'."

    results = []
    changed = 0

    if action == "add":
        if not condition_type or not payload_json or not condition_mode:
            return "❌ Για action='add' απαιτούνται condition_type, payload_json, condition_mode."
        try:
            json.loads(payload_json) # Validate JSON
        except json.JSONDecodeError:
            return "❌ Το payload_json δεν είναι έγκυρο JSON."

        for routine in routines:
            r_id = routine["id"]
            label = routine["event"]
            r_day = str(routine["day"]).lower()
            
            # Smart check: If the condition concerns a shift and the routine is EXCLUSIVELY for the Weekend,
            # we ignore it automatically, as the user's shifts are Monday-Friday.
            # If the user explicitly provided day_of_week, then we allow it.
            if condition_type == "shift_mode" and r_day in ("saturday", "sunday") and not day_of_week:
                results.append(f"⏩ Η ρουτίνα '{label}' αγνοήθηκε αυτόματα γιατί τρέχει '{routine['day']}' (ΣΚ) και δεν έχεις βάρδιες.")
                continue

            added = append_routine_condition(r_id, condition_type=condition_type, condition_payload=payload_json, condition_mode=condition_mode, source_memory_ref="llm_agent")
            if added:
                results.append(f"⚙️ Η ρουτίνα '{label}' απέκτησε condition: {condition_type} ({condition_mode}).")
                changed += 1
            else:
                results.append(f"⚠️ Η ρουτίνα '{label}' είχε ήδη αυτό το condition.")

    elif action == "remove":
        for routine in routines:
            r_id = routine["id"]
            label = routine["event"]
            # Clear legacy conditions
            set_routine_condition(r_id, condition_type="", condition_payload="", condition_mode="", source_memory_ref="")
            # Clear conditions_json
            import sqlite3
            from memory.routine_db import get_connection, db_write_lock
            with db_write_lock:
                conn = get_connection(write=True)
                conn.execute("UPDATE routines SET conditions_json = NULL WHERE id = ?", (r_id,))
                conn.commit()
            results.append(f"🧹 Η ρουτίνα '{label}' καθαρίστηκε from conditions.")
            changed += 1

    if changed == 0:
        return f"ℹ️ Δεν έγινε καμία αλλαγή ρουτίνας για: {event_name}"
    return "\n".join(results)

@tool
def control_routine_schedule(event_name: str, action: str, until_date: str = "",
                              active_from: str = "", active_until: str = "",
                              resume_rule: str = "", reason: str = "", source_text: str = "") -> str:
    """
    [OVERRIDE]: Manual control of the SEASONAL/TEMPORARY inactivity of a routine
    (not notifications — that's what control_routine_notifications is for). Use
    it ONLY when Lazaros EXPLICITLY asks to "freeze" / "stop" / "resume" a
    routine due to summer break, camp, season change, etc.

    DIFFERENCE FROM control_routine_notifications:
    - control_routine_notifications = "do not SEND me" (notification layer, the routine
      remains active in terms of confidence/missed-tracking).
    - control_routine_schedule = "this routine DOES NOT APPLY now" (business-logic layer —
      it does not enter missed/failed logic, confidence does not drop, it simply "freezes").
    For a summer break of a school/seasonal activity (e.g., football, school)
    ALWAYS use this tool, NOT mute, unless Lazaros explicitly asks for "mute"/
    "mute notifications".

    VERY IMPORTANT — DO NOT call it just because the user gave you an INFORMATION (e.g.,
    "Alexandros is away at camp for 2 weeks"). An information IS NOT a request. Call
    it ONLY when there is an explicit request to pause/resume a routine.

    ARGUMENTS:
    - event_name: the name of the routine as spoken by the user — fuzzy match in memory.
    - action: one of "pause", "resume", "set_window", "clear_window".
      • pause → freezes the routine until until_date (YYYY-MM-DD), optional reason
        (e.g., "summer_break", "camp", "shift_change") and optional resume_rule
        (e.g., "every_september", "next_school_year", "manual_only").
      • resume → removes the pause, the routine immediately returns to normal operation.
      • set_window → sets active_from and/or active_until (YYYY-MM-DD) — the routine
        applies ONLY within this date window.
      • clear_window → removes the active_from/active_until window.
    - until_date: ONLY for action="pause". Calculate it YOURSELF from the context.
    - active_from / active_until: ONLY for action="set_window" (YYYY-MM-DD, only
      one of the two can be provided).
    - resume_rule: optional, along with action="pause" — how/when it will resume.
    - reason: optional, human description of the reason (e.g., "summer_break").
    - source_text: The exact original message/sentence of the user that led to
      this call (ALWAYS MANDATORY).

    EXAMPLE:
    "Alexandros' football stops until September for the summer"
      → action="pause", until_date="2026-09-01", reason="summer_break",
        resume_rule="every_september"
    """
    from datetime import datetime
    from memory.routine_db import (
        find_routines_for_schedule_control, set_routine_paused_until, clear_routine_paused_until,
        set_routine_active_window, set_routine_resume_rule, get_routine_schedule_meta,
        normalize_event
    )

    routine_names = _get_routine_names_for_intent_classification()
    intent_result = classify_routine_intent(source_text, routine_names=routine_names)
    if intent_result.intent == "context_update":
        return (
            "ℹ️ Αυτό μοιάζει με context/fact update και όχι με ρητή χειροκίνητη εντολή αλλαγής ρουτίνας. "
            "Δεν έγινε schedule change."
        )

    VALID_ACTIONS = {"pause", "resume", "set_window", "clear_window"}
    if action not in VALID_ACTIONS:
        return f"❌ Μη έγκυρο action: '{action}'. Επιτρεπτά: {', '.join(sorted(VALID_ACTIONS))}."

    def _valid_date(d: str) -> bool:
        try:
            datetime.strptime(d, "%Y-%m-%d")
            return True
        except ValueError:
            return False

    decision_text = source_text or event_name
    changed = 0
    already_ok = 0

    try:
        routines = find_routines_for_schedule_control(event_name)
    except Exception as e:
        return f"❌ Error αναζήτησης ρουτίνας: {e}"

    if not routines:
        return f"ℹ️ Δεν βρέθηκε σαφής ρουτίνα για: {event_name}"

    results = []

    try:
        if action == "pause":
            until_date = (until_date or "").strip()
            if not until_date:
                return "❌ Χρειάζομαι until_date (YYYY-MM-DD) — υπολόγισέ το from τα συμφραζόμενα της κουβέντας."
            if not _valid_date(until_date):
                return f"❌ Λάθος format ημερομηνίας: '{until_date}'. Χρησιμοποίησε YYYY-MM-DD."
            reason_clean = reason.strip() or None
            for routine in routines:
                r_id = routine["id"]
                label = routine["event"]
                day = routine.get("day") or "?"
                meta = get_routine_schedule_meta(r_id)
                existing_until = meta.get("paused_until")
                if existing_until and existing_until >= until_date:
                    results.append(f"ℹ️ [{day}] Η ρουτίνα '{label}' είναι ήδη παγωμένη μέχρι {existing_until} — δεν έκανα τίποτα.")
                    already_ok += 1
                    continue
                set_routine_paused_until(r_id, until_date, reason=reason_clean)
                if resume_rule.strip():
                    set_routine_resume_rule(r_id, resume_rule.strip())
                results.append(f"❄️ [{day}] Η ρουτίνα '{label}' πάγωσε μέχρι {until_date}" + (f" (λόγος: {reason_clean})" if reason_clean else "") + ".")
                changed += 1
            if changed == 0 and already_ok > 0:
                return f"ℹ️ Οι ρουτίνες ήταν ήδη στην επιθυμητή κατάσταση για: {event_name}"
            if changed == 0:
                return f"ℹ️ Δεν έγινε καμία αλλαγή ρουτίνας για: {event_name}"
            return "\n".join(results)

        if action == "resume":
            for routine in routines:
                r_id = routine["id"]
                label = routine["event"]
                day = routine.get("day") or "?"
                clear_routine_paused_until(r_id)
                results.append(f"▶️ [{day}] Η ρουτίνα '{label}' ξαναενεργοποιήθηκε κανονικά.")
                changed += 1
            if changed == 0:
                return f"ℹ️ Δεν έγινε καμία αλλαγή ρουτίνας για: {event_name}"
            return "\n".join(results)

        if action == "set_window":
            active_from_clean = active_from.strip() or None
            active_until_clean = active_until.strip() or None
            if not active_from_clean and not active_until_clean:
                return "❌ Χρειάζομαι active_from και/ή active_until (YYYY-MM-DD)."
            if active_from_clean and not _valid_date(active_from_clean):
                return f"❌ Λάθος format active_from: '{active_from_clean}'. Χρησιμοποίησε YYYY-MM-DD."
            if active_until_clean and not _valid_date(active_until_clean):
                return f"❌ Λάθος format active_until: '{active_until_clean}'. Χρησιμοποίησε YYYY-MM-DD."
            reason_clean = reason.strip() or None
            for routine in routines:
                r_id = routine["id"]
                label = routine["event"]
                day = routine.get("day") or "?"
                set_routine_active_window(r_id, active_from=active_from_clean, active_until=active_until_clean, reason=reason_clean)
                results.append(f"📅 [{day}] Η ρουτίνα '{label}' έχει πλέον παράθυρο ισχύος: from={active_from_clean or '—'}, μέχρι={active_until_clean or '—'}.")
            return "\n".join(results)

        if action == "clear_window":
            for routine in routines:
                r_id = routine["id"]
                label = routine["event"]
                day = routine.get("day") or "?"
                set_routine_active_window(r_id, active_from=None, active_until=None)
                results.append(f"📅 [{day}] Το παράθυρο ισχύος της ρουτίνας '{label}' αφαιρέθηκε — ισχύει πάντα πλέον.")
            return "\n".join(results)
    except Exception as e:
        return f"❌ Error ενημέρωσης χρονοδιαγράμματος ρουτίνας: {e}"

    return "❌ Άγνωστο σφάλμα."


@tool
def control_routine_cooldown(
    event_name: str,
    action: str,
    source_text: str = "",
    day_of_week: str = "",
    time_str: str = "",
) -> str:
    """
    [OVERRIDE]: Manual routine cooldown control.

    Use this ONLY when the user explicitly requests something like:
    - "reset the cooldown"
    - "reset cooldown"
    - "take it out of cooldown"
    - "I want it to be sent normally tomorrow"
    - "to be resent normally"

    DO NOT call this for a simple context update.
    DO NOT call this just because the user was late to reply.
    DO NOT confuse this with mute/schedule/conditions.

    ARGUMENTS:
    - event_name: routine name as stated by the user
    - action: "reset" only
    - source_text: the exact message of the user
    - day_of_week/time_str: optional clarification if multiple similar routines exist
    """
    from memory.routine_db import (
        find_routines_for_schedule_control,
        reset_routine_cooldown,
        get_routine_notify_info,
    )

    routine_names = _get_routine_names_for_intent_classification()
    intent_result = classify_routine_intent(source_text, routine_names=routine_names)
    if intent_result.intent == "context_update":
        return (
            "ℹ️ Αυτό μοιάζει με context/fact update και όχι με ρητή χειροκίνητη εντολή αλλαγής cooldown ρουτίνας. "
            "Δεν έγινε cooldown reset."
        )

    VALID_ACTIONS = {"reset"}
    if action not in VALID_ACTIONS:
        return f"❌ Μη έγκυρο action: '{action}'. Επιτρεπτά: reset."

    routines = find_routines_for_schedule_control(
        event_name,
        day_of_week=day_of_week if day_of_week else None,
        time_str=time_str if time_str else None,
    )
    if not routines:
        return f"❌ Δεν βρέθηκε καμία ρουτίνα που να ταιριάζει στο '{event_name}'."

    results = []
    changed = 0

    for routine in routines:
        r_id = routine["id"]
        label = routine["event"]
        r_day = routine.get("day") or "?"
        r_time = routine.get("time") or "?"
        before = get_routine_notify_info(r_id)

        reset_routine_cooldown(r_id, clear_last_notified=True)

        after = get_routine_notify_info(r_id)
        results.append(
            f"🔄 [{r_day} {r_time}] Routine '{label}' removed from cooldown "
            f"({before['cooldown_hours']}h -> {after['cooldown_hours']}h)."
        )
        changed += 1

    if changed == 0:
        return f"ℹ️ Δεν έγινε καμία αλλαγή cooldown για: {event_name}"

    return "\n".join(results)


@tool
def control_pending_followup(
    subject_query: str,
    action: str,
    source_text: str = "",
    topic: str = "",
    delay_minutes: int = 0,
    target_window: str = "",
) -> str:
    """
    [OVERRIDE]: Manual check of pending conversational follow-ups.

    Use this ONLY when the user explicitly asks to change/delete/defer a pending follow-up.

    Examples:
    - "delete the pending followup for the steaks"
    - "change the pending for the park to later"
    - "defer the followup for Sophia to tomorrow afternoon"
    - "fix the old pending followups"

    actions:
    - "delete": deletes the matching follow-up
    - "defer": defers the matching follow-up with new minutes/window
    - "repair_legacy": backfills old followups that are missing metadata fields
    """
    from memory.pending_followups import (
        backfill_legacy_followups,
        delete_followup,
        defer_followup,
        find_followups_for_control,
        find_pending_followups,
    )

    action = (action or "").strip().lower()
    if action not in {"delete", "defer", "repair_legacy"}:
        return "❌ Μη έγκυρο action. Επιτρεπτά: delete, defer, repair_legacy."

    if action != "repair_legacy":
        if not _looks_like_manual_followup_control(source_text):
            return (
                "ℹ️ Αυτό μοιάζει περισσότερο με απλό context update και όχι με ρητή χειροκίνητη εντολή "
                "αλλαγής pending follow-up. Δεν έγινε καμία αλλαγή."
            )

    if action == "repair_legacy":
        repaired = backfill_legacy_followups(force_retime=True)
        rows = find_pending_followups(limit=10)
        if not repaired:
            return "ℹ️ Δεν βρήκα legacy pending followups που να χρειάζονται repair."
        preview = []
        for row in rows[:5]:
            preview.append(
                f"- #{row['id']} {row['subject']} -> {row['followup_after_ts']}"
            )
        body = "\n".join(preview)
        return f"🛠️ Έγινε repair σε {repaired} legacy pending followups.\n{body}"

    matches = find_followups_for_control(subject_query, topic=topic)
    if not matches:
        return f"ℹ️ Δεν βρήκα pending/sent follow-up που να ταιριάζει στο '{subject_query}'."

    if len(matches) > 1:
        opts = "\n".join(
            f"- #{m['id']} {m['subject']} ({m['topic']}, {m['status']})"
            for m in matches[:5]
        )
        return f"⚠️ Βρήκα πολλά pending followups. Διευκρίνισε ποιο εννοείς:\n{opts}"

    item = matches[0]
    if action == "delete":
        ok = delete_followup(item["id"], reason="manual_delete")
        if not ok:
            return f"❌ Δεν κατάφερα να διαγράψω το pending follow-up #{item['id']}."
        return f"✅ Διαγράφηκε το pending follow-up #{item['id']} για '{item['subject']}'."

    if delay_minutes <= 0 and not target_window.strip():
        return "❌ Για defer χρειάζομαι delay_minutes ή/και target_window."

    defer_followup(
        item["id"],
        delay_minutes=delay_minutes or int(item.get("metadata", {}).get("delay_minutes_final") or 60),
        reason="manual_defer",
        target_window=(target_window or str(item.get("metadata", {}).get("target_window") or "")).strip(),
        topic=item["topic"],
    )
    updated = find_pending_followups(limit=20)
    refreshed = next((row for row in updated if row["id"] == item["id"]), None)
    if not refreshed:
        return f"✅ Το pending follow-up #{item['id']} μετατέθηκε."
    return (
        f"✅ Το pending follow-up #{item['id']} για '{refreshed['subject']}' μετατέθηκε.\n"
        f"Νέο due: {refreshed['followup_after_ts']}\n"
        f"Νέο expiry: {refreshed['expires_at']}"
    )


@tool
def manage_list(action: str, list_name: str, item: str = "") -> str:
    """Manages lists. Actions: 'add', 'remove', 'read', 'clear', 'delete'.
    For multiple items at once, separate them with a comma (item='milk, cheese')."""
    conn = None
    try:
        conn = sqlite3.connect(STATE_DB)
        cursor = conn.cursor()
        
        cursor.execute("SELECT DISTINCT list_name FROM lists")
        existing_lists = [row[0] for row in cursor.fetchall()]
        
        if list_name not in existing_lists:
            list_name_lower = list_name.lower()
            for existing_key in existing_lists:
                if list_name_lower in existing_key.lower() or existing_key.lower().startswith(list_name_lower):
                    list_name = existing_key
                    break

        if action == "read":
            cursor.execute("SELECT item FROM lists WHERE list_name=?", (list_name,))
            items = [row[0] for row in cursor.fetchall()]
            if not items:
                return f"Η λίστα '{list_name}' είναι άδεια."
            return f"Περιεχόμενα '{list_name}':\n" + "\n".join([f"- {i}" for i in items])

        to_process = [i.strip() for i in item.split(",")] if item else []

        if action == "add":
            for obj in to_process:
                if obj:
                    cursor.execute("SELECT id FROM lists WHERE list_name=? AND item=?", (list_name, obj))
                    if not cursor.fetchone():
                        cursor.execute("INSERT INTO lists (list_name, item) VALUES (?, ?)", (list_name, obj))
        elif action == "remove":
            for obj in to_process:
                cursor.execute("DELETE FROM lists WHERE list_name=? AND item=?", (list_name, obj))
        elif action == "clear" or action == "delete":
            cursor.execute("DELETE FROM lists WHERE list_name=?", (list_name,))

        conn.commit()

        added_str = ", ".join(to_process) if to_process else "κανένα"
        return f"System: Η ενέργεια '{action}' completed (Αντικείμενα: {added_str})."
    except Exception as e:
        return f"Error: Error λίστας: {str(e)}"
    finally:
        if conn:
            conn.close()


# ────────────────────────────────────────────────────────────────
# GOOGLE SERVICES
# ────────────────────────────────────────────────────────────────

from astakos_skills.gcalendar import google_calendar_tool


def _normalize_google_task_due(due: str | None) -> str | None:
    if not due:
        return None
    due = due.strip()
    if len(due) == 10:
        return f"{due}T00:00:00.000Z"
    return due


@tool
def google_tasks_tool(
    action: str,
    title: str = "",
    due: str = None,
    task_id: str = None,
    notes: str = "",
    tasklist_id: str = "@default",
    max_results: int = 20,
) -> str:
    """
    Manages Google Tasks.
    Actions:
      'create'   — new task (requires title, optionally due/notes)
      'list'     — list of open tasks
      'complete' — complete a task (requires task_id)
      'update'   — modify title/due/notes (requires task_id and at least one field)
      'delete'   — delete a task (requires task_id, CRITICAL approval)
    🚨 [MASTER-RULE FOR TITLE]: The 'title' parameter MUST clearly describe the task (e.g., 'Rose bush care').
    It is STRICTLY FORBIDDEN to use command verbs (e.g., 'put', 'do', 'remind me', 'reminder') as a title.
    If the user simply says 'add a reminder' without specifying the topic, DO NOT call this tool. Ask them first what they want you to write!
    """
    try:
        action = (action or "list").strip().lower()
        tasklist_id = tasklist_id or "@default"
        print(f"\033[93m[Tasks]: Action '{action}'...\033[0m")
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, ['https://www.googleapis.com/auth/tasks'])
        service = build('tasks', 'v1', credentials=creds)

        if action == "list":
            result = service.tasks().list(
                tasklist=tasklist_id,
                showCompleted=False,
                maxResults=max(1, min(int(max_results or 20), 50)),
            ).execute()
            items = result.get("items", [])
            if not items:
                return "✅ Δεν υπάρχουν ανοιχτά Google Tasks."
            lines = ["📋 Ανοιχτά Google Tasks:"]
            for task in items:
                due_text = task.get("due", "")[:10]
                due_part = f" | due: {due_text}" if due_text else ""
                lines.append(f"• {task.get('title', '(χωρίς τίτλο)')} | ID: `{task.get('id')}`{due_part}")
            return "\n".join(lines)

        if action == "create":
            if not title:
                return "❌ Για create χρειάζεται title."
            task = {"title": title}
            normalized_due = _normalize_google_task_due(due)
            if normalized_due:
                task["due"] = normalized_due
            if notes:
                task["notes"] = notes
            created = service.tasks().insert(tasklist=tasklist_id, body=task).execute()
            return f"✅ Η εργασία '{created.get('title', title)}' προστέθηκε στα Google Tasks! ID: `{created.get('id')}`"

        if action == "complete":
            if not task_id:
                return "❌ Για complete χρειάζεται task_id."
            service.tasks().patch(
                tasklist=tasklist_id,
                task=task_id,
                body={"status": "completed"},
            ).execute()
            return f"✅ Το Google Task `{task_id}` completed."

        if action == "update":
            if not task_id:
                return "❌ Για update χρειάζεται task_id."
            body = {}
            if title:
                body["title"] = title
            normalized_due = _normalize_google_task_due(due)
            if normalized_due:
                body["due"] = normalized_due
            if notes:
                body["notes"] = notes
            if not body:
                return "❌ Για update δώσε title, due ή notes."
            updated = service.tasks().patch(tasklist=tasklist_id, task=task_id, body=body).execute()
            return f"✅ Το Google Task updated: {updated.get('title', task_id)}"

        if action == "delete":
            if not task_id:
                return "❌ Για delete χρειάζεται task_id."
            service.tasks().delete(tasklist=tasklist_id, task=task_id).execute()
            return f"🗑️ Το Google Task `{task_id}` διαγράφηκε."

        return "❌ Άγνωστο action. Δοκίμασε: list, create, complete, update, delete."
    except Exception as e:
        return f"Tasks Error: {str(e)}"

@tool
def create_file_tool(file_type: str, filename: str, data: str) -> str:
    """
    [WARNING: For .docx, .xlsx, .pptx files, the use of this tool is FORBIDDEN. Use ONLY run_officecli]
    Creates local PDF, TXT (and legacy DOCX/XLSX) files.
    file_type: 'docx', 'pdf', 'xlsx', 'txt'
    filename: The name of the file (e.g., 'report.txt')
    data: The content. 
    """
    import os
    import json
    from config import BASE_DIR

    output_dir = os.path.realpath(os.path.join(BASE_DIR, "outputs"))
    os.makedirs(output_dir, exist_ok=True)

    # [SECURITY]: basename + resolve check — prevents path traversal (e.g., ../config.py)
    safe_filename = os.path.basename(filename)
    if not safe_filename:
        return "❌ Error: Μη έγκυρο όνομα αρχείου."
    full_path = os.path.realpath(os.path.join(output_dir, safe_filename))
    if not full_path.startswith(output_dir + os.sep) and full_path != output_dir:
        return "❌ Error: Το path εκτός outputs δεν επιτρέπεται."
    file_type = file_type.lower()

    try:
        if file_type == "docx":
            import docx
            doc = docx.Document()
            for line in data.split("\n"):
                doc.add_paragraph(line)
            doc.save(full_path)

        elif file_type == "xlsx":
            import pandas as pd
            try:
                content = json.loads(data)
                df = pd.DataFrame(content)
            except (json.JSONDecodeError, ValueError):
                df = pd.DataFrame([data], columns=["Content"])
            df.to_excel(full_path, index=False)

        elif file_type == "pdf":
            from fpdf import FPDF
            font_path = os.path.join(BASE_DIR, "assets", "DejaVuSans.ttf")
            pdf = FPDF()
            pdf.add_page()
            if os.path.exists(font_path):
                pdf.add_font("DejaVu", "", font_path, uni=True)
                pdf.set_font("DejaVu", size=12)
            else:
                # Fallback without Greek if the font is missing
                pdf.set_font("Arial", size=12)
            pdf.multi_cell(0, 10, data)
            pdf.output(full_path)

        elif file_type in ["txt", "json", "csv", "html", "md"]:
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(data)

        else:
            return f"❌ Error: Ο τύπος '{file_type}' δεν υποστηρίζεται."

        return f"✅ Έτοιμο Μάστορα! Το αρχείο created επιτυχώς.\n[CREATED_FILE: {full_path}]"

    except Exception as e:
        return f"❌ Error κατά τη δημιουργία: {str(e)}"
@tool
def generate_image_tool(prompt: str) -> str:
    """
    Creates an image based on a description (prompt) via Vertex AI Imagen.
    """
    import os
    import time
    from slugify import slugify
    from config import BASE_DIR

    output_dir = os.path.join(BASE_DIR, "outputs")
    os.makedirs(output_dir, exist_ok=True)

    safe_filename = slugify(prompt[:30]) or "gen_image"
    filename = f"{safe_filename}_{int(time.time())}.jpg"
    full_path = os.path.join(output_dir, filename)

    # ── Vertex AI Imagen ──────────────────────────────────────────
    try:
        import vertexai
        from vertexai.preview.vision_models import ImageGenerationModel

        vertexai.init(
            project=os.getenv("PROJECT_ID", "astakos-finall"),
            location="us-central1"  # Imagen does not support "global"
        )
        model = ImageGenerationModel.from_pretrained("imagen-3.0-generate-001")
        response = model.generate_images(
            prompt=prompt,
            number_of_images=1,
            aspect_ratio="1:1",
        )
        if not response.images:
            return "❌ Το Vertex AI Imagen δεν επέστρεψε εικόνα."
        response.images[0].save(location=full_path, include_generation_parameters=False)
        return f"✅ Έτοιμο! Η εικόνα created.\n[SEND_PHOTO: {full_path}]"

    except Exception as e:
        return f"❌ Error Vertex AI Imagen: {str(e)}"
def _escape_drive_query_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


@tool
def drive_manager(
    action: str = "list_files",
    file_id: str = None,
    local_path: str = None,
    folder_id: str = "12YrIZ3uAQWmmwIlEkIkDf-4gcz2P8Ktv",
    query: str = None,
    new_name: str = None,
    target_folder_id: str = None,
    share_email: str = None,
    share_role: str = "reader",
) -> str:
    """Manages Lazaros's Google Drive.

    Actions:
      'list_files'   — List files in folder (default: root astakos folder)
      'search'       — Search by name or keyword (requires query=)
      'download'     — Download file (requires file_id=)
      'upload'       — Upload file (requires local_path=)
      'delete'       — Delete file (requires file_id=)
      'rename'       — Rename (requires file_id= + new_name=)
      'move'         — Move to another folder (requires file_id= + target_folder_id=)
      'share'        — Share (requires file_id= + share_email= + share_role='reader'/'writer')
      'create_folder'— Create folder (requires new_name=, optionally folder_id= for parent)
      'info'         — File information (requires file_id=)
    """
    try:
        from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
        import io

        action = (action or "list_files").strip().lower()
        print(f"\033[93m[Drive]: Action '{action}'...\033[0m")
        creds   = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
        service = build('drive', 'v3', credentials=creds)

        # ── LIST FILES ───────────────────────────────────────────
        if action == "list_files":
            results = service.files().list(
                q=f"'{folder_id}' in parents and trashed=false",
                fields="files(id, name, mimeType, size, modifiedTime)",
                orderBy="modifiedTime desc",
                pageSize=50
            ).execute()
            items = results.get('files', [])
            if not items:
                return "📁 Ο φάκελος είναι άδειος."
            lines = ["📁 Αρχεία στο Drive:\n"]
            for i in items:
                size_kb = round(int(i.get('size', 0)) / 1024, 1) if i.get('size') else "—"
                mod = i.get('modifiedTime', '')[:10]
                lines.append(f"• {i['name']} | ID: `{i['id']}` | {size_kb} KB | {mod}")
            return "\n".join(lines)

        # ── SEARCH ───────────────────────────────────────────────
        elif action == "search":
            if not query:
                return "❌ Χρειάζεται query= για αναζήτηση."
            q_str = f"name contains '{_escape_drive_query_value(query)}' and trashed=false"
            results = service.files().list(
                q=q_str,
                fields="files(id, name, mimeType, size, modifiedTime, parents)",
                orderBy="modifiedTime desc",
                pageSize=20
            ).execute()
            items = results.get('files', [])
            if not items:
                return f"🔍 Δεν βρέθηκαν αρχεία για '{query}'."
            lines = [f"🔍 Αποτελέσματα για '{query}':\n"]
            for i in items:
                size_kb = round(int(i.get('size', 0)) / 1024, 1) if i.get('size') else "—"
                mod = i.get('modifiedTime', '')[:10]
                lines.append(f"• {i['name']} | ID: `{i['id']}` | {size_kb} KB | {mod}")
            return "\n".join(lines)

        # ── DOWNLOAD ─────────────────────────────────────────────
        elif action == "download":
            if not file_id:
                return "❌ Χρειάζεται file_id=."
            file_metadata = service.files().get(fileId=file_id, fields="name,mimeType").execute()
            mime_type = file_metadata.get('mimeType', '')
            file_name = file_metadata.get('name', 'downloaded_file')

            # Google Docs/Sheets/Slides → export as text/xlsx/pptx
            export_map = {
                'application/vnd.google-apps.document':     ('text/plain', '.txt'),
                'application/vnd.google-apps.spreadsheet':  ('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', '.xlsx'),
                'application/vnd.google-apps.presentation': ('application/vnd.openxmlformats-officedocument.presentationml.presentation', '.pptx'),
            }
            if mime_type in export_map:
                export_mime, ext = export_map[mime_type]
                request = service.files().export_media(fileId=file_id, mimeType=export_mime)
                if not file_name.endswith(ext):
                    file_name += ext
            else:
                request = service.files().get_media(fileId=file_id)

            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()

            # [SECURITY]: always download to outputs — local_path is ignored if it is outside
            from config import BASE_DIR as _BASE_DIR
            _outputs_dir = os.path.realpath(os.path.join(_BASE_DIR, "outputs"))
            os.makedirs(_outputs_dir, exist_ok=True)
            if local_path:
                _lp_real = os.path.realpath(local_path)
                if not _lp_real.startswith(_outputs_dir + os.sep):
                    return f"❌ Απαγορευμένο download path: επιτρέπεται μόνο within outputs/."
                save_target = _lp_real
            else:
                save_target = os.path.join(_outputs_dir, os.path.basename(file_name))
            os.makedirs(os.path.dirname(save_target), exist_ok=True)
            with open(save_target, "wb") as f:
                f.write(fh.getvalue())

            # If it is text, also return the content
            if mime_type == 'application/vnd.google-apps.document' or file_name.endswith('.txt'):
                content = fh.getvalue().decode('utf-8', errors='ignore')[:6000]
                return f"✅ '{file_name}' κατέβηκε → {save_target}\n\n{content}"
            return f"✅ '{file_name}' κατέβηκε → {save_target}"

        # ── UPLOAD ───────────────────────────────────────────────
        elif action == "upload":
            if not local_path or not os.path.exists(local_path):
                return f"❌ Αρχείο δεν βρέθηκε: {local_path}"
            # [SECURITY]: upload only from allowed dirs — prevents uploading credentials/config
            from config import BASE_DIR as _BASE_DIR
            _upload_allowed = [
                os.path.realpath(os.path.join(_BASE_DIR, "outputs")),
                os.path.realpath(os.path.join(_BASE_DIR, "telegram_uploads")),
                os.path.realpath(os.path.join(_BASE_DIR, "telegram_photos")),
                os.path.realpath(os.path.join(_BASE_DIR, "watch_folder")),
            ]
            _lp_real = os.path.realpath(local_path)
            if not any(_lp_real.startswith(d + os.sep) or _lp_real == d for d in _upload_allowed):
                return f"❌ Απαγορευμένο upload path: επιτρέπεται μόνο from outputs/, telegram_uploads/, telegram_photos/, watch_folder/."
            file_metadata = {'name': os.path.basename(local_path), 'parents': [folder_id]}
            media = MediaFileUpload(local_path, resumable=True)
            file = service.files().create(body=file_metadata, media_body=media, fields='id,name').execute()
            return f"✅ '{file.get('name')}' uploaded! (ID: {file.get('id')})"

        # ── DELETE ───────────────────────────────────────────────
        elif action == "delete":
            if not file_id:
                return "❌ Χρειάζεται file_id=."
            meta = service.files().get(fileId=file_id, fields="name").execute()
            service.files().update(fileId=file_id, body={"trashed": True}).execute()
            return f"🗑️ '{meta.get('name')}' μεταφέρθηκε στον κάδο."

        # ── RENAME ───────────────────────────────────────────────
        elif action == "rename":
            if not file_id or not new_name:
                return "❌ Χρειάζεται file_id= και new_name=."
            service.files().update(fileId=file_id, body={"name": new_name}).execute()
            return f"✏️ Μετονομάστηκε σε '{new_name}'."

        # ── MOVE ─────────────────────────────────────────────────
        elif action == "move":
            if not file_id or not target_folder_id:
                return "❌ Χρειάζεται file_id= και target_folder_id=."
            file = service.files().get(fileId=file_id, fields="parents").execute()
            old_parents = ",".join(file.get('parents', []))
            service.files().update(
                fileId=file_id,
                addParents=target_folder_id,
                removeParents=old_parents,
                fields="id, parents"
            ).execute()
            return f"📦 Αρχείο μετακινήθηκε στον φάκελο {target_folder_id}."

        # ── SHARE ────────────────────────────────────────────────
        elif action == "share":
            if not file_id or not share_email:
                return "❌ Χρειάζεται file_id= και share_email=."
            if share_role not in {"reader", "writer", "commenter"}:
                return "❌ share_role πρέπει να είναι reader, writer ή commenter."
            permission = {"type": "user", "role": share_role, "emailAddress": share_email}
            service.permissions().create(fileId=file_id, body=permission, sendNotificationEmail=False).execute()
            return f"🔗 Κοινοποιήθηκε στον/στην {share_email} ως {share_role}."

        # ── CREATE FOLDER ─────────────────────────────────────────
        elif action == "create_folder":
            if not new_name:
                return "❌ Χρειάζεται new_name= για το όνομα του φακέλου."
            metadata = {
                "name": new_name,
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [folder_id]
            }
            folder = service.files().create(body=metadata, fields="id, name").execute()
            return f"📁 Folder '{folder.get('name')}' created (ID: {folder.get('id')})."

        # ── INFO ─────────────────────────────────────────────────
        elif action == "info":
            if not file_id:
                return "❌ Χρειάζεται file_id=."
            meta = service.files().get(
                fileId=file_id,
                fields="name,mimeType,size,modifiedTime,createdTime,parents,webViewLink,owners"
            ).execute()
            size_kb = round(int(meta.get('size', 0)) / 1024, 1) if meta.get('size') else "—"
            owners = ", ".join(o.get('emailAddress','') for o in meta.get('owners', []))
            return (
                f"📄 *{meta.get('name')}*\n"
                f"Type: {meta.get('mimeType')}\n"
                f"Μέγεθος: {size_kb} KB\n"
                f"Δημιουργήθηκε: {meta.get('createdTime','')[:10]}\n"
                f"Τροποποιήθηκε: {meta.get('modifiedTime','')[:10]}\n"
                f"Ιδιοκτήτης: {owners}\n"
                f"Link: {meta.get('webViewLink','—')}"
            )

        return "❌ Άγνωστο action. Δες το docstring για τις επιλογές."

    except Exception as e:
        return f"❌ Drive Error: {str(e)}"


# ────────────────────────────────────────────────────────────────
# FILE & DEV TOOLS
# ────────────────────────────────────────────────────────────────

@tool
def read_local_file(file_path: str) -> str:
    """Reads PDF, XLSX, CSV, DOCX, TXT, PY, JS (Mastro-Optimized)."""
    import os
    from config import BASE_DIR, PHOTOS_DIR
    
    # Path cleanup
    file_path = file_path.strip().strip("'").strip('"')
    filename = os.path.basename(file_path)
    base_dir = BASE_DIR

    # [SECURITY]: Only these folders are allowed to be read
    _allowed_dirs = [
        os.path.realpath(PHOTOS_DIR),
        os.path.realpath(os.path.join(base_dir, "telegram_uploads")),
        os.path.realpath(os.path.join(base_dir, "telegram_photos")),
        os.path.realpath(os.path.join(base_dir, "uploads")),
        os.path.realpath(os.path.join(base_dir, "outputs")),
        os.path.realpath(os.path.join(base_dir, "watch_folder")),
        # [SELF-DIAGNOSIS]: Source code folders — Lobster can read
        # its code for self-debugging (e.g., why a tool failed).
        os.path.realpath(os.path.join(base_dir, "tools")),
        os.path.realpath(os.path.join(base_dir, "core")),
        os.path.realpath(os.path.join(base_dir, "memory")),
        os.path.realpath(os.path.join(base_dir, "services")),
        os.path.realpath(os.path.join(base_dir, "clients")),
        os.path.realpath(os.path.join(base_dir, "astakos_skills")),
        os.path.realpath(os.path.join(base_dir, "api")),
    ]
    _allowed_files = [
        os.path.realpath(os.path.join(BASE_DIR, "messenger_draft.json")),
        os.path.realpath(os.path.join(BASE_DIR, "linkedin_draft.json")),
    ]
    # [SECURITY]: Sensitive files that are not allowed even if they are in an allowed dir
    _blocked_filenames = {
        "config.py", ".env", "secrets.py",
    }
    _blocked_extensions = {".db", ".sqlite", ".sqlite3", ".key", ".pem"}

    def _is_blocked(path):
        name = os.path.basename(path)
        ext  = os.path.splitext(name)[1].lower()
        return name in _blocked_filenames or ext in _blocked_extensions

    def _in_allowed(path):
        real = os.path.realpath(path)
        if _is_blocked(path):
            return False
        return any(real.startswith(d + os.sep) or real == d for d in _allowed_dirs)

    def _is_allowed_file(path):
        real = os.path.realpath(path)
        if _is_blocked(path):
            return False
        return any(real == f for f in _allowed_files)

    full_path = None
    print(f"\033[93m[Tool Debug]: Searching for file: {filename}\033[0m")

    # If an absolute path was provided, check that it is within the allowed dirs
    if os.path.isabs(file_path):
        if os.path.exists(file_path) and os.path.isfile(file_path) and (_in_allowed(file_path) or _is_allowed_file(file_path)):
            full_path = file_path
            print(f"\033[92m[Tool Debug]: ✅ Absolute path within allowed -> {full_path}\033[0m")
        elif os.path.exists(file_path):
            return f"❌ Απαγορευμένο path: {os.path.basename(file_path)} βρίσκεται εκτός εγκεκριμένων φακέλων."

    # Exact allowlist for root-level runtime files such as the Messenger draft.
    if not full_path:
        for allowed_file in _allowed_files:
            if filename == os.path.basename(allowed_file) and os.path.exists(allowed_file) and os.path.isfile(allowed_file):
                full_path = allowed_file
                print(f"\033[92m[Tool Debug]: ✅ Exact allowed file -> {full_path}\033[0m")
                break

    # Search by basename in the allowed dirs_
    if not full_path:
        for d in _allowed_dirs:
            test_path = os.path.join(d, filename)
            if os.path.exists(test_path) and os.path.isfile(test_path) and _in_allowed(test_path):
                full_path = test_path
                print(f"\033[92m[Tool Debug]: ✅ Found at -> {full_path}\033[0m")
                break

    if not full_path:
        return f"❌ Error: Το αρχείο {filename} δεν βρέθηκε στους φακέλους αναζήτησης."

    ext = os.path.splitext(full_path)[1].lower()

    try:
        if ext == ".pdf":
            # Using pypdf (more reliable than PyPDF2)
            try:
                from pypdf import PdfReader
            except ImportError:
                from PyPDF2 import PdfReader # Fallback if you haven't managed to install in time
            
            text = ""
            reader = PdfReader(full_path)
            for page in reader.pages:
                extracted = page.extract_text()
                if extracted:
                    text += extracted + "\n"
                if len(text) > 12000: # Limit to avoid "choking" the context
                    break
            
            if not text.strip():
                return f"⚠️ Το PDF ({filename}) φαίνεται να είναι σκαναρισμένο (εικόνα). Χρειάζεται OCR για να διαβαστεί."
                
            return f"📄 PDF ({filename}):\n{text[:12000]}"

        elif ext in [".xlsx", ".xls"]:
            import pandas as pd
            excel_file = pd.ExcelFile(full_path)
            output_text = f"📊 Excel ({filename}) - Φύλλα: {', '.join(excel_file.sheet_names)}\n\n"
            for sheet in excel_file.sheet_names:
                df = pd.read_excel(full_path, sheet_name=sheet).fillna("-")
                output_text += f"═══ Φύλλο: {sheet} ═══\n"
                output_text += df.head(50).to_string(index=False) + "\n\n"
                if len(output_text) > 12000: break
            return output_text[:12000]

        elif ext == ".csv":
            import pandas as pd
            df = pd.read_csv(full_path).fillna("-")
            return f"📊 CSV ({filename}):\n{df.head(100).to_string(index=False)}"

        elif ext == ".docx":
            import docx
            doc = docx.Document(full_path)
            text = "\n".join([p.text for p in doc.paragraphs])
            return f"📝 Word ({filename}):\n{text[:12000]}"

        else: # TXT, PY, JS, etc.
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                return f"📄 Αρχείο ({filename}):\n{f.read(12000)}"

    except Exception as e:
        return f"❌ Error ανάγνωσης {filename}: {str(e)}"

@tool
def write_code(filename: str, code: str) -> str:
    """Writes code ONLY inside the astakos_skills folder."""
    safe_filename = os.path.basename(filename)
    if safe_filename in PROTECTED_FILES:
        return f"System Error: ΑΠΑΓΟΡΕΥΕΤΑΙ να τροποποιήσεις το {safe_filename}."

    if re.search(r"(^|\n)\s*@tool\b|langchain_core\.tools\s+import\s+tool", code):
        return (
            "System Error: skill tools must be created with write_custom_tool, "
            "then registered with register_tool dry_run/apply."
        )

    for word in DANGEROUS_WORDS:
        if word in code:
            return f"System Error: Ο κώδικας απορρίφθηκε ({word})."

    file_path = os.path.join(WORKSPACE_DIR, safe_filename)

    try:
        print(f"\033[93m[Dev]: Saving in {file_path}...\033[0m")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(code)
        return f"System: Ο κώδικας γράφτηκε στο {file_path}."
    except Exception as e:
        return f"Write Error: {str(e)}"


@tool
def run_code(filename: str, script_args: str = "") -> str:
    """
    Executes a Python file ONLY from the astakos_skills folder.
    You can optionally pass arguments (script_args) as a string.
    Example: script_args="SKG KUT 2026-08-09 -r 2026-08-15"
    """
    import os
    import sys
    import subprocess
    from core.safe_executor import safe_execute

    safe_filename = os.path.basename(filename)
    file_path = os.path.join(WORKSPACE_DIR, safe_filename)

    if not os.path.exists(file_path):
        return f"Error: Το αρχείο {file_path} δεν exists στο Sandbox."

    # ── SafeExec check ───────────────────────────────────────────
    cmd_str = f"python {safe_filename} {script_args}".strip()
    check = safe_execute(cmd_str, lambda c: {"status": "ok"})
    if check.get("status") == "blocked":
        return f"🛡️ [SAFE EXECUTOR - BLOCKED]: {check['reason']}"
    if check.get("status") == "cancelled":
        return f"⚠️ [SAFE EXECUTOR]: Η εκτέλεση απαιτεί επιβεβαίωση. Ξαναστείλε με `/confirm {cmd_str}`"
    # ────────────────────────────────────────────────────────────

    try:
        cmd = [sys.executable, file_path]
        if script_args:
            cmd.extend(script_args.split())

        print(f"\033[93m[Dev]: Executing {safe_filename} with arguments: {script_args}\033[0m")

        res = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        output = res.stdout if res.stdout else ""
        if res.stderr:
            output += f"\nERRORS:\n{res.stderr}"

        return f"Terminal Output:\n{output[:5000]}" if output else "Εκτελέστηκε επιτυχώς (χωρίς output)."

    except subprocess.TimeoutExpired:
        return "Error: Το script κόλλησε (>20 δευτερόλεπτα) και τερματίστηκε."
    except Exception as e:
        return f"Run Error: {str(e)}"


@tool
def write_custom_tool(tool_name: str, tool_code: str) -> str:
    """Writes and tests a new tool in astakos_skills/.
    It does not register it automatically in system/risk/registry — this is done with register_tool."""
    import ast

    clean_code = re.sub(r"```(?:python)?", "", tool_code).replace("```", "").strip()

    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", tool_name):
        return "System Error: invalid tool_name. Use a Python identifier, e.g. my_tool."

    def _decorator_name(decorator):
        if isinstance(decorator, ast.Call):
            return _decorator_name(decorator.func)
        if isinstance(decorator, ast.Name):
            return decorator.id
        if isinstance(decorator, ast.Attribute):
            base = _decorator_name(decorator.value)
            return f"{base}.{decorator.attr}" if base else decorator.attr
        return ""

    def _has_tool_decorator(function_node):
        return any(_decorator_name(dec).split(".")[-1] == "tool" for dec in function_node.decorator_list)

    # [SECURITY]: Blocklist for generated tool code — filesystem, network, execution
    _dangerous_patterns = [
        r"subprocess",
        r"os\s*\.\s*system",
        r"__import__",
        r"eval\s*\(",
        r"exec\s*\(",
        r"pathlib",                           # filesystem ops
        r"shutil",                            # copy/move/delete files
        r"import\s+socket",                   # raw network
        r"from\s+socket\s+import",            # raw network
        r"import\s+requests",                 # HTTP calls
        r"from\s+requests\s+import",          # HTTP calls
        r"requests\s*\.",                     # HTTP calls
        r"import\s+urllib",                   # HTTP calls
        r"from\s+urllib\s+import",            # HTTP calls
        r"urllib\s*\.",                       # HTTP calls
        r"import\s+httpx",                    # HTTP calls
        r"from\s+httpx\s+import",             # HTTP calls
        r"httpx\s*\.",                        # HTTP calls
        r"import\s+aiohttp",                  # async HTTP
        r"from\s+aiohttp\s+import",           # async HTTP
        r"aiohttp\s*\.",                      # async HTTP
        r"import\s+ftplib",                   # FTP
        r"from\s+ftplib\s+import",            # FTP
        r"import\s+smtplib",                  # email sending
        r"from\s+smtplib\s+import",           # email sending
        r"import\s+paramiko",                 # SSH
        r"from\s+paramiko\s+import",          # SSH
        r"ctypes",                            # low-level OS access
        r"importlib",                         # dynamic imports
        r"compile\s*\(",                      # bytecode compile
        r"globals\s*\(\s*\)",                 # globals manipulation
        r"locals\s*\(\s*\)",                  # locals manipulation
        r"__builtins__",                      # builtins override
    ]
    for _dp in _dangerous_patterns:
        if re.search(_dp, clean_code, re.IGNORECASE):
            return f"System Error: Απορρίφθηκε — ανιχνεύτηκε απαγορευμένο pattern: `{_dp}`."
    dangerous_pattern = None  # legacy — replaced by _dangerous_patterns
    # (legacy check replaced by the _dangerous_patterns loop above)

    try:
        tree = ast.parse(clean_code)
    except SyntaxError as se:
        return f"❌ Συντακτικό σφάλμα (γραμμή {se.lineno}): {se.msg}\nΚοίτα: {se.text}"

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open":
            return "System Error: Απορρίφθηκε — ανιχνεύτηκε απαγορευμένο built-in open() call."

    top_level_functions = [
        node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    matching_functions = [node for node in top_level_functions if node.name == tool_name]
    if len(matching_functions) != 1:
        return (
            f"System Error: code must contain exactly one top-level function "
            f"named '{tool_name}'."
        )

    target_function = matching_functions[0]
    if not _has_tool_decorator(target_function):
        return f"System Error: function '{tool_name}' must have the @tool decorator."

    extra_tool_functions = [
        node.name for node in top_level_functions
        if node.name != tool_name and _has_tool_decorator(node)
    ]
    if extra_tool_functions:
        return (
            "System Error: only one @tool function is allowed. "
            f"Extra decorated functions: {', '.join(extra_tool_functions)}."
        )

    try:
        workspace_dir = os.path.realpath(WORKSPACE_DIR)
        final_path = os.path.realpath(os.path.join(workspace_dir, f"{tool_name}.py"))
        if not final_path.startswith(workspace_dir + os.sep):
            return "System Error: invalid tool path."
        if os.path.exists(final_path):
            return f"System Error: astakos_skills/{tool_name}.py already exists."
        temp_path = os.path.join(WORKSPACE_DIR, f"_test_{tool_name}.py")
    except:
        temp_path = f"_test_{tool_name}.py"
        final_path = f"{tool_name}.py"

    test_script = f"""import math, json, inspect
from langchain_core.tools import tool

{clean_code}

if __name__ == "__main__":
    sig = inspect.signature({tool_name}.func if hasattr({tool_name}, 'func') else {tool_name})
    dummy = {{}}
    for p, param in sig.parameters.items():
        ann = param.annotation
        if ann in (int, float):
            dummy[p] = 1.0
        else:
            dummy[p] = "test"
    try:
        target_func = {tool_name}.func if hasattr({tool_name}, 'func') else {tool_name}
        if hasattr({tool_name}, 'invoke'):
            result = {tool_name}.invoke(dummy)
        else:
            result = target_func(**dummy)
        print(f"TEST_OK: {{result}}")
    except Exception as e:
        print(f"TEST_FAIL: {{e}}")
"""

    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write(test_script)

        res = subprocess.run([sys.executable, temp_path], capture_output=True, text=True, timeout=15)
        stdout = res.stdout.strip()
        stderr = res.stderr.strip()

        try:
            os.remove(temp_path)
        except:
            pass

        if "TEST_FAIL" in stdout or (res.returncode != 0 and not stdout):
            error_detail = stdout or stderr
            return f"❌ Tool '{tool_name}' ΔΕΝ πέρασε το test.\nError: {error_detail[:600]}"

        sep = "═" * 62
        code_body = re.sub(
            r"^\s*from\s+langchain_core\.tools\s+import\s+tool\s*\n",
            "",
            clean_code,
            flags=re.MULTILINE,
        ).strip()
        paste_code = f"from langchain_core.tools import tool\nimport math\n\n{code_body}"
        with open(final_path, "w", encoding="utf-8") as f:
            f.write(paste_code.rstrip() + "\n")

        print(f"\n\033[92m{sep}")
        print(f"  ✅  TOOL WRITTEN: {tool_name}")
        print(f"  🧪  Test: {stdout}")
        print(sep)
        print(paste_code)
        print(f"{sep}\033[0m\n")
        print("Lazaros: ", end="", flush=True)

        return f"✅ Tool '{tool_name}' γράφτηκε στο astakos_skills/{tool_name}.py και πέρασε το test ({stdout})."

    except subprocess.TimeoutExpired:
        try:
            os.remove(temp_path)
        except:
            pass
        return "❌ Timeout: το test script κόλλησε πάνω from 15 δευτερόλεπτα."
    except Exception as e:
        return f"Error: {str(e)}"


# ────────────────────────────────────────────────────────────────
# EMAIL
# ────────────────────────────────────────────────────────────────
_BASE = os.path.dirname(os.path.abspath(__file__))
TOKEN_PATH = os.path.join(_BASE, '..', 'credentials', 'token.json')
CREDS_PATH = os.path.join(_BASE, '..', 'credentials', 'credentials.json')

SCOPES = [
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/tasks',
    'https://www.googleapis.com/auth/fitness.activity.read',
    'https://www.googleapis.com/auth/fitness.sleep.read',
    'https://www.googleapis.com/auth/fitness.heart_rate.read',
]

def get_gmail_service():
    """Creates the Gmail API service using OAuth."""
    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if not os.path.exists(CREDS_PATH):
            raise Exception("Λsaidι το αρχείο credentials.json! Κατέβασέ το from το Google Cloud.")

        if creds and creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request
            try:
                creds.refresh(Request())
            except RefreshError as e:
                if "invalid_scope" not in str(e).lower():
                    raise
                print("[GoogleAuth] token invalid_scope - forcing fresh OAuth consent.")
                creds = None

        if not creds or not creds.valid:
            flow = InstalledAppFlow.from_client_secrets_file(CREDS_PATH, SCOPES)
            creds = flow.run_local_server(port=0, prompt='consent', access_type='offline')

        with open(TOKEN_PATH, 'w') as token:
            token.write(creds.to_json())

    return build('gmail', 'v1', credentials=creds)


def decode_base64(data):
    return base64.urlsafe_b64decode(data.encode("UTF-8")).decode("utf-8", errors="replace")


def extract_body(payload):
    """Extracts body with fallback: plain text → HTML → nested parts."""
    import html

    def _parse_part(part):
        mime = part.get('mimeType', '')
        body = part.get('body', {})

        if 'parts' in part:
            for p in part['parts']:
                if p.get('mimeType') == 'text/plain' and 'data' in p.get('body', {}):
                    return decode_base64(p['body']['data'])
            for p in part['parts']:
                if p.get('mimeType') == 'text/html' and 'data' in p.get('body', {}):
                    return _html_to_text(decode_base64(p['body']['data']))
            for p in part['parts']:
                result = _parse_part(p)
                if result:
                    return result

        if 'data' in body:
            if mime == 'text/plain':
                return decode_base64(body['data'])
            elif mime == 'text/html':
                return _html_to_text(decode_base64(body['data']))

        return ""

    def _html_to_text(raw_html):
        # <br> and </p> → newlines for readable text
        raw_html = re.sub(r'<br\s*/?>', '\n', raw_html, flags=re.IGNORECASE)
        raw_html = re.sub(r'</p>', '\n', raw_html, flags=re.IGNORECASE)
        text = re.sub(r'<[^>]+>', ' ', raw_html)
        text = html.unescape(text)
        return re.sub(r'\s+', ' ', text).strip()

    return _parse_part(payload)


def clean_text(text):
    """Cleans whitespace and removes quoted replies (lines with >)."""
    lines = text.splitlines()
    lines = [l for l in lines if not l.strip().startswith('>')]
    cleaned = '\n'.join(lines)
    return re.sub(r'\s+', ' ', cleaned).strip()


def _encode_gmail_message(message: EmailMessage) -> str:
    return base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")


def _build_plain_email(to_email: str, subject: str, body: str) -> EmailMessage:
    message = EmailMessage()
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(body, charset="utf-8")
    return message


def _build_plain_reply(to_email: str, subject: str, body: str,
                       message_id: str = "", references: str = "") -> EmailMessage:
    message = _build_plain_email(to_email, subject, body)
    if message_id:
        message["In-Reply-To"] = message_id
    if references:
        message["References"] = references
    return message


@tool
def mail_manager(action: str, query: str = None, email_id: str = None,
                 to_email: str = None, subject: str = None, body: str = None,
                 limit: int = 10) -> str:
    """
    Gmail management via Google API. 
    Actions: 'search' (requires query), 'read_full' (requires email_id), 
             'read_thread' (requires email_id, reads the entire conversation),
             'send' (requires to_email, subject, body),
             'reply' (requires email_id, body),
             'delete' (requires email_id).
    """
    try:
        if not action:
            return "❌ Δώσε action: search, read_full, read_thread, send, reply ή delete."

        print(f"\033[94m[Mail API]: Executing action '{action}'...\033[0m")
        action = action.lower()
        if action == "read" and email_id:
            action = "read_full"
        elif action == "read":
            action = "search"
        service = get_gmail_service()

        # =========================
        # SEND
        # =========================
        if action == "send":
            if not to_email or not subject or not body:
                return "❌ Για send χρειάζονται: to_email, subject, body."
            raw = _encode_gmail_message(_build_plain_email(to_email, subject, body))
            service.users().messages().send(userId="me", body={"raw": raw}).execute()
            return "✅ Email sent κανονικά."

        # =========================
        # REPLY
        # =========================
        elif action == "reply":
            if not email_id or not body:
                return "❌ Για reply χρειάζεται email_id και body."
            
            original = service.users().messages().get(
                userId="me", id=email_id, format="metadata",
                metadataHeaders=["Subject", "From", "Message-ID", "References"]
            ).execute()
            
            headers = original["payload"]["headers"]
            orig_subject = next((h["value"] for h in headers if h["name"] == "Subject"), "Re: (no subject)")
            orig_from    = next((h["value"] for h in headers if h["name"] == "From"), "")
            orig_msg_id  = next((h["value"] for h in headers if h["name"] == "Message-ID"), "")
            orig_refs    = next((h["value"] for h in headers if h["name"] == "References"), "")
            
            reply_subject = orig_subject if orig_subject.startswith("Re:") else f"Re: {orig_subject}"
            references = f"{orig_refs} {orig_msg_id}".strip()

            reply_message = _build_plain_reply(
                orig_from,
                reply_subject,
                body,
                message_id=orig_msg_id,
                references=references,
            )
            raw = _encode_gmail_message(reply_message)
            thread_id = original.get("threadId")
            send_body = {"raw": raw}
            if thread_id:
                send_body["threadId"] = thread_id
            service.users().messages().send(
                userId="me",
                body=send_body
            ).execute()
            return f"✅ Reply sent στον {orig_from}."

        # =========================
        # SEARCH
        # =========================
        elif action in ["search", "check_emails", "check"]:
            results = service.users().messages().list(userId="me", q=query, maxResults=limit).execute()
            messages = results.get("messages", [])

            if not messages:
                return f"Δεν βρέθηκαν email για την αναζήτηση: {query}"

            output = []
            for msg in messages:
                data = service.users().messages().get(
                    userId="me", id=msg['id'],
                    format="metadata",
                    metadataHeaders=["Subject", "From", "Date"]
                ).execute()
                headers = data['payload']['headers']
                subject_val = next((h['value'] for h in headers if h['name'] == 'Subject'), "No Subject")
                from_val    = next((h['value'] for h in headers if h['name'] == 'From'), "Unknown")
                date_val    = next((h['value'] for h in headers if h['name'] == 'Date'), "")
                output.append(f"ID: {msg['id']} | {date_val} | Από: {from_val} | Θέμα: {subject_val}")

            return "\n".join(output)

        # =========================
        # READ FULL (Single Message)
        # =========================
        elif action == "read_full":
            if not email_id:
                return "❌ Για read_full χρειάζεται email_id."
            data = service.users().messages().get(userId="me", id=email_id, format="full").execute()
            body_text = extract_body(data['payload'])
            return f"📩 Περιεχόμενο:\n{clean_text(body_text)[:5000]}"

        # =========================
        # READ THREAD (Full Conversation)
        # =========================
        elif action == "read_thread":
            if not email_id:
                return "❌ Για read_thread χρειάζεται email_id (ενός μηνύματος της συνομιλίας)."
            # Get the message to find its threadId
            msg_meta = service.users().messages().get(userId="me", id=email_id, format="minimal").execute()
            thread_id = msg_meta.get("threadId", email_id)
            
            thread_data = service.users().threads().get(userId="me", id=thread_id).execute()
            messages_in_thread = thread_data.get("messages", [])
            
            output = []
            for i, m in enumerate(messages_in_thread):
                headers = m['payload']['headers']
                from_val = next((h['value'] for h in headers if h['name'] == 'From'), "Unknown")
                date_val = next((h['value'] for h in headers if h['name'] == 'Date'), "")
                
                body_text = extract_body(m['payload'])
                output.append(f"--- Μήνυμα {i+1} | Από: {from_val} ({date_val}) ---\n{clean_text(body_text)[:2000]}")
            
            full_text = "\n\n".join(output)
            return f"📩 Ολόκληρη η συνομιλία ({len(messages_in_thread)} μηνύματα):\n{full_text[:8000]}"

        # =========================
        # DELETE
        # =========================
        elif action == "delete":
            if not email_id:
                return "❌ Για delete χρειάζεται email_id."
            service.users().messages().trash(userId="me", id=email_id).execute()
            return f"🗑️ Το email {email_id} μεταφέρθηκε στον κάδο."

        return f"❌ Άγνωστη εντολή: {action}"

    except Exception as e:
        return f"Mail API Error: {str(e)}"

# ────────────────────────────────────────────────────────────────
# GITHUB
# ────────────────────────────────────────────────────────────────

import subprocess
import shlex
from github import Github
from langchain_core.tools import tool

@tool
def github_manager(action: str, repo_name: str = "", target_files: str = "",
                   commit_message: str = "", content: str = "") -> str:
    """
    Manages GitHub operations and local Git commits.
    
    Actions: 
    - 'list_repos', 'read_file', 'create_file', 'update_file' (Cloud API Operations)
    - 'push_local_commits' (Runs local Git CLI commands)
    
    CRITICAL RULES for 'push_local_commits': 
    - target_files MUST be a comma-separated list of exact paths (e.g. "core/brain.py, api/server.py"). 
    - Using "." or "*" or "all" is STRICTLY FORBIDDEN.
    """
    token = os.getenv("GITHUB_TOKEN") 
    if not token:
        return "Error: Missing GITHUB_TOKEN."

    try:
        # ─── 1. LOCAL GIT CLI OPERATIONS (Mastro-Shielded) ──────────────
        if action == "push_local_commits":
            if not target_files or target_files.strip() in [".", "*", "all"]:
                return "🛡️ [GIT OVERRIDE]: Blind sweeps are forbidden. Specify exact file paths."
            if not commit_message:
                return "Error: Commit message is required."

            # ── SafeExec check ───────────────────────────────────────────
            from core.safe_executor import safe_execute
            push_check = safe_execute("git push origin main", lambda c: {"status": "ok"})
            if push_check.get("status") == "blocked":
                return f"🛡️ [SAFE EXECUTOR - BLOCKED]: {push_check['reason']}"
            if push_check.get("status") == "cancelled":
                return "⚠️ [SAFE EXECUTOR]: Το git push απαιτεί επιβεβαίωση. Ξαναστείλε με `/confirm`"
            # ────────────────────────────────────────────────────────────

            files = [f.strip() for f in target_files.split(",") if f.strip()]

            # 1. git add <files>
            add_cmd = ["git", "add"] + files
            subprocess.run(add_cmd, check=True, capture_output=True, text=True)

            # 2. git commit -m "message"
            commit_cmd = ["git", "commit", "-m", commit_message]
            subprocess.run(commit_cmd, check=True, capture_output=True, text=True)

            # 3. git push origin main
            push_cmd = ["git", "push", "origin", "main"]
            subprocess.run(push_cmd, check=True, capture_output=True, text=True)

            return f"System: Local changes successfully pushed!\nFiles: {files}\nMessage: {commit_message}"

        # ─── 2. GITHUB CLOUD API OPERATIONS ─────────────────────────────
        g = Github(token)
        user = g.get_user()

        if action == "list_repos":
            repos = [f"- {r.name} ({'Private' if r.private else 'Public'})" for r in user.get_repos()]
            return f"Found {len(repos)} Repositories:\n" + "\n".join(repos)

        elif action == "read_file":
            repo = g.get_repo(f"{user.login}/{repo_name}")
            file_content = repo.get_contents(target_files)
            return f"Content of {target_files}:\n{file_content.decoded_content.decode('utf-8')[:10000]}"

        elif action in ["create_file", "update_file"]:
            if not content.strip():
                return "🛡️ [GIT OVERRIDE]: Content is empty. Refusing to overwrite file with empty data."
            repo = g.get_repo(f"{user.login}/{repo_name}")
            try:
                file_info = repo.get_contents(target_files)
                repo.update_file(target_files, commit_message, content, file_info.sha)
                return f"System: '{target_files}' in '{repo_name}' updated via API!"
            except:
                repo.create_file(target_files, commit_message, content)
                return f"System: '{target_files}' created in '{repo_name}' via API!"

        else:
            return "Error: Invalid action specified."

    except subprocess.CalledProcessError as e:
        return f"Local Git Command Error: {e.stderr}"
    except Exception as e:
        return f"GitHub API Error: {str(e)}"


# ────────────────────────────────────────────────────────────────
# HARDWARE CONTROL
# ────────────────────────────────────────────────────────────────

@tool
def control_vacuum(action: str) -> str:
    """Controls the Xiaomi X20+ robot vacuum.
    Actions: 'start', 'stop', 'home', 'status' (for battery/status), 'room:<room_name>' (e.g., room:Kitchen)."""
    ip = VACUUM_IP
    token = VACUUM_TOKEN

    if not ip or not token:
        return "Error: Δεν βρέθηκαν VACUUM_IP ή VACUUM_TOKEN."

    try:
        vac = Device(ip, token)

        if action == "start":
            vac.send("action", {"did": "astakos", "siid": 2, "aiid": 1, "in": []})
            return "Ο Astakos έδωσε εντολή: Η X20+ started το σκούπισμα! 🧹"

        elif action == "stop":
            vac.send("action", {"did": "astakos", "siid": 2, "aiid": 2, "in": []})
            return "Ο Astakos έδωσε εντολή: Η σκούπα σταμάτησε."

        elif action == "home":
            vac.send("action", {"did": "astakos", "siid": 3, "aiid": 1, "in": []})
            return "Ο Astakos έδωσε εντολή: Η σκούπα επιστρέφει στη βάση. 🏠"

        elif action.startswith("room:"):
            room_name = action.split(":", 1)[1].strip()
            import os, json
            
            # Loading of room_map.json
            room_map_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "room_map.json")
            try:
                with open(room_map_path, "r", encoding="utf-8") as f:
                    room_map = json.load(f)
            except Exception:
                # Fallback if the file does not exist (we have hardcoded the ones we found)
                room_map = {"Κουζίνα": 5, "Μπάνιο": 7, "Κρεβατοκάμαρα": 1, "Παιδικό": 3, "Σαλόνι": 4}

            room_id = room_map.get(room_name)
            if room_id is None:
                available = ", ".join(room_map.keys())
                return f"Error: Not found: δωμάτιο '{room_name}'. Διαθέσιμα δωμάτια: {available}"

            vac.send("action", {
                "did": "astakos", 
                "siid": 4, 
                "aiid": 1, 
                "in": [
                    {"piid": 1, "value": 18}, 
                    {"piid": 10, "value": f'{{"selects":[[{room_id},1,2,1,1]]}}'}
                ]
            })
            return f"Ο Astakos έδωσε εντολή: Η X20+ πάει για σκούπισμα στο δωμάτιο: {room_name}! 🧹"

        else:
            return f"Άγνωστη εντολή: {action}."

    except Exception as e:
        return f"Error επικοινωνίας με τη σκούπα: {str(e)}"
@tool
def post_to_linkedin(text: str = None, image_path: str = None, image_paths: str = None) -> str:
    """
    Publishes text and optionally images to LinkedIn.
    If no text is provided, it is automatically retrieved from linkedin_draft.json.
    image_path: a single image (backward compatibility)
    image_paths: multiple images separated by commas, e.g., "C:/a.jpg,C:/b.jpg,C:/c.jpg"
                 The images are uploaded as a carousel on LinkedIn (up to 9).
    """
    import os
    import json
    import requests
    from dotenv import load_dotenv, find_dotenv
    from config import LINKEDIN_DRAFT_FILE

    # [MASTRO-INTERCEPTOR]: Autonomy from Working Memory
    if not text:
        if os.path.exists(LINKEDIN_DRAFT_FILE):
            try:
                with open(LINKEDIN_DRAFT_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    text = data.get("content") or data.get("text")
                    if not image_paths and not image_path:
                        image_paths = data.get("image_paths")
                        image_path = data.get("image_path")
            except Exception as e:
                print(f"⚠️ Error reading draft: {e}")

    if not text:
        return "❌ Error: Δεν βρέθηκε κείμενο (ούτε στο draft, ούτε στα ορίσματα)."

    # Gathering of all paths into a list
    all_paths = []
    if image_paths:
        all_paths = [p.strip() for p in image_paths.split(",") if p.strip()]
    elif image_path:
        all_paths = [image_path]

    # Validate paths
    for p in all_paths:
        if not os.path.exists(p):
            return f"❌ Image δεν βρέθηκε: {p}"

    # --- LinkedIn API Logic ---
    load_dotenv(find_dotenv(), override=True)
    token = os.getenv("LINKEDIN_TOKEN")
    if not token: return "❌ Λsaidι το LINKEDIN_TOKEN."

    headers = {
        "Authorization": f"Bearer {token}",
        "X-Restli-Protocol-Version": "2.0.0",
        "Content-Type": "application/json"
    }

    try:
        # 1. Identification
        user_res = requests.get("https://api.linkedin.com/v2/userinfo", headers=headers)
        if user_res.status_code != 200: return f"❌ Auth Error: {user_res.text}"
        person_urn = f"urn:li:person:{user_res.json().get('sub')}"

        # 2. Upload Images (single or multiple)
        asset_urns = []
        for path in all_paths[:9]:  # LinkedIn max 9 images
            reg_url = "https://api.linkedin.com/v2/assets?action=registerUpload"
            reg_data = {"registerUploadRequest": {"recipes": ["urn:li:digitalmediaRecipe:feedshare-image"], "owner": person_urn, "serviceRelationships": [{"relationshipType": "OWNER", "identifier": "urn:li:userGeneratedContent"}]}}
            reg_res = requests.post(reg_url, headers=headers, json=reg_data)
            if reg_res.status_code == 200:
                upload_url = reg_res.json()['value']['uploadMechanism']['com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest']['uploadUrl']
                asset_urn = reg_res.json()['value']['asset']
                with open(path, 'rb') as f:
                    requests.post(upload_url, headers={"Authorization": f"Bearer {token}"}, data=f.read())
                asset_urns.append(asset_urn)

        # 3. Create Post
        post_url = "https://api.linkedin.com/v2/ugcPosts"
        media_content = {
            "shareCommentary": {"text": text},
            "shareMediaCategory": "IMAGE" if asset_urns else "NONE"
        }
        if asset_urns:
            media_content["media"] = [
                {"status": "READY", "media": urn, "title": {"text": f"Photo {i+1}"}}
                for i, urn in enumerate(asset_urns)
            ]

        payload = {
            "author": person_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {"com.linkedin.ugc.ShareContent": media_content},
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"}
        }

        res = requests.post(post_url, headers=headers, json=payload)

        if res.status_code == 201:
            # [MASTRO-CLEANUP]: Draft cleanup after success
            if os.path.exists(LINKEDIN_DRAFT_FILE):
                with open(LINKEDIN_DRAFT_FILE, "w", encoding="utf-8") as f:
                    json.dump({}, f)
            img_count = len(asset_urns)
            img_msg = f" με {img_count} εικόν{'α' if img_count == 1 else 'ες'}" if img_count else ""
            return f"✅ Το LinkedIn post uploaded{img_msg} και το draft καθαρίστηκε!"

        return f"❌ Αποτυχία: {res.text}"

    except Exception as e:
        return f"❌ Κρίσιμο Error: {str(e)}"
import math

def _is_home(lat: float, lon: float, home_lat: float = 40.646537, home_lon: float = 22.939025, radius_m: float = 150) -> bool:
    """Checks if the coordinates are within 150 meters of Piston 7."""
    R = 6371000
    dlat = math.radians(lat - home_lat)
    dlon = math.radians(lon - home_lon)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(home_lat)) * math.cos(math.radians(lat)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a)) < radius_m


@tool
def get_current_location() -> str:
    """
    Returns the last recorded GPS coordinate of Lazaros from last_location.json.
    Used to know where the user is in real-time.
    """
    import json
    import os
    import time
    from datetime import datetime
    from config import GPS_STORAGE_FILE

    if not os.path.exists(GPS_STORAGE_FILE):
        return "📍 Δεν exists καταγεγραμμένο στίγμα remaining. Ζήτα from τον Λάζαρο να στείλει Live Location."

    try:
        with open(GPS_STORAGE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            lat = data.get("lat")
            lon = data.get("lon")
            ts = data.get("timestamp", 0)

            # Calculation of "freshness"
            diff_minutes = int((time.time() - ts) / 60)
            last_seen = datetime.fromtimestamp(ts).strftime('%H:%M:%S')

            if diff_minutes > 1440:
                return f"📍 Το στίγμα είναι πολύ παλιό (ηλικίας {diff_minutes // 60}h, τελευταία ενημέρωση {last_seen})."

            maps_link = f"https://maps.google.com/?q={lat},{lon}"
            home_status = "🏠 Είναι ΣΠΙΤΙ" if _is_home(float(lat), float(lon)) else "🚶 Είναι ΕΚΤΟΣ σπιτιού"

            return (
                f"📍 Συντεταγμένες: {lat}, {lon}\n"
                f"{home_status}\n"
                f"🗺️ <a href='{maps_link}'>Δες στον Χάρτη</a>\n"
                f"⏱️ Ενημερώθηκε πριν {diff_minutes} λεπτά (στις {last_seen})."
            )

    except Exception as e:
        return f"❌ Error κατά την ανάγνωση του GPS: {str(e)}"

@tool
def control_spotify(
    action: str,
    query: str = ""
) -> str:
    """Controls Spotify.
    action: 'play', 'pause', 'next', 'now_playing', 'top_tracks', 'search'
    query: Title/Artist for action='search'"""
    try:
        scope = "user-modify-playback-state user-read-playback-state user-top-read user-read-currently-playing"
        sp = spotipy.Spotify(auth_manager=SpotifyOAuth(scope=scope))

        if action == "top_tracks":
            results = sp.current_user_top_tracks(limit=5, time_range='long_term')
            if not results['items']:
                return "Δεν βρέθηκαν δεδομένα για top tracks."
            tracks = [f"{i+1}. {t['name']} - {t['artists'][0]['name']}" for i, t in enumerate(results['items'])]
            return "🎵 Top 5 τραγούδια σου:\n" + "\n".join(tracks)

        elif action == "pause":
            sp.pause_playback()
            return "⏸️ Η μουσική σταμάτησε."

        elif action == "next":
            sp.next_track()
            return "⏭️ Πήγαμε στο επόμενο τραγούδι!"

        elif action == "now_playing":
            current = sp.current_playback()
            if not current or not current.get("item"):
                return "Δεν παίζει τίποτα αυτή τη στιγμή."
            track = current["item"]
            artist = track["artists"][0]["name"]
            name = track["name"]
            playing = "▶️" if current["is_playing"] else "⏸️"
            return f"{playing} {name} — {artist}"

        elif action == "search":
            if not query:
                return "❌ Δώσε τίτλο ή καλλιτέχνη για αναζήτηση."
            res = sp.search(q=query, type='track', limit=1)
            if not res['tracks']['items']:
                return f"❌ Δεν βρήκα το '{query}'."
            track_uri = res['tracks']['items'][0]['uri']
            track_name = res['tracks']['items'][0]['name']
            sp.start_playback(uris=[track_uri])
            return f"▶️ Έβαλα να παίζει: {track_name} 🎵"

        elif action == "play":
            sp.start_playback()
            return "▶️ Η μουσική started ξανά!"

        return "❌ Άγνωστη εντολή. Δοκίμασε: play, pause, next, now_playing, top_tracks, search."

    except Exception as e:
        return f"⚠️ Spotify Error: {str(e)}. (Μήπως δεν έχεις ανοιχτή την εφαρμογή;)"

@tool
def get_fit_summary(days_ago: int = 1) -> str:
    """
    Returns a Google Fit summary for Lazaros.
    days_ago=0 → today, days_ago=1 → yesterday (default).
    Includes: steps, sleep (hours + deep/REM), heart rate.
    """
    try:
        from astakos_skills.google_fit import get_daily_summary
        return get_daily_summary(days_ago=days_ago)
    except Exception as e:
        return f"❌ Google Fit σφάλμα: {e}"


@tool
def save_goal_tool(project: str, description: str, status: str = "active", progress: int = 0, milestones: str = "") -> str:
    """
    Saves or updates a long-term goal for Lazaros.
    project: Short project name (e.g., 'ShiftMaster', 'Astakos', 'PraxisERP').
    description: What he wants to achieve (e.g., 'To finish the licensing module').
    status: 'active' (in progress) | 'paused' (shelved) | 'done' (completed).
    progress: Progress percentage 0-100.
    milestones: Smaller steps or milestones (as a string).
    """
    from memory.vector_store import save_goal
    ok = save_goal(project=project, description=description, status=status, progress=progress, milestones=milestones)
    if ok:
        return f"✅ Goal '{project}' αποθηκεύτηκε ({status}, {progress}%)."
    return f"❌ Αποτυχία αποθήκευσης goal '{project}'."


@tool
def update_goal_status_tool(project: str, status: str) -> str:
    """
    Updates the status of an existing goal.
    project: The name of the project (e.g., 'ShiftMaster').
    status: 'active' | 'paused' | 'done'
    """
    from memory.vector_store import update_goal_status
    ok = update_goal_status(project=project, status=status)
    if ok:
        return f"✅ Goal '{project}' → {status}."
    return f"❌ Δεν βρέθηκε goal '{project}'."


@tool
def update_goal_progress_tool(project: str, progress: int) -> str:
    """
    Updates the progress percentage of an existing goal (0-100).
    project: The name of the project.
    progress: An integer from 0 to 100.
    """
    from memory.vector_store import update_goal_progress
    ok = update_goal_progress(project=project, progress=progress)
    if ok:
        return f"✅ Goal '{project}' progress → {progress}%."
    return f"❌ Δεν βρέθηκε goal '{project}'."


@tool
def update_goal_milestones_tool(project: str, milestones: str) -> str:
    """
    Updates the milestones of an existing goal.
    project: The name of the project.
    milestones: The new milestones (in string format, e.g., '1) UI, 2) DB').
    """
    from memory.vector_store import update_goal_milestones
    ok = update_goal_milestones(project=project, milestones=milestones)
    if ok:
        return f"✅ Goal '{project}' milestones updated."
    return f"❌ Δεν βρέθηκε goal '{project}'."


@tool
def tool_stats(days: int = 7) -> str:
    """
    Displays performance statistics of the tools for the last N days.
    days: How many days back to look (default 7).
    Returns per tool: calls, errors, error rate, average duration.
    """
    import os, json
    from datetime import datetime, timedelta
    from collections import defaultdict

    traces_dir = os.path.join(os.path.dirname(__file__), "..", "logs", "traces")
    if not os.path.isdir(traces_dir):
        return "❌ Δεν βρέθηκε φάκελος traces."

    stats: dict[str, dict] = defaultdict(lambda: {"calls": 0, "errors": 0, "durations": []})

    today = datetime.now().date()
    loaded_days = 0
    for i in range(days):
        day = today - timedelta(days=i)
        path = os.path.join(traces_dir, f"{day}.json")
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                entries = json.load(f)
        except Exception:
            continue
        loaded_days += 1
        for entry in entries:
            for tc in entry.get("tool_calls", []):
                name = tc.get("tool", "unknown")
                stats[name]["calls"] += 1
                if tc.get("error"):
                    stats[name]["errors"] += 1
                dur = tc.get("duration_ms")
                if dur is not None:
                    stats[name]["durations"].append(dur)

    if not stats:
        return f"📊 No traces found για τις τελευταίες {days} μέρες."

    # Sorting: first those with errors, then alphabetically
    rows = []
    for name, s in sorted(stats.items(), key=lambda x: (-x[1]["errors"], x[0])):
        calls = s["calls"]
        errors = s["errors"]
        rate = f"{errors/calls*100:.0f}%" if calls else "—"
        avg_dur = f"{sum(s['durations'])//len(s['durations'])}ms" if s["durations"] else "—"
        err_icon = "🔴" if errors > 0 else "✅"
        rows.append(f"{err_icon} {name}: {calls} κλήσεις, {errors} σφάλματα ({rate}), avg {avg_dur}")

    header = f"📊 Tool Stats — τελευταίες {days} μέρες ({loaded_days} αρχεία traces)\n"
    return header + "\n".join(rows)


def _doctor_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _doctor_load_json(path: str):
    try:
        if not os.path.exists(path):
            return []
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _doctor_event_has_error(event: dict) -> bool:
    action = str(event.get("action", "")).lower()
    return bool(event.get("error")) or action in {"error", "failed", "failure", "exception"} or "error" in action


def _doctor_trace_has_issue(trace: dict) -> bool:
    if trace.get("error") or trace.get("loop_guard"):
        return True
    return any(tc.get("error") for tc in trace.get("tool_calls", []))


def _doctor_summarize_logs(days: int = 2, *, root: str | None = None, slow_ms: int = 45000) -> dict:
    root = root or _doctor_root()
    days = max(1, int(days or 1))
    today = datetime.now().date()
    summary = {
        "days": days,
        "event_files": 0,
        "events": 0,
        "event_errors": 0,
        "trace_files": 0,
        "traces": 0,
        "trace_issues": 0,
        "loop_guards": 0,
        "slow_traces": 0,
        "last_issues": [],
    }

    for i in range(days):
        day = today - timedelta(days=i)
        day_str = day.isoformat()

        events_path = os.path.join(root, "logs", "events", f"{day_str}.json")
        events = _doctor_load_json(events_path)
        if events:
            summary["event_files"] += 1
        summary["events"] += len(events)
        summary["event_errors"] += sum(1 for event in events if _doctor_event_has_error(event))

        traces_path = os.path.join(root, "logs", "traces", f"{day_str}.json")
        traces = _doctor_load_json(traces_path)
        if traces:
            summary["trace_files"] += 1
        summary["traces"] += len(traces)
        for trace in traces:
            is_issue = _doctor_trace_has_issue(trace)
            is_loop = bool(trace.get("loop_guard"))
            is_slow = int(trace.get("duration_ms") or 0) >= slow_ms
            summary["trace_issues"] += int(is_issue)
            summary["loop_guards"] += int(is_loop)
            summary["slow_traces"] += int(is_slow)
            if (is_issue or is_slow) and len(summary["last_issues"]) < 5:
                label = "loop guard" if is_loop else "error" if is_issue else "slow"
                summary["last_issues"].append({
                    "timestamp": trace.get("timestamp", "?"),
                    "agent": trace.get("agent") or "?",
                    "label": label,
                    "message": str(trace.get("user_message") or "")[:90],
                })

    return summary


def _doctor_compact_map(values: dict | None) -> str:
    if not values:
        return "none"
    return ", ".join(f"{k}:{v}" for k, v in values.items())


def _count_memory_audit_ops(entries: list[dict]) -> dict[str, int]:
    counts = {
        "add": 0,
        "overwrite": 0,
        "add_alongside": 0,
        "skip_duplicate": 0,
        "skip_keep_old": 0,
        "reflection": 0,
        "total": len(entries),
    }
    for entry in entries:
        op = entry.get("op")
        if op in counts:
            counts[op] += 1
        elif op in ("reflection_applied", "reflection_saved"):
            counts["reflection"] += 1
    return counts


def _format_memory_ops_summary(counts: dict[str, int]) -> str:
    if not counts.get("total"):
        return "0 ops"
    parts = [
        f"add {counts.get('add', 0)}",
        f"overwrite {counts.get('overwrite', 0)}",
        f"alongside {counts.get('add_alongside', 0)}",
        f"skipped {counts.get('skip_duplicate', 0) + counts.get('skip_keep_old', 0)}",
        f"reflections {counts.get('reflection', 0)}",
    ]
    return f"{counts.get('total', 0)} ops (" + ", ".join(parts) + ")"


def _format_pending_routines(pending_routines: dict) -> str:
    if not pending_routines:
        return "0"
    names = []
    for routine_id, item in list(pending_routines.items())[:3]:
        event = item.get("event") if isinstance(item, dict) else ""
        event = str(event or f"routine #{routine_id}").strip()
        names.append(event[:60])
    suffix = ", ".join(names)
    if len(pending_routines) > 3:
        suffix += f", +{len(pending_routines) - 3}"
    return f"{len(pending_routines)} — {suffix}"


def _doctor_status_label(*, warnings: list[str], pending_actions: list, logs: dict) -> str:
    if logs.get("event_errors") or any("unreadable" in w for w in warnings):
        return "Άμεσος έλεγχος"
    if pending_actions or logs.get("trace_issues") or logs.get("loop_guards") or warnings:
        return "Προσοχή"
    return "OK"


@tool
def system_doctor(days: int = 1) -> str:
    """
    Fast read-only health check of the Astakos runtime.
    days: how many days of logs/traces to look at (default 1, i.e. today).
    """
    lines: list[str] = []
    warnings: list[str] = []

    logs = _doctor_summarize_logs(days=days)
    if logs["event_errors"]:
        warnings.append(f"{logs['event_errors']} event errors")
    if logs["trace_issues"]:
        warnings.append(f"{logs['trace_issues']} trace issues")
    if logs["loop_guards"]:
        warnings.append(f"{logs['loop_guards']} loop guards")

    try:
        from core.approval import list_pending
        pending_actions = list_pending()
    except Exception:
        pending_actions = []
        warnings.append("approval store unreadable")

    try:
        from core.messenger_draft import debug_draft_state
        draft = debug_draft_state()
    except Exception:
        draft = {"exists": False, "active": False}
        warnings.append("draft state unreadable")

    try:
        from memory.conversation_history import load_conversation_stats
        from memory.session_memory import AUTO_SESSION_SUMMARY_EXCHANGE_THRESHOLD
        conv = load_conversation_stats()
        unsummarized = int(conv.get("unsummarized_exchanges") or 0)
        threshold = int(AUTO_SESSION_SUMMARY_EXCHANGE_THRESHOLD)
        if unsummarized >= threshold:
            warnings.append("session summary due")
    except Exception:
        conv = {}
        unsummarized = 0
        threshold = 0
        warnings.append("conversation stats unreadable")

    try:
        from memory.routine_db import load_pending_confirmations
        pending_routines = load_pending_confirmations()
    except Exception:
        pending_routines = {}
        warnings.append("routine pending store unreadable")

    try:
        memory_ops = _count_memory_audit_ops(_load_audit_log(days=days))
    except Exception:
        memory_ops = {"total": 0}
        warnings.append("memory audit unreadable")

    try:
        cond_routines = _doctor_conditioned_routines()
    except Exception:
        cond_routines = "error reading conditions"

    status = _doctor_status_label(warnings=warnings, pending_actions=pending_actions, logs=logs)
    lines.append(f"🩺 Astakos Doctor: {status}")
    lines.append(f"• Logs ({logs['days']}d): events {logs['events']} / errors {logs['event_errors']}, traces {logs['traces']} / issues {logs['trace_issues']}")
    lines.append(f"• Loop guards: {logs['loop_guards']} | Slow turns: {logs['slow_traces']}")
    lines.append(f"• Pending approvals: {len(pending_actions)}" + (f" ({', '.join(a.get('tool_name', '?') for a in pending_actions[:3])})" if pending_actions else ""))
    lines.append(f"• Messenger draft: {'active' if draft.get('active') else 'no'}" + (f" → {draft.get('target_name')}" if draft.get("active") and draft.get("target_name") else ""))
    lines.append(f"• Session backlog: {unsummarized}/{threshold} unsummarized ({_doctor_compact_map(conv.get('unsummarized_by_channel'))})")
    lines.append(f"• Memory ops: {_format_memory_ops_summary(memory_ops)}")
    lines.append(f"• Pending routine confirmations: {_format_pending_routines(pending_routines)}")

    if cond_routines and cond_routines != "None":
        lines.append("• Conditioned routines:")
        lines.append(cond_routines)

    try:
        ctx_panel = _doctor_runtime_context()
        if ctx_panel and ctx_panel != "None":
            lines.append("• Runtime Context:")
            for c_line in ctx_panel.splitlines():
                lines.append(f"  {c_line}")
    except Exception:
        pass

    if logs["last_issues"]:
        lines.append("• Recent things to inspect:")
        for item in logs["last_issues"][-3:]:
            lines.append(f"  - {item['timestamp']} [{item['label']}] {item['agent']}: {item['message']}")

    if warnings:
        lines.append("• Σημείωση: " + ", ".join(warnings[:5]))
    else:
        lines.append("• Όλα δείχνουν ήσυχα.")

    return "\n".join(lines)


def _doctor_runtime_context() -> str:
    try:
        from services.routine_context import build_runtime_routine_context
        ctx = build_runtime_routine_context()
        if not ctx:
            return "None"
        import json
        return json.dumps(ctx, indent=2, ensure_ascii=False)
    except Exception as e:
        return f"Error: {e}"

def _doctor_conditioned_routines() -> str:
    try:
        from memory.routine_db import get_connection
        from services.routine_conditions import evaluate_routine_condition
        from services.routine_context import build_runtime_routine_context

        conn = get_connection()
        cursor = conn.cursor()
        rows = cursor.execute(
            """
            SELECT id, event_name, condition_type, condition_mode, condition_payload, priority, conflict_group
            FROM routines
            WHERE state = 'active' AND (condition_type IS NOT NULL OR priority > 0 OR conflict_group IS NOT NULL)
            """
        ).fetchall()
        conn.close()

        if not rows:
            return "None"

        context = build_runtime_routine_context()
        lines = []
        for r_id, event_name, c_type, c_mode, c_payload, priority, conflict_group in rows:
            eval_result = {}
            if c_type:
                eval_result = evaluate_routine_condition(
                    {
                        "condition_type": c_type,
                        "condition_payload": c_payload,
                        "condition_mode": c_mode,
                    },
                    context,
                )
            
            status = "allowed" if eval_result.get("allowed", True) else "blocked"
            eval_reason = eval_result.get("reason", "")
            
            mode_desc = f"{c_mode}" if c_mode else "no_condition"
            
            import json
            try:
                payload_dict = json.loads(c_payload) if c_payload else {}
                if "flag" in payload_dict:
                    target = f"{payload_dict['flag']}={payload_dict.get('equals', True)}"
                elif "shift" in payload_dict:
                    target = f"shift={payload_dict['shift']}"
                else:
                    target = str(c_payload)
            except Exception:
                target = str(c_payload)

            details = []
            if c_type:
                details.append(f"cond: {mode_desc} ({target}) -> {status} [{eval_reason}]")
            if priority or conflict_group:
                details.append(f"conflict: grp='{conflict_group or event_name.split()[0]}' prio={priority or 0}")
                
            lines.append(f"  #{r_id} {event_name} | " + " | ".join(details))

        if not lines:
            return "None"
        return "\n".join(lines)
    except Exception as e:
        return f"error: {str(e)}"

# ────────────────────────────────────────────────────────────────
# MEMORY REVIEW
# ────────────────────────────────────────────────────────────────

def _load_audit_log(days: int = 1) -> list[dict]:
    """Loads entries from the memory audit log for the last X days."""
    from config import MEMORY_AUDIT_DIR
    from datetime import date, timedelta
    entries = []
    today = date.today()
    for i in range(days):
        day = today - timedelta(days=i)
        path = os.path.join(MEMORY_AUDIT_DIR, f"{day.isoformat()}.json")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        entries.extend(data)
            except Exception:
                pass
    return entries


def _memory_review_period(days: int) -> str:
    return "Σήμερα" if days <= 1 else f"Τις τελευταίες {days} μέρες"


def _normalize_memory_review_op(op: str | None) -> str:
    value = (op or "").strip().lower()
    aliases = {
        "add": "add",
        "adds": "add",
        "new": "add",
        "νέα": "add",
        "overwrite": "overwrite",
        "overwrites": "overwrite",
        "διόρθωση": "overwrite",
        "add_alongside": "add_alongside",
        "alongside": "add_alongside",
        "keep_both": "add_alongside",
        "skip": "skip",
        "skipped": "skip",
        "duplicate": "skip_duplicate",
        "duplicates": "skip_duplicate",
        "skip_duplicate": "skip_duplicate",
        "skip_keep_old": "skip_keep_old",
        "keep_old": "skip_keep_old",
        "reflection": "reflection",
        "reflections": "reflection",
        "lesson": "reflection",
    }
    return aliases.get(value, value)


def _filter_memory_audit_entries(entries: list[dict], *, op: str = "", category: str = "") -> list[dict]:
    normalized_op = _normalize_memory_review_op(op)
    category_value = (category or "").strip().lower()
    filtered = entries
    if normalized_op:
        if normalized_op == "skip":
            filtered = [e for e in filtered if e.get("op") in ("skip_duplicate", "skip_keep_old")]
        elif normalized_op == "reflection":
            filtered = [e for e in filtered if e.get("op") in ("reflection_applied", "reflection_saved")]
        else:
            filtered = [e for e in filtered if e.get("op") == normalized_op]
    if category_value:
        filtered = [e for e in filtered if str(e.get("category", "")).strip().lower() == category_value]
    return filtered


def _memory_review_has_filter(op: str = "", category: str = "") -> bool:
    return bool((op or "").strip() or (category or "").strip())


def _append_memory_review_section(
    lines: list[str],
    *,
    title: str,
    entries: list[dict],
    has_filter: bool,
    limit: int,
    formatter,
) -> None:
    if has_filter and not entries:
        return
    lines.append(f"\n{title}: {len(entries)}")
    for entry in entries[-limit:]:
        lines.append(formatter(entry))


@tool
def memory_review(days: int = 1, op: str = "", category: str = "") -> str:
    """
    Displays what Astakos stored in memory during the last X days.
    Includes: new entries, overwrites, duplicates skipped, reflections.
    days: how many days back (default=1 = today).
    op: optional filter (add, overwrite, add_alongside, skip, skip_duplicate, skip_keep_old, reflection).
    category: optional category filter (e.g., family, lazeros, projects).
    """
    all_entries = _load_audit_log(days)
    entries = _filter_memory_audit_entries(all_entries, op=op, category=category)
    period = _memory_review_period(days)
    if not entries:
        filters = []
        if op:
            filters.append(f"op={op}")
        if category:
            filters.append(f"category={category}")
        filter_text = f" με φίλτρα ({', '.join(filters)})" if filters else ""
        return f"📋 Memory Review: {period.lower()}{filter_text} δεν υπάρχουν records."

    # Grouping by operation
    adds        = [e for e in entries if e.get("op") == "add"]
    overwrites  = [e for e in entries if e.get("op") == "overwrite"]
    alongside   = [e for e in entries if e.get("op") == "add_alongside"]
    skip_dup    = [e for e in entries if e.get("op") == "skip_duplicate"]
    skip_old    = [e for e in entries if e.get("op") == "skip_keep_old"]
    reflections = [e for e in entries if e.get("op") in ("reflection_applied", "reflection_saved")]

    filters = []
    if op:
        filters.append(f"op={op}")
    if category:
        filters.append(f"category={category}")
    filter_text = f" ({', '.join(filters)})" if filters else ""
    has_filter = _memory_review_has_filter(op=op, category=category)
    lines = [f"📋 *Memory Review — {period}{filter_text}: {len(entries)} κινήσεις μνήμης*\n"]

    _append_memory_review_section(
        lines,
        title="✅ *Έμαθα / κράτησα νέα*",
        entries=adds,
        has_filter=has_filter,
        limit=5,
        formatter=lambda e: f"  [{e.get('ts','')}] [{e.get('category','?')}] {e.get('fact','')[:80]}",
    )
    _append_memory_review_section(
        lines,
        title="♻️ *Διόρθωσα παλιές μνήμες*",
        entries=overwrites,
        has_filter=has_filter,
        limit=5,
        formatter=lambda e: f"  [{e.get('ts','')}] {e.get('fact','')[:60]} ← {e.get('old','')[:40]} ({e.get('reason','')})",
    )
    _append_memory_review_section(
        lines,
        title="🧩 *Κράτησα κοντινές μνήμες ως ξεχωριστές*",
        entries=alongside,
        has_filter=has_filter,
        limit=5,
        formatter=lambda e: f"  [{e.get('ts','')}] {e.get('fact','')[:70]} (dist={e.get('distance','?')}, overlap={e.get('overlap','?')})",
    )
    _append_memory_review_section(
        lines,
        title="🔁 *Αγνόησα ως διπλότυπα*",
        entries=skip_dup,
        has_filter=has_filter,
        limit=3,
        formatter=lambda e: f"  [{e.get('ts','')}] {e.get('fact','')[:70]} (dist={e.get('distance','?')})",
    )
    _append_memory_review_section(
        lines,
        title="🔒 *Κράτησα την παλιότερη/πλουσιότερη μνήμη*",
        entries=skip_old,
        has_filter=has_filter,
        limit=3,
        formatter=lambda e: f"  [{e.get('ts','')}] {e.get('fact','')[:70]}",
    )
    _append_memory_review_section(
        lines,
        title="🧠 *Μαθήματα / reflections*",
        entries=reflections,
        has_filter=has_filter,
        limit=5,
        formatter=lambda e: f"  [{e.get('ts','')}] {'✓ applied' if e.get('op') == 'reflection_applied' else 'saved'}: {(e.get('lesson') or e.get('observation') or '')[:80]}",
    )

    return "\n".join(lines)


all_tools = [
    search_memory, save_to_memory, delete_from_memory, retrieve_photo, update_pending_linkedin_post, process_and_clear_linkedin_post,
    set_local_reminder, manage_list,
    google_calendar_tool, google_tasks_tool, drive_manager,
    read_local_file, write_code, run_code, write_custom_tool,
    mail_manager, github_manager, control_vacuum, control_spotify, recipe_expert, search_flights, search_google_places,
    log_meal, create_file_tool, get_current_location,
    get_news, get_weather_forecast, search_supermarket_prices, relay_local_payload,
    search_goldmall_offers, execute_local_pipeline, archive_file, get_navigation_info, generate_image_tool, post_to_linkedin, learn_routine, edit_routine, delete_routine, get_routines, control_routine_notifications, control_routine_schedule, control_routine_condition, control_routine_cooldown, control_pending_followup, browse_url,
    duckduckgo_search, run_terminal_command, get_fit_summary, save_goal_tool, update_goal_status_tool, update_goal_progress_tool, update_goal_milestones_tool, tool_stats, system_doctor, memory_review,
    repo_mapper,
    scan_receipt,
    text_stats,
    register_tool,
    research_last30days,
    # Project tools
    grant_project_access, list_project_files, read_project_file,
    edit_project_file, write_project_file, grep_project_files,
    list_recent_files,
    # File generator
    generate_excel, generate_word_doc, generate_pdf, generate_csv,
    list_agent_skills, read_agent_skill, run_officecli,
]
