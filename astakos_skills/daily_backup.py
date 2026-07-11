# ================================================================
# Project: Astakos AI Agent 🦞
# Developer: Lazaros (Piston-7)
# Description: Modular LLM-agnostic multi-agent framework
# Copyright (c) 2026 - All Rights Reserved
# ================================================================


import os
import io
import datetime
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request



SCOPES = ['https://www.googleapis.com/auth/drive'] # Full access to Drive

def authenticate_google_drive():
    # print("Loading credentials...") # Keep prints concise to avoid cluttering the log
    creds = None
    # We use the absolute paths that were indicated
    token_path = r"C:\astakos_v2\credentials\token.json"
    credentials_path = r"C:\astakos_v2\credentials\credentials.json"

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            # print("Refreshing token...")_
            creds.refresh(Request())
        else:
            # This is where the OAuth flow would happen if run in a real user environment
            print(f"Error αυθεντικοποίησης: Τα αρχεία 'token.json' ή 'credentials.json' δεν βρέθηκαν ή δεν is έγκυρα στις διαδρομές: {token_path}, {credentials_path}.")
            print("Παρακαλώ βεβαιωθείτε ότι έχετε ρυθμίσει την αυθεντικοποίηση της Google API inν υπολογιστή σας.")
            return None
    # print("Credentials loaded successfully (or failed)...")
    return creds

def upload_folder_recursive(service, local_path, drive_parent_id, exclude_items):
    # --- [MASTRO-CONFIG]: File types that we DO NOT want in Drive ---
    exclude_exts = {'.pdf', '.xlsx', '.xls', '.jpg', '.jpeg', '.png', '.ogg', '.mp3', '.zip'}
    
    uploaded_items = []
    
    # Check if the folder exists locally
    if not os.path.exists(local_path):
        return uploaded_items

    for item_name in os.listdir(local_path):
        # 1. Check for names (folders like 'venv' or 'messenger_profile')
        if item_name in exclude_items:
            print(f"  [Skip] Εξαιρείται βάσει ονόματος: {item_name}")
            continue

        current_local_path = os.path.join(local_path, item_name)

        # 2. Case: File
        if os.path.isfile(current_local_path):
            # We get the extension (e.g. .pdf)
            ext = os.path.splitext(item_name)[1].lower()
            
            if ext in exclude_exts:
                print(f"  [Skip] Εξαιρείται βάσει τύπου ({ext}): {item_name}")
                continue

            print(f"- Ανέβασμα αρχείου: {item_name} in Drive folder ID: {drive_parent_id}")
            file_metadata = {'name': item_name, 'parents': [drive_parent_id]}
            media = MediaFileUpload(current_local_path, resumable=True)
            
            try:
                file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
                uploaded_items.append(f"Ανέβηκε '{item_name}' (ID: {file.get('id')})")
            except Exception as e:
                print(f"❌ Error in ανέβασμα του {item_name}: {e}")

        # 3. Case: Folder (Recursion)
        elif os.path.isdir(current_local_path):
            print(f"- Creating φακέλου in Drive: {item_name} μέσα in Drive folder ID: {drive_parent_id}")
            folder_metadata = {
                'name': item_name,
                'mimeType': 'application/vnd.google-apps.folder',
                'parents': [drive_parent_id]
            }
            
            try:
                folder = service.files().create(body=folder_metadata, fields='id').execute()
                new_drive_folder_id = folder.get('id')
                print(f"  Φάκελος '{item_name}' δημιουργήθηκε (ID: {new_drive_folder_id}).")
                
                # We make the recursive call to enter inside the folder
                uploaded_items.extend(upload_folder_recursive(service, current_local_path, new_drive_folder_id, exclude_items))
            except Exception as e:
                print(f"❌ Error στη δημιουργία φακέλου {item_name}: {e}")

    return uploaded_items

def daily_backup_to_drive():
    DRIVE_FOLDER_ID = "12YrIZ3uAQWmmwIlEkIkDf-4gcz2P8Ktv"
    ASTAKOS_V2_PATH = r"C:\astakos_v2" 

    print("Έναρξη διαδικασίας backup...")
    creds = authenticate_google_drive()
    if not creds:
        print("Η αυθεντικοποίηση in Google Drive failed. The backup δεν θα εκτελεστεί.")
        return "Backup απέτυχε."

    try:
        print("Σύνδεση με Drive...")
        service = build('drive', 'v3', credentials=creds)

        # Create a folder with the date in Google Drive
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        backup_folder_name = f"astakos_v2_backup_{today}"
        print(f"Creating/Εύρεση φακέλου backup in Drive: {backup_folder_name}")

        # Check if a folder with this name already exists
        query = f"name = '{backup_folder_name}' and mimeType = 'application/vnd.google-apps.folder' and '{DRIVE_FOLDER_ID}' in parents"
        response = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
        files = response.get('files', [])

        if files:
            backup_folder_id = files[0].get('id')
            print(f"Ο φάκελος '{backup_folder_name}' υπάρχει ήδη (ID: {backup_folder_id}). Χρησιμοποιείται για το backup.")
        else:
            file_metadata = {
                'name': backup_folder_name,
                'mimeType': 'application/vnd.google-apps.folder',
                'parents': [DRIVE_FOLDER_ID]
            }
            backup_folder = service.files().create(body=file_metadata, fields='id').execute()
            backup_folder_id = backup_folder.get('id')
            print(f"Ο φάκελος '{backup_folder_name}' δημιουργήθηκε με επιτυχία (ID: {backup_folder_id}).")

        print(f"Ξεκινά το αναδρομικό backup from τον φάκελο '{ASTAKOS_V2_PATH}'...")

        # List of folders/files to exclude (only in the initial call)
        EXCLUDE_ITEMS = ['venv', '__pycache__', '.git', 'messenger_profile']
        
        uploaded_items = upload_folder_recursive(service, ASTAKOS_V2_PATH, backup_folder_id, EXCLUDE_ITEMS)

        if not uploaded_items:
            return f"Δεν βρέθηκαν αρχεία ή φάκελοι για ανέβασμα στον φάκελο '{ASTAKOS_V2_PATH}' (εξαιρουμένων των: {', '.join(EXCLUDE_ITEMS)})."
        else:
            return f"Backup ολοκληρώθηκε επιτυχώς στον φάκελο '{backup_folder_name}' (ID: {backup_folder_id}).\nΑρχεία και φάκελοι που ανέβηκαν:\n" + "\n".join(uploaded_items)

    except Exception as e:
        return f"Προέκυψε σφάλμα κατά το backup στο Google Drive: {e}"

if __name__ == "__main__":
    print(daily_backup_to_drive())
