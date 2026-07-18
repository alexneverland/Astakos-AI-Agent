import pytest
import sqlite3
import os
from unittest.mock import patch, MagicMock

from config import STATE_DB
from memory.pending_assets import (
    init_pending_assets_table,
    create_pending_asset_archive,
    get_latest_pending_asset,
    mark_pending_asset_confirmed,
    mark_pending_asset_cancelled,
    classify_pending_asset_reply,
    looks_like_asset_confirmation_prompt
)

@pytest.fixture(autouse=True)
def setup_test_db():
    # Use an in-memory DB or temporary file for tests if needed, 
    # but here we'll just mock the db connection or use a clean test DB.
    db_path = "test_state_docs.db"
    if os.path.exists(db_path):
        os.remove(db_path)
        
    with patch("memory.pending_assets.STATE_DB", db_path):
        init_pending_assets_table()
        yield
        
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except Exception:
            pass

def test_document_confirmation_prompt():
    prompt = "Να το αποθηκεύσω μόνιμα στη μνήμη μου;\nΑπάντησέ μου μόνο με: ναι ή όχι."
    assert looks_like_asset_confirmation_prompt(prompt) is True

    prompt_photo = "Να την αποθηκεύσω μόνιμα στη μνήμη μου;"
    assert looks_like_asset_confirmation_prompt(prompt_photo) is True

    prompt_bad = "Τι θέλεις να κάνω με αυτό το αρχείο;"
    assert looks_like_asset_confirmation_prompt(prompt_bad) is False

def test_document_confirmation_prompt_accepts_markdown_emphasis():
    prompt = "Να την **αποθηκεύσω** μόνιμα στη μνήμη μου;"

    assert looks_like_asset_confirmation_prompt(prompt) is True

def test_document_pending_flow():
    # 1. Create a pending document
    with patch("memory.pending_assets.STATE_DB", "test_state_docs.db"):
        create_pending_asset_archive(
            channel="web",
            asset_type="document",
            file_path="/tmp/test_doc.pdf",
            filename="test_doc.pdf",
            analysis="This is a test document.",
            caption="test caption"
        )

        # 2. Retrieve it
        pending = get_latest_pending_asset("web", "document")
        assert pending is not None
        assert pending["asset_type"] == "document"
        assert pending["filename"] == "test_doc.pdf"
        assert pending["status"] == "pending"

        # 3. Classify reply
        assert classify_pending_asset_reply("Ναι, αποθήκευσέ το") == "yes"
        assert classify_pending_asset_reply("Όχι, άστο") == "no"

        # 4. Confirm
        mark_pending_asset_confirmed(pending["id"])
        confirmed = get_latest_pending_asset("web", "document")
        assert confirmed is None # Only returns pending

        # Check status in db
        conn = sqlite3.connect("test_state_docs.db")
        cur = conn.cursor()
        cur.execute("SELECT status FROM pending_asset_archives WHERE id=?", (pending["id"],))
        status = cur.fetchone()[0]
        assert status == "confirmed"
        conn.close()
