# ================================================================
# Project: Astakos AI Agent 🦞
# Description: Modular LLM-agnostic multi-agent framework
# Copyright (c) 2026 - All Rights Reserved
# ================================================================


import os
import sys
# Add the project root to sys.path so this module can run independently.
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import io
import datetime
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from core.i18n import t



SCOPES: list[str] = ["https://www.googleapis.com/auth/drive"]

BACKUP_EXCLUDE_ITEMS = {
    'venv',
    '.venv',
    '__pycache__',
    '.git',
    'messenger_profile',
    'credentials',
    'credentials.json',
    'token.json',
    '.astakos_token',
    'client_secrets.json',
    '.env',
}


def is_excluded_backup_item(item_name: str, exclude_items: set[str] | list[str] | None = None) -> bool:
    """
    Determines whether a file or directory should be excluded from daily backup.
    Excludes .env, all .env.* variants, credentials/, credentials.json, token.json,
    .astakos_token, client_secrets.json, and standard ignored directories (venv, .venv, .git, etc.).
    """
    if exclude_items and item_name in exclude_items:
        return True
    if item_name in BACKUP_EXCLUDE_ITEMS:
        return True
    if item_name == ".env" or item_name.startswith(".env."):
        return True
    return False


def authenticate_google_drive():
    try:
        from core.workspace_oauth import load_workspace_credentials, WorkspaceAuthError
        return load_workspace_credentials(scopes=SCOPES)
    except Exception as e:
        print(f"Google Drive Authentication Error: {e}")
        return None

def upload_folder_recursive(service, local_path, drive_parent_id, exclude_items):
    # --- [MASTRO-CONFIG]: File types that we DO NOT want in Drive ---
    exclude_exts = {'.pdf', '.xlsx', '.xls', '.jpg', '.jpeg', '.png', '.ogg', '.mp3', '.zip'}
    
    uploaded_items = []
    
    # Check if the folder exists locally
    if not os.path.exists(local_path):
        return uploaded_items

    for item_name in os.listdir(local_path):
        # 1. Check for excluded items (secrets, .env*, credentials, venv, .venv, etc.)
        if is_excluded_backup_item(item_name, exclude_items):
            print(f"  [Skip] Excluded by name: {item_name}")
            continue

        current_local_path = os.path.join(local_path, item_name)

        # 2. Reject symlinks to prevent following links to secrets or escaping backup root
        if os.path.islink(current_local_path):
            print(f"  [Skip] Excluded symlink: {item_name}")
            continue

        # 3. Case: File
        if os.path.isfile(current_local_path):

            # We get the extension (e.g. .pdf)
            ext = os.path.splitext(item_name)[1].lower()
            
            if ext in exclude_exts:
                print(f"  [Skip] Excluded by type ({ext}): {item_name}")
                continue

            print(f"- Uploading file: {item_name} to Drive folder ID: {drive_parent_id}")
            file_metadata = {'name': item_name, 'parents': [drive_parent_id]}
            media = MediaFileUpload(current_local_path, resumable=True)
            
            try:
                file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
                uploaded_items.append(t("skills.daily_backup.msg_upload_success", item=item_name, id=file.get("id")))
            except Exception as e:
                print(f"❌ Error uploading {item_name}: {e}")

        # 3. Case: Folder (Recursion)
        elif os.path.isdir(current_local_path):
            print(f"- Creating folder in Drive: {item_name} inside Drive folder ID: {drive_parent_id}")
            folder_metadata = {
                'name': item_name,
                'mimeType': 'application/vnd.google-apps.folder',
                'parents': [drive_parent_id]
            }
            
            try:
                folder = service.files().create(body=folder_metadata, fields='id').execute()
                new_drive_folder_id = folder.get('id')
                print(f"  Folder '{item_name}' created (ID: {new_drive_folder_id}).")
                
                # We make the recursive call to enter inside the folder
                uploaded_items.extend(upload_folder_recursive(service, current_local_path, new_drive_folder_id, exclude_items))
            except Exception as e:
                print(f"❌ Error creating folder {item_name}: {e}")

    return uploaded_items

def daily_backup_to_drive():
    import config
    DRIVE_FOLDER_ID = getattr(config, "BACKUP_DRIVE_FOLDER_ID", "")
    ASTAKOS_V2_PATH = config.BASE_DIR 

    print("Starting backup process...")
    creds = authenticate_google_drive()
    if not creds:
        print("Google Drive authentication failed. Backup will not be executed.")
        return t("skills.daily_backup.fail")

    try:
        print("Connecting to Drive...")
        service = build('drive', 'v3', credentials=creds, cache_discovery=False)

        # Create a folder with the date in Google Drive
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        backup_folder_name = f"astakos_v2_backup_{today}"
        print(f"Creating/Finding backup folder in Drive: {backup_folder_name}")

        # Check if a folder with this name already exists
        if DRIVE_FOLDER_ID and DRIVE_FOLDER_ID != "root":
            query = f"name = '{backup_folder_name}' and mimeType = 'application/vnd.google-apps.folder' and '{DRIVE_FOLDER_ID}' in parents and trashed = false"
        else:
            query = f"name = '{backup_folder_name}' and mimeType = 'application/vnd.google-apps.folder' and 'root' in parents and trashed = false"

        response = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
        files = response.get('files', [])

        if files:
            backup_folder_id = files[0].get('id')
            print(f"Folder '{backup_folder_name}' already exists (ID: {backup_folder_id}). Using it for backup.")
        else:
            file_metadata = {
                'name': backup_folder_name,
                'mimeType': 'application/vnd.google-apps.folder',
            }
            if DRIVE_FOLDER_ID and DRIVE_FOLDER_ID != "root":
                file_metadata['parents'] = [DRIVE_FOLDER_ID]

            backup_folder = service.files().create(body=file_metadata, fields='id').execute()
            backup_folder_id = backup_folder.get('id')
            print(f"Folder '{backup_folder_name}' created successfully (ID: {backup_folder_id}).")

        print(f"Starting recursive backup from folder '{ASTAKOS_V2_PATH}'...")

        # List of folders/files to exclude (only in the initial call)
        EXCLUDE_ITEMS = list(BACKUP_EXCLUDE_ITEMS)
        
        uploaded_items = upload_folder_recursive(service, ASTAKOS_V2_PATH, backup_folder_id, EXCLUDE_ITEMS)


        if not uploaded_items:
            return t("skills.daily_backup.msg_no_files_exc", path=ASTAKOS_V2_PATH, exc=', '.join(EXCLUDE_ITEMS))
        else:
            return t("skills.daily_backup.msg_backup_success_list", folder=backup_folder_name, id=backup_folder_id, items="\n".join(uploaded_items))

    except Exception as e:
        return t("skills.daily_backup.msg_backup_error", e=e)


if __name__ == "__main__":
    print(daily_backup_to_drive())
