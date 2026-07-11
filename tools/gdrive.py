# ================================================================
# Project: Astakos AI Agent 🦞
# Module:  Google Drive Uploader
# Uses Application Default Credentials (same as Vertex AI).
# Requires: gcloud auth application-default login with Drive scope,
# or: gcloud auth application-default login --scopes=
#   https://www.googleapis.com/auth/drive.file,
#   https://www.googleapis.com/auth/cloud-platform
# ================================================================

import os
import mimetypes


def upload_to_drive(file_path: str, folder_id: str = None) -> str:
    """
    Uploads a file to Google Drive using Application Default Credentials.
    Returns the shareable URL (viewable by anyone with the link),
    or "" if it fails.
    """
    try:
        from google.auth import default as google_auth_default
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload

        creds, _ = google_auth_default()
        service = build("drive", "v3", credentials=creds, cache_discovery=False)

        filename  = os.path.basename(file_path)
        mime_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"

        file_metadata = {"name": filename}
        if folder_id:
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

    except Exception as e:
        print(f"⚠️ [GDrive]: Upload failed — {e}")
        return ""
