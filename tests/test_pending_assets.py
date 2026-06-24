import pytest
import sqlite3
import os
from datetime import datetime, timedelta

from memory.pending_assets import (
    init_pending_assets_table,
    create_pending_asset_archive,
    get_latest_pending_asset,
    mark_pending_asset_confirmed,
    mark_pending_asset_cancelled,
    clear_expired_pending_assets,
    _get_conn
)

def setup_module():
    init_pending_assets_table()
    
    # Cleanup any existing records for tests
    conn = _get_conn()
    conn.execute("DELETE FROM pending_asset_archives")
    conn.commit()
    conn.close()

def teardown_function():
    # Cleanup after each test
    conn = _get_conn()
    conn.execute("DELETE FROM pending_asset_archives")
    conn.commit()
    conn.close()

def test_create_and_fetch_pending_asset():
    asset_id = create_pending_asset_archive(
        channel="telegram",
        asset_type="photo",
        file_path="C:\\tmp\\a.jpg",
        filename="a.jpg",
        analysis="test analysis",
        caption="test caption",
    )
    
    assert asset_id > 0
    
    row = get_latest_pending_asset("telegram", "photo")
    assert row is not None
    assert row["filename"] == "a.jpg"
    assert row["status"] == "pending"
    assert row["channel"] == "telegram"

def test_create_pending_photo_archive_replaces_previous_pending_same_channel():
    # Create first one
    asset_id_1 = create_pending_asset_archive(
        channel="telegram",
        asset_type="photo",
        file_path="C:\\tmp\\1.jpg",
        filename="1.jpg",
        analysis="analysis 1",
    )
    
    # Create second one on same channel
    asset_id_2 = create_pending_asset_archive(
        channel="telegram",
        asset_type="photo",
        file_path="C:\\tmp\\2.jpg",
        filename="2.jpg",
        analysis="analysis 2",
    )
    
    # Second should be returned
    row = get_latest_pending_asset("telegram", "photo")
    assert row is not None
    assert row["id"] == asset_id_2
    assert row["filename"] == "2.jpg"
    
    # Check first one is cancelled
    conn = _get_conn()
    row_1 = conn.execute("SELECT status FROM pending_asset_archives WHERE id = ?", (asset_id_1,)).fetchone()
    conn.close()
    assert row_1[0] == "cancelled"

def test_confirm_pending_asset():
    asset_id = create_pending_asset_archive(
        channel="web",
        asset_type="photo",
        file_path="C:\\tmp\\b.jpg",
        filename="b.jpg",
        analysis="analysis",
        caption="caption",
    )
    
    mark_pending_asset_confirmed(asset_id)
    
    row = get_latest_pending_asset("web", "photo")
    assert row is None
    
    conn = _get_conn()
    db_row = conn.execute("SELECT status FROM pending_asset_archives WHERE id = ?", (asset_id,)).fetchone()
    conn.close()
    assert db_row[0] == "confirmed"

def test_cancel_pending_asset():
    asset_id = create_pending_asset_archive(
        channel="web",
        asset_type="photo",
        file_path="C:\\tmp\\c.jpg",
        filename="c.jpg",
        analysis="analysis",
        caption="caption",
    )
    
    mark_pending_asset_cancelled(asset_id)
    
    row = get_latest_pending_asset("web", "photo")
    assert row is None
    
    conn = _get_conn()
    db_row = conn.execute("SELECT status FROM pending_asset_archives WHERE id = ?", (asset_id,)).fetchone()
    conn.close()
    assert db_row[0] == "cancelled"

def test_get_latest_pending_asset_ignores_expired():
    # Insert an expired asset manually
    conn = _get_conn()
    now = datetime.now()
    created_at = now - timedelta(hours=1)
    expires_at = now - timedelta(minutes=10) # expired 10 mins ago
    
    cursor = conn.execute(
        """
        INSERT INTO pending_asset_archives (
            channel, asset_type, file_path, filename,
            analysis, caption, status, created_at, expires_at
        )
        VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)
        """,
        (
            "telegram", "photo", "C:\\tmp\\old.jpg", "old.jpg",
            "analysis", "", created_at.isoformat(), expires_at.isoformat(),
        ),
    )
    conn.commit()
    expired_id = cursor.lastrowid
    conn.close()
    
    # get_latest_pending_asset should trigger clear_expired_pending_assets
    row = get_latest_pending_asset("telegram", "photo")
    assert row is None
    
    # Verify it was updated to cancelled
    conn = _get_conn()
    db_row = conn.execute("SELECT status FROM pending_asset_archives WHERE id = ?", (expired_id,)).fetchone()
    conn.close()
    assert db_row[0] == "cancelled"

def test_negative_archive_reply_wins_over_save_word():
    from memory.pending_assets import classify_pending_asset_reply
    text = "ΟΧΙ ΜΗΝ ΤΟ ΑΠΟΘΗΚΕΥΣΕΙΣ αφορά αυτό που λέγαμε"
    assert classify_pending_asset_reply(text) == "no"

def test_positive_archive_reply():
    from memory.pending_assets import classify_pending_asset_reply
    assert classify_pending_asset_reply("ναι αποθήκευσέ το") == "yes"
