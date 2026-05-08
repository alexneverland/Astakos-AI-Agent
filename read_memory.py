import chromadb
import os

db_path = './chroma_db'
if not os.path.exists(db_path):
    print('\n[!] Δεν βρέθηκε φάκελος chroma_db. Η μνήμη είναι άδεια.')
    exit()

try:
    client = chromadb.PersistentClient(path=db_path)
    collections = client.list_collections()
    
    if not collections:
        print('\n[!] Η βάση υπάρχει, αλλά δεν έχει μέσα συλλογές.')
        exit()
        
    for c in collections:
        col_name = c.name if hasattr(c, 'name') else c
        print(f'\n==================================================')
        print(f'🧠 ΑΝΟΙΓΜΑ ΜΝΗΜΗΣ: {col_name}')
        print(f'==================================================')
        
        col = client.get_collection(col_name)
        data = col.get()
        docs = data.get('documents', [])
        
        if not docs:
            print('  [Άδεια συλλογή]')
            continue
            
        for i, doc in enumerate(docs):
            print(f'\n[ΕΓΓΡΑΦΗ {i+1}]:\n{doc}')
            print('-' * 50)
except Exception as e:
    print(f'\nΣφάλμα ανάγνωσης: {e}')
