# ================================================================
# Project: Astakos AI Agent 🦞
# Module:  Google Drive Uploader
# Χρησιμοποιεί Application Default Credentials (ίδια με Vertex AI).
# Απαιτεί: gcloud auth application-default login με Drive scope,
# ή: gcloud auth application-default login --scopes=
#   https://www.googleapis.com/auth/drive.file,
#   https://www.googleapis.com/auth/cloud-platform
# ================================================================

import os
import mimetypes


def upload_to_drive(file_path: str, folder_id: str = None) -> str:
    """
    Ανεβάζει αρχείο στο Google Drive χρησιμοποιώντας Application Default Credentials.
    Επιστρέφει το shareable URL (viewable από οποιονδήποτε με link),
    ή "" αν αποτύχει.
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
            print("⚠️ [GDrive]: Δεν επεστράφη file_id")
            return ""

        # Κάνε το αρχείο viewable από οποιονδήποτε με link
        service.permissions().create(
            fileId=file_id,
            body={"type": "anyone", "role": "reader"}
        ).execute()

        share_url = f"https://drive.google.com/file/d/{file_id}/view"
        print(f"✅ [GDrive]: '{filename}' ανέβηκε → {share_url}")
        return share_url

    except Exception as e:
        print(f"⚠️ [GDrive]: Upload απέτυχε — {e}")
        return ""
