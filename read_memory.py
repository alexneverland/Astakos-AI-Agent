# ================================================================
# Project: Astakos AI Agent ðŸ¦ž
# Developer: Lazaros (Piston-7)
# Description: Modular LLM-agnostic multi-agent framework
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

import chromadb
import os

db_path = './chroma_db'
if not os.path.exists(db_path):
    print('\n[!] Î”ÎµÎ½ Î²ÏÎ­Î¸Î·ÎºÎµ Ï†Î¬ÎºÎµÎ»Î¿Ï‚ chroma_db. Î— Î¼Î½Î®Î¼Î· ÎµÎ¯Î½Î±Î¹ Î¬Î´ÎµÎ¹Î±.')
    exit()

try:
    client = chromadb.PersistentClient(path=db_path)
    collections = client.list_collections()
    
    if not collections:
        print('\n[!] Î— Î²Î¬ÏƒÎ· Ï…Ï€Î¬ÏÏ‡ÎµÎ¹, Î±Î»Î»Î¬ Î´ÎµÎ½ Î­Ï‡ÎµÎ¹ Î¼Î­ÏƒÎ± ÏƒÏ…Î»Î»Î¿Î³Î­Ï‚.')
        exit()
        
    for c in collections:
        col_name = c.name if hasattr(c, 'name') else c
        print(f'\n==================================================')
        print(f'ðŸ§  Î‘ÎÎŸÎ™Î“ÎœÎ‘ ÎœÎÎ—ÎœÎ—Î£: {col_name}')
        print(f'==================================================')
        
        col = client.get_collection(col_name)
        data = col.get()
        docs = data.get('documents', [])
        
        if not docs:
            print('  [Î†Î´ÎµÎ¹Î± ÏƒÏ…Î»Î»Î¿Î³Î®]')
            continue
            
        for i, doc in enumerate(docs):
            print(f'\n[Î•Î“Î“Î¡Î‘Î¦Î— {i+1}]:\n{doc}')
            print('-' * 50)
except Exception as e:
    print(f'\nÎ£Ï†Î¬Î»Î¼Î± Î±Î½Î¬Î³Î½Ï‰ÏƒÎ·Ï‚: {e}')
