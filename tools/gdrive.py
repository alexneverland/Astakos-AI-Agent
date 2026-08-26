# ================================================================
# Project: Astakos AI Agent 🦞
# Module:  Google Drive Uploader
# Uses Google Workspace user OAuth (token.json).
# ================================================================

import os
import mimetypes
from core.workspace_oauth import (
    load_workspace_credentials,
    WorkspaceAuthError,
)
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import config


def upload_to_drive(file_path: str, folder_id: str = None) -> str:
    """
    Uploads a file to Google Drive using the authenticated user's Workspace OAuth credentials.
    Returns the shareable URL (viewable by anyone with the link),
    or "" if it fails or if Workspace OAuth is not configured.
    """
    try:
        creds = load_workspace_credentials(scopes=["https://www.googleapis.com/auth/drive"])
        service = build("drive", "v3", credentials=creds, cache_discovery=False)

        filename  = os.path.basename(file_path)
        mime_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"

        file_metadata = {"name": filename}
        if folder_id and folder_id != "root":
            file_metadata["parents"] = [folder_id]

        media = MediaFileUpload(file_path, mimetype=mime_type, resumable=True)
        uploaded = service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id,name,webViewLink"
        ).execute()

        file_id = uploaded.get("id")
        if not file_id:
            print("⚠️ [GDrive]: Not returned file_id")
            return ""

        # Make the file viewable by anyone with a link
        service.permissions().create(
            fileId=file_id,
            body={"type": "anyone", "role": "reader"}
        ).execute()

        share_url = f"https://drive.google.com/file/d/{file_id}/view"
        print(f"✅ [GDrive]: '{filename}' uploaded → {share_url}")
        return share_url

    except WorkspaceAuthError as e:
        print(f"⚠️ [GDrive]: Google Workspace OAuth not available — {e}")
        return ""
    except Exception as e:
        print(f"⚠️ [GDrive]: Upload failed — {e}")
        return ""
