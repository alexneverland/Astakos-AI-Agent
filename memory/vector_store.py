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
from langchain_chroma import Chroma
from config import CHROMA_DB_DIR, PHOTOS_INDEX_FILE, SIM_THRESHOLD_DISTANCE
from services.embeddings import embeddings

vector_lock = threading.Lock()
memory_lock = threading.Lock()

vector_store = Chroma(
    collection_name="astakos_long_term",
    embedding_function=embeddings,
    persist_directory=CHROMA_DB_DIR
)


def is_semantically_duplicate(new_text: str, existing_list: list, threshold: float = 0.88) -> bool:
    """Ελέγχει αν το νόημα του new_text υπάρχει ήδη στην existing_list."""
    text_list = []
    for item in existing_list:
        if isinstance(item, str):
            text_list.append(item)
        elif isinstance(item, dict) and "fact" in item:
            text_list.append(item["fact"])

    if not text_list:
        return False

    try:
        new_emb = embeddings.embed_query(new_text)
        existing_embs = embeddings.embed_documents(text_list)

        norm_a = sum(a * a for a in new_emb) ** 0.5
        if norm_a == 0:
            return False

        for emb in existing_embs:
            dot_product = sum(a * b for a, b in zip(new_emb, emb))
            norm_b = sum(b * b for b in emb) ** 0.5
            if norm_b == 0:
                continue
            similarity = dot_product / (norm_a * norm_b)
            if similarity >= threshold:
                return True

    except Exception as e:
        print(f"⚠️ [Similarity Check Error]: {e}")

    return False


class AstakosMemoryManager:
    """Κεντρικός Memory Manager — το ΕΝΑ και ΜΟΝΑΔΙΚΟ σημείο εγγραφής."""

    def save(self, memory_type: str, **kwargs):
        with vector_lock, memory_lock:
            try:
                if memory_type == "fact":
                    return self._save_fact(**kwargs)
                elif memory_type == "photo":
                    return self._save_photo(**kwargs)
                elif memory_type == "document":
                    return self._save_document(**kwargs)
                elif memory_type == "session":
                    return self._save_session(**kwargs)
                elif memory_type == "working":
                    return self._save_working(**kwargs)
                else:
                    print(f"⚠️ [MemoryManager]: Άγνωστος τύπος μνήμης '{memory_type}'")
            except Exception as e:
                print(f"\033[91m[MemoryManager Error]: {e}\033[0m")
                return False

    def _save_working(self, new_tags: str):
        from config import WORKING_MEMORY_FILE
        data = []
        if os.path.exists(WORKING_MEMORY_FILE):
            with open(WORKING_MEMORY_FILE, "r", encoding="utf-8") as f:
                try:
                    data = json.load(f)
                except:
                    data = []

        data.append({"tag": new_tags, "time": datetime.now().strftime("%H:%M")})
        data = data[-15:]

        with open(WORKING_MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True

    def _save_fact(self, fact: str, category: str, agent_name: str, photo_path: str = None, source: str = "unknown", reason: str = "agent_inferred"):
        from config import PROFILE_FILE

        # ── Threshold ανά τύπο fact ──────────────────────────────
        if "[LESSON]" in fact:
            dup_threshold = 0.82   # τεχνικά μαθήματα — αυστηρό
        elif "[USER_FACT]" in fact:
            dup_threshold = 0.82   # γεγονότα — μέτριο
        else:
            dup_threshold = 0.85   # γενικό

# 1. Semantic Overwrite για [LESSON] / [USER_FACT]
        if "[LESSON]" in fact or "[USER_FACT]" in fact:
            query_emb = embeddings.embed_query(fact)
            old_results = vector_store._collection.query(query_embeddings=[query_emb], n_results=1)
            if old_results['ids'] and old_results['ids'][0]:
                dist = old_results['distances'][0][0]
                if dist < 0.25:
                    old_id = old_results['ids'][0][0]
                    old_content = old_results['documents'][0][0]
                    # Κράτα την πιο λεπτομερή — αν η παλιά είναι >30% μεγαλύτερη, ΜΗΝ αντικαταστήσεις
                    if len(old_content) > len(fact) * 1.3:
                        print(f"\033[90m[MemoryManager]: Keep richer! Παλιά ({len(old_content)} χαρ.) > Νέα ({len(fact)} χαρ.) — παραμένει η λεπτομερής.\033[0m")
                    else:
                        vector_store._collection.delete(ids=[old_id])
                        print(f"\033[94m[MemoryManager]: Overwrite! ({old_content[:80]} | Dist: {dist:.3f})\033[0m")

        # 2. Duplicate check με dynamic threshold
        results = vector_store.similarity_search_with_score(fact, k=1)
        for doc, score in results:
            if score < SIM_THRESHOLD_DISTANCE and doc.metadata.get("category") == category:
                print(f"\033[90m[MemoryManager]: Duplicate skip (distance={score:.3f}): {doc.page_content}\033[0m")
                return False

        # 3. Αποθήκευση Chroma
        metadata = {
            "category": category, "agent": agent_name,
            "timestamp": datetime.now().timestamp(), "date": datetime.now().strftime("%Y-%m-%d"),
            "retrieval_count": 0,
            "source": source,
            "reason": reason,
        }
        if photo_path:
            if not os.path.isabs(photo_path):
                photo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", photo_path)
            metadata["photo_path"] = photo_path

        vector_store.add_texts([fact], metadatas=[metadata])

# 4. Αποθήκευση JSON Profile — με έξυπνο OVERWRITE
        if category != "photos":
            db = {"general": [], "family": [], "projects": [], "work": [], "home": [], "lesson": [], "photos": []}
            if os.path.exists(PROFILE_FILE):
                with open(PROFILE_FILE, "r", encoding="utf-8") as f:
                    try:
                        db = json.load(f)
                    except:
                        pass

            if category not in db:
                db[category] = []

            # Φτιάχνουμε μια λίστα μόνο με τα strings για να τρέξουμε τα embeddings
            existing_facts = [
                item if isinstance(item, str) else item.get("fact", "")
                for item in db[category]
            ]
            
            best_sim = 0.0
            best_idx = -1
            
            # Mastro-Scanner: Αναζήτηση για παλιά εγγραφή που πρέπει να αντικατασταθεί
            if existing_facts:
                new_emb = embeddings.embed_query(fact)
                existing_embs = embeddings.embed_documents(existing_facts)
                
                norm_a = sum(a * a for a in new_emb) ** 0.5
                if norm_a > 0:
                    for i, emb in enumerate(existing_embs):
                        dot = sum(a * b for a, b in zip(new_emb, emb))
                        norm_b = sum(b * b for b in emb) ** 0.5
                        if norm_b > 0:
                            sim = dot / (norm_a * norm_b)
                            if sim > best_sim:
                                best_sim = sim
                                best_idx = i

            new_entry = {"fact": fact, "photo_path": photo_path, "date": datetime.now().strftime("%Y-%m-%d")} if photo_path else fact

            # OVERWRITE: Αν βρήκαμε κάτι με μεγάλη ομοιότητα, το ΑΝΤΙΚΑΘΙΣΤΟΥΜΕ!
            threshold = dup_threshold if 'dup_threshold' in locals() else 0.88
            if best_sim >= threshold and best_idx != -1:
                print(f"\033[94m[JSON Profile]: Αντικατάσταση παλιάς εγγραφής! (Ομοιότητα: {best_sim:.3f})\033[0m")
                db[category][best_idx] = new_entry
            else:
                print(f"\033[92m[JSON Profile]: Νέα εγγραφή προστέθηκε.\033[0m")
                db[category].append(new_entry)

            # Κρατάμε αυστηρά μέχρι 50 ανά category
            db[category] = db[category][-50:]

            with open(PROFILE_FILE, "w", encoding="utf-8") as f:
                json.dump(db, f, ensure_ascii=False, indent=4)

        return True

    def _save_photo(self, file_path: str, analysis: str, caption: str):
        fact = f"[PHOTO]: {caption or 'Φωτογραφία'} | {analysis[:200]}..."
        metadata = {
            "category": "photos", "agent": "Direct_Index", "photo_path": file_path,
            "timestamp": datetime.now().timestamp(), "date": datetime.now().strftime("%Y-%m-%d"),
            "retrieval_count": 0,
        }
        vector_store.add_texts([fact], metadatas=[metadata])
        print(f"\033[92m[ChromaDB]: Φωτογραφία 'καρφώθηκε' ({os.path.basename(file_path)})\033[0m")

        entry = {
            "file_path": file_path, "analysis": analysis, "caption": caption,
            "date": datetime.now().strftime("%Y-%m-%d"), "timestamp": datetime.now().isoformat(),
        }
        index = []
        if os.path.exists(PHOTOS_INDEX_FILE):
            with open(PHOTOS_INDEX_FILE, "r", encoding="utf-8") as f:
                try:
                    index = json.load(f)
                except:
                    pass
        index.append(entry)
        with open(PHOTOS_INDEX_FILE, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)
        return True

    def _save_document(self, file_path: str, analysis: str, caption: str):
        fact = f"[DOCUMENT]: {caption or 'Έγγραφο'} | {analysis[:1000]}..."
        metadata = {
            "category": "documents", "agent": "Direct_Index", "file_path": file_path,
            "timestamp": datetime.now().timestamp(), "date": datetime.now().strftime("%Y-%m-%d"),
            "retrieval_count": 0,
        }
        vector_store.add_texts([fact], metadatas=[metadata])
        print(f"\033[92m[ChromaDB]: Έγγραφο 'καρφώθηκε' ({os.path.basename(file_path)})\033[0m")

        from config import DOCS_INDEX_FILE
        docs_index_file = DOCS_INDEX_FILE
        entry = {
            "file_path": file_path, "summary": analysis, "caption": caption,
            "date": datetime.now().strftime("%Y-%m-%d"), "timestamp": datetime.now().isoformat(),
        }
        index = []
        if os.path.exists(docs_index_file):
            with open(docs_index_file, "r", encoding="utf-8") as f:
                try:
                    index = json.load(f)
                except:
                    pass
        index.append(entry)
        with open(docs_index_file, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)
        return True

    def _save_session(self, summary: dict, session_text: str):
        from config import SESSIONS_FILE
        vector_store.add_texts([session_text], metadatas=[{
            "category": "session", "date": summary.get("date"),
            "mood": summary.get("mood", "unknown"), "agent": "SessionSummary",
            "timestamp": datetime.now().timestamp(),
            "retrieval_count": 0,
        }])

        sessions = []
        if os.path.exists(SESSIONS_FILE):
            with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
                try:
                    sessions = json.load(f)
                except:
                    pass
        sessions.append(summary)
        sessions = sessions[-30:]
        with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(sessions, f, ensure_ascii=False, indent=2)
        return True


def bump_retrieval_count(doc_ids: list[str]):
    """
    Αυξάνει κατά 1 το retrieval_count για κάθε doc_id.
    Καλείται μετά από κάθε semantic search που επιστρέφει αποτελέσματα.
    """
    if not doc_ids:
        return
    try:
        with vector_lock:
            existing = vector_store._collection.get(ids=doc_ids, include=["metadatas", "documents", "embeddings"])
            if not existing["ids"]:
                return
            new_metas = []
            for meta in existing["metadatas"]:
                m = dict(meta)
                m["retrieval_count"] = int(m.get("retrieval_count", 0)) + 1
                new_metas.append(m)
            vector_store._collection.update(ids=existing["ids"], metadatas=new_metas)
    except Exception as e:
        print(f"\033[90m[bump_retrieval_count]: {e}\033[0m")


# Singleton
memory = AstakosMemoryManager()


def save_photo_to_index(file_path: str, analysis: str, caption: str = ""):
    """Wrapper — στέλνει τα δεδομένα φωτογραφίας στον Memory Manager."""
    memory.save(memory_type="photo", file_path=file_path, analysis=analysis, caption=caption)

# ================================================================
# Long-Term Goals
# ================================================================

def save_goal(project: str, description: str, status: str = "active") -> bool:
    """Αποθηκεύει ή ενημερώνει goal. Κάνει overwrite αν υπάρχει ήδη."""
    try:
        with vector_lock:
            existing = vector_store._collection.get(where={"category": "goal", "project": project})
            if existing["ids"]:
                vector_store._collection.delete(ids=existing["ids"])
                print(f"\033[94m[Goals]: Overwrite '{project}'\033[0m")
            text = f"[GOAL] {project}: {description}"
            metadata = {
                "category": "goal", "project": project, "status": status,
                "agent": "GoalTracker", "timestamp": datetime.now().timestamp(),
                "date": datetime.now().strftime("%Y-%m-%d"), "retrieval_count": 0,
            }
            vector_store.add_texts([text], metadatas=[metadata])
            print(f"\033[92m[Goals]: '{project}' ({status})\033[0m")
            return True
    except Exception as e:
        print(f"\033[91m[Goals Error]: {e}\033[0m")
        return False


def update_goal_status(project: str, status: str) -> bool:
    """Αλλάζει το status ενός goal."""
    try:
        with vector_lock:
            existing = vector_store._collection.get(where={"category": "goal", "project": project})
            if not existing["ids"]:
                return False
            old_meta = dict(existing["metadatas"][0])
            vector_store._collection.delete(ids=existing["ids"])
            new_meta = {**old_meta, "status": status, "timestamp": datetime.now().timestamp()}
            vector_store.add_texts([existing["documents"][0]], metadatas=[new_meta])
            print(f"\033[92m[Goals]: '{project}' → {status}\033[0m")
            return True
    except Exception as e:
        print(f"\033[91m[Goals Error]: {e}\033[0m")
        return False


def get_active_goals() -> list[dict]:
    """Επιστρέφει active/paused goals."""
    try:
        with vector_lock:
            results = vector_store._collection.get(where={"category": "goal"})
        goals = []
        for doc, meta in zip(results.get("documents", []), results.get("metadatas", [])):
            if meta.get("status") in ("active", "paused"):
                goals.append({
                    "project":     meta.get("project", ""),
                    "description": doc.split(": ", 1)[-1].replace("[GOAL] ", ""),
                    "status":      meta.get("status", "active"),
                    "date":        meta.get("date", ""),
                })
        return goals
    except Exception as e:
        print(f"\033[91m[Goals Error]: {e}\033[0m")
        return []
