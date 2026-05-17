import json
import os
import sys

# Προσθήκη του τρέχοντος φακέλου στο path για να βρει τα modules
sys.path.append(os.getcwd())

from memory.vector_store import vector_store, embeddings
from config import PROFILE_FILE

# 1. Διαγραφή από το JSON Profile
if os.path.exists(PROFILE_FILE):
    with open(PROFILE_FILE, "r", encoding="utf-8") as f:
        db = json.load(f)
    
    target_fact = "Η σημερινή ημέρα αποτελεί την προθεσμία για την υποβολή της αίτησης κατασκήνωσης."
    if "family" in db:
        original_count = len(db["family"])
        db["family"] = [item for item in db["family"] if (item if isinstance(item, str) else item.get("fact", "")) != target_fact]
        if len(db["family"]) < original_count:
            with open(PROFILE_FILE, "w", encoding="utf-8") as f:
                json.dump(db, f, ensure_ascii=False, indent=4)
            print(f"✅ Διαγράφηκε από το JSON ({PROFILE_FILE}).")
        else:
            print("⚠️ Δεν βρέθηκε στο JSON.")

# 2. Διαγραφή από το ChromaDB
query_emb = embeddings.embed_query("Η σημερινή ημέρα αποτελεί την προθεσμία για την υποβολή της αίτησης κατασκήνωσης.")
results = vector_store._collection.query(query_embeddings=[query_emb], n_results=5)

ids_to_delete = []
if results['ids'] and results['ids'][0]:
    for i, dist in enumerate(results['distances'][0]):
        if dist < 0.1: # Πολύ κοντινή ομοιότητα
            ids_to_delete.append(results['ids'][0][i])
            print(f"🗑️ Προετοιμασία διαγραφής από Chroma: {results['documents'][0][i]} (Dist: {dist:.4f})")

if ids_to_delete:
    vector_store._collection.delete(ids=ids_to_delete)
    print(f"✅ Διαγράφηκαν {len(ids_to_delete)} εγγραφές από το ChromaDB.")
else:
    print("⚠️ Δεν βρέθηκε ακριβής αντιστοιχία στο ChromaDB.")
